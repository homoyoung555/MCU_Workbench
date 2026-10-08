"""Public-interface tests for FLASH_WINDOW and its shared Recipe Modules."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

import pandas as pd

from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.fbist_pattern_plan import (
    FbistPatternField,
    FbistPatternGenerationPlan,
    FbistPumpAggregate,
    FbistPumpTarget,
)
from program_gen.core.flash_window import (
    BuildMapFieldWrite,
    BuildMapPlan,
    BuildMapRegisterPlan,
    BuildMapTerm,
    FlashWindowCompileError,
    NmLoopRepeat,
    NmLoopRun,
    compile_flash_window_plans,
    compile_nm_loop_plan,
)
from program_gen.core.flash_compare_plan import (
    BulkCoverage,
    BulkStrategy,
    DataKind,
    FlashCompareRequest,
    Operation,
    PageData,
    Scope,
)
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan,
    SetVpospPurpose,
    SetVpospSnapshot,
    compile_set_vposp_plan,
)
from program_gen.core.trim_use_def import (
    TrimDacUseDefError,
    validate_trim_dac_use_def,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.compiler import ProductCompiler
from program_gen.flow_kinds import FlowOperation, compile_flow_rows
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platform_program.builder import PlatformProgramBuilder
from program_gen.platform_program.contracts import ProgramAssemblyInput
from program_gen.platform_program.pattern import (
    GeneratedPatternProducer,
    WorkspacePatternProducer,
)
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class FlashWindowPlanTests(unittest.TestCase):
    def test_buildmap_emits_one_shift_add_assignment_per_register(self):
        plan = BuildMapPlan("CP1", (BuildMapRegisterPlan(
            "trim0", "FLASH_OP0",
            "{1'b0,VBDAC[4:0],PRE_PDAC[4:0],PRE_NDAC[4:0]}",
            0xFFFF0000,
            0x0000,
            (
                BuildMapTerm(15, value=0),
                BuildMapTerm(10, symbol="VBL_DAC_FINAL"),
                BuildMapTerm(5, symbol="VPOSP_DAC_FINAL"),
                BuildMapTerm(0, symbol="VNEGP_DAC_FINAL"),
            ),
            (
                BuildMapFieldWrite("Vnegp", "VNEGP_DAC_FINAL", 0, 5),
                BuildMapFieldWrite("Vbl", "VBL_DAC_FINAL", 10, 5),
                BuildMapFieldWrite("Vposp", "VPOSP_DAC_FINAL", 5, 5),
            ),
        ),))

        expected = {
            "chroma": (
                "    REG_FLASH_OP0[SOCKET]=(0<<15)+"
                "(VBL_DAC_FINAL[SOCKET]<<10)+(VPOSP_DAC_FINAL[SOCKET]<<5)+"
                "(VNEGP_DAC_FINAL[SOCKET]<<0);"
            ),
            "s100": (
                "\t\tREG_FLASH_OP0[T_SOCKET]=(0<<15)+"
                "(VBL_DAC_FINAL[T_SOCKET]<<10)+(VPOSP_DAC_FINAL[T_SOCKET]<<5)+"
                "(VNEGP_DAC_FINAL[T_SOCKET]<<0);"
            ),
        }
        for platform, statement in expected.items():
            emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("BUILDMAP", plan, platform)
            self.assertIn(statement, emission.statements)
            body = "\n".join(emission.statements)
            self.assertIn("trim0 page address map", body)
            self.assertIn("//{1'b0,VBDAC[4:0],PRE_PDAC[4:0],PRE_NDAC[4:0]}", body)
            self.assertIn("//Default = 0xFFFF0000", body)
            self.assertEqual(
                sum("REG_FLASH_OP0" in line for line in emission.statements), 1
            )

    def test_type_wake_is_flash_window(self):
        operation = compile_flow_rows(pd.DataFrame([{
            "CP NO": "CP1", "item": "Memory_Wakeup", "type": "wake",
            "mode": "/", "FV/FI": "/",
        }]), workbook_identity="book", source_sha256="sha")[0]

        self.assertEqual((operation.typed_kind, operation.family), (
            "FLASH_WINDOW", "FLASH_WINDOW",
        ))

    def test_cp1_uses_sm_writes_and_nm_only_reads_with_canonical_counts(self):
        plan = compile_nm_loop_plan("CP1", "VCC_MAX", _flash_requests())
        runs = tuple(_runs(plan.instructions))
        nm_names = tuple(
            run.pattern.pattern.name for run in runs
            if run.pattern.pattern.name not in (
                "enter_fbist_mode", "set_all_final_vposp",
            )
        )
        repeats = tuple(
            instruction.count for instruction in plan.instructions
            if isinstance(instruction, NmLoopRepeat)
        )

        self.assertEqual(repeats, (100, 49, 100))
        self.assertTrue(nm_names)
        self.assertTrue(all(
            not name.endswith("_sm") if "_read_" in name else name.endswith("_sm")
            for name in nm_names
        ))
        self.assertEqual(
            sum(run.pattern.pattern.name == "set_all_final_vposp" for run in runs),
            2,
        )

    def test_nmloop_rejects_missing_or_ambiguous_required_pattern(self):
        requests = _flash_requests()
        missing = tuple(
            request for request in requests
            if request.output_identity != "fbist_bulk_prog_ckbd_nm_sm"
        )
        with self.assertRaises(FlashWindowCompileError) as raised:
            compile_nm_loop_plan("CP1", "VCC_MAX", missing)
        self.assertEqual(raised.exception.code, "NMLOOP.PATTERN.BINDING_MISSING")

        duplicate = requests + (
            replace(requests[0], output_identity="same_erase_semantics"),
        )
        with self.assertRaises(FlashWindowCompileError) as raised:
            compile_nm_loop_plan("CP2", "VCC_MAX", duplicate)
        self.assertEqual(
            raised.exception.code, "NMLOOP.PATTERN.BINDING_AMBIGUOUS"
        )

    def test_cp2_nmloop_requires_a_prior_clean_setvposp_snapshot(self):
        operation = _operation(0, "CP2", "FLASH_WINDOW")
        rows = {0: _recipe("NMLOOP")}

        with self.assertRaises(FlashWindowCompileError) as raised:
            compile_flash_window_plans(
                (operation,), rows, _flow("CP2"), {}, _addr_map(), _fbist_plan(),
                _flash_requests(),
            )

        self.assertEqual(raised.exception.code, "NMLOOP.SETVPOSP.NOT_READY")

    def test_cp2_consumes_snapshot_prepared_by_an_earlier_test_item(self):
        prepare = _operation(0, "CP2", "STANDARD_VERIFY")
        wake = _operation(1, "CP2", "FLASH_WINDOW")
        result = compile_flash_window_plans(
            (prepare, wake),
            {0: _recipe("SETVPOSP"), 1: _recipe("NMLOOP")},
            pd.DataFrame((
                {"CP NO": "CP2", "Vcc": "VCC_MAX"},
                {"CP NO": "CP2", "Vcc": "VCC_MAX"},
            )),
            {}, _addr_map(), _fbist_plan(), _flash_requests(),
        )

        plan = result.plans[1]
        self.assertEqual(plan.effective_recipe, ("NMLOOP",))
        names = tuple(
            run.pattern.pattern.name
            for run in _runs(plan.steps[0].module_plan.instructions)
            if run.pattern.pattern.name not in (
                "enter_fbist_mode", "set_all_final_vposp",
            )
        )
        self.assertTrue(all(not name.endswith("_sm") for name in names))

    def test_buildmap_starts_every_cp_register_from_default_then_overlays_prior_trim(self):
        wake = _operation(1, "CP1", "FLASH_WINDOW")
        prior = SimpleNamespace(
            cp="CP1", item="Vposp", dac_final_symbol="VPOSP_DAC_FINAL",
        )
        later = SimpleNamespace(
            cp="CP1", item="Iref1U", dac_final_symbol="IREF1U_DAC_FINAL",
        )
        result = compile_flash_window_plans(
            (wake,),
            {1: _recipe("BUILDMAP", "SETVPOSP", "NMLOOP")},
            pd.DataFrame((
                {"CP NO": "CP1", "item": "Vposp", "type": "trim"},
                {"CP NO": "CP1", "Vcc": "VCC_MAX"},
                {"CP NO": "CP1", "item": "Iref1U", "type": "trim"},
            )),
            {0: prior, 2: later}, _addr_map(), _fbist_plan(), _flash_requests(),
        )

        build = result.plans[1].steps[0].module_plan
        self.assertEqual(build.registers[0].default_value, 0x00A5)
        self.assertEqual(
            build.registers[0].description,
            "{Vposp[3:0],Iref1U[3:0]}",
        )
        self.assertEqual(
            tuple((write.field, write.symbol) for write in build.registers[0].writes),
            (("Vposp", "VPOSP_DAC_FINAL"),),
        )
        self.assertEqual(result.warnings[0].code, "BUILDMAP.TRIM.PRODUCER_AFTER_CONSUMER")


class SetVpospFlashPurposeTests(unittest.TestCase):
    def test_clean_prepare_for_flash_is_noop_not_run(self):
        transition = compile_set_vposp_plan(
            (PumpDacPlan("Vposp", "VPOSP_DAC_FINAL"),),
            _fbist_labels(),
            SetVpospSnapshot(prepared_items=frozenset(("vposp",))),
            swd_pin="PA13",
            run_pattern=_run_plan("set_all_final_vposp"),
            purpose=SetVpospPurpose.PREPARE_FOR_FLASH,
        )

        self.assertFalse(transition.plan.should_run)
        for platform in ("chroma", "s100"):
            emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
                "SETVPOSP", transition.plan, platform
            )
            self.assertEqual(emission.statements, ())

    def test_nmloop_is_registered_for_both_platforms(self):
        plan = compile_nm_loop_plan("CP1", "VCC_MAX", _flash_requests())
        for platform in ("chroma", "s100"):
            emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("NMLOOP", plan, platform)
            body = "\n".join(emission.statements)
            required = {
                requirement.logical_identity
                for requirement in emission.resource_requires
            }
            self.assertTrue({
                "pattern:fbist_bulk_read_ckbd_nm",
                "pattern:fbist_bulk_read_ickbd_nm",
                "pattern:fbist_bulk_read_allf_nm",
            }.issubset(required))
            self.assertTrue(all(
                not identity.endswith("_nm_sm")
                for identity in required if "_read_" in identity
            ))
            self.assertIn("I<100", body)
            self.assertIn("I<49", body)
            self.assertEqual(sum(
                "set_all_final_vposp" in statement
                and ("JUDGE_PAT(" in statement or "RUN_PATTERN(" in statement)
                for statement in emission.statements
            ), 2)


class TrimDacUseDefTests(unittest.TestCase):
    def test_declared_page_image_use_requires_a_later_exact_consumer(self):
        flow = pd.DataFrame(({
            "CP NO": "CP1", "item": "Vposp", "type": "trim",
            "OTP": "yes", "UID": "no", "PUMP": "no",
        },))
        with self.assertRaises(TrimDacUseDefError) as raised:
            validate_trim_dac_use_def(
                flow, {}, {}, SimpleNamespace(rows={})
            )
        self.assertEqual(
            raised.exception.code, "TRIM.USE_DEF.PAGE_IMAGE_UNCONSUMED"
        )

    def test_declared_pump_use_requires_a_later_same_cp_setvposp(self):
        flow = pd.DataFrame(({
            "CP NO": "CP1", "item": "Vposp", "type": "trim",
            "OTP": "no", "UID": "no", "PUMP": "yes",
        },))
        with self.assertRaises(TrimDacUseDefError) as raised:
            validate_trim_dac_use_def(
                flow,
                {0: SimpleNamespace(
                    flow=SimpleNamespace(cp="CP2"),
                    operations=(SimpleNamespace(name="SETVPOSP"),),
                )},
                {},
                SimpleNamespace(rows={}),
            )
        self.assertEqual(
            raised.exception.code, "TRIM.USE_DEF.SETVPOSP_UNCONSUMED"
        )


class FlashWindowFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook)

    def test_cp1_native_builder_closes_generated_flash_resources_without_publication(self):
        plans = tuple(self.compilation.plan.catalogs.flash_window_plans.values())
        self.assertEqual(len(plans), 1)
        self.assertEqual(
            plans[0].effective_recipe,
            ("BUILDMAP", "SETVPOSP", "NMLOOP"),
        )
        build = next(
            step.module_plan for step in plans[0].steps
            if step.module == "BUILDMAP"
        )
        register_names = {register.register.upper() for register in build.registers}
        # BUILDMAP's page-level use-def keeps these defaults for early UID PGMOTP.
        # Early LOADMAP itself excludes the Verify registers from pattern filling.
        self.assertTrue({
            "VREFINT_VERIFY",
            "VREFBUF1P024_VERIFY",
            "VREFBUF2P048_VERIFY",
            "VREFBUF2P5_VERIFY",
            "VREFBUF2P9_VERIFY",
            "VREFBUF4P096_VERIFY",
            "TS_30C_VERIFY",
        }.issubset(register_names))
        self.assertTrue({
            "TS_125C_VERIFY",
            "REDRA_CFG0",
            "HSI_8M_TRIM",
        }.issubset(register_names))
        target = TargetKey("s100", "CP1", "lab", "FLASH_WINDOW_S100_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = GeneratedPatternProducer.from_compilation(
            self.compilation,
            "s100",
            fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100"),
        )
        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "FLASH_WINDOW",
            plans,
            TypedKindContext(
                self.compilation,
                target,
                facts,
                producer,
            ),
        )
        self.assertEqual(len(assembly.contributions), 1)
        self.assertEqual(len(assembly.bodies), 1)
        generated = next(
            requirement for requirement in assembly.contributions[0].resource_requires
            if requirement.logical_identity == "pattern:fbist_bulk_prog_ckbd_nm_sm"
        )
        self.assertTrue(
            producer.produce(generated).source_identity.startswith("flash-compare:")
        )
        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
            runtime_declarations=self.compilation.for_cp("CP1").runtime_state.declarations,
        ))
        self.assertIn(
            b"Cmd[3:0]=1001 write data",
            render_plan.artifact("fbist_bulk_prog_ckbd_nm_sm.sd").content,
        )

    def test_nmloop_consumes_names_from_required_flash_requests(self):
        compilation = self.compilation.flash_compare_compilation
        renamed = tuple(
            replace(request, output_identity=f"renamed_{request.output_identity}")
            for request in compilation.requests
        )

        for cp in ("CP1", "CP2"):
            plan = compile_nm_loop_plan(cp, "VCC_MAX", renamed)
            names = tuple(
                run.pattern.pattern.name
                for run in _runs(plan.instructions)
                if run.pattern.pattern.name not in (
                    "enter_fbist_mode", "set_all_final_vposp",
                )
            )
            self.assertTrue(names)
            self.assertTrue(all(name.startswith("renamed_") for name in names))

    def test_chroma_and_s100_assemble_the_same_business_plan(self):
        plans = tuple(self.compilation.plan.catalogs.flash_window_plans.values())
        identities = []
        bodies = {}
        for platform in ("chroma", "s100"):
            target = TargetKey(
                platform, "CP1", "lab", f"FLASH_WINDOW_{platform}_CP1"
            )
            facts = compile_platform_program_facts(self.workbook, target)
            producer = GeneratedPatternProducer.from_compilation(
                self.compilation,
                platform,
                fallback=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                ),
            )
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "FLASH_WINDOW",
                plans,
                TypedKindContext(
                    self.compilation,
                    target,
                    facts,
                    producer,
                ),
            )
            identities.append(tuple(
                requirement.logical_identity
                for requirement in assembly.contributions[0].resource_requires
            ))
            flash = next(
                requirement
                for requirement in assembly.contributions[0].resource_requires
                if requirement.logical_identity == "pattern:fbist_bulk_prog_ckbd_nm_sm"
            )
            self.assertTrue(
                producer.produce(flash).source_identity.startswith("flash-compare:")
            )
            if platform == "chroma":
                render_plan = PlatformProgramBuilder(producer).build(
                    ProgramAssemblyInput(
                        target=target,
                        platform_facts=facts,
                        canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
                        contributions=assembly.contributions,
                        bodies=assembly.bodies,
                        runtime_declarations=(
                            self.compilation.for_cp("CP1").runtime_state.declarations
                        ),
                    )
                )
                self.assertIn(
                    b"Cmd[3:0]=1001 write data",
                    render_plan.artifact(
                        "pat/fbist_bulk_prog_ckbd_nm_sm.pat"
                    ).content,
                )
            bodies[platform] = assembly.bodies[0].fragment.content.decode("gbk")
        self.assertEqual(identities[0], identities[1])
        for body in bodies.values():
            self.assertIn("I<49", body)
            self.assertEqual(body.count("I<100"), 2)
        self.assertEqual(
            bodies["chroma"].count("JUDGE_PAT(set_all_final_vposp"), 2
        )
        self.assertEqual(
            bodies["s100"].count("RUN_PATTERN(set_all_final_vposp"), 2
        )
        self.assertEqual(bodies["chroma"].count("POWER_OFF();"), 2)
        self.assertEqual(bodies["s100"].count("CALL_MACRO POWER_OFF();"), 2)
        self.assertTrue(bodies["chroma"].rstrip().endswith("}"))
        self.assertTrue(bodies["s100"].rstrip().endswith("@@END_PLAN"))


def _operation(row, cp, kind):
    return FlowOperation(
        row, cp, "Memory_Wakeup" if kind == "FLASH_WINDOW" else "Prepare",
        "wake" if kind == "FLASH_WINDOW" else "verify", "/", kind, kind,
        None, WorkbookProvenance("FLOW", f"A{row + 2}", "book", "sha"),
    )


def _recipe(*modules):
    return SimpleNamespace(operations=tuple(SimpleNamespace(name=name) for name in modules))


def _flow(cp):
    return pd.DataFrame(({"CP NO": cp, "Vcc": "VCC_MAX"},))


def _addr_map():
    return compile_addr_map_catalog(pd.DataFrame(({
        "Word No.": "trim0", "line": "CP1,CP2",
        "bit[31:16]": "REG_TRIM0[15:0] complement",
        "bit[15:0]": "REG_TRIM0[15:0]", "data type": "lable",
        "CP Data[31:0]": "32'hFF5A_00A5",
        "CP addr map": "Vposp[3:0],Iref1U[3:0]",
    },)))


def _fbist_plan():
    field = FbistPatternField(
        10, 0, "VPOSP[3:0]", "vposp", 0, 4, 3, 0, "000*", True,
    )
    target = FbistPumpTarget(
        "Vposp", 10, "set_vposp_dac", "trim dac", "0000001", field,
    )
    return FbistPatternGenerationPlan(
        "book", "PA0", "PA13", (), (),
        FbistPumpAggregate("set_all_final_vposp", (), (target,)),
        ("Vposp",), (),
    )


def _fbist_labels():
    from program_gen.core.fbist_pattern_plan import compile_fbist_label_catalog
    return compile_fbist_label_catalog(_fbist_plan())


def _flash_requests():
    requests = []
    for coverage, suffix in (
        (BulkCoverage.NM_ONLY, "nm"),
        (BulkCoverage.NM_PLUS_SM, "nm_sm"),
    ):
        requests.append(FlashCompareRequest(
            f"fbist_bulk_erase_{suffix}",
            Scope.BULK,
            Operation.ERASE,
            bulk_coverage=coverage,
        ))
        for data, token in (
            (DataKind.ZERO, "all0"),
            (DataKind.PCKB, "ckbd"),
            (DataKind.NCKB, "ickbd"),
            (DataKind.ONE, "allf"),
        ):
            requests.append(FlashCompareRequest(
                f"fbist_bulk_prog_{token}_{suffix}",
                Scope.BULK,
                Operation.PROGRAM,
                data=PageData(data),
                bulk_strategy=(
                    BulkStrategy.ALL_PAGES
                    if coverage is BulkCoverage.NM_PLUS_SM
                    and data in (DataKind.ZERO, DataKind.ONE)
                    else BulkStrategy.EVEN_ODD
                ),
                bulk_coverage=coverage,
            ))
    for data, token in (
        (DataKind.PCKB, "ckbd"),
        (DataKind.NCKB, "ickbd"),
        (DataKind.ONE, "allf"),
    ):
        requests.append(FlashCompareRequest(
            f"fbist_bulk_read_{token}_nm",
            Scope.BULK,
            Operation.READ,
            data=PageData(data),
        ))
    return tuple(requests)


def _run_plan(name):
    return RunPatternPlan(
        PatternResourceRef(name, f"pattern:{name}", ("START", "END")),
        PatternSpan.full(), "TS_5MHZ",
    )


def _runs(instructions):
    for instruction in instructions:
        if isinstance(instruction, NmLoopRun):
            yield instruction
        elif isinstance(instruction, NmLoopRepeat):
            yield from instruction.runs


if __name__ == "__main__":
    unittest.main()
