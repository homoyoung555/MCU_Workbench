import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from flow_recipe import compile_recipe_rows, dynamic_recipe_enter_operations, parse_recipe
from program_gen.core.shmoo import ShmooRecipeError, compile_shmoo_plans
from program_gen.core.recipe_trim import generated_flow_item_name
from program_gen.core import pattern_data
from program_gen.platforms.chroma import writers as chroma_writers
from program_gen.platforms.s100 import writers as s100_writers


def _pattern():
    return pd.DataFrame([
        {
            "item": "Mr_VDDD_DC",
            "addr": "0011101",
            "description": "7,DAC[2:0]=001*",
            "pattern": "verify mode",
        },
    ])


def _flow():
    common = {
        "CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "shmoo",
        "mode": "fbist", "Recipe": "ENTER-JUDGE(PF=YES)",
        "Vcc": "VCC_TYP", "meas pin": "PA0", "FV/FI": "0uA",
        "UNIT": "V", "PE": "no", "UID": "no", "OTP": "no",
        "Hbin": 3, "relay": "/",
    }
    return pd.DataFrame([
        dict(common, sub="dac0", step=0, target=1.00,
             **{"low_range(%)": 0.90, "high_range(%)": 1.10}),
        dict(common, sub="dac3", step=3, target=1.20,
             **{"low_range(%)": 1.10, "high_range(%)": 1.30}),
        dict(common, sub="dac7", step=7, target=1.40,
             **{"low_range(%)": 1.30, "high_range(%)": 1.50}),
    ])


def _pf_no_flow():
    flow = _flow().iloc[[0]].copy()
    flow["step"] = flow["step"].astype(object)
    flow.loc[0, "Recipe"] = "ENTER-JUDGE(PF=NO)"
    flow.loc[0, "sub"] = "/"
    flow.loc[0, "step"] = "0-7"
    flow.loc[0, "low_range(%)"] = float("nan")
    flow.loc[0, "high_range(%)"] = float("nan")
    return flow


class ShmooRecipeTests(unittest.TestCase):
    def test_shmoo_row_does_not_duplicate_legacy_pattern_adjacency(self):
        pattern_items = ["Mr_VDDD_DC", float("nan"), float("nan"), "Vrefint"]
        pattern_roles = ["trim mode", "trim dac", "verify mode", "trim mode"]
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim"},
            {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify"},
            {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "shmoo"},
            {"CP NO": "CP1", "item": "Vrefint", "type": "trim"},
        ])

        def fake_col(sheet, column):
            if sheet == "PATTERN":
                return list({"item": pattern_items, "pattern": pattern_roles}[column])
            if sheet == "FLOW":
                return list(flow[column])
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        with (
            patch.object(pattern_data.G, "col", side_effect=fake_col),
            patch.object(pattern_data.G, "i", 0),
            patch.object(
                pattern_data,
                "fbist_pattern_get",
                return_value=["mr_trim", "mr_dac", "mr_verify", "vrefint_trim"],
            ),
        ):
            names = pattern_data.pattern_testitem_merge_rname(["PROGRAM_CP1"])
            patterns = pattern_data.pattern_testitem_merge_rpattern(["PROGRAM_CP1"])

        self.assertEqual(
            names,
            ["Mr_VDDD_DC"] * 6 + ["Vrefint"],
        )
        self.assertEqual(
            patterns,
            ["mr_trim", "mr_trim", "mr_dac", "mr_dac", "mr_verify", "mr_verify", "vrefint_trim"],
        )

    def test_shmoo_function_identity_matches_booking_identity(self):
        flow = _flow()

        self.assertEqual(generated_flow_item_name(flow, 0), "Mr_VDDD_DC_Shmoo")

    def test_judge_pf_parameter_is_canonical_and_shmoo_default_gets_runtime_helper(self):
        self.assertEqual(parse_recipe("JUDGE(pf=yes)")[0].named_parameter("PF"), "YES")
        rows = compile_recipe_rows(_flow(), _pattern())

        helpers = dynamic_recipe_enter_operations(rows, "CP1")

        self.assertEqual(
            [(helper.reference, helper.default_value, helper.field_width) for helper in helpers],
            [("enter_mr_vddd_dc_verify", "001", 3)],
        )

    def test_pf_yes_rows_compile_one_plan_with_decimal_steps_and_per_sub_limits(self):
        plans = compile_shmoo_plans(_flow(), _pattern())

        self.assertEqual(list(plans), [0])
        plan = plans[0]
        self.assertEqual(plan.pattern_name, "enter_mr_vddd_dc_verify")
        self.assertEqual(plan.field_width, 3)
        self.assertEqual(plan.default_value, "001")
        self.assertEqual([point.dac for point in plan.points], [0, 3, 7])
        self.assertEqual([point.sub for point in plan.points], ["dac0", "dac3", "dac7"])
        self.assertEqual(
            [point.log_name for point in plan.points],
            ["Mr_VDDD_DC_dac0", "Mr_VDDD_DC_dac3", "Mr_VDDD_DC_dac7"],
        )
        self.assertEqual(
            [(point.down_limit, point.up_limit) for point in plan.points],
            [(0.9, 1.1), (1.1, 1.3), (1.3, 1.5)],
        )

    def test_step_must_fit_dynamic_pattern_width(self):
        flow = _flow()
        flow.loc[2, "step"] = 8

        with self.assertRaisesRegex(ShmooRecipeError, "3 bit"):
            compile_shmoo_plans(flow, _pattern())

    def test_pf_no_single_row_expands_decimal_range_without_sub_or_limits(self):
        flow = _pf_no_flow()

        plan = compile_shmoo_plans(flow, _pattern())[0]

        self.assertFalse(plan.pass_fail)
        self.assertEqual([point.dac for point in plan.points], list(range(8)))
        self.assertEqual(
            [point.log_name for point in plan.points],
            [f"Mr_VDDD_DC_dac{dac}" for dac in range(8)],
        )

    def test_chroma_pf_no_keeps_datalog_and_clears_item_result(self):
        flow = _pf_no_flow()
        plan = compile_shmoo_plans(flow, _pattern())[0]

        def fake_col(sheet, column):
            if sheet == "FLOW":
                return list(flow[column])
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        with (
            patch.object(chroma_writers.G, "col", side_effect=fake_col),
            patch.object(chroma_writers.G, "i", 0),
            patch.object(chroma_writers.G, "BASE_DIR", "base"),
            patch.object(chroma_writers.G, "OUT_DIR", "out"),
            patch.object(chroma_writers, "copy_file"),
            patch.object(chroma_writers, "flow_relay", return_value="/"),
        ):
            chroma_writers.shmoo_item_write(["PROGRAM_CP1"], output, plan)

        generated = output.getvalue()
        self.assertIn('"Mr_VDDD_DC_dac0"', generated)
        self.assertIn('"Mr_VDDD_DC_dac7"', generated)
        self.assertIn("PLAN_RESULT_MS[SOCKET]=PASS;", generated)

        pf_yes = compile_shmoo_plans(_flow(), _pattern())[0]
        output = io.StringIO()
        with (
            patch.object(chroma_writers.G, "col", side_effect=lambda sheet, column: list(_flow()[column])),
            patch.object(chroma_writers.G, "i", 0),
            patch.object(chroma_writers.G, "BASE_DIR", "base"),
            patch.object(chroma_writers.G, "OUT_DIR", "out"),
            patch.object(chroma_writers, "copy_file"),
            patch.object(chroma_writers, "flow_relay", return_value="/"),
        ):
            chroma_writers.shmoo_item_write(["PROGRAM_CP1"], output, pf_yes)
        self.assertNotIn("PLAN_RESULT_MS[SOCKET]=PASS;", output.getvalue())

    def test_s100_pf_no_logs_each_dac_without_limits(self):
        flow = _pf_no_flow()
        plan = compile_shmoo_plans(flow, _pattern())[0]

        def fake_col(sheet, column):
            if sheet == "FLOW":
                return list(flow[column])
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        with (
            patch.object(s100_writers.G, "col", side_effect=fake_col),
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "BASE_DIR", "base"),
            patch.object(s100_writers.G, "OUT_DIR", "out"),
            patch.object(s100_writers, "copy_file"),
        ):
            s100_writers.shmoo_item_write(["PROGRAM_CP1"], output, plan)

        generated = output.getvalue()
        self.assertIn("LOG_ALIAS=Mr_VDDD_DC_dac0", generated)
        self.assertIn("LOG_ALIAS=Mr_VDDD_DC_dac7", generated)
        self.assertNotIn("DOWN_LIMIT", generated)
        self.assertNotIn("UP_LIMIT", generated)

    def test_bare_judge_defaults_to_pf_yes_and_duplicate_dac_is_rejected(self):
        flow = _flow()
        flow["Recipe"] = "ENTER-JUDGE"
        flow.loc[2, "step"] = 3

        with self.assertRaisesRegex(ShmooRecipeError, "step=3 重复"):
            compile_shmoo_plans(flow, _pattern())

    def test_platform_writers_use_dynamic_chroma_log_and_static_s100_alias(self):
        plan = compile_shmoo_plans(_flow(), _pattern())[0]
        flow = _flow()

        def fake_col(sheet, column):
            if sheet == "FLOW":
                return list(flow[column])
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers in (chroma_writers, s100_writers):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                ):
                    writers.shmoo_item_write(["PROGRAM_CP1"], output, plan)
                generated = output.getvalue()
                self.assertIn("for(", generated)
                self.assertIn("set_enter_mr_vddd_dc_verify_data(shmooDac[I])", generated)
                self.assertIn("set_enter_mr_vddd_dc_verify_data(1)", generated)

                if writers is chroma_writers:
                    # CRAFT's DATALOG_MSG grammar does not accept a dynamic
                    # two-dimensional char-array index (shmooLog[I]). Emit a
                    # literal alias per STEP while keeping item+sub semantics.
                    self.assertIn("switch(I)", generated)
                    self.assertIn('case 0: DATALOG_MSG="Mr_VDDD_DC_dac0"; break;', generated)
                    self.assertIn('case 1: DATALOG_MSG="Mr_VDDD_DC_dac3"; break;', generated)
                    self.assertIn('case 2: DATALOG_MSG="Mr_VDDD_DC_dac7"; break;', generated)
                    self.assertNotIn("DATALOG_MSG=shmooLog[I]", generated)
                    self.assertNotIn("char shmooLog[", generated)
                    self.assertIn("JUDGE_V_PPMU(PA0, shmooDown[I], shmooUp[I]", generated)
                else:
                    self.assertIn("switch(I)", generated)
                    self.assertIn("LOG_ALIAS=Mr_VDDD_DC_dac0", generated)
                    self.assertIn("LOG_ALIAS=Mr_VDDD_DC_dac3", generated)
                    self.assertIn("LOG_ALIAS=Mr_VDDD_DC_dac7", generated)
                    self.assertNotIn("LOG_ALIAS=shmooLog[I]", generated)


if __name__ == "__main__":
    unittest.main()
