import unittest

from openpyxl import Workbook

import analog_sweep as A
from program_gen.core.encoding import (
    calc_dac_limits,
    dac_reference_voltage,
    dac_target_voltage,
    resolve_vcc_value,
)


class DacLimitTests(unittest.TestCase):
    def test_dac_cases_normalizes_0x_prefix_for_pattern_names(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "DAC"
        ws.append(["mode", "step", "code", "down_limit", "up_limit"])
        ws.append(["BUFFOFF", "/", "0x001", "-0.01", "+0.01"])

        self.assertEqual(
            A.dac_cases(wb),
            [{"mode": "BUFFOFF", "codes": [("001", "/", "-0.01", "+0.01")]}],
        )

    def test_target_voltage_uses_hex_code_resolution_and_vcc(self):
        self.assertAlmostEqual(dac_target_voltage("800", 4096, 3.3), 1.65)

    def test_signed_pair_is_relative_to_calculated_target(self):
        self.assertEqual(
            calc_dac_limits("800", 4096, 3.3, "-0.01", "+0.01"),
            (1.64, 1.66),
        )

    def test_vref2p9_signed_pair_uses_2p9v_reference(self):
        self.assertEqual(
            calc_dac_limits(
                "800", 4096, 3.3, "-0.01", "+0.01", mode="VREF2P9"
            ),
            (1.44, 1.46),
        )

    def test_vref2p9_absolute_limits_remain_direct_values(self):
        self.assertEqual(
            calc_dac_limits(
                "800", 4096, 3.3, "1.44", "1.46", mode="VREF2P9"
            ),
            (1.44, 1.46),
        )

    def test_vref2p9_percent_pair_uses_2p9v_reference(self):
        self.assertEqual(
            calc_dac_limits(
                "800", 4096, 3.3, "10%", "10%", mode="VREF2P9"
            ),
            (1.305, 1.595),
        )

    def test_vref2p5_signed_pair_uses_voltage_encoded_in_mode(self):
        self.assertEqual(
            calc_dac_limits(
                "800", 4096, 3.3, "-0.01", "+0.01", mode="VREF2P5"
            ),
            (1.24, 1.26),
        )

    def test_vref_mode_parser_supports_multiple_decimal_digits(self):
        self.assertEqual(dac_reference_voltage("VREF1P25", 3.3), 1.25)
        self.assertEqual(dac_reference_voltage("BUFFON", 3.3), 3.3)

    def test_percent_pair_is_relative_to_calculated_target(self):
        self.assertEqual(
            calc_dac_limits("800", 4096, 3.3, "10%", "10%"),
            (1.485, 1.815),
        )

    def test_unsigned_values_are_absolute_limits(self):
        self.assertEqual(
            calc_dac_limits("FFF", 4096, 3.3, "3.289", "3.3092"),
            (3.289, 3.309),
        )

    def test_flow_vcc_name_resolves_against_version_row(self):
        self.assertEqual(resolve_vcc_value("VCC_TYP", 2.7, 3.3, 5.5), 3.3)
        self.assertEqual(resolve_vcc_value("VCC_MAX", 2.7, 3.3, 5.5), 5.5)


if __name__ == "__main__":
    unittest.main()
