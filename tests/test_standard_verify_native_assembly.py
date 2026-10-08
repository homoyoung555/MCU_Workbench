"""Tracer A: CP3 Hsi_Pre_Check native STANDARD_VERIFY assembly."""

from pathlib import Path
from dataclasses import replace
from collections import Counter
import unittest
from unittest.mock import patch

from flow_recipe import RecipeValueToken

from program_gen.compiler import ProductCompiler
from program_gen.core.verify_modules import EnterPlan, JudgePlan
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.core.commit_module import compile_commit_module_plan
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
)
from program_gen.core.standard_verify import (
    ShmooExecutionPlan,
    StandardVerifyStep,
)
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.render_plan import RenderSymbolRef, TargetKey
from program_gen.standard_verify_assembly import compile_standard_verify_assembly
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class StandardVerifyNativeAssemblyTracerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Node 8 deliberately rejects the formal CP2/Vrefint bare EXPORT.
        # Node 9 assembles the already compiled legacy 57-row fixture only.
        cls._use_def = patch("program_gen.compiler.validate_export_use_def")
        cls._use_def.start()
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = next(
            plan
            for plan in cls.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP3" and plan.item == "Hsi_Pre_Check"
        )

    @classmethod
    def tearDownClass(cls):
        cls._use_def.stop()

    def test_upper_plan_owns_all_tracer_module_facts(self):
        self.assertEqual(self.plan.initial_power_profile, "VCC_MAX")
        self.assertEqual(self.plan.relay, "/")
        self.assertEqual(self.plan.test_number, 17700)
        self.assertEqual(self.plan.protocol_enter.pattern.name, "enter_fbist_mode")
        self.assertEqual(self.plan.protocol_exit.pattern.name, "exit_fbist_mode")
        self.assertIsInstance(self.plan.steps[0].module_plan, EnterPlan)
        self.assertIsInstance(self.plan.steps[1].module_plan, JudgePlan)
        judge = self.plan.steps[1].module_plan.measurement
        self.assertEqual(
            (judge.pin, judge.low_limit, judge.high_limit, judge.unit),
            ("TP", 124.5, 125.5, "KHz"),
        )

    def test_tracer_assembles_from_plan_for_both_platforms(self):
        for platform, extension, expected in (
            ("chroma", ".pln", "JUDGE_FREQ(TP"),
            ("s100", ".prg", "LOGIC_TMU_MEAS_FREQ"),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP3", "lab", f"SV_TRACER_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                producer = WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                )
                assembly = compile_standard_verify_assembly(
                    (self.plan,),
                    TypedKindContext(self.compilation, target, facts, producer),
                )

                self.assertEqual(assembly.typed_kind, "STANDARD_VERIFY")
                self.assertEqual(len(assembly.contributions), 1)
                self.assertEqual(len(assembly.bodies), 1)
                body = assembly.bodies[0].fragment.content.decode("gbk")
                self.assertIn("enter_fbist_mode", body)
                self.assertIn("enter_hsi_pre_check_verify", body)
                self.assertIn(expected, body)
                self.assertIn("exit_fbist_mode", body)
                if platform == "chroma":
                    self.assertIn(
                        "\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);", body
                    )
                    self.assertIn(
                        "\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);", body
                    )
                    self.assertIn("POWER_ON(VCC_MAX);", body)
                    self.assertIn("SET_TFTM_MODE(TP, SCHMITT_OFF);", body)
                    self.assertIn("POWER_OFF();", body)
                else:
                    self.assertIn(
                        "@@PLAN Hsi_Pre_Check_Verify\r\n"
                        "\tSITE_SEQUENCE      = OFF;\r\n"
                        "\tGO_THROUGH         = ON;\r\n"
                        "\tDISABLE_BY_MARK_NO = NULL;\r\n"
                        "\tS_SETUP_FILE       = c:\\set.dat;\r\n"
                        "\tREMARK             = Hsi_Pre_Check_Verify;\r\n",
                        body,
                    )
                    self.assertNotIn("@@PLAN Hsi_Pre_Check_Verify\r\n{", body)
                    self.assertIn(
                        "\n\tRUN_PATTERN(enter_fbist_mode:START,", body
                    )
                    self.assertIn(
                        "\n\tRUN_PATTERN(exit_fbist_mode:START,", body
                    )
                    self.assertIn("CALL_MACRO POWER_ON(_C_VCC_MAX);", body)
                    self.assertIn("CALL_MACRO POWER_OFF();", body)
                    self.assertIn("REJECT_BIN = 26;", body)
                    self.assertIn("@@END_PLAN", body)
                self.assertEqual(
                    assembly.bodies[0].fragment.artifact_path,
                    f"{target.program_name}{extension}",
                )

    def test_native_assembly_does_not_read_workbook_or_legacy_writers(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "program_gen"
            / "standard_verify_assembly.py"
        ).read_text(encoding="utf-8").casefold()
        for forbidden in (".dataframe(", "platforms.chroma.writers", "platforms.s100.writers"):
            self.assertNotIn(forbidden, source)

    def test_native_assembly_rejects_a_recipe_step_without_compiled_plan(self):
        broken_step = replace(self.plan.steps[0], module_plan=None)
        broken_plan = replace(
            self.plan,
            steps=(broken_step, *self.plan.steps[1:]),
        )
        target = TargetKey("chroma", "CP3", "lab", "SV_BROKEN")
        facts = compile_platform_program_facts(self.workbook, target)

        with self.assertRaisesRegex(
            ValueError, "SV.ASSEMBLY.MODULE_PLAN_MISSING.*ENTER"
        ):
            compile_standard_verify_assembly(
                (broken_plan,),
                TypedKindContext(
                    self.compilation,
                    target,
                    facts,
                    WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma"),
                ),
            )

    def test_all_formal_standard_verify_plans_assemble_once_per_schedule_entry(self):
        plans = tuple(self.compilation.plan.catalogs.standard_verify_plans.values())
        self.assertEqual(len(plans), 59)
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                cp_plans = tuple(plan for plan in plans if plan.cp == cp)
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"SV_ALL_{platform}_{cp}")
                    facts = compile_platform_program_facts(self.workbook, target)
                    assembly = compile_standard_verify_assembly(
                        cp_plans,
                        TypedKindContext(
                            self.compilation, target, facts,
                            WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform),
                        ),
                    )
                    self.assertEqual(len(assembly.contributions), len(cp_plans))
                    self.assertEqual(len(assembly.bodies), len(cp_plans))

    def test_shmoo_modifier_loops_one_complete_session_per_point_and_restores(self):
        for row, point_count, pass_fail in ((40, 8, False), (110, 3, True)):
            plan = self.compilation.plan.catalogs.standard_verify_plans[row]
            for platform in ("chroma", "s100"):
                with self.subTest(row=row, platform=platform):
                    target = TargetKey(
                        platform, plan.cp, "lab", f"SV_SHMOO_{platform}_{plan.cp}"
                    )
                    facts = compile_platform_program_facts(self.workbook, target)
                    assembly = compile_standard_verify_assembly(
                        (plan,),
                        TypedKindContext(
                            self.compilation, target, facts,
                            WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform),
                        ),
                    )
                    body = assembly.bodies[0].fragment.content.decode("gbk")
                    power_on = (
                        "POWER_ON(VCC_TYP);" if platform == "chroma"
                        else "CALL_MACRO POWER_ON(_C_VCC_TYP);"
                    )
                    self.assertEqual(body.count(power_on), 1)
                    self.assertEqual(body.count("POWER_OFF"), 1)
                    self.assertIn(
                        f"for(int shmoo_index=0;shmoo_index<{point_count};shmoo_index++)",
                        body,
                    )
                    self.assertEqual(
                        body.count("WRITE_PAT_MEM" if platform == "chroma"
                                   else "LOGIC_WRITE_PATTERN_MEMORY"),
                        2,
                    )
                    self.assertIn("Mr_VDDD_DC_dac0", body)
                    if platform == "s100":
                        self.assertNotIn(
                            "C_ASSIGN(GB1,shmoo_step[shmoo_index]);", body
                        )
                        for index, point in enumerate(plan.shmoo.points):
                            self.assertIn(
                                f"case {index}: C_ASSIGN(GB1,{point.step}); break;",
                                body,
                            )
                        self.assertEqual("REJECT_BIN" in body, pass_fail)
                    if not pass_fail and platform == "chroma":
                        self.assertEqual(
                            body.count("PLAN_RESULT_MS[SOCKET]=PASS"), 1
                        )

    def test_dac_write_can_consume_step_without_executing_the_restore_pattern(self):
        base = self.compilation.plan.catalogs.standard_verify_plans[109]
        scan = self.compilation.plan.catalogs.standard_verify_plans[110]
        dac = base.steps[1].module_plan
        points = tuple(
            replace(point, steps=base.steps) for point in scan.shmoo.points
        )
        plan = replace(
            scan,
            steps=base.steps,
            effective_recipe=base.effective_recipe,
            shmoo=ShmooExecutionPlan(
                "DAC_WRITE", 1, dac.target.bit_width, 0, True, points
            ),
        )
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP2", "lab", f"SV_DAC_SHMOO_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                assembly = compile_standard_verify_assembly(
                    (plan,),
                    TypedKindContext(
                        self.compilation, target, facts,
                        WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform),
                    ),
                )
                body = assembly.bodies[0].fragment.content.decode("gbk")
                run_token = (
                    "JUDGE_PAT(set_mr_vddd_dc_dac"
                    if platform == "chroma" else
                    "RUN_PATTERN(set_mr_vddd_dc_dac:START"
                )
                self.assertEqual(body.count(run_token), len(points))
                self.assertEqual(
                    body.count("WRITE_PAT_MEM" if platform == "chroma"
                               else "LOGIC_WRITE_PATTERN_MEMORY"),
                    len(points) * 2,
                )

    def test_formal_59_plans_cover_ordinary_and_shmoo_profiles(self):
        profiles = Counter()
        for plan in self.compilation.plan.catalogs.standard_verify_plans.values():
            modules = set(plan.effective_recipe)
            judge = next(
                step.module_plan for step in plan.steps if step.module == "JUDGE"
            )
            measurement = judge.measurement
            export = next(
                (step.module_plan for step in plan.steps if step.module == "EXPORT"),
                None,
            )
            if "DAC_WRITE" in modules:
                profile = "DAC_WRITE_PPMU"
            elif export is not None:
                profile = f"EXPORT_{export.format.value}"
                if judge.pe_window is not None:
                    profile += f"_{judge.pe_window.kind.value}"
            elif measurement.kind is JudgeMeasurementKind.FREQUENCY:
                profile = "FREQ"
                if judge.pe_window is not None:
                    profile += f"_{judge.pe_window.kind.value}"
            elif measurement.limit_source.startswith("VERSION:"):
                profile = f"VERSION_{judge.pe_window.kind.value}"
            elif (
                measurement.kind is JudgeMeasurementKind.CURRENT
                and measurement.force.casefold() != "0v"
            ):
                profile = "PPMU_RESTORE"
            elif judge.pe_window is not None:
                profile = f"PPMU_{judge.pe_window.kind.value}"
            else:
                profile = "PPMU"
            profiles[profile] += 1

        self.assertEqual(profiles, Counter({
            "DAC_WRITE_PPMU": 2,
            "FREQ": 11,
            "FREQ_ERASE": 2,
            "PPMU": 21,
            "PPMU_RESTORE": 4,
            "PPMU_ERASE": 1,
            "VERSION_ERASE": 4,
            "PPMU_PROGRAM": 2,
            "VERSION_PROGRAM": 4,
            "EXPORT_ADC12_3V3": 2,
            "EXPORT_BCD16_MV": 5,
            "EXPORT_BCD16_MV_ERASE": 1,
        }))

    def test_all_formal_assemblies_close_in_the_platform_program_builder(self):
        plans = tuple(self.compilation.plan.catalogs.standard_verify_plans.values())
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"SV_CLOSE_{platform}_{cp}")
                    facts = compile_platform_program_facts(self.workbook, target)
                    producer = WorkspacePatternProducer(
                        WORKSPACE_ROOT / "input" / platform
                    )
                    assembly = compile_standard_verify_assembly(
                        tuple(plan for plan in plans if plan.cp == cp),
                        TypedKindContext(self.compilation, target, facts, producer),
                    )
                    render = PlatformProgramBuilder(producer).build(
                        ProgramAssemblyInput(
                            target=target,
                            platform_facts=facts,
                            canonical_schedule=(
                                self.compilation.for_cp(cp).canonical_schedule
                            ),
                            contributions=assembly.contributions,
                            bodies=assembly.bodies,
                            runtime_declarations=(
                                self.compilation.for_cp(cp).runtime_state.declarations
                            ),
                        )
                    )
                    self.assertEqual(len(assembly.bodies), sum(
                        plan.cp == cp for plan in plans
                    ))
                    self.assertIsNotNone(render.artifact(
                        f"{target.program_name}{'.pln' if platform == 'chroma' else '.prg'}"
                    ))

    def test_both_platforms_restore_the_four_nonzero_current_force_rows(self):
        plans = tuple(self.compilation.plan.catalogs.standard_verify_plans.values())
        for cp in ("CP1", "CP2"):
            for item in ("Isa", "Ihvpl"):
                for platform in ("chroma", "s100"):
                    with self.subTest(cp=cp, item=item, platform=platform):
                        plan = next(
                            plan for plan in plans if plan.cp == cp and plan.item == item
                        )
                        target = TargetKey(
                            platform, cp, "lab", f"SV_RESTORE_{cp}_{item}"
                        )
                        facts = compile_platform_program_facts(self.workbook, target)
                        assembly = compile_standard_verify_assembly(
                            (plan,),
                            TypedKindContext(
                                self.compilation,
                                target,
                                facts,
                                WorkspacePatternProducer(
                                    WORKSPACE_ROOT / "input" / platform
                                ),
                            ),
                        )
                        body = assembly.bodies[0].fragment.content.decode("gbk")
                        exit_pattern, restore = (
                            ("JUDGE_PAT(exit_fbist_mode", "FORCE_V_PPMU(TP, 0V")
                            if platform == "chroma"
                            else (
                                "RUN_PATTERN(exit_fbist_mode:START",
                                "LOGIC_PPMU_FV(TP, 0V, E2, I5);",
                            )
                        )
                        self.assertGreater(body.index(restore), body.index(exit_pattern))

    def test_commit_step_closes_runtime_rmw_and_two_pattern_resources(self):
        base = next(
            plan
            for plan in self.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP1" and plan.item == "Vrefint"
        )
        operation = PersistenceOperation(
            "COMMIT", base.excel_row, ("trim1",), ("trim1",),
            (PersistenceFieldWrite(
                "Mr_VDDD_DC", "trim1", "PMU_TRIM2", 4, 4,
                RecipeValueToken("DECIMAL", "3"),
            ),),
            "EXPLICIT",
        )
        commit = compile_commit_module_plan(
            operation,
            self.compilation.plan.catalogs.addr_map,
            cp="CP1",
            swd_pin=self.compilation.plan.catalogs.fbist_pattern_plan.swd_pin,
            flash_labels=self.compilation.flash_label_plan.contract,
        )
        plan = replace(
            base,
            effective_recipe=(*base.effective_recipe, "COMMIT"),
            steps=(*base.steps, StandardVerifyStep(
                "COMMIT", len(base.steps), module_plan=commit
            )),
        )

        for platform, rmw in (
            ("chroma", "REG_PMU_TRIM2[SOCKET]=(REG_PMU_TRIM2[SOCKET]&0xFF0F)"),
            ("s100", "REG_PMU_TRIM2[T_SOCKET]=(REG_PMU_TRIM2[T_SOCKET]&0xFF0F)"),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", f"SV_COMMIT_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                producer = WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                )
                assembly = compile_standard_verify_assembly(
                    (plan,), TypedKindContext(self.compilation, target, facts, producer)
                )
                render = PlatformProgramBuilder(producer).build(
                    ProgramAssemblyInput(
                        target=target,
                        platform_facts=facts,
                        canonical_schedule=(
                            self.compilation.for_cp("CP1").canonical_schedule
                        ),
                        contributions=assembly.contributions,
                        bodies=assembly.bodies,
                        runtime_declarations=(
                            self.compilation.for_cp("CP1").runtime_state.declarations
                        ),
                    )
                )
                extension = ".pln" if platform == "chroma" else ".prg"
                source = render.artifact(
                    f"{target.program_name}{extension}"
                ).content.decode("gbk")
                self.assertIn(rmw, source)
                self.assertIsNotNone(render.artifact(
                    "pat/fbist_page_prog_trim1.pat"
                    if platform == "chroma"
                    else "fbist_page_prog_trim1.sd"
                ))
                self.assertIsNotNone(render.artifact(
                    "pat/fbist_page_read_trim1.pat"
                    if platform == "chroma"
                    else "fbist_page_read_trim1.sd"
                ))
                self.assertNotIn("fbist_page_prog_trim1:START", source)

    def test_cp1_vrefint_export_closes_bcd16_result_for_both_platforms(self):
        plan = next(
            item
            for item in self.compilation.plan.catalogs.standard_verify_plans.values()
            if item.cp == "CP1" and item.item == "Vrefint"
        )
        self.assertEqual(plan.effective_recipe, ("ENTER", "JUDGE", "EXPORT"))
        self.assertEqual(
            plan.steps[-1].module_plan.semantic_identity,
            "CP1:VREFINT_EXPORT",
        )

        for platform, extension, encoded in (
            (
                "chroma", ".pln",
                "VREFINT_EXPORT[SOCKET]=(int)(RESULT_PIN(SOCKET, TP)*1000+0.5);",
            ),
            (
                "s100", ".prg",
                "VREFINT_EXPORT[T_SOCKET]=(int)(GB[5+T_SOCKET*64]*1000+0.5);",
            ),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", f"SV_VREFINT_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
                assembly = compile_standard_verify_assembly(
                    (plan,), TypedKindContext(self.compilation, target, facts, producer)
                )
                self.assertIn(
                    RenderSymbolRef("RESULT", "CP1:VREFINT_EXPORT"),
                    tuple(item.ref for item in assembly.contributions[0].provides),
                )
                render = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                    target=target,
                    platform_facts=facts,
                    canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
                    contributions=assembly.contributions,
                    bodies=assembly.bodies,
                    runtime_declarations=(
                        self.compilation.for_cp("CP1").runtime_state.declarations
                    ),
                ))
                source = render.artifact(
                    f"{target.program_name}{extension}"
                ).content.decode("gbk")

                self.assertIn("VREFINT_EXPORT[MAX_SITE]", source)
                self.assertIn(encoded, source)
                judge_token = (
                    "JUDGE_V_PPMU(TP" if platform == "chroma"
                    else "LOGIC_PPMU_MV(TP"
                )
                self.assertLess(source.index(judge_token), source.index(encoded))
                if platform == "chroma":
                    self.assertLess(
                        source.index("RELAY_ON(TP,PPMU_PDCL,2mS);"),
                        source.index("JUDGE_V_PPMU(TP"),
                    )
                    self.assertIn("RELAY_OFF(TP, PPMU_PDCL, 2mS);", source)
                    tail = source[source.index("JUDGE_PAT(exit_fbist_mode"):]
                    self.assertNotIn("FORCE_V_PPMU(TP, 0V", tail)
                    self.assertNotIn("FORCE_I_PPMU(TP, 0uA", tail)

    def test_erase_and_program_pe_windows_wrap_judge_with_segmented_run(self):
        for item, expected_kind in (("Vpose", "ERASE"), ("Vbl", "PROGRAM")):
            plan = next(
                candidate
                for candidate in self.compilation.plan.catalogs.standard_verify_plans.values()
                if candidate.cp == "CP1" and candidate.item == item
            )
            judge = next(
                step.module_plan for step in plan.steps if step.module == "JUDGE"
            )
            self.assertEqual(judge.pe_window.kind.value, expected_kind)
            pattern = judge.pe_window.before.pattern.name

            for platform in ("chroma", "s100"):
                with self.subTest(item=item, platform=platform):
                    target = TargetKey(platform, "CP1", "lab", f"PE_{item}_{platform}")
                    facts = compile_platform_program_facts(self.workbook, target)
                    producer = WorkspacePatternProducer(
                        WORKSPACE_ROOT / "input" / platform
                    )
                    assembly = compile_standard_verify_assembly(
                        (plan,),
                        TypedKindContext(self.compilation, target, facts, producer),
                    )
                    body = assembly.bodies[0].fragment.content.decode("gbk")
                    if platform == "chroma":
                        before = f"JUDGE_PAT({pattern},{pattern}:pe_1);"
                        measure = "JUDGE_V_PPMU("
                        after = f"JUDGE_PAT({pattern}:pe_1,__{pattern});"
                    else:
                        before = (
                            f"RUN_PATTERN({pattern}:START,{pattern}:pe_1,1,TS_5MHZ);"
                        )
                        measure = "LOGIC_PPMU_MV("
                        after = (
                            f"RUN_PATTERN({pattern}:pe_1,{pattern}:END,1,TS_5MHZ);"
                        )
                    self.assertLess(body.index(before), body.index(measure))
                    self.assertLess(body.index(measure), body.index(after))
                    self.assertTrue(any(
                        requirement.logical_identity == f"pattern:{pattern}"
                        for requirement in assembly.contributions[0].resource_requires
                    ))


if __name__ == "__main__":
    unittest.main()
