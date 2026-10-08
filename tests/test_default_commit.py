import unittest

import pandas as pd

from flow_recipe import FlowCompileError, compile_recipe_rows
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.default_commit import compile_default_commit_bindings


class DefaultCommitTests(unittest.TestCase):
    def test_verify_persistence_never_guesses_a_missing_export_symbol(self):
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
             "mode": "fbist", "Recipe": "ENTER-JUDGE", "OTP": "yes", "UID": "no"},
            {"CP NO": "CP1", "item": "Trimdata_Rewrite", "type": "write", "sub": "/",
             "mode": "fbist", "Recipe": "COMMIT-PGMOTP", "OTP": "/", "UID": "/"},
        ])
        pattern = pd.DataFrame([
            {"item": "Vrefint", "addr": "0", "description": "4,code=0000",
             "pattern": "verify mode"},
        ])
        catalog = compile_addr_map_catalog(pd.DataFrame([
            _map("trim1", "VREFINT_VERIFY", "Vrefint_Verify[15:0]"),
        ]))

        with self.assertRaisesRegex(FlowCompileError, "缺少上游.*EXPORT symbol"):
            compile_default_commit_bindings(
                flow, compile_recipe_rows(flow, pattern), catalog
            )

    def test_trim_write_and_uid_commit_have_distinct_destinations(self):
        flow = pd.DataFrame([
            {"CP NO": "CP3", "item": "Hsi_8M", "type": "trim", "sub": "/",
             "mode": "fbist", "Recipe": "ENTER-TRIM-JUDGE", "OTP": "yes", "UID": "yes"},
            {"CP NO": "CP3", "item": "Trimdata_Write", "type": "write", "sub": "/",
             "mode": "fbist", "Recipe": "COMMIT-PGMOTP", "OTP": "/", "UID": "/"},
            {"CP NO": "CP3", "item": "Pgm_CP3ID_Read", "type": "uid", "sub": "/",
             "mode": "fbist", "Recipe": "COMMIT-PGMOTP(UID)", "OTP": "/", "UID": "/"},
        ])
        pattern = pd.DataFrame([
            {"item": "Hsi_8M", "addr": "0", "description": "12,trim_code=000000000000",
             "pattern": "trim mode"},
            {"item": None, "addr": "1", "description": "12,trim_code=000000000000*",
             "pattern": "trim dac"},
        ])
        catalog = compile_addr_map_catalog(pd.DataFrame([
            _map("trim1", "CLK_TRIM0", "Hsi_8M[11:0]"),
            _map("uid", "Hsi_8M_Trim", "Hsi_8M[11:0]"),
        ]))
        rows = compile_recipe_rows(flow, pattern)

        bindings = compile_default_commit_bindings(flow, rows, catalog)

        self.assertEqual([a.field for a in bindings[1]], ["Hsi_8M"])
        self.assertEqual([a.field for a in bindings[2]], ["Hsi_8M"])
        self.assertEqual(bindings[1][0].value.token, "HSI_8M_DAC_FINAL")

    def test_rewrite_uses_verify_otp_but_not_uid_only_value(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Vrefint", "type": "verify", "sub": "/",
             "mode": "fbist", "Recipe": "ENTER-JUDGE-EXPORT", "OTP": "yes", "UID": "yes"},
            {"CP NO": "CP2", "item": "Ts_125C", "type": "verify", "sub": "/",
             "mode": "fbist", "Recipe": "ENTER-JUDGE", "OTP": "no", "UID": "yes"},
            {"CP NO": "CP2", "item": "Trimdata_Rewrite", "type": "write", "sub": "/",
             "mode": "fbist", "Recipe": "COMMIT-PGMOTP", "OTP": "/", "UID": "/"},
        ])
        pattern = pd.DataFrame([
            {"item": "Vrefint", "addr": "0", "description": "4,code=0000", "pattern": "verify mode"},
            {"item": "Ts_125C", "addr": "0", "description": "4,code=0000", "pattern": "verify mode"},
        ])
        catalog = compile_addr_map_catalog(pd.DataFrame([
            _map("trim1", "VREFINT_VERIFY", "Vrefint_Verify[15:0]"),
            _map("uid", "TS_VERIFY", "Ts_125C_Verify[15:0]"),
        ]))

        bindings = compile_default_commit_bindings(flow, compile_recipe_rows(flow, pattern), catalog,
                                                   export_symbols={0: "VREFINT_EXPORT"})

        self.assertEqual([a.field for a in bindings[2]], ["Vrefint_Verify"])
        self.assertEqual(bindings[2][0].value.token, "VREFINT_EXPORT")


def _map(page, register, fields):
    return {
        "Word No.": page, "line": "CP1/2/3", "bit[31:16]": "complement",
        "bit[15:0]": f"{register}[15:0]", "data type": "lable",
        "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": fields,
    }


if __name__ == "__main__":
    unittest.main()
