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


class DcParametricNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plans = tuple(
            cls.compilation.plan.catalogs.dc_parametric_plans.values()
        )

    def test_registered_slice_closes_on_both_platforms_with_explicit_stubs(self):
        self.assertIn(
            "DC_PARAMETRIC_TEST",
            NATIVE_TYPED_KIND_REGISTRY.registered_kinds,
        )
        for platform in ("chroma", "s100"):
            target = TargetKey(platform, "CP3", "lab", f"DC_{platform}")
            facts = compile_platform_program_facts(self.workbook, target)
            producer = WorkspacePatternProducer(
                WORKSPACE_ROOT / "input" / platform
            )
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "DC_PARAMETRIC_TEST",
                self.plans,
                TypedKindContext(self.compilation, target, facts, producer),
            )
            rendered = PlatformProgramBuilder(producer).build(
                ProgramAssemblyInput(
                    target,
                    facts,
                    self.compilation.for_cp("CP3").canonical_schedule,
                    assembly.contributions,
                    assembly.bodies,
                )
            )
            extension = ".pln" if platform == "chroma" else ".prg"
            program = rendered.artifact(target.program_name + extension).content
            self.assertEqual(len(assembly.contributions), 3)
            self.assertEqual(len(assembly.bodies), 3)
            if platform == "chroma":
                self.assertEqual(program.count(b"int GetPinbyName(char *name)"), 1)
                self.assertEqual(program.count(b'for(I=1;I<=' + str(len(facts.pin_groups.dc_groups)).encode() + b';I++)'), 4)
                self.assertEqual(program.count(b'GetPinbyName(temp_group);'), 4)
                self.assertNotIn(b'RELAY_ON(DC1_pins,', program)
                for sub in (b'vol_test', b'voh_test', b'rpd_test', b'rpu_test'):
                    self.assertIn(b'sprintf(log_msg,"' + sub + b'_dc%d",I);', program)
                self.assertEqual(program.count(b"  POWER_ON("), 3)
                self.assertEqual(program.count(b"  POWER_OFF();"), 3)
            else:
                self.assertEqual(program.count(b"CALL_MACRO POWER_ON("), 3)
                self.assertEqual(program.count(b"CALL_MACRO POWER_OFF();"), 3)
            self.assertIn(b"Dc_Leakage_Test", program)
            self.assertIn(b"Dc_Volvoh_Test", program)
            self.assertIn(b"Dc_Rpdrpu_Test", program)
            stub_resources = tuple(
                artifact for artifact in rendered.artifacts
                if b"STUB: no real DC SWD configuration" in artifact.content
            )
            self.assertEqual(len(stub_resources), 5)

    def test_target_pin_groups_exclude_nrst_and_tp_and_balance_to_eight(self):
        for platform in ("chroma", "s100"):
            facts = compile_platform_program_facts(
                self.workbook,
                TargetKey(platform, "CP3", "production", f"DC_{platform}"),
            )
            groups = facts.pin_groups
            dc_names = tuple(
                pin.name for group in groups.dc_groups for pin in group
            )
            leakage_names = tuple(
                pin.name for pin in (*groups.leakage_odd, *groups.leakage_even)
            )
            self.assertNotIn("NRST", dc_names)
            self.assertNotIn("TP", dc_names)
            self.assertEqual(set(dc_names), set(leakage_names))
            self.assertLessEqual(max(map(len, groups.dc_groups)), 8)
            self.assertLessEqual(
                max(map(len, groups.dc_groups))
                - min(map(len, groups.dc_groups)),
                1,
            )


if __name__ == "__main__":
    unittest.main()
