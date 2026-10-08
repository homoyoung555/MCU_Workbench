import unittest

from program_gen.adc_test_assembly import compile_adc_test_assembly
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


class AdcNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = cls.compilation.plan.catalogs.adc_test_plans[195]

    def test_adc_plan_assembles_one_canonical_definition_on_both_platforms(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP3", "lab", f"ADC_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                assembly = compile_adc_test_assembly(
                    (self.plan,),
                    TypedKindContext(self.compilation, target, facts, None),
                )

                self.assertEqual(assembly.typed_kind, "ADC_TEST")
                self.assertEqual(len(assembly.contributions), 1)
                self.assertEqual(len(assembly.bodies), 1)
                contribution = assembly.contributions[0]
                self.assertEqual(len(contribution.definitions), 1)
                self.assertEqual(len(contribution.schedule_entries), 1)
                self.assertEqual(len(contribution.resource_requires), 4)
                self.assertEqual(contribution.resources, ())
                if platform == "s100":
                    self.assertEqual(len(contribution.lifecycle_actions), 1)
                    startup = contribution.lifecycle_actions[0]
                    self.assertEqual(startup.hook, "START_UP")
                    self.assertEqual(startup.content.count("SET_CSV_LOG_ALIAS("), 18)
                    self.assertIn("LOG_ALIAS=ADC1_CH18_BUFOUT_VERIFY", startup.content)
                    self.assertNotIn("LOG_ALIAS=ADC1_CH0_PD10_VERIFY", startup.content)
                else:
                    self.assertEqual(contribution.lifecycle_actions, ())

    def test_registered_adc_slice_closes_with_explicit_compile_only_stubs(self):
        self.assertIn("ADC_TEST", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP3", "lab", f"ADC_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
                context = TypedKindContext(self.compilation, target, facts, producer)
                assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                    "ADC_TEST", (self.plan,), context
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
                self.assertIn(b"Adc_Test", program)
                pattern_artifacts = tuple(
                    artifact for artifact in rendered.artifacts
                    if artifact.relative_path.casefold().endswith((".pat", ".sd"))
                )
                self.assertEqual(len(pattern_artifacts), 4)
                self.assertTrue(all(b"STUB" in artifact.content for artifact in pattern_artifacts))
                if platform == "s100":
                    startup = program[:program.index(b"@@END_START_UP")]
                    self.assertEqual(startup.count(b"SET_CSV_LOG_ALIAS("), 18)
                    project = rendered.artifact(target.program_name + ".prj").content
                    for artifact in pattern_artifacts:
                        stem = artifact.relative_path.rsplit("/", 1)[-1].removesuffix(".sd")
                        self.assertIn(stem.encode("gbk"), project)


if __name__ == "__main__":
    unittest.main()
