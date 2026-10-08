import unittest

import pandas as pd

from program_gen.core.logical_item import LogicalItemCatalog


class LogicalItemCatalogTests(unittest.TestCase):
    def test_one_logical_item_owns_stage_names_patterns_and_dac_symbol(self):
        flow = pd.DataFrame(
            [
                {"item": "Iref1U", "type": "trim", "Recipe": "ENTER\nTRIM\nJUDGE"},
                {"item": "Iref1U", "type": "verify", "Recipe": None},
            ]
        )
        pattern = pd.DataFrame(
            [
                {"item": "Iref1U", "pattern": "trim mode", "addr": "1", "description": "0,EN=1"},
                {"item": None, "pattern": "trim dac", "addr": "2", "description": "3,DAC[3:0]=0000*"},
                {"item": None, "pattern": "verify mode", "addr": "3", "description": "0,EN=1"},
            ]
        )

        catalog = LogicalItemCatalog.compile(flow, pattern)

        item = catalog.resolve("Iref1U")
        self.assertIs(item, catalog.resolve("Iref1U_Trim"))
        self.assertIs(item, catalog.resolve("Iref1U_Verify"))
        self.assertEqual(item.function_name("trim"), "Iref1U_Trim")
        self.assertEqual(item.function_name("verify"), "Iref1U_Verify")
        self.assertEqual(item.pattern("trim mode"), "enter_iref1u")
        self.assertEqual(item.pattern("trim dac"), "set_iref1u_dac")
        self.assertEqual(item.pattern("verify mode"), "enter_iref1u_verify")
        self.assertEqual(item.dac_final_symbol, "IREF1U_DAC_FINAL")


if __name__ == "__main__":
    unittest.main()
