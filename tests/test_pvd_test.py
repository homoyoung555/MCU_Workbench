import unittest

from flow_recipe import compile_recipe_rows
from program_gen.compiler import ProductCompiler
from program_gen.core.pvd_test import compile_pvd_test_plans
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction
from program_gen.flow_kinds import compile_flow_rows
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class PvdTestCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)

    def test_formal_pvd_sheet_compiles_seven_independent_four_point_cases(self):
        flow = self.workbook.dataframe("FLOW")
        row = int(flow.index[flow["item"] == "Pvd_Test"][0])
        operations = compile_flow_rows(
            flow,
            workbook_identity=self.workbook.identity,
            source_sha256=self.workbook.source_sha256,
        )
        recipes = compile_recipe_rows(flow, self.workbook.dataframe("pattern"))

        plans = compile_pvd_test_plans(
            operations,
            recipes,
            flow,
            self.workbook.dataframe("PVD"),
            self.workbook.dataframe("VERSION"),
        )

        plan = plans[row]
        self.assertEqual(plan.typed_kind, "PVD_TEST")
        self.assertEqual(plan.effective_recipe, ("PVD_TEST",))
        self.assertEqual(plan.compare_pins, ("PA13", "PA14"))
        self.assertEqual(plan.power_profile, "VCC_MAX")
        self.assertEqual(len(plan.cases), 7)
        self.assertEqual(
            plan.cases[0].entry_actions,
            (
                LevelSequenceAction("PA0", "HL", 5_000_000),
                SendCodeAction("PA0", 222),
                SendCodeAction("PA0", 15),
                SendCodeAction("PA0", 1),
            ),
        )
        self.assertEqual(
            tuple((point.voltage, point.expected) for point in plan.cases[0].points),
            (
                (2.87, ("L", "L")),
                (2.73, ("H", "H")),
                (2.83, ("H", "H")),
                (2.97, ("L", "L")),
            ),
        )
        self.assertEqual(plan.cases[-1].entry_actions[-1].value, 7)

    def test_product_compiler_publishes_pvd_plan_and_canonical_definition(self):
        compilation = ProductCompiler().compile(self.workbook).require_success()

        plans = compilation.plan.catalogs.pvd_test_plans
        self.assertEqual(len(plans), 1)
        plan = next(iter(plans.values()))
        definition = next(
            definition for definition in compilation.for_cp("CP3").definitions
            if definition.item == plan.item
        )
        self.assertEqual(definition.typed_kind, "PVD_TEST")
        self.assertEqual(definition.effective_recipe, ("PVD_TEST",))


if __name__ == "__main__":
    unittest.main()
