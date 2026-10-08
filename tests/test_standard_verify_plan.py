from dataclasses import FrozenInstanceError
import unittest

import pandas as pd

from flow_recipe import (
    ExecutableFlowRow,
    FlowRow,
    RecipeParameter,
    ResolvedRecipeCall,
    ResultExportPlan,
)
from pattern_bundle import PatternField
from program_gen.core.standard_verify import (
    StandardVerifyPlanError,
    compile_standard_verify_plans,
)
from program_gen.core.run_pattern import PatternSpanKind
from program_gen.core.run_pattern import RunPatternPlan
from program_gen.core.verify_modules import EnterPlan
from program_gen.core.commit_module import CommitModulePlan
from program_gen.core.verify_modules import PeWindowKind
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class StandardVerifyPlanTests(unittest.TestCase):
    def test_pe_cell_compiles_one_judge_window_from_nm_pattern_facts(self):
        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "V", "meas pin": "TP",
            "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.18, "high_range(%)": 1.22, "PE": "ERASE",
        }])
        nm_pattern = pd.DataFrame([{
            "used": "page erase 1st", "Pattern name": "nm_page_erase.pat",
        }])

        judge = compile_standard_verify_plans(
            (_operation(4),), {}, flow, nm_pattern_frame=nm_pattern
        )[4].steps[1].module_plan

        self.assertEqual(judge.pe_window.kind, PeWindowKind.ERASE)
        self.assertEqual(judge.pe_window.before.pattern.name, "nm_page_erase")
        self.assertEqual(judge.pe_window.before.span.kind, PatternSpanKind.SEGMENT)
        self.assertEqual(
            (judge.pe_window.before.span.start_label,
             judge.pe_window.before.span.end_label),
            ("START", "pe_1"),
        )
        self.assertEqual(
            (judge.pe_window.after.span.start_label,
             judge.pe_window.after.span.end_label),
            ("pe_1", "END"),
        )

    def test_version_target_overrides_flow_limits_for_declared_pump_column(self):
        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "V", "meas pin": "TP",
            "FV/FI": "0uA", "target": 9.9,
            "low_range(%)": 9.8, "high_range(%)": 10.0,
        }])
        version = pd.DataFrame([{"CP num": "CP1", "Vrefint": 1.4}])

        judge = compile_standard_verify_plans(
            (_operation(4),), {}, flow, version_frame=version
        )[4].steps[1].module_plan.measurement

        self.assertEqual(judge.limit_source, "VERSION:Vrefint")
        self.assertEqual((judge.low_limit, judge.high_limit), (1.35, 1.45))

    def test_frequency_judge_uses_chroma_tmu_range_instead_of_time_literal(self):
        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "KHz", "meas pin": "TP",
            "FV/FI": "/", "target": 125,
            "low_range(%)": 124.5, "high_range(%)": 125.5,
        }])

        measurement = compile_standard_verify_plans(
            (_operation(4),), {}, flow
        )[4].steps[1].module_plan.measurement

        self.assertEqual(measurement.gate, "@1MHZ")

    def test_uid_export_extends_default_recipe_with_stable_bcd16_result(self):
        export = ResultExportPlan(
            flow_row_index=4,
            item="Vrefint",
            sub="/",
            flow_type="verify",
            source_kind="MEASUREMENT",
            format="BCD16_MV",
            symbol="VREFINT_EXPORT",
            c_type="int",
            explicit=False,
            implied_by_uid=True,
        )

        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "V", "meas pin": "TP",
            "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.18, "high_range(%)": 1.22,
        }])
        plan = compile_standard_verify_plans(
            (_operation(4),), {}, flow, {4: export}
        )[4]

        self.assertEqual(plan.effective_recipe, ("ENTER", "JUDGE", "EXPORT"))
        module_plan = plan.steps[-1].module_plan
        self.assertEqual(module_plan.semantic_identity, "CP1:VREFINT_EXPORT")
        self.assertEqual(module_plan.source_judge_ordinal, 1)
        self.assertEqual(module_plan.format.value, "BCD16_MV")

    def test_blank_recipe_becomes_explicit_enter_judge_plan(self):
        plans = compile_standard_verify_plans((_operation(4),), {})

        plan = plans[4]
        self.assertEqual(plan.effective_recipe, ("ENTER", "JUDGE"))
        self.assertEqual(tuple(step.judge_ordinal for step in plan.steps), (None, 1))
        with self.assertRaises(FrozenInstanceError):
            plan.item = "mutated"

    def test_multiple_judges_bind_each_export_to_closest_completed_judge(self):
        recipe = _recipe_row(
            4, "ENTER", "JUDGE", "EXPORT", "DAC_WRITE", "JUDGE", "EXPORT"
        )

        plan = compile_standard_verify_plans((_operation(4),), {4: recipe})[4]

        self.assertEqual(plan.effective_recipe, (
            "ENTER", "JUDGE", "EXPORT", "DAC_WRITE", "JUDGE", "EXPORT"
        ))
        self.assertEqual(
            tuple(
                step.export_judge_ordinal
                for step in plan.steps
                if step.module == "EXPORT"
            ),
            (1, 2),
        )

    def test_recipe_requires_enter_and_at_least_one_judge(self):
        for names, code in (
            (("JUDGE",), "SV.RECIPE.ENTER_REQUIRED"),
            (("ENTER",), "SV.RECIPE.JUDGE_REQUIRED"),
        ):
            with self.subTest(names=names):
                with self.assertRaises(StandardVerifyPlanError) as caught:
                    compile_standard_verify_plans(
                        (_operation(4),), {4: _recipe_row(4, *names)}
                    )
                self.assertEqual(caught.exception.code, code)

    def test_export_before_any_judge_is_rejected(self):
        with self.assertRaises(StandardVerifyPlanError) as caught:
            compile_standard_verify_plans(
                (_operation(4),),
                {4: _recipe_row(4, "ENTER", "EXPORT", "JUDGE")},
            )

        self.assertEqual(caught.exception.code, "SV.RECIPE.EXPORT_BEFORE_JUDGE")

    def test_recipe_rejects_modules_outside_standard_verify_contract(self):
        with self.assertRaises(StandardVerifyPlanError) as caught:
            compile_standard_verify_plans(
                (_operation(4),),
                {4: _recipe_row(4, "ENTER", "TRIM", "JUDGE")},
            )

        self.assertEqual(caught.exception.code, "SV.RECIPE.MODULE_UNSUPPORTED")

    def test_explicit_recipe_facts_survive_in_the_upper_plan(self):
        recipe = _recipe_row(4, "ENTER", "RUN", "JUDGE")
        recipe = ExecutableFlowRow(
            flow=recipe.flow,
            operations=(
                recipe.operations[0],
                ResolvedRecipeCall(
                    "RUN", "ready_pattern", value_source="PATTERN_REF",
                    value="ready_pattern",
                ),
                recipe.operations[2],
            ),
        )

        run = compile_standard_verify_plans(
            (_operation(4),), {4: recipe}
        )[4].steps[1]

        self.assertEqual(run.argument, "ready_pattern")
        self.assertEqual(run.value_source, "PATTERN_REF")
        self.assertEqual(run.value, "ready_pattern")
        self.assertIsInstance(run.module_plan, RunPatternPlan)
        self.assertEqual(run.module_plan.pattern.name, "ready_pattern")

    def test_explicit_enter_pattern_is_retained_by_standard_verify_plan(self):
        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "V", "meas pin": "TP",
            "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.18, "high_range(%)": 1.22,
        }])
        recipe = ExecutableFlowRow(
            _recipe_row(4, "ENTER", "JUDGE").flow,
            (
                ResolvedRecipeCall(
                    "ENTER", None, pattern_role="verify mode",
                    pattern_name="enter_other_verify", pattern_explicit=True,
                    value_source="STATIC",
                ),
                ResolvedRecipeCall("JUDGE", None),
            ),
        )

        enter = compile_standard_verify_plans(
            (_operation(4),), {4: recipe}, flow
        )[4].steps[0].module_plan

        self.assertIsInstance(enter, EnterPlan)
        self.assertEqual(enter.pattern.name, "enter_other_verify")
        self.assertEqual(enter.pattern.logical_identity, "pattern:enter_other_verify")

    def test_explicit_commit_binds_the_precompiled_shared_module_plan(self):
        recipe = _recipe_row(4, "ENTER", "JUDGE", "COMMIT")
        commit = CommitModulePlan((), (), "PA13")

        plan = compile_standard_verify_plans(
            (_operation(4),), {4: recipe}, commit_rows={4: (commit,)}
        )[4]

        self.assertIs(plan.steps[-1].module_plan, commit)

    def test_shmoo_modifier_folds_range_into_one_base_verify_plan(self):
        flow = pd.DataFrame([{}] * 4 + [{
            "Vcc": "VCC_TYP", "relay": "/", "UNIT": "V", "meas pin": "TP",
            "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.18, "high_range(%)": 1.22,
            "step": "0-2", "sub": "/",
        }])
        field = PatternField(2, 0, "dac[2:0]", "001", True)
        recipe = _recipe_row(4, "ENTER", "JUDGE")
        recipe = ExecutableFlowRow(recipe.flow, (
            ResolvedRecipeCall(
                "ENTER", None, pattern_role="verify mode",
                dynamic_field=field, value_source="DEFAULT", value="001",
                parameters=(RecipeParameter("SHMOO", "STEP"),),
            ),
            ResolvedRecipeCall(
                "JUDGE", None,
                parameters=(RecipeParameter("PF", "NO"),),
            ),
        ))

        plan = compile_standard_verify_plans(
            (_operation(4),), {4: recipe}, flow
        )[4]

        self.assertEqual(plan.effective_recipe, ("ENTER", "JUDGE"))
        self.assertEqual(plan.shmoo.consumer_module, "ENTER")
        self.assertEqual(plan.shmoo.default_value, 1)
        self.assertFalse(plan.shmoo.pass_fail)
        self.assertEqual(
            [(point.step, point.sub, point.log_name) for point in plan.shmoo.points],
            [(0, "dac0", "Vrefint_dac0"),
             (1, "dac1", "Vrefint_dac1"),
             (2, "dac2", "Vrefint_dac2")],
        )
        self.assertEqual(
            plan.shmoo.points[2].steps[1].module_plan.measurement.alias,
            "Vrefint_dac2",
        )


def _operation(row: int) -> FlowOperation:
    return FlowOperation(
        row=row,
        cp="CP1",
        item="Vrefint",
        source_type="verify",
        mode="fbist",
        typed_kind="STANDARD_VERIFY",
        family="FBIST",
        relay=None,
        provenance=WorkbookProvenance(
            sheet="FLOW",
            coordinate=f"A{row + 2}",
            workbook_identity="wb",
            source_sha256="sha",
        ),
    )


def _recipe_row(row: int, *names: str) -> ExecutableFlowRow:
    return ExecutableFlowRow(
        flow=FlowRow(
            excel_row=row + 2,
            cp="CP1",
            item="Vrefint",
            flow_type="verify",
            sub="/",
            mode="fbist",
            recipe=(),
        ),
        operations=tuple(ResolvedRecipeCall(name, None) for name in names),
    )


if __name__ == "__main__":
    unittest.main()
