from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
import unittest
from pathlib import Path

import pandas as pd

from flow_recipe import compile_dac_write_plan_set, compile_recipe_rows


class DacWriteFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        master = (
            EXTERNAL_FORMAL_MASTER
        )
        sheets = pd.read_excel(master, sheet_name=None)
        by_name = {name.casefold(): frame for name, frame in sheets.items()}
        cls.flow = by_name["flow"]
        cls.rows = compile_recipe_rows(cls.flow, by_name["pattern"])

    def _plan_for(self, cp):
        plans = compile_dac_write_plan_set(self.rows, cp).plans
        matches = [plan for plan in plans if plan.item == "Mr_VDDD_DC"]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_formal_master_keeps_dac_write_on_cp1_and_cp2_verify_rows(self):
        selected = self.flow[
            (self.flow["item"] == "Mr_VDDD_DC")
            & (self.flow["type"].str.casefold() == "verify")
            & (self.flow["CP NO"].isin(["CP1", "CP2"]))
        ]
        self.assertEqual(list(selected["CP NO"]), ["CP1", "CP2"])
        self.assertEqual(
            list(selected["Recipe"]),
            [
                "ENTER(ROLE=TRIM)\nDAC_WRITE\nJUDGE",
                "ENTER(ROLE=TRIM)\nDAC_WRITE\nJUDGE",
            ],
        )

    def test_cp1_reuses_live_trim_dac_and_existing_helper(self):
        plan = self._plan_for("CP1")
        self.assertEqual(plan.value_source, "DAC_FINAL")
        self.assertFalse(plan.needs_global_variable)
        self.assertFalse(plan.needs_set_helper)

    def test_cp2_requires_addr_map_restore_and_generated_helper(self):
        plan = self._plan_for("CP2")
        self.assertEqual(plan.value_source, "ADDR_MAP")
        self.assertTrue(plan.needs_global_variable)
        self.assertTrue(plan.needs_set_helper)
        self.assertEqual(plan.dac_symbol, "MR_VDDD_DC_DAC_FINAL")
        self.assertEqual(plan.helper_name, "set_mr_vddd_dc_trim_data")


if __name__ == "__main__":
    unittest.main()
