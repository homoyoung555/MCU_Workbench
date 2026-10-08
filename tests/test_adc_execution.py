import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.adc_execution import project_adc_phase
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class AdcExecutionProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = cls.compilation.plan.catalogs.adc_test_plans[195]

    def test_target_pin_facts_project_force_and_judge_without_compressing_slots(self):
        target = TargetKey("chroma", "CP3", "lab", "ADC_projection")
        facts = compile_platform_program_facts(self.workbook, target)
        adc1 = project_adc_phase(self.plan.phases[0], facts.io_pins)

        self.assertEqual(tuple(slot.channel for slot in adc1.slots), tuple(range(22)))
        self.assertEqual(
            tuple(slot.channel for slot in adc1.slots if slot.judge_enabled),
            (2, 3, 4, 5, 8, 9, 15, 18, 19, 20, 21),
        )
        self.assertEqual(
            tuple((drive.pin, drive.voltage) for drive in adc1.drives),
            (("PC14", 1.0), ("PC15", 1.5), ("PA0", 2.0),
             ("PA7", 2.5), ("PA1", 1.2), ("PA2", 1.4)),
        )
        self.assertFalse(adc1.slots[0].force_enabled)
        self.assertFalse(adc1.slots[0].judge_enabled)
        self.assertFalse(adc1.slots[18].force_enabled)
        self.assertTrue(adc1.slots[18].judge_enabled)

    def test_pin_matching_is_case_insensitive_and_shared_pin_is_forced_once(self):
        projected = project_adc_phase(
            self.plan.phases[0],
            ("pc14", "pc15", "pa0", "pa7", "pa1", "pa2"),
        )

        self.assertEqual(len(projected.drives), 6)
        self.assertEqual(
            tuple(slot.channel for slot in projected.slots if slot.force_enabled),
            (2, 3, 4, 5, 8, 9, 15),
        )


if __name__ == "__main__":
    unittest.main()
