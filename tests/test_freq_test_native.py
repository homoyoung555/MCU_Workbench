import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import PlatformProgramBuilder, ProgramAssemblyInput, WorkspacePatternProducer
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class FreqTestNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plans = tuple(cls.compilation.plan.catalogs.freq_test_plans.values())

    def test_registered_slice_closes_on_both_platforms_with_fourteen_stubs(self):
        self.assertIn("FREQ_TEST", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma", "s100"):
            target = TargetKey(platform, "CP3", "lab", f"FREQ_{platform}")
            facts = compile_platform_program_facts(self.workbook, target)
            producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "FREQ_TEST", self.plans,
                TypedKindContext(self.compilation, target, facts, producer),
            )
            rendered = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                target, facts, self.compilation.for_cp("CP3").canonical_schedule,
                assembly.contributions, assembly.bodies,
            ))
            extension = ".pln" if platform == "chroma" else ".prg"
            program = rendered.artifact(target.program_name + extension).content
            self.assertIn(b"Clock_Check_Test", program)
            self.assertIn(b"Hse_Test", program)
            self.assertIn(b"Pll_Test", program)
            self.assertEqual(sum(
                b"STUB: no real FREQ configuration vector" in artifact.content
                for artifact in rendered.artifacts
            ), 14)
            self.assertIn(b"PD0", program)


if __name__ == "__main__":
    unittest.main()
