from dataclasses import replace
import unittest

from program_gen.adc_test_assembly import compile_adc_test_assembly
from program_gen.compiler import ProductCompiler
from program_gen.core.adc_test import AdcPhaseKind
from program_gen.core.firmware_judge import DigitalCompareJudgePlan
from program_gen.core.result_binding import ResultIdentity
from program_gen.core.run_sequence import LevelSequenceAction, WaitAction
from program_gen.core.sram_capture import SramCapturePlan, compile_sram_capture_layout
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
)
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.adc_test_renderer import render_adc_test as chroma_render
from program_gen.platforms.s100.adc_test_renderer import render_adc_test as s100_render
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class AdcKeilVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.formal = cls.compilation.plan.catalogs.adc_test_plans[195]
        cls.facts = {
            platform: compile_platform_program_facts(
                cls.workbook, TargetKey(platform, "CP3", "lab", f"ADC_{platform}")
            )
            for platform in ("chroma", "s100")
        }

    def test_keil_sram_capture_runs_sequence_then_capture_then_adc_judge(self):
        phase = self._sram_phase(self.formal.phases[0])
        plan = replace(self.formal, phases=(phase,))
        for platform, renderer in (("chroma", chroma_render), ("s100", s100_render)):
            with self.subTest(platform=platform):
                emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
                    "SRAM_CAPTURE", phase.sram_capture, platform
                )
                rendered = renderer(
                    plan, "Adc_Test", 9, self.facts[platform], {phase.row: emission}
                )
                body = rendered.content
                run_marker = "Trigger_HL_5mS"
                force_marker = "FORCE_V_PPMU(" if platform == "chroma" else "LOGIC_SET_DRV_LEVEL("
                capture_marker = "SRAM_CAPTURE READ32 0X3000"
                judge_marker = phase.sram_capture.result_symbol
                cleanup_marker = "RELAY_OFF(" if platform == "chroma" else "DRIVE_DISABLE"
                self.assertLess(body.index("POWER_ON("), body.index(force_marker))
                self.assertLess(body.index(force_marker), body.index(run_marker))
                self.assertLess(body.index(run_marker), body.index(capture_marker))
                self.assertLess(body.index(capture_marker), body.rindex(judge_marker))
                self.assertLess(body.rindex(judge_marker), body.index(cleanup_marker))
                self.assertLess(body.index(cleanup_marker), body.index("POWER_OFF("))
                self.assertEqual(len(rendered.resources), 1)
                self.assertEqual(rendered.resource_requires, ())

    def test_keil_digital_compare_uses_shared_judge_without_sram(self):
        phase = self._digital_phase(self.formal.phases[0])
        plan = replace(self.formal, phases=(phase,))
        for platform, renderer in (("chroma", chroma_render), ("s100", s100_render)):
            with self.subTest(platform=platform):
                rendered = renderer(plan, "Adc_Test", 9, self.facts[platform])
                body = rendered.content
                self.assertIn("PA11_PA13_Compare:HH", body)
                self.assertNotIn("SRAM_CAPTURE", body)
                self.assertNotIn("C_COMPARE", body)
                self.assertEqual(len(rendered.resources), 2)
                self.assertEqual(rendered.resource_requires, ())

    def test_assembly_declares_sram_value_dependency_and_closes_resources(self):
        phase = self._sram_phase(self.formal.phases[0])
        plan = replace(self.formal, phases=(phase, self.formal.phases[1]))
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP3", "lab", f"ADC_{platform}")
                producer = WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                )
                assembly = compile_adc_test_assembly(
                    (plan,),
                    TypedKindContext(
                        self.compilation, target, self.facts[platform], producer
                    ),
                )
                contribution = assembly.contributions[0]
                self.assertEqual(len(contribution.provides), 1)
                self.assertEqual(contribution.provides[0].ref.namespace, "CAPTURED_VALUES")
                self.assertIn(
                    contribution.provides[0].ref,
                    tuple(requirement.ref for requirement in contribution.requires),
                )
                self.assertEqual(len(contribution.resources), 1)
                self.assertEqual(len(contribution.resource_requires), 3)
                rendered = PlatformProgramBuilder(producer).build(
                    ProgramAssemblyInput(
                        target,
                        self.facts[platform],
                        self.compilation.for_cp("CP3").canonical_schedule,
                        assembly.contributions,
                        assembly.bodies,
                    )
                )
                sram = rendered.artifact(
                    "pat/sram_capture.pat" if platform == "chroma" else "sram_capture.sd"
                )
                if platform == "chroma":
                    self.assertIn(b"STUB", sram.content)
                    self.assertIn(b"addr:", sram.content)
                    self.assertIn(b"parity:", sram.content)
                else:
                    self.assertNotIn(b"STUB", sram.content)

    @staticmethod
    def _sram_phase(source):
        capture = SramCapturePlan(
            layout=compile_sram_capture_layout("0X3000,22x16@2"),
            result_identity=ResultIdentity(
                "CP3", "Adc_Test", source.adc_id, "SRAM_CAPTURE"
            ),
            provenance=source.provenance,
            capture_pin=source.capture_pin,
        )
        return replace(
            source,
            mode="keil",
            kind=AdcPhaseKind.KEIL_SRAM_CAPTURE,
            effective_recipe=("RUN_SEQUENCE", "SRAM_CAPTURE", "ADC_JUDGE"),
            pattern_roles=(),
            run_actions=(LevelSequenceAction("PA11", "HL", 5_000_000), WaitAction(5)),
            sram_capture=capture,
            digital_judge=None,
        )

    @staticmethod
    def _digital_phase(source):
        judge = DigitalCompareJudgePlan(
            pins=("PA11", "PA13"),
            expected=("H", "H"),
            unit="/",
            sub=source.sub,
            provenance=source.provenance,
        )
        return replace(
            source,
            mode="keil",
            kind=AdcPhaseKind.KEIL_DIGITAL_COMPARE,
            effective_recipe=("RUN_SEQUENCE", "JUDGE"),
            pattern_roles=(),
            run_actions=(LevelSequenceAction("PA11", "HL", 5_000_000),),
            sram_capture=None,
            digital_judge=judge,
        )


if __name__ == "__main__":
    unittest.main()
