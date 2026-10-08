import unittest

import pandas as pd

from program_gen.core.firmware_force import (
    ClockForceAction,
    FirmwareForceCompileError,
    ForceVoltageAction,
    SupplyForceAction,
    VoltageForcePoint,
    compile_firmware_force_action,
)


class FirmwareForceCompilerTests(unittest.TestCase):
    def test_power_force_carries_supply_lease_compliance(self):
        plan = compile_firmware_force_action(
            pd.Series({
                "FV/FI": "VCC_MAX",
                "meas pin": "VCC4",
                "target": 2400,
                "low_range(%)": 0.5,
                "high_range(%)": 1700,
                "UNIT": "uA",
            }),
            row=189,
        )

        self.assertEqual(
            plan,
            SupplyForceAction(
                rail="VCC4",
                voltage="VCC_MAX",
                current_compliance=2400.0,
                current_unit="uA",
            ),
        )

    def test_clock_force_preserves_all_signals_in_flow_order(self):
        plan = compile_firmware_force_action(
            pd.Series({
                "FV/FI": "PD0:24MHz\nPC14:32768Hz",
                "meas pin": "PA13+PA14",
                "target": "HH",
                "UNIT": "/",
            }),
            row=200,
        )

        self.assertIsInstance(plan, ClockForceAction)
        self.assertEqual(
            tuple((signal.pin, signal.frequency_hz) for signal in plan.signals),
            (("PD0", 24_000_000.0), ("PC14", 32_768.0)),
        )

    def test_supply_compliance_covers_the_high_judge_limit(self):
        plan = compile_firmware_force_action(
            pd.Series({
                "FV/FI": "VCC_MAX",
                "meas pin": "VCC4",
                "target": 3.8,
                "low_range(%)": 0.5,
                "high_range(%)": 28,
                "UNIT": "uA",
            }),
            row=191,
        )

        self.assertEqual(plan.current_compliance, 28.0)

    def test_unsupported_force_shape_fails_instead_of_guessing(self):
        with self.assertRaises(FirmwareForceCompileError) as caught:
            compile_firmware_force_action(
                pd.Series({
                    "FV/FI": "/",
                    "meas pin": "PA0",
                    "target": "/",
                    "UNIT": "/",
                }),
                row=3,
            )

        self.assertEqual(caught.exception.code, "FW.FORCE.SHAPE_UNSUPPORTED")

    def test_direct_keil_opa_force_keeps_force_and_measure_pins_separate(self):
        plan = compile_firmware_force_action(
            pd.Series({
                "FV/FI": "PA0:1.2V",
                "meas pin": "PA1",
                "target": 1.2,
                "UNIT": "V",
            }),
            row=8,
        )

        self.assertEqual(
            plan,
            ForceVoltageAction((VoltageForcePoint("PA0", "1.2V"),)),
        )


if __name__ == "__main__":
    unittest.main()
