"""Public Interface tests for the shared EXPORT Recipe Module."""

import unittest

from program_gen.core.result_export import (
    ResultExportFormat,
    ResultExportModulePlan,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import RenderSymbolRef


class ResultExportModuleTests(unittest.TestCase):
    def test_bcd16_mv_export_routes_to_both_platforms_with_one_stable_identity(self):
        plan = ResultExportModulePlan(
            semantic_identity="CP1:VREFINT_EXPORT",
            symbol="VREFINT_EXPORT",
            source_judge_ordinal=1,
            source_pin="TP",
            format=ResultExportFormat.BCD16_MV,
            c_type="int",
        )

        chroma = NATIVE_RECIPE_MODULE_REGISTRY.emit("EXPORT", plan, "chroma")
        s100 = NATIVE_RECIPE_MODULE_REGISTRY.emit("EXPORT", plan, "s100")

        self.assertIn(
            "EXPORT", NATIVE_RECIPE_MODULE_REGISTRY.registered_modules
        )
        self.assertIn(
            "    VREFINT_EXPORT[SOCKET]=(int)(RESULT_PIN(SOCKET, TP)*1000+0.5);",
            chroma.statements,
        )
        self.assertIn(
            "\t\tVREFINT_EXPORT[T_SOCKET]=(int)(GB[5+T_SOCKET*64]*1000+0.5);",
            s100.statements,
        )
        expected_ref = RenderSymbolRef("RESULT", "CP1:VREFINT_EXPORT")
        self.assertEqual(chroma.provides[0].ref, expected_ref)
        self.assertEqual(s100.provides[0].ref, expected_ref)


if __name__ == "__main__":
    unittest.main()
