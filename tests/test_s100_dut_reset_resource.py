from __future__ import annotations

import unittest

from program_gen.core.firmware_test import DutResetAction
from program_gen.platforms.s100.dut_reset_resource import (
    generate_dut_reset_resource,
)


class S100DutResetResourceTests(unittest.TestCase):
    def test_generates_real_low_high_release_sd_resource(self):
        resource = generate_dut_reset_resource("NRST", DutResetAction())

        self.assertEqual(resource.logical_identity, "pattern:dut_reset")
        self.assertEqual(resource.relative_path, "dut_reset.sd")
        self.assertEqual(resource.spec_identity, "v14.dut-reset/1:s100:5ms-5ms")
        self.assertTrue(resource.source_identity.startswith("generated:s100:dut-reset:sha256:"))
        self.assertEqual(resource.purpose, "FIRMWARE DutResetAction NRST reset")
        self.assertEqual(
            resource.content.decode("ascii"),
            "HEAD[PIN_NAME]:\n"
            "\n"
            "NRST;\n"
            "\n"
            "END_HEAD;\n"
            "\n"
            "@@PATTERN_DEFINE\n"
            "\n"
            "START:X;\n"
            "      0;RPT 25000;// low 5ms\n"
            "      1;RPT 25000;// high 5ms\n"
            "      X;// release NRST\n"
            "  END:X;\n"
            "\n"
            "@@END_PATTERN_DEFINE\n",
        )

    def test_rejects_a_profile_other_than_the_confirmed_reset_waveform(self):
        with self.assertRaisesRegex(ValueError, "S100.DUT_RESET.PROFILE_UNSUPPORTED"):
            generate_dut_reset_resource(
                "NRST",
                DutResetAction(low_duration_ms=50, high_duration_ms=50),
            )

    def test_rejects_an_invalid_pin_identifier(self):
        with self.assertRaisesRegex(ValueError, "S100.DUT_RESET.PIN_INVALID"):
            generate_dut_reset_resource("NRST,PA0", DutResetAction())


if __name__ == "__main__":
    unittest.main()
