import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
)
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class VihVilNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plans = tuple(cls.compilation.plan.catalogs.vih_vil_plans.values())

    def test_registered_swd_slice_closes_on_both_platforms_with_five_stubs(self):
        self.assertIn("DC_VIH_VIL", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma", "s100"):
            target = TargetKey(platform, "CP3", "lab", f"VIHVIL_{platform}")
            facts = compile_platform_program_facts(self.workbook, target)
            producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "DC_VIH_VIL", self.plans,
                TypedKindContext(self.compilation, target, facts, producer),
            )
            rendered = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                target, facts, self.compilation.for_cp("CP3").canonical_schedule,
                assembly.contributions, assembly.bodies,
            ))
            extension = ".pln" if platform == "chroma" else ".prg"
            program = rendered.artifact(target.program_name + extension).content
            self.assertIn(b"Dc_Vihvil_Test", program)
            self.assertIn(b"VILVIH_ODD", program)
            self.assertIn(b"VILVIH_EVEN", program)
            self.assertEqual(sum(
                b"STUB: no real VIH/VIL SWD vector" in artifact.content
                for artifact in rendered.artifacts
            ), 5)

    def test_vih_vil_groups_follow_pad_number_parity_and_exclusions(self):
        facts = compile_platform_program_facts(
            self.workbook, TargetKey("chroma", "CP3", "lab", "VIHVIL_GROUPS")
        )
        groups = facts.pin_groups
        excluded = {"NRST", "TP", facts.swd_pin, facts.clk_pin}
        self.assertTrue(set(pin.name for pin in groups.vih_vil_odd).isdisjoint(excluded))
        self.assertTrue(set(pin.name for pin in groups.vih_vil_even).isdisjoint(excluded))
        self.assertTrue(all(int(pin.name[2:]) % 2 == 0 for pin in groups.vih_vil_odd))
        self.assertTrue(all(int(pin.name[2:]) % 2 == 1 for pin in groups.vih_vil_even))


if __name__ == "__main__":
    unittest.main()
