import unittest

import pandas as pd

from program_gen.core.trim_data import compile_trim_data_plan


class TrimDataPlanTests(unittest.TestCase):
    def test_new_flow_item_resolves_new_and_historical_addr_map_references(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Iref1U", "type": "trim", "DAC bit": 4, "PUMP": "no"},
                {"CP NO": "CP1", "item": "Hsi_8M", "type": "trim", "DAC bit": 10, "PUMP": "no"},
                {"CP NO": "CP2", "item": "Iref1U", "type": "verify", "DAC bit": None, "PUMP": "no"},
            ]
        )

        plan = compile_trim_data_plan(flow)

        iref = plan.resolve("Iref1U_Trim[3:0]")
        self.assertIs(iref, plan.resolve("Iref1U[3:0]"))
        self.assertEqual(iref.item, "Iref1U")
        self.assertEqual(iref.addr_map_name, "Iref1U_Trim")
        self.assertEqual(iref.dac_final_symbol, "IREF1U_DAC_FINAL")
        self.assertEqual(iref.reference("SOCKET"), "IREF1U_DAC_FINAL[SOCKET]")
        self.assertIs(iref, plan.resolve("IREF1U_DAC_FINAL[SOCKET]"))
        self.assertTrue(iref.matches_addr_map("Iref1U_Trim[3:0]"))
        self.assertTrue(iref.matches_addr_map("Iref1U[3:0]"))
        self.assertFalse(iref.matches_addr_map("Iref1U_Verify"))
        self.assertEqual(
            [binding.item for binding in plan.for_cp("CP1")],
            ["Iref1U", "Hsi_8M"],
        )


if __name__ == "__main__":
    unittest.main()
