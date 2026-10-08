"""One capture feeds ordered FLOW result rows without retrigger or reset."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

import pandas as pd

from flow_recipe import ExecutableFlowRow, FlowRow, ResolvedRecipeCall, parse_recipe
from program_gen.core.firmware_test import compile_firmware_test_plans, FirmwareTestCompileError
from program_gen.platforms.chroma.firmware_test_renderer import render_firmware_test
from tests.test_firmware_judge import _operation


def fixture():
    return pd.DataFrame([
        dict(sub=sub, Recipe=recipe, step=step, Vcc="VCC_TYP", UNIT="/",
             target="/", **{"low_range(%)": low, "high_range(%)": high})
        for sub, recipe, step, low, high in (
            ("TK_24M_JC_MAX", "RUN_SEQUENCE-SRAM_CAPTURE(0x0F00,3x16@2)-JUDGE", "HL-001-051-W1100", 1000, 23500),
            ("TK_24M_JC_MIN", "JUDGE", "/", 1000, 23500),
            ("TK_24M_JC_dex", "JUDGE", "/", 1, 85),
        )
    ])


def compile_plan(flow):
    operations = tuple(replace(_operation(i), item="TK_24M_Test") for i in range(len(flow)))
    rows = {}
    for op in operations:
        calls = parse_recipe(flow.iloc[op.row].Recipe)
        row = FlowRow(op.row + 2, op.cp, op.item, "verify", flow.iloc[op.row]["sub"], "keil", calls)
        rows[op.row] = ExecutableFlowRow(row, tuple(ResolvedRecipeCall(
            call.name, call.argument, parameters=call.parameters, sram_capture=call.sram_capture
        ) for call in calls))
    version = pd.DataFrame([{"CP num": "CP3", "GET PIN": "PA4", "SWD PIN": "PA4"}])
    return compile_firmware_test_plans(operations, rows, flow, version)[0]


class FirmwareSramTests(unittest.TestCase):
    def test_current_workbook_compiles_and_gui_preview_contains_all_results(self):
        from program_gen.workbook import WorkbookReader
        from program_gen.compiler import ProductCompiler
        from tests.workspace_paths import FORMAL_MASTER
        from tests.test_firmware_product_compiler import _with_flow
        from gui.item_preview import render_item_preview

        workbook = WorkbookReader().read(FORMAL_MASTER)
        flow = workbook.dataframe("FLOW")
        # Insert our fixture in memory, independent of edits to the user workbook.
        flow = flow.loc[flow["item"] != "TK_24M_Test"].reset_index(drop=True)
        positions = list(flow.index[(flow["CP NO"] == "CP3") & (flow["item"] == "Power_Test")])
        self.assertEqual(len(positions), 3)
        for position, (_, values) in zip(positions, fixture().iterrows()):
            flow.loc[position, "item"] = "TK_24M_Test"
            for column, value in values.items():
                flow.loc[position, column] = value
        start = positions[0]
        workbook = _with_flow(workbook, flow)
        compilation = ProductCompiler().compile(workbook).require_success()
        preview = render_item_preview(workbook, compilation, start + 2, "chroma", "lab")
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["text"].count("JUDGE_VARIABLE("), 3)

    def test_capture_is_shared_and_chroma_judges_three_unsigned_results(self):
        plan = compile_plan(fixture())
        self.assertEqual(tuple(p.judge.index for p in plan.phases), (0, 1, 2))
        self.assertEqual(len(plan.execution_steps), 3)
        capture = plan.phases[0].judge.capture
        self.assertTrue(all(p.judge.capture is capture for p in plan.phases))
        self.assertEqual(tuple(v.value_address for v in capture.layout.values), (0xF00, 0xF02, 0xF04))
        facts = SimpleNamespace(platform="chroma", cp="CP3", swd_pin="PA4",
                                pins=(SimpleNamespace(name="PA4", kind="io"),))
        rendered = render_firmware_test(plan, "TK_24M_Test", 64, facts)
        text = rendered.content
        self.assertEqual(text.count("POWER_ON("), 1)
        self.assertEqual(text.count("WAIT(1100mS)"), 1)
        self.assertEqual(text.count("PEL_K, ON"), 1)
        self.assertEqual(text.count("// SRAM_CAPTURE READ32"), 2)
        self.assertEqual(text.count("JUDGE_VARIABLE("), 3)
        for index, low, high, sub in ((0, 1000, 23500, "MAX"), (1, 1000, 23500, "MIN"), (2, 1, 85, "dex")):
            self.assertIn(f'{capture.result_symbol}[SOCKET][{index}],{low},{high},"TK_24M_JC_{sub}"', text)
        self.assertNotIn("firmware_dut_reset", text)
        self.assertEqual(rendered.resource_requires[0].relative_path, "pat/sram_capture.pat")

    def test_invalid_capture_result_groups_fail_closed(self):
        cases = [(1, "Recipe", "RUN_SEQUENCE-JUDGE"), (1, "step", "001"),
                 (2, "low_range(%)", "nan"), (2, "high_range(%)", 0),
                 (1, "UNIT", "V"), (1, "target", "H"),
                 (1, "sub", "TK_24M_JC_MAX"), (1, "Vcc", "VCC_MAX"),
                 (0, "Recipe", "RUN_SEQUENCE-SRAM_CAPTURE(0xF00,4x16@2)-JUDGE"),
                 (0, "Recipe", "RUN_SEQUENCE-SRAM_CAPTURE(0xF00,2x16@2)-JUDGE"),
                 (0, "Recipe", "RUN_SEQUENCE-SRAM_CAPTURE(0xF00,3x16@2)"),
                 (0, "Recipe", "RUN_SEQUENCE-SRAM_CAPTURE(0xF00,3x16@2)-JUDGE(PF=NO)")]
        for row, column, value in cases:
            with self.subTest(row=row, column=column, value=value):
                flow = fixture().astype(object)
                flow.loc[row, column] = value
                with self.assertRaises(FirmwareTestCompileError):
                    compile_plan(flow)


if __name__ == "__main__":
    unittest.main()
