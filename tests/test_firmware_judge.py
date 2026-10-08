from dataclasses import FrozenInstanceError
import unittest

import pandas as pd

from program_gen.core.firmware_judge import (
    DigitalCompareJudgePlan,
    FirmwareJudgeCompileError,
    ScalarMeasurementJudgePlan,
    compile_firmware_judge_plan,
    compile_firmware_judge_plans,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation, compile_flow_operations
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class FirmwareJudgeCompilerTests(unittest.TestCase):
    def test_current_judge_compiles_flow_limits_without_force_action(self):
        flow = pd.DataFrame([{
            "sub": "stop0",
            "meas pin": "VCC4",
            "target": 2400,
            "low_range(%)": "0.5",
            "high_range(%)": "1700",
            "UNIT": "uA",
        }])

        plans = compile_firmware_judge_plans((_operation(0),), flow)
        plan = plans[0]

        self.assertIsInstance(plan, ScalarMeasurementJudgePlan)
        self.assertEqual(plan.kind.value, "CURRENT")
        self.assertEqual(plan.pin, "VCC4")
        self.assertEqual((plan.low_limit, plan.high_limit), (0.5, 1700.0))
        self.assertEqual((plan.unit, plan.sub), ("uA", "stop0"))
        self.assertEqual(plan.provenance.coordinate, "A2")
        self.assertFalse(hasattr(plan, "force"))
        self.assertFalse(hasattr(plan, "target"))
        with self.assertRaises(FrozenInstanceError):
            plan.pin = "VCC1"
        with self.assertRaises(TypeError):
            plans[1] = plan

    def test_digital_judge_compiles_ordered_pins_and_expected_states(self):
        flow = pd.DataFrame([{
            "sub": "SRAM_CKB",
            "meas pin": "PA13+PA11",
            "target": "HH",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "UNIT": "/",
        }])

        plan = compile_firmware_judge_plans((_operation(0),), flow)[0]

        self.assertIsInstance(plan, DigitalCompareJudgePlan)
        self.assertEqual(plan.pins, ("PA13", "PA11"))
        self.assertEqual(plan.expected, ("H", "H"))
        self.assertEqual((plan.unit, plan.sub), ("/", "SRAM_CKB"))
        self.assertEqual(plan.provenance.coordinate, "A2")

    def test_single_judge_compiler_is_reusable_by_typed_keil_families(self):
        record = pd.Series({
            "sub": "ADC1",
            "meas pin": "PA13+PA14",
            "target": "HH",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "UNIT": "/",
        })

        plan = compile_firmware_judge_plan(
            _operation(0, typed_kind="ADC_TEST"), record
        )

        self.assertIsInstance(plan, DigitalCompareJudgePlan)
        self.assertEqual(plan.pins, ("PA13", "PA14"))
        self.assertEqual(plan.expected, ("H", "H"))

    def test_voltage_judge_supports_direct_keil_opa_or_dac(self):
        flow = pd.DataFrame([{
            "sub": "direct",
            "meas pin": "PA1",
            "target": 1.2,
            "low_range(%)": "1.1",
            "high_range(%)": "1.3",
            "UNIT": "V",
        }])

        plan = compile_firmware_judge_plans((_operation(0),), flow)[0]

        self.assertEqual(plan.kind.value, "VOLTAGE")
        self.assertEqual((plan.low_limit, plan.high_limit), (1.1, 1.3))

    def test_digital_judge_rejects_pin_expected_arity_mismatch(self):
        flow = pd.DataFrame([{
            "sub": "RTC_TEST",
            "meas pin": "PA13+PA14",
            "target": "H",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "UNIT": "/",
        }])

        with self.assertRaises(FirmwareJudgeCompileError) as caught:
            compile_firmware_judge_plans((_operation(0),), flow)

        self.assertEqual(caught.exception.code, "FW.JUDGE.DIGITAL_ARITY")

    def test_digital_judge_rejects_non_hl_expected_state(self):
        flow = pd.DataFrame([{
            "sub": "RTC_TEST",
            "meas pin": "PA13+PA14",
            "target": "HX",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "UNIT": "/",
        }])

        with self.assertRaises(FirmwareJudgeCompileError) as caught:
            compile_firmware_judge_plans((_operation(0),), flow)

        self.assertEqual(caught.exception.code, "FW.JUDGE.DIGITAL_TARGET_INVALID")

    def test_protocol_specific_keil_kinds_are_not_compiled(self):
        flow = pd.DataFrame([{
            "sub": "PVD",
            "meas pin": "/",
            "target": "/",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "UNIT": "/",
        }])

        plans = compile_firmware_judge_plans(
            (_operation(0, typed_kind="VERIFY_PVD"),), flow
        )

        self.assertEqual(dict(plans), {})

    def test_missing_flow_row_reports_stable_error(self):
        flow = pd.DataFrame([{}])

        with self.assertRaises(FirmwareJudgeCompileError) as caught:
            compile_firmware_judge_plans((_operation(1),), flow)

        self.assertEqual(caught.exception.code, "FW.JUDGE.ROW_MISSING")

    def test_formal_generic_keil_rows_compile_twelve_digital_and_three_current_judges(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        plans = compile_firmware_judge_plans(
            compile_flow_operations(workbook), workbook.dataframe("FLOW")
        )

        digital_rows = {
            row for row, plan in plans.items()
            if isinstance(plan, DigitalCompareJudgePlan)
        }
        scalar_rows = {
            row for row, plan in plans.items()
            if isinstance(plan, ScalarMeasurementJudgePlan)
        }
        self.assertEqual(
            digital_rows,
            {79, 81, 83, 85, 87, 151, 153, 155, 157, 159, 200, 201},
        )
        self.assertEqual(scalar_rows, {189, 190, 191})
        self.assertTrue(all(
            plans[row].pins in (("PA13", "PA11"), ("PA13", "PA14"))
            and plans[row].expected == ("H", "H")
            for row in digital_rows
        ))
        self.assertEqual(
            tuple(
                (plans[row].sub, plans[row].low_limit, plans[row].high_limit)
                for row in sorted(scalar_rows)
            ),
            (
                ("stop0", 0.5, 1700.0),
                ("stop1", 0.5, 1700.0),
                ("standby", 0.5, 28.0),
            ),
        )


def _operation(row: int, *, typed_kind: str = "VERIFY_KEIL") -> FlowOperation:
    return FlowOperation(
        row=row,
        cp="CP3",
        item="Power_Test",
        source_type="verify",
        mode="keil",
        typed_kind=typed_kind,
        family="KEIL",
        relay=None,
        provenance=WorkbookProvenance(
            sheet="FLOW",
            coordinate=f"A{row + 2}",
            workbook_identity="wb",
            source_sha256="sha",
        ),
    )


if __name__ == "__main__":
    unittest.main()
