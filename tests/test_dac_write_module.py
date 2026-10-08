"""Public Interface tests for the shared DAC_WRITE Recipe Module."""

from __future__ import annotations

from dataclasses import replace
import unittest

from flow_recipe import DacWritePlanSet
from program_gen.compiler import ProductCompiler
from program_gen.core.dac_write import compile_dac_write_module_plans
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.platforms.chroma.fbist_pattern_generator import (
    generate_fbist_patterns as generate_chroma_patterns,
)
from program_gen.platforms.s100.fbist_pattern_generator import (
    generate_fbist_patterns as generate_s100_patterns,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.standard_verify_assembly import compile_standard_verify_assembly
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class DacWriteModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    @classmethod
    def _cp2_plan(cls):
        verify = next(
            plan
            for plan in cls.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP2" and plan.item == "Mr_VDDD_DC"
        )
        return next(
            step.module_plan for step in verify.steps if step.module == "DAC_WRITE"
        )

    @classmethod
    def _cp2_verify(cls):
        return next(
            plan
            for plan in cls.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP2" and plan.item == "Mr_VDDD_DC"
        )

    def test_cp2_mr_vddd_compiles_restored_dac_and_generated_pattern_target(self):
        dac_write = self._cp2_plan()

        self.assertEqual(dac_write.source.symbol, "MR_VDDD_DC_DAC_FINAL")
        self.assertEqual(dac_write.source.register_symbol, "REG_PMU_TRIM2")
        self.assertEqual((dac_write.source.bit_lsb, dac_write.source.bit_width), (4, 4))
        self.assertEqual(
            (dac_write.source.page, dac_write.source.restored_at_excel_row),
            ("trim1", 105),
        )
        self.assertEqual(dac_write.target.pattern.name, "set_mr_vddd_dc_dac")
        self.assertEqual(dac_write.target.chroma_start_label, "a_data")
        self.assertEqual(
            (dac_write.target.s100_start_label, dac_write.target.s100_end_label),
            ("a_data_st", "a_data_sp"),
        )
        self.assertEqual(dac_write.swd_pin, "PA13")
        self.assertIs(dac_write.run_pattern.pattern, dac_write.target.pattern)

    def test_mr_vddd_enter_role_uses_trim_mode_pattern_for_both_cps(self):
        for cp in ("CP1", "CP2"):
            with self.subTest(cp=cp):
                verify = next(
                    plan
                    for plan in self.compilation.plan.catalogs.standard_verify_plans.values()
                    if plan.cp == cp and plan.item == "Mr_VDDD_DC"
                )
                enter = next(
                    step for step in verify.steps if step.module == "ENTER"
                )
                self.assertEqual(enter.pattern_role, "trim mode")
                self.assertEqual(
                    enter.module_plan.pattern.name, "enter_mr_vddd_dc"
                )

    def test_chroma_restores_each_site_writes_generated_label_and_runs_once(self):
        emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "DAC_WRITE", self._cp2_plan(), "chroma"
        )
        text = "\n".join(emission.statements)

        self.assertIn(
            "MR_VDDD_DC_DAC_FINAL[SOCKET]=(REG_PMU_TRIM2[SOCKET]&0x00F0)>>4;",
            text,
        )
        self.assertIn(
            "convert_to_string(MR_VDDD_DC_DAC_FINAL[SOCKET],4,", text
        )
        self.assertIn(
            "WRITE_PAT_MEM(SOCKET,PA13,set_mr_vddd_dc_dac:a_data+I,,BUFF_W_P[I]);",
            text,
        )
        self.assertEqual(
            text.count("JUDGE_PAT(set_mr_vddd_dc_dac,__set_mr_vddd_dc_dac);"),
            1,
        )
        self.assertEqual(
            tuple(item.logical_identity for item in emission.resource_requires),
            ("pattern:set_mr_vddd_dc_dac",),
        )

    def test_s100_restores_each_site_writes_generated_range_and_runs_once(self):
        emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "DAC_WRITE", self._cp2_plan(), "s100"
        )
        text = "\n".join(emission.statements)

        self.assertIn(
            "MR_VDDD_DC_DAC_FINAL[T_SOCKET]=(REG_PMU_TRIM2[T_SOCKET]&0x00F0)>>4;",
            text,
        )
        self.assertIn(
            "CALL_MACRO write_pat_temp_arry(MR_VDDD_DC_DAC_FINAL);", text
        )
        self.assertIn(
            "LOGIC_WRITE_PATTERN_MEMORY(set_mr_vddd_dc_dac:a_data_st,"
            "set_mr_vddd_dc_dac:a_data_sp,PA13,GB1,BIT_COUNT=4,SERIAL,MSB_LSB);",
            text,
        )
        self.assertEqual(
            text.count(
                "RUN_PATTERN(set_mr_vddd_dc_dac:START,"
                "set_mr_vddd_dc_dac:END,1,TS_5MHZ);"
            ),
            1,
        )
        self.assertEqual(
            tuple(item.logical_identity for item in emission.resource_requires),
            ("pattern:set_mr_vddd_dc_dac",),
        )

    def test_cp2_native_program_closes_declarations_order_and_generated_pattern(self):
        fbist = self.compilation.plan.catalogs.fbist_pattern_plan
        for platform, extension, generator, restore, run, judge in (
            (
                "chroma", ".pln", generate_chroma_patterns,
                "MR_VDDD_DC_DAC_FINAL[SOCKET]=(REG_PMU_TRIM2[SOCKET]&0x00F0)>>4;",
                "JUDGE_PAT(set_mr_vddd_dc_dac,__set_mr_vddd_dc_dac);",
                "JUDGE_V_PPMU(TP",
            ),
            (
                "s100", ".prg", generate_s100_patterns,
                "MR_VDDD_DC_DAC_FINAL[T_SOCKET]=(REG_PMU_TRIM2[T_SOCKET]&0x00F0)>>4;",
                "RUN_PATTERN(set_mr_vddd_dc_dac:START,",
                "LOGIC_PPMU_MV(TP",
            ),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(
                    platform, "CP2", "lab", f"SV_DAC_WRITE_CP2_{platform}"
                )
                facts = compile_platform_program_facts(self.workbook, target)
                producer = GeneratedPatternProducer(
                    generator(fbist),
                    fallback=WorkspacePatternProducer(
                        WORKSPACE_ROOT / "input" / platform
                    ),
                )
                assembly = compile_standard_verify_assembly(
                    (self._cp2_verify(),),
                    TypedKindContext(self.compilation, target, facts, producer),
                )
                render = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                    target=target,
                    platform_facts=facts,
                    canonical_schedule=(
                        self.compilation.for_cp("CP2").canonical_schedule
                    ),
                    contributions=assembly.contributions,
                    bodies=assembly.bodies,
                    runtime_declarations=(
                        self.compilation.for_cp("CP2").runtime_state.declarations
                    ),
                ))
                source = render.artifact(
                    f"{target.program_name}{extension}"
                ).content.decode("gbk")

                self.assertIn("MR_VDDD_DC_DAC_FINAL[MAX_SITE]", source)
                self.assertIn("REG_PMU_TRIM2[MAX_SITE]", source)
                self.assertLess(source.index(restore), source.index(run))
                self.assertLess(source.index(run), source.index(judge))
                pattern_path = (
                    "pat/set_mr_vddd_dc_dac.pat"
                    if platform == "chroma" else "set_mr_vddd_dc_dac.sd"
                )
                self.assertTrue(render.artifact(pattern_path).content)

    def test_cp1_live_dac_final_is_written_without_register_restore(self):
        verify = next(
            plan
            for plan in self.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP1" and plan.item == "Mr_VDDD_DC"
        )
        dac_write = next(
            step.module_plan for step in verify.steps if step.module == "DAC_WRITE"
        )

        self.assertEqual(dac_write.source.kind.value, "DAC_FINAL")
        self.assertIsNone(dac_write.source.register_symbol)
        self.assertEqual(dac_write.source.produced_at_excel_row, 7)
        for platform in ("chroma", "s100"):
            text = "\n".join(
                NATIVE_RECIPE_MODULE_REGISTRY.emit(
                    "DAC_WRITE", dac_write, platform
                ).statements
            )
            self.assertNotIn("REG_PMU_TRIM2", text)
            self.assertIn("MR_VDDD_DC_DAC_FINAL", text)

    def test_cp1_native_structure_uses_live_dac_after_trim_mode_enter(self):
        verify = next(
            plan
            for plan in self.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP1" and plan.item == "Mr_VDDD_DC"
        )
        fbist = self.compilation.plan.catalogs.fbist_pattern_plan
        for platform, generator, enter, write, run, judge in (
            (
                "chroma", generate_chroma_patterns,
                "JUDGE_PAT(enter_mr_vddd_dc,__enter_mr_vddd_dc);",
                "convert_to_string(MR_VDDD_DC_DAC_FINAL[SOCKET],4,",
                "JUDGE_PAT(set_mr_vddd_dc_dac,__set_mr_vddd_dc_dac);",
                "JUDGE_V_PPMU(TP",
            ),
            (
                "s100", generate_s100_patterns,
                "RUN_PATTERN(enter_mr_vddd_dc:START,",
                "CALL_MACRO write_pat_temp_arry(MR_VDDD_DC_DAC_FINAL);",
                "RUN_PATTERN(set_mr_vddd_dc_dac:START,",
                "LOGIC_PPMU_MV(TP",
            ),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", f"CP1_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                producer = GeneratedPatternProducer(
                    generator(fbist),
                    fallback=WorkspacePatternProducer(
                        WORKSPACE_ROOT / "input" / platform
                    ),
                )
                assembly = compile_standard_verify_assembly(
                    (verify,),
                    TypedKindContext(self.compilation, target, facts, producer),
                )
                body = assembly.bodies[0].fragment.content.decode("gbk")

                self.assertNotIn("enter_mr_vddd_dc_verify", body)
                self.assertNotIn("REG_PMU_TRIM2", body)
                self.assertLess(body.index(enter), body.index(write))
                self.assertLess(body.index(write), body.index(run))
                self.assertLess(body.index(run), body.index(judge))

    def test_explicit_binary_value_is_site_scoped_without_addr_map_restore(self):
        legacy = replace(
            self.compilation.for_cp("CP2").dac_write_plans.for_row(109),
            value_source="ARGUMENT",
            value="0011",
            needs_global_variable=False,
        )
        plan = compile_dac_write_module_plans(
            DacWritePlanSet((legacy,)),
            self.compilation.plan.catalogs.addr_map,
            self.compilation.plan.catalogs.fbist_pattern_plan,
            "CP2",
        )[109]

        self.assertEqual(plan.source.literal, 3)
        for platform, site in (("chroma", "SOCKET"), ("s100", "T_SOCKET")):
            text = "\n".join(
                NATIVE_RECIPE_MODULE_REGISTRY.emit(
                    "DAC_WRITE", plan, platform
                ).statements
            )
            self.assertIn(f"dacWriteData[{site}]=3;", text)
            self.assertNotIn("REG_PMU_TRIM2", text)


if __name__ == "__main__":
    unittest.main()
