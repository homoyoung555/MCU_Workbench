from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
import unittest
from pathlib import Path

import pandas as pd

from flow_recipe import compile_recipe_rows, compile_result_export_plan_set


class ExportFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        master = (
            EXTERNAL_FORMAL_MASTER
        )
        sheets = pd.read_excel(master, sheet_name=None)
        by_name = {name.casefold(): frame for name, frame in sheets.items()}
        cls.flow = by_name["flow"]
        cls.rows = compile_recipe_rows(cls.flow, by_name["pattern"])

    def _vrefint_plan(self, cp):
        plans = compile_result_export_plan_set(self.flow, self.rows, cp).plans
        matches = [plan for plan in plans if plan.item == "Vrefint"]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_cp1_uid_implies_bcd16_export_without_recipe_entry(self):
        plan = self._vrefint_plan("CP1")
        self.assertFalse(plan.explicit)
        self.assertTrue(plan.implied_by_uid)
        self.assertEqual(plan.format, "BCD16_MV")
        self.assertEqual(plan.symbol, "VREFINT_EXPORT")

    def test_cp2_explicit_export_is_raw_and_does_not_require_uid(self):
        selected = self.flow[
            (self.flow["CP NO"] == "CP2")
            & (self.flow["item"] == "Vrefint")
            & (self.flow["type"].str.casefold() == "verify")
        ]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected.iloc[0]["Recipe"], "ENTER\nJUDGE\nEXPORT")
        self.assertEqual(str(selected.iloc[0]["UID"]).casefold(), "no")

        plan = self._vrefint_plan("CP2")
        self.assertTrue(plan.explicit)
        self.assertFalse(plan.implied_by_uid)
        self.assertEqual(plan.format, "RAW")
        self.assertEqual(plan.c_type, "double")
        self.assertEqual(plan.symbol, "VREFINT_EXPORT")


if __name__ == "__main__":
    unittest.main()
