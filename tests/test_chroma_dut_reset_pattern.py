"""Semantic tests for the Chroma firmware DUT reset Pattern resource."""

from __future__ import annotations

import unittest

from program_gen.core.firmware_test import DutResetAction
from program_gen.platforms.chroma.dut_reset_pattern import (
    generate_dut_reset_pattern,
)


class ChromaDutResetPatternTests(unittest.TestCase):
    def test_generates_low_high_release_profile_at_ts1_200ns(self):
        resource = generate_dut_reset_pattern("NRST", DutResetAction())

        self.assertEqual(
            resource.logical_identity,
            "firmware-dut-reset:NRST:low5ms:high5ms:released-high",
        )
        self.assertEqual(resource.relative_path, "pat/firmware_dut_reset.pat")
        source = resource.content.decode("ascii")
        self.assertIn("HEADER\n\nNRST;", source)
        self.assertIn("SPM_PATTERN(firmware_dut_reset)", source)
        self.assertIn("  *X*TS1;", source)
        self.assertIn("  *0*RPT 25000;// assert NRST low for 5ms", source)
        self.assertIn("  *1*RPT 25000;// deassert NRST high for 5ms", source)
        self.assertTrue(source.rstrip().endswith("*X*STOP;// release NRST\n}"))
        self.assertNotIn("placeholder", source.casefold())
        self.assertNotIn("*0*STOP", source)

    def test_rejects_a_profile_other_than_the_fixed_dut_reset_contract(self):
        with self.assertRaisesRegex(ValueError, "CHROMA.DUT_RESET.PROFILE_UNSUPPORTED"):
            generate_dut_reset_pattern(
                "NRST",
                DutResetAction(low_duration_ms=1),
            )

    def test_rejects_an_invalid_chroma_pin_symbol(self):
        with self.assertRaisesRegex(ValueError, "CHROMA.DUT_RESET.PIN_INVALID"):
            generate_dut_reset_pattern("NRST); POWER_OFF(", DutResetAction())
        with self.assertRaisesRegex(ValueError, "CHROMA.DUT_RESET.PIN_INVALID"):
            generate_dut_reset_pattern(None, DutResetAction())


if __name__ == "__main__":
    unittest.main()
