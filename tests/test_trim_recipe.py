import unittest

import pandas as pd

from program_gen.core.encoding import pattern_field_is_dynamic, value_to_binary
from program_gen.core.recipe_trim import (
    TrimRecipeError,
    compile_trim_recipe_plans,
    dac_final_symbol,
    dynamic_enter_operations,
    generated_flow_item_name,
    recipe_pattern_name,
)


class TrimRecipeTests(unittest.TestCase):
    def test_mrvddd_trim_plan_owns_explicit_pattern_and_symbol_names(self):
        plans = compile_trim_recipe_plans(_flow_frame(), _pattern_frame())

        plan = plans[0]
        self.assertEqual(plan.flow_row_index, 0)
        self.assertEqual(plan.item, "Mr_VDDD_DC")
        self.assertEqual(plan.dac_final_symbol, "MR_VDDD_DC_DAC_FINAL")
        enter, trim, judge = plan.operations
        self.assertEqual(enter.pattern_name, "enter_mr_vddd_dc")
        self.assertEqual(enter.value, "001")
        self.assertEqual(trim.pattern_name, "set_mr_vddd_dc_dac")
        self.assertEqual(trim.default_value, "0000")
        self.assertEqual(trim.field_width, 4)
        self.assertEqual(judge.name, "JUDGE")

    def test_trim_plan_carries_mode_for_enter_and_set_data_adapter_selection(self):
        plan = compile_trim_recipe_plans(_flow_frame(), _pattern_frame())[0]

        self.assertEqual(plan.mode, "fbist")

    def test_unimplemented_trim_mode_is_rejected_at_the_adapter_seam(self):
        flow = _flow_frame()
        flow.loc[0, "mode"] = "swd"

        with self.assertRaisesRegex(TrimRecipeError, "mode=swd.*尚未实现"):
            compile_trim_recipe_plans(flow, _pattern_frame())

    def test_trim_plan_rejects_recipe_that_hides_or_reorders_the_required_phases(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = "TRIM-ENTER-JUDGE"

        with self.assertRaisesRegex(
            TrimRecipeError,
            r"ENTER-\[DEPEND\]-TRIM-\[DAC_ADJ\]-JUDGE",
        ):
            compile_trim_recipe_plans(flow, _pattern_frame())

    def test_trim_plan_preserves_two_default_enters_before_trim_and_judge(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = "ENTER\nENTER\nTRIM\nJUDGE"

        plan = compile_trim_recipe_plans(flow, _pattern_frame())[0]

        self.assertEqual(
            [operation.name for operation in plan.operations],
            ["ENTER", "ENTER", "TRIM", "JUDGE"],
        )
        self.assertEqual(
            [operation.pattern_name for operation in plan.operations[:2]],
            ["enter_mr_vddd_dc", "enter_mr_vddd_dc"],
        )
        self.assertEqual(
            [operation.value_source for operation in plan.operations[:2]],
            ["DEFAULT", "DEFAULT"],
        )

    def test_trim_plan_accepts_dynamic_enter_and_preserves_argument_and_default(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = "ENTER(010)\nTRIM\nJUDGE"

        enter = compile_trim_recipe_plans(flow, _pattern_frame())[0].operations[0]

        self.assertEqual(enter.value_source, "ARGUMENT")
        self.assertEqual(enter.value, "010")
        self.assertEqual(enter.default_value, "001")
        self.assertEqual(enter.field_width, 3)

    def test_trim_plan_accepts_static_enter_without_dynamic_helper(self):
        pattern = _pattern_frame()
        pattern.loc[0, "description"] = "2,MR_ENABLE=1"

        enter = compile_trim_recipe_plans(_flow_frame(), pattern)[0].operations[0]

        self.assertEqual(enter.value_source, "STATIC")
        self.assertIsNone(enter.default_value)
        self.assertIsNone(enter.field_width)

    def test_dynamic_enter_helpers_are_cp_scoped_and_deduplicated_by_pattern(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = "ENTER(001)\nENTER(010)\nTRIM\nJUDGE"

        plans = compile_trim_recipe_plans(flow, _pattern_frame())

        helpers = dynamic_enter_operations(plans, "CP1")
        self.assertEqual(len(helpers), 1)
        self.assertEqual(helpers[0].pattern_name, "enter_mr_vddd_dc")
        self.assertEqual(dynamic_enter_operations(plans, "CP2"), ())

    def test_trim_plan_carries_enter_force_and_current_set_dac_waits(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = (
            "ENTER(WAIT=1MS)\n"
            "TRIM(FWAIT=2MS,SWAIT=30US)\n"
            "JUDGE"
        )

        enter, trim, _judge = compile_trim_recipe_plans(flow, _pattern_frame())[0].operations

        self.assertEqual(enter.wait.canonical, "1MS")
        self.assertEqual(trim.force_wait.canonical, "2MS")
        self.assertEqual(trim.set_wait.canonical, "30US")

    def test_judge_binds_effective_dac_and_owns_final_waits(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = (
            "ENTER\nTRIM\nJUDGE(SWAIT=20US,FWAIT=3MS)"
        )

        judge = compile_trim_recipe_plans(flow, _pattern_frame())[0].operations[-1]

        self.assertEqual(judge.name, "JUDGE")
        self.assertEqual(judge.pattern_name, "set_mr_vddd_dc_dac")
        self.assertEqual(judge.value_source, "EFFECTIVE_DAC")
        self.assertEqual(judge.set_wait.canonical, "20US")
        self.assertEqual(judge.force_wait.canonical, "3MS")

    def test_trim_plan_keeps_dac_adj_between_trim_and_judge(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = (
            "ENTER\n"
            "TRIM\n"
            "DAC_ADJ(<1.16:+1,SWAIT=20US,FWAIT=3MS)\n"
            "JUDGE"
        )

        plan = compile_trim_recipe_plans(flow, _pattern_frame())[0]

        self.assertEqual(
            [operation.name for operation in plan.operations],
            ["ENTER", "TRIM", "DAC_ADJ", "JUDGE"],
        )
        adjust = plan.operations[2]
        self.assertEqual(adjust.pattern_name, "set_mr_vddd_dc_dac")
        self.assertEqual(adjust.value, "<1.16:+1")
        self.assertEqual(adjust.set_wait.canonical, "20US")
        self.assertEqual(adjust.force_wait.canonical, "3MS")

    def test_trim_plan_resolves_explicit_depend_to_target_set_data(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = "ENTER\nDEPEND(Hsi_Vrega)\nTRIM\nJUDGE"
        pattern = pd.concat(
            [
                _pattern_frame(),
                pd.DataFrame(
                    [
                        {
                            "item": "Hsi_Vrega",
                            "addr": "0000010",
                            "description": "15,HSI_VREG[2:0]=000*",
                            "pattern": "trim dac",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

        plan = compile_trim_recipe_plans(flow, pattern)[0]

        self.assertEqual(
            [operation.name for operation in plan.operations],
            ["ENTER", "DEPEND", "TRIM", "JUDGE"],
        )
        depend = plan.operations[1]
        self.assertEqual(depend.pattern_name, "set_hsi_vrega_dac")
        self.assertEqual(depend.value_source, "DAC_FINAL")
        self.assertEqual(depend.value, "Hsi_Vrega")

    def test_trim_recipe_preserves_multiple_and_repeated_run_actions(self):
        flow = _flow_frame()
        flow.loc[0, "Recipe"] = (
            "ENTER\nRUN(probe_a)\nRUN(probe_b)\nRUN(probe_a)\nTRIM\nJUDGE"
        )

        plan = compile_trim_recipe_plans(flow, _pattern_frame())[0]

        self.assertEqual(
            [(operation.name, operation.pattern_name) for operation in plan.operations],
            [
                ("ENTER", "enter_mr_vddd_dc"),
                ("RUN", "probe_a"),
                ("RUN", "probe_b"),
                ("RUN", "probe_a"),
                ("TRIM", "set_mr_vddd_dc_dac"),
                ("JUDGE", "set_mr_vddd_dc_dac"),
            ],
        )

    def test_judge_wait_is_rejected_until_verify_adapter_consumes_it(self):
        flow = _flow_frame()
        flow.loc[1, "CP NO"] = "CP1"
        flow.loc[1, "item"] = "Mr_VDDD_DC"
        flow.loc[1, "type"] = "verify"
        flow.loc[1, "Recipe"] = "ENTER\nJUDGE(FWAIT=3MS)"
        flow.loc[1, "mode"] = "fbist"

        with self.assertRaisesRegex(TrimRecipeError, "Verify adapter 尚未接入"):
            compile_trim_recipe_plans(flow, _pattern_frame())

    def test_role_is_part_of_enter_pattern_identity(self):
        self.assertEqual(recipe_pattern_name("Mr_VDDD_DC", "trim mode"), "enter_mr_vddd_dc")
        self.assertEqual(recipe_pattern_name("Mr_VDDD_DC", "verify mode"), "enter_mr_vddd_dc_verify")
        self.assertEqual(recipe_pattern_name("Vrefint_Verify", "verify mode"), "enter_vrefint_verify")
        self.assertEqual(dac_final_symbol("Mr_VDDD_DC"), "MR_VDDD_DC_DAC_FINAL")

    def test_migrated_trim_gets_type_qualified_generated_function_identity(self):
        flow = _flow_frame()

        self.assertEqual(generated_flow_item_name(flow, 0), "Mr_VDDD_DC_Trim")
        self.assertEqual(generated_flow_item_name(flow, 1), "Unmigrated")

    def test_fbist_verify_gets_type_qualified_identity_before_recipe_migration(self):
        flow = _flow_frame()
        flow.loc[1, "mode"] = "fbist"

        self.assertEqual(generated_flow_item_name(flow, 1), "Unmigrated_Verify")

    def test_starred_default_is_baked_into_pattern_and_remains_dynamic(self):
        self.assertTrue(pattern_field_is_dynamic("3,MR_DAC[3:0]=0011*"))
        self.assertEqual(value_to_binary("3,MR_DAC[3:0]=0011*", 16), "0000000000000011")


def _flow_frame():
    return pd.DataFrame(
        [
            {
                "CP NO": "CP1",
                "item": "Mr_VDDD_DC",
                "type": "trim",
                "sub": "/",
                "Recipe": "ENTER\nTRIM\nJUDGE",
                "mode": "fbist",
            },
            {
                "CP NO": "CP1",
                "item": "Unmigrated",
                "type": "verify",
                "sub": "/",
                "Recipe": None,
            },
        ]
    )


def _pattern_frame():
    return pd.DataFrame(
        [
            {
                "item": "Mr_VDDD_DC",
                "addr": "0101110",
                "description": "2,MR_LEVEL[2:0]=001*",
                "pattern": "trim mode",
            },
            {
                "item": None,
                "addr": "0000010",
                "description": "3,MR_DAC[3:0]=0000*",
                "pattern": "trim dac",
            },
            {
                "item": None,
                "addr": "0101110",
                "description": "2,MR_LEVEL[2:0]=001*",
                "pattern": "verify mode",
            },
        ]
    )


if __name__ == "__main__":
    unittest.main()
