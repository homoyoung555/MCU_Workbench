from dataclasses import FrozenInstanceError
import unittest

from tests.workspace_paths import FORMAL_MASTER

from program_gen.compiler import ProductCompiler
from program_gen.core.dc_parametric import (
    LeakagePlan,
    RpdRpuPlan,
    VolVohPlan,
)
from program_gen.workbook import WorkbookReader


class DcParametricFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        )

    def test_six_formal_rows_compile_as_three_discriminated_plans(self):
        self.assertTrue(self.compilation.is_valid, self.compilation.diagnostics)
        plans = self.compilation.plan.catalogs.dc_parametric_plans

        self.assertEqual(tuple(plans), (181, 183, 185))
        self.assertIsInstance(plans[181], LeakagePlan)
        self.assertIsInstance(plans[183], VolVohPlan)
        self.assertIsInstance(plans[185], RpdRpuPlan)
        self.assertTrue(all(
            plan.typed_kind == "DC_PARAMETRIC_TEST"
            and plan.effective_recipe == ("DC_TEST",)
            and len(plan.phases) == 2
            and plan.shared_power_session
            for plan in plans.values()
        ))
        self.assertEqual(plans[181].excel_rows, (183, 184))
        self.assertEqual(plans[183].excel_rows, (185, 186))
        self.assertEqual(plans[185].excel_rows, (187, 188))

    def test_formal_variant_facts_keep_workbook_order_and_units(self):
        plans = self.compilation.plan.catalogs.dc_parametric_plans

        self.assertEqual(
            tuple(phase.sub for phase in plans[181].phases),
            ("Leakage_High_Test", "Leakage_Low_Test"),
        )
        self.assertEqual(plans[181].config_patterns, ("PT104_SWD_Leakage",))
        self.assertEqual(
            tuple(phase.force.quantity for phase in plans[183].phases),
            ("CURRENT", "CURRENT"),
        )
        self.assertEqual(
            tuple(phase.measurement.unit for phase in plans[183].phases),
            ("V", "V"),
        )
        self.assertEqual(
            plans[185].config_patterns,
            ("PT104_SWD_RPU", "PT104_SWD_RPD"),
        )
        with self.assertRaises(FrozenInstanceError):
            plans[181].item = "mutated"


if __name__ == "__main__":
    unittest.main()
