import io
import unittest
from unittest.mock import patch

import pandas as pd

from program_gen.platforms.chroma import writers
from program_gen.platforms.s100 import writers as s100_writers


class ChromaVerifyItemNormalizationTests(unittest.TestCase):
    @staticmethod
    def _render_verify(item, line="/"):
        flow_row = {
            "CP NO": "CP1",
            "type": "verify",
            "mode": "fbist",
            "item": item,
            "Vcc": "VCC_TYP",
            "UID": "no",
            "UNIT": "/",
            "meas pin": "/",
            "FV/FI": "/",
            "target": "/",
            "low_range(%)": "/",
            "high_range(%)": "/",
            "PE": "no",
            "OTP": "no",
            "LINE": line,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        out = io.StringIO()
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "trash", []),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "VERSION", pd.DataFrame()),
            patch.object(writers, "flow_relay", return_value="/"),
            patch.object(writers, "copy_file"),
            patch.object(writers, "vcc_rails_str", return_value="VCC"),
        ):
            writers.verify_item_write(["PROGRAM_CP1"], out, 0)
        return out.getvalue()

    def test_flow_item_key_strips_and_lowercases_pdr_bor_names(self):
        for module in (writers, s100_writers):
            for raw, expected in (
                ("PDR_Verify", "pdr_verify"),
                (" Pdr_Verify ", "pdr_verify"),
                ("BOR_VERIFY", "bor_verify"),
                (" Bor_Verify ", "bor_verify"),
            ):
                with self.subTest(module=module.__name__, raw=raw):
                    self.assertEqual(module._flow_item_key(raw), expected)

    def test_uppercase_pdr_verify_uses_special_pdr_branch(self):
        generated = self._render_verify("PDR_Verify")
        self.assertIn("int pdrVerifyflag[MAX_SITE]", generated)
        self.assertIn("LEVELS(PDR_MAX_LVL, 3mS)", generated)
        self.assertIn("LEVELS(PDR_MIN_LVL, 3mS)", generated)
        self.assertNotIn("borRisingvoltage", generated)

    def test_uppercase_bor_verify_uses_special_bor_branch(self):
        generated = self._render_verify(
            "BOR_VERIFY", "rising:1.8,2.0\nfalling:1.7,1.5\ndac:1,2"
        )
        self.assertIn("int borVerifyflag[MAX_SITE]", generated)
        self.assertIn("double borRisingvoltage[2]", generated)
        self.assertIn("set_bor_data(borDac[I])", generated)
        self.assertNotIn("PDR_MAX_LVL", generated)


if __name__ == "__main__":
    unittest.main()
