"""CP2 tracer and CP3 generality proof for native TRIMDATA_READ assembly."""

import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    PlatformProgramBuilder, ProgramAssemblyInput, WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class TrimdataReadNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_master_compiles_cp2_and_cp3_without_uid_page(self):
        plans = self.compilation.plan.catalogs.trimdata_read_plans
        self.assertEqual(
            tuple((plan.cp, plan.item) for plan in plans.values()),
            (("CP2", "Trimdata_Read"), ("CP3", "Trimdata_Read")),
        )
        for platform in ("chroma", "s100"):
            for cp in ("CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    source = self._assemble(platform, cp)
                    self.assertNotIn("uid", source.casefold())
                    self.assertEqual(source.count("POWER_ON"), 2)
                    self.assertEqual(source.count("POWER_OFF"), 2)

    def test_two_fbist_sessions_enclose_capture_then_runtime_check(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                source = self._assemble(platform, "CP2")
                power_on = [index for index in range(len(source)) if source.startswith("POWER_ON", index)]
                power_off = [index for index in range(len(source)) if source.startswith("POWER_OFF", index)]
                capture = source.index("trim0_capture")
                load = source.index("fbist_page_prog_trim0")
                prepared_run = source.rindex("set_all_final_vposp")
                check = source.rindex("fbist_page_read_trim0")
                self.assertLess(power_on[0], capture)
                self.assertLess(capture, power_off[0])
                self.assertLess(power_off[0], load)
                self.assertLess(load, power_on[1])
                self.assertLess(power_on[1], prepared_run)
                self.assertLess(prepared_run, check)
                self.assertLess(check, power_off[1])

    def test_cp2_full_program_resource_graph_closes_on_both_platforms(self):
        plan = self.compilation.plan.catalogs.trimdata_read_plans[103]
        restored_pump_symbols = tuple(
            pump.sources[0].symbol
            for step in plan.steps
            if step.module == "READOTPMAP"
            for pump in step.module_plan.pumps
        )
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP2", "lab", f"TRIMDATA_READ_FULL_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                fallback = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
                producer = GeneratedPatternProducer.from_compilation(
                    self.compilation, platform, fallback=fallback,
                ).for_target(facts)
                assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                    "TRIMDATA_READ", (plan,),
                    TypedKindContext(self.compilation, target, facts, producer),
                )
                render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                    target=target,
                    platform_facts=facts,
                    canonical_schedule=self.compilation.for_cp("CP2").canonical_schedule,
                    contributions=assembly.contributions,
                    bodies=assembly.bodies,
                    runtime_declarations=self.compilation.for_cp("CP2").runtime_state.declarations,
                ))
                self.assertGreater(len(render_plan.artifacts), 1)
                extension = "pln" if platform == "chroma" else "prg"
                source = render_plan.artifact(
                    f"{target.program_name}.{extension}"
                ).content.decode("gbk")
                for symbol in restored_pump_symbols:
                    self.assertEqual(
                        source.count(f"{symbol}[MAX_SITE]"),
                        1,
                        symbol,
                    )

    def test_capture_and_pattern_write_sections_are_visually_separated(self):
        plan = self.compilation.plan.catalogs.trimdata_read_plans[103]
        load_map = next(step.module_plan for step in plan.steps if step.module == "LOADMAP")
        for platform, indent in (("chroma", "  "), ("s100", "\t")):
            with self.subTest(platform=platform):
                source = self._assemble(platform, "CP2").replace("\r\n", "\n")
                self.assertIn(f"\n\n{indent}// trim1 candidate Page Image capture", source)
                self.assertIn(f"\n\n{indent}// factory23 candidate Page Image capture", source)
                self.assertIn(
                    f"\n\n{indent}// ==================== Restore captured DAC values ====================",
                    source,
                )
                self.assertEqual(
                    source.count(" pattern overwrite ===================="),
                    len(load_map.targets) + len(load_map.word_writes) + len(load_map.field_values)
                    + bool(load_map.field_values),
                )
                self.assertIn(
                    "// ==================== trim0 / FLASH_OP0 pattern overwrite ====================",
                    source,
                )

    def _assemble(self, platform, cp):
        target = TargetKey(platform, cp, "lab", f"TRIMDATA_READ_{platform}_{cp}")
        plan = next(
            plan for plan in self.compilation.plan.catalogs.trimdata_read_plans.values()
            if plan.cp == cp
        )
        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "TRIMDATA_READ", (plan,),
            TypedKindContext(
                self.compilation,
                target,
                compile_platform_program_facts(self.workbook, target),
                WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform),
            ),
        )
        self.assertEqual(assembly.contributions[0].definitions[0].typed_kind, "TRIMDATA_READ")
        return assembly.bodies[0].fragment.content.decode("gbk")


if __name__ == "__main__":
    unittest.main()
