import unittest
from types import SimpleNamespace
import pandas as pd

from program_gen.core.dac_adjust import (
    DacAdjustCompileError, DacAdjustCondition, DacAdjustModulePlan,
)
from program_gen.core.result_use_def import ResultUseDefError, validate_export_use_def
from flow_recipe import ResultExportPlan, ResultExportPlanSet, compile_recipe_rows
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.compiler import _compiler_exception_diagnostic


class DacAdjustModuleTests(unittest.TestCase):
    def test_moves_each_site_by_domain_position_and_saturates_both_bounds(self):
        plan = DacAdjustModulePlan(
            condition=DacAdjustCondition("A_EXPORT", "V", "<", 0.4),
            target_symbol="VPOSE_DAC_FINAL",
            codes=(7, 3, 0, 5),
            delta=2,
        )

        self.assertEqual(plan.apply((0.3, 0.5, 0.1, 0.3), (7, 3, 0, 5)),
                         (0, 3, 5, 5))
        self.assertEqual(
            plan.apply_change_set((0.3,), (7,), invalidates=("VPOSP",)).invalidated_items,
            frozenset(("vposp",)),
        )
        lower = DacAdjustModulePlan(
            condition=DacAdjustCondition("A_EXPORT", "V", ">=", 0.4),
            target_symbol="VPOSE_DAC_FINAL",
            codes=(7, 3, 0, 5),
            delta=-2,
        )
        self.assertEqual(lower.apply((0.5,), (3,)), (7,))

    def test_rejects_unsupported_condition_operator_at_compile_time(self):
        with self.assertRaisesRegex(DacAdjustCompileError, "OPERATOR"):
            DacAdjustModulePlan(
                condition=DacAdjustCondition("A_EXPORT", "V", "==", 0.4),
                target_symbol="VPOSE_DAC_FINAL",
                codes=(0, 1),
                delta=1,
            )

    def test_rejects_unconsumed_and_non_raw_cross_item_exports(self):
        export = ResultExportPlan(0, "A", "/", "verify", "MEASUREMENT", "RAW",
                                  "A_EXPORT", "double", True, False)
        with self.assertRaisesRegex(ResultUseDefError, "UNCONSUMED"):
            validate_export_use_def({"CP1": ResultExportPlanSet((export,))}, {})

    def test_unconsumed_allowlist_exempts_only_the_named_cp_item(self):
        vrefint = ResultExportPlan(
            0, "Vrefint", "/", "verify", "MEASUREMENT", "RAW",
            "VREFINT_EXPORT", "double", True, False,
        )
        other = ResultExportPlan(
            1, "Other", "/", "verify", "MEASUREMENT", "RAW",
            "OTHER_EXPORT", "double", True, False,
        )
        allowed = frozenset((("cp2", "vrefint"),))

        validate_export_use_def(
            {"CP2": ResultExportPlanSet((vrefint,))}, {},
            allowed_unconsumed=allowed,
        )
        with self.assertRaisesRegex(ResultUseDefError, "CP2/Other"):
            validate_export_use_def(
                {"CP2": ResultExportPlanSet((vrefint, other))}, {},
                allowed_unconsumed=allowed,
            )

    def test_dac_adjust_is_registered_as_a_shared_recipe_module(self):
        self.assertIn("DAC_ADJ", NATIVE_RECIPE_MODULE_REGISTRY.registered_modules)

    def test_action_recipe_retains_cross_item_raw_dac_adjust_fact_without_assembly(self):
        rows = compile_recipe_rows(pd.DataFrame([{
            "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
            "Recipe": "DAC_ADJ(A<0.4:VPOSE+2)-SETVPOSP-COMMIT",
        }]), pd.DataFrame(columns=("item", "addr", "description", "pattern")))

        self.assertEqual(rows[0].operations[0].value, "A<0.4:VPOSE+2")

    def test_action_recipe_accepts_negative_position_delta(self):
        rows = compile_recipe_rows(pd.DataFrame([{
            "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
            "Recipe": "DAC_ADJ(A>=0.4:VPOSE-2)",
        }]), pd.DataFrame(columns=("item", "addr", "description", "pattern")))

        self.assertEqual(rows[0].operations[0].value, "A>=0.4:VPOSE-2")

    def test_export_use_def_allows_dac_adjust_fanout(self):
        export = ResultExportPlan(
            0, "A", "/", "verify", "MEASUREMENT", "RAW",
            "A_EXPORT", "double", True, False, unit="V",
        )
        rows = compile_recipe_rows(pd.DataFrame([
            {"CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
             "Recipe": "DAC_ADJ(A<0.4:VPOSE+2)"},
            {"CP NO": "CP1", "item": "VNEG", "type": "adjust", "sub": "/",
             "Recipe": "DAC_ADJ(A>=0.2:VNEG+1)"},
        ], index=(1, 2)), pd.DataFrame(columns=("item", "addr", "description", "pattern")))

        consumers = validate_export_use_def(
            {"CP1": ResultExportPlanSet((export,))}, rows
        )

        self.assertEqual(tuple(item.target_item for item in consumers), ("VPOSE", "VNEG"))

    def test_export_use_def_rejects_ambiguous_duplicate_producers(self):
        exports = ResultExportPlanSet(tuple(
            ResultExportPlan(
                row, "A", "/", "verify", "MEASUREMENT", "RAW",
                f"A_EXPORT_{row}", "double", True, False, unit="V",
            )
            for row in (0, 1)
        ))

        with self.assertRaisesRegex(ResultUseDefError, "AMBIGUOUS"):
            validate_export_use_def({"CP1": exports}, {})

    def test_export_use_def_requires_raw_physical_value_type(self):
        export = ResultExportPlan(
            0, "A", "/", "verify", "MEASUREMENT", "RAW",
            "A_EXPORT", "int", True, False, unit="V",
        )
        rows = compile_recipe_rows(pd.DataFrame([{
            "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
            "Recipe": "DAC_ADJ(A<0.4:VPOSE+2)",
        }], index=(1,)), pd.DataFrame(columns=("item", "addr", "description", "pattern")))

        with self.assertRaisesRegex(ResultUseDefError, "TYPE_INCOMPATIBLE"):
            validate_export_use_def({"CP1": ResultExportPlanSet((export,))}, rows)

    def test_same_named_exports_bind_to_their_own_cp(self):
        cp1 = ResultExportPlan(
            0, "A", "/", "verify", "MEASUREMENT", "RAW",
            "CP1_A_EXPORT", "double", True, False, persist_to_otp=True, unit="V",
        )
        cp2 = ResultExportPlan(
            1, "A", "/", "verify", "MEASUREMENT", "RAW",
            "CP2_A_EXPORT", "double", True, False, unit="V",
        )
        rows = compile_recipe_rows(pd.DataFrame([{
            "CP NO": "CP2", "item": "VPOSE", "type": "adjust", "sub": "/",
            "Recipe": "DAC_ADJ(A<0.4:VPOSE+2)",
        }], index=(2,)), pd.DataFrame(columns=("item", "addr", "description", "pattern")))

        validate_export_use_def({
            "CP1": ResultExportPlanSet((cp1,)),
            "CP2": ResultExportPlanSet((cp2,)),
        }, rows)

    def test_use_def_error_keeps_its_stable_product_diagnostic_code(self):
        diagnostic = _compiler_exception_diagnostic(
            SimpleNamespace(identity="book", source_sha256="sha"),
            ResultUseDefError("EXPORT.USE_DEF.UNCONSUMED: CP2/A has no consumer"),
        )

        self.assertEqual(diagnostic.code, "EXPORT.USE_DEF.UNCONSUMED")
        self.assertEqual(diagnostic.provenance.sheet, "FLOW")


if __name__ == "__main__":
    unittest.main()
