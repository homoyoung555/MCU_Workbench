import unittest

from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.verify_modules import (
    EnterPlan,
    JudgeMeasurementKind,
    JudgeMeasurementPlan,
    JudgePeWindowPlan,
    JudgePlan,
    PeWindowKind,
    VerifyModulePlanError,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY


class EnterJudgeModuleTests(unittest.TestCase):
    def test_pe_window_rejects_runs_that_do_not_share_one_pe_1_boundary(self):
        first = PatternResourceRef(
            "erase_a", "pattern:erase_a", ("START", "pe_1", "END")
        )
        second = PatternResourceRef(
            "erase_b", "pattern:erase_b", ("START", "pe_1", "END")
        )

        with self.assertRaises(VerifyModulePlanError) as caught:
            JudgePeWindowPlan(
                PeWindowKind.ERASE,
                RunPatternPlan(
                    first, PatternSpan.segment("START", "pe_1"), "TS_5MHZ"
                ),
                RunPatternPlan(
                    second, PatternSpan.segment("pe_1", "END"), "TS_5MHZ"
                ),
            )

        self.assertEqual(caught.exception.code, "VM.JUDGE.PE_WINDOW_INVALID")

    def test_registered_enter_and_judge_translate_one_typed_tracer_plan(self):
        enter = EnterPlan(PatternResourceRef(
            "enter_hsi_pre_check_verify",
            "pattern:enter_hsi_pre_check_verify",
            ("START", "END"),
        ))
        judge = JudgePlan(
            item="Hsi_Pre_Check",
            measurement=JudgeMeasurementPlan(
                kind=JudgeMeasurementKind.FREQUENCY,
                pin="TP",
                force="/",
                low_limit=124.5,
                high_limit=125.5,
                unit="KHz",
                gate="@1MHZ",
                settle="50mS",
                alias="hsi_pre_check",
            ),
        )

        chroma_enter = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "ENTER", enter, "chroma"
        )
        s100_enter = NATIVE_RECIPE_MODULE_REGISTRY.emit("ENTER", enter, "s100")
        chroma_judge = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "JUDGE", judge, "chroma"
        )
        s100_judge = NATIVE_RECIPE_MODULE_REGISTRY.emit("JUDGE", judge, "s100")

        self.assertTrue({"ENTER", "JUDGE"}.issubset(
            NATIVE_RECIPE_MODULE_REGISTRY.registered_modules
        ))
        self.assertTrue(any(
            "JUDGE_PAT(enter_hsi_pre_check_verify,__enter_hsi_pre_check_verify);"
            in line for line in chroma_enter.statements
        ))
        self.assertIn(
            "\tRUN_PATTERN(enter_hsi_pre_check_verify:START,"
            "enter_hsi_pre_check_verify:END,1,TS_5MHZ);",
            s100_enter.statements,
        )
        self.assertTrue(any("JUDGE_FREQ(TP" in line for line in chroma_judge.statements))
        self.assertTrue(any("LOGIC_TMU_MEAS_FREQ" in line for line in s100_judge.statements))


if __name__ == "__main__":
    unittest.main()
