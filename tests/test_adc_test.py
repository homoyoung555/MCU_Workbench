import unittest

from flow_recipe import compile_recipe_rows
from program_gen.compiler import ProductCompiler
from program_gen.core.adc_test import (
    AdcPhaseKind,
    AdcPatternRole,
    AdcSourceKind,
    AdcTestCompileError,
    compile_adc_test_plans,
)
from program_gen.core.firmware_judge import DigitalCompareJudgePlan
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction
from program_gen.flow_kinds import compile_flow_rows
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class AdcTestCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = cls.compilation.plan.catalogs.adc_test_plans[195]

    def test_formal_adc_rows_compile_as_one_plan_and_one_definition(self):
        plans = self.compilation.plan.catalogs.adc_test_plans
        self.assertEqual(tuple(plans), (195,))
        plan = plans[195]
        self.assertEqual(plan.row_indices, (195, 196))
        self.assertEqual(tuple(phase.adc_id for phase in plan.phases), ("ADC1", "ADC2"))

        definitions = tuple(
            definition
            for definition in self.compilation.for_cp("CP3").definitions
            if definition.item == "Adc_Test"
        )
        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].typed_kind, "ADC_TEST")
        self.assertEqual(definitions[0].source_rows, (197, 198))
        self.assertEqual(definitions[0].datalog_points, ("ADC1", "ADC2"))
        self.assertEqual(
            definitions[0].effective_recipe,
            ("SWD_CAPTURE", "ADC_JUDGE"),
        )

    def test_each_phase_has_an_independent_swd_capture_session(self):
        for phase in self.plan.phases:
            with self.subTest(adc=phase.adc_id):
                self.assertTrue(phase.independent_power_session)
                self.assertEqual(phase.mode, "swd")
                self.assertEqual(phase.power_profile, "VCC_TYP")
                self.assertEqual(phase.reference_voltage, 3.3)
                self.assertEqual(phase.capture_pin, "PA13")
                self.assertEqual(
                    phase.pattern_roles,
                    (
                        AdcPatternRole.CONFIG_PATTERN,
                        AdcPatternRole.CAPTURE_PATTERN,
                    ),
                )
                self.assertEqual(
                    phase.effective_recipe,
                    ("SWD_CAPTURE", "ADC_JUDGE"),
                )

    def test_formal_phases_keep_all_twenty_two_sixteen_bit_slots(self):
        adc1, adc2 = self.plan.phases
        for phase in (adc1, adc2):
            with self.subTest(adc=phase.adc_id):
                self.assertEqual(tuple(slot.channel for slot in phase.slots), tuple(range(22)))
                self.assertEqual(phase.capture.word_width_bits, 16)
                self.assertEqual(phase.capture.code_width_bits, 12)
                self.assertTrue(phase.capture.upper_bits_must_be_zero)
                self.assertFalse(phase.capture.masks_upper_bits)

        first = adc1.slots[0]
        self.assertEqual(first.logical_pin, "PD10")
        self.assertEqual(first.source_kind, AdcSourceKind.EXTERNAL)
        self.assertEqual(first.force_voltage, 0.3)
        self.assertEqual((first.expected_code, first.low_limit, first.high_limit), (372, 308, 436))

        internal = adc1.slots[18]
        self.assertEqual(internal.logical_pin, "INT_BUFOUT")
        self.assertEqual(internal.source_kind, AdcSourceKind.INTERNAL)
        self.assertIsNone(internal.force_voltage)
        self.assertEqual((internal.expected_code, internal.low_limit, internal.high_limit), (943, 815, 1071))
        self.assertFalse(hasattr(first, "present"))
        self.assertEqual(adc2.slots[4].logical_pin, "PB2")

    def test_capture_keeps_upper_four_bits_so_adc_judge_rejects_them(self):
        phase = self.plan.phases[0]
        slot = phase.slots[0]
        raw_word = 0x1000 | slot.expected_code

        self.assertEqual(phase.capture.decode_word(raw_word), raw_word)
        self.assertFalse(slot.accepts(phase.capture.decode_word(raw_word)))

    def test_legacy_step_cap_cfg_and_unit_do_not_select_the_native_contract(self):
        baseline = self._compile_core(self.workbook.dataframe("FLOW"))
        changed = self.workbook.dataframe("FLOW").copy()
        changed.loc[[195, 196], "step"] = ["legacy-one", "legacy-two"]
        changed.loc[[195, 196], "cap_cfg"] = ["legacy-cap-a", "legacy-cap-b"]
        changed.loc[[195, 196], "UNIT"] = ["legacy-unit-a", "legacy-unit-b"]

        self.assertEqual(self._compile_core(changed), baseline)

    def test_missing_capture_slot_is_a_stable_compile_error(self):
        adc = self.workbook.dataframe("ADC").drop(index=7).reset_index(drop=True)

        with self.assertRaisesRegex(AdcTestCompileError, "ADC.SLOTS.NOT_CONTIGUOUS"):
            self._compile_core(self.workbook.dataframe("FLOW"), adc=adc)

    def test_all_phases_must_share_the_group_bin(self):
        flow = self.workbook.dataframe("FLOW").copy()
        flow.loc[196, "Sbin"] = 17

        with self.assertRaisesRegex(AdcTestCompileError, "ADC.GROUP.BIN_MISMATCH"):
            self._compile_core(flow)

    def test_explicit_swd_recipe_must_match_the_phase_contract(self):
        flow = self.workbook.dataframe("FLOW").copy()
        flow.loc[195, "Recipe"] = "JUDGE"

        with self.assertRaisesRegex(AdcTestCompileError, "ADC.RECIPE.INVALID"):
            self._compile_core(flow)

    def test_keil_sram_capture_compiles_typed_run_capture_and_adc_judge(self):
        flow = self.workbook.dataframe("FLOW").copy()
        flow.loc[[195, 196], "mode"] = "keil"
        flow.loc[[195, 196], "Recipe"] = (
            "RUN_SEQUENCE-SRAM_CAPTURE(0X3000,22x16@2)-ADC_JUDGE"
        )
        flow.loc[[195, 196], "step"] = "PA0:HL-5ms-222-15"

        phases = self._compile_core(flow)[195].phases

        for phase in phases:
            with self.subTest(adc=phase.adc_id):
                self.assertEqual(phase.kind, AdcPhaseKind.KEIL_SRAM_CAPTURE)
                self.assertEqual(
                    phase.effective_recipe,
                    ("RUN_SEQUENCE", "SRAM_CAPTURE", "ADC_JUDGE"),
                )
                self.assertEqual(
                    tuple(type(action) for action in phase.run_actions),
                    (LevelSequenceAction, SendCodeAction, SendCodeAction),
                )
                self.assertEqual(
                    phase.sram_capture.layout.canonical_spec,
                    "0X3000,22x16@2",
                )
                self.assertEqual(phase.sram_capture.capture_pin, "PA13")
                self.assertIsNone(phase.digital_judge)

    def test_keil_digital_compare_reuses_shared_judge_plan(self):
        flow = self.workbook.dataframe("FLOW").copy()
        flow.loc[[195, 196], "mode"] = "keil"
        flow.loc[[195, 196], "Recipe"] = "RUN_SEQUENCE-JUDGE"
        flow.loc[[195, 196], "step"] = "PA0:HL-5ms"
        flow.loc[[195, 196], "meas pin"] = "PA13+PA14"
        flow.loc[[195, 196], "target"] = "HH"
        flow.loc[[195, 196], "UNIT"] = "/"

        phases = self._compile_core(flow)[195].phases

        for phase in phases:
            with self.subTest(adc=phase.adc_id):
                self.assertEqual(phase.kind, AdcPhaseKind.KEIL_DIGITAL_COMPARE)
                self.assertEqual(phase.effective_recipe, ("RUN_SEQUENCE", "JUDGE"))
                self.assertIsNone(phase.sram_capture)
                self.assertIsInstance(phase.digital_judge, DigitalCompareJudgePlan)
                self.assertEqual(phase.digital_judge.pins, ("PA13", "PA14"))
                self.assertEqual(phase.digital_judge.expected, ("H", "H"))

    def _compile_core(self, flow, *, adc=None):
        operations = compile_flow_rows(
            flow,
            workbook_identity=self.workbook.identity,
            source_sha256=self.workbook.source_sha256,
        )
        recipes = compile_recipe_rows(flow, self.workbook.dataframe("pattern"))
        return compile_adc_test_plans(
            operations,
            recipes,
            flow,
            self.workbook.dataframe("ADC") if adc is None else adc,
            self.workbook.dataframe("IOMUX"),
            self.workbook.dataframe("VERSION"),
        )


if __name__ == "__main__":
    unittest.main()
