"""Typed SYSTEM_OTP_READ / SYSTEM_NM_DATA_READ compiler contracts."""

from __future__ import annotations

import unittest

from program_gen.compiler import ProductCompiler
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class SystemReadSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()

    def test_product_compiler_publishes_complete_specs_for_every_cp(self):
        for cp in ("CP1", "CP2", "CP3"):
            with self.subTest(cp=cp):
                specs = self.compilation.system_read_specs(cp)
                self.assertEqual(specs.otp_read.typed_kind, "SYSTEM_OTP_READ")
                self.assertEqual(specs.nm_data_read.typed_kind, "SYSTEM_NM_DATA_READ")
                self.assertEqual(specs.otp_read.cp, cp)
                self.assertEqual(specs.otp_read.swd_pin, "PA13")
                self.assertEqual(specs.otp_read.page_bytes, 256)
                self.assertEqual(specs.otp_read.read_bit, 64)
                self.assertEqual(
                    specs.otp_read.ra_addresses,
                    (0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F),
                )
                self.assertEqual(specs.nm_data_read.page_count, 1024)
                self.assertEqual(specs.nm_data_read.bank_count, 2)
                self.assertEqual(specs.nm_data_read.pages_per_bank, 512)

    def test_chroma_bin_reuse_is_resolved_before_rendering(self):
        specs = self.compilation.system_read_specs("CP1")
        for item in (specs.otp_read, specs.nm_data_read):
            self.assertEqual(item.chroma_hardware_bin, "60")
            self.assertEqual(item.chroma_software_bin, "60")
            self.assertIn("Pgm_CP1ID_Read", item.chroma_bin_source)

    def test_specs_expose_no_workbook_or_dataframe(self):
        specs = self.compilation.system_read_specs("CP1")
        text = repr(specs)
        self.assertNotIn("Workbook", text)
        self.assertNotIn("DataFrame", text)
        self.assertNotIn("ADDR_MAP", text)


if __name__ == "__main__":
    unittest.main()
