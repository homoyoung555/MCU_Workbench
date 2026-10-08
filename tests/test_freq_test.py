from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.freq_test import FreqTestPlan
from program_gen.platforms.chroma.freq_test_renderer import render_freq_test
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class FreqTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        cls.plans = cls.compilation.plan.catalogs.freq_test_plans

    def test_formal_three_items_compile_fourteen_typed_cases(self):
        self.assertEqual(tuple(self.plans), (192, 193, 194))
        self.assertEqual(tuple(len(plan.cases) for plan in self.plans.values()), (4, 1, 9))
        self.assertTrue(all(isinstance(plan, FreqTestPlan) for plan in self.plans.values()))
        self.assertTrue(all(plan.typed_kind == "FREQ_TEST" for plan in self.plans.values()))
        self.assertTrue(all(plan.effective_recipe == ("FREQ_TEST",) for plan in self.plans.values()))

    def test_target_and_pattern_identity_use_full_source_multiplier_divider(self):
        pll = self.plans[194]
        identities = tuple(case.config_pattern for case in pll.cases)
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(tuple(case.target for case in pll.cases[:3]), (375.0, 562.5, 375.0))
        self.assertNotEqual(identities[0], identities[1])
        self.assertEqual(pll.cases[-1].external_clock.pin, "PD0")
        self.assertEqual(pll.cases[-1].external_clock.frequency_hz, 32_000_000.0)

    def test_hsi16_rp_splits_clock_check_into_two_sessions(self):
        clock = self.plans[192]
        self.assertEqual(tuple(case.repower_before for case in clock.cases), (False, True, False, False))
        self.assertEqual(clock.session_count, 2)
        with self.assertRaises(FrozenInstanceError):
            clock.item = "mutated"

    def test_chroma_schmitt_spans_each_power_session(self):
        for row, expected_sessions in ((192, 2), (194, 1)):
            plan = self.plans[row]
            with self.subTest(item=plan.item):
                content = render_freq_test(
                    plan, plan.item, 1, SimpleNamespace(platform="chroma", cp=plan.cp),
                ).content
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                on = f"SET_TFTM_MODE({plan.measurement_pin},SCHMITT_ON);"
                off = f"SET_TFTM_MODE({plan.measurement_pin},SCHMITT_OFF);"
                self.assertEqual(lines.count(on), expected_sessions)
                self.assertEqual(lines.count(off), expected_sessions)
                self.assertEqual(content.count("JUDGE_FREQ("), len(plan.cases))
                active = False
                for index, line in enumerate(lines):
                    if line.startswith("POWER_ON("):
                        self.assertEqual(lines[index + 1], on)
                    elif line == on:
                        self.assertFalse(active)
                        active = True
                    elif line == off:
                        self.assertTrue(active)
                        active = False
                    elif line.startswith("JUDGE_FREQ("):
                        self.assertTrue(active)
                    elif line == "POWER_OFF();":
                        self.assertEqual(lines[index - 1], off)
                self.assertFalse(active)


if __name__ == "__main__":
    unittest.main()
