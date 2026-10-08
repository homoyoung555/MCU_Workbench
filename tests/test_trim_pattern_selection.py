"""Regression coverage for row-local ordinary-TRIM Pattern selection."""

from dataclasses import replace
import unittest

import pandas as pd

from flow_recipe import (
    FlowCompileError,
    compile_recipe_program,
    compile_recipe_rows,
    parse_recipe,
)
from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    WorkspacePatternProducer,
    build_standard_trim_program_plan,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.render_plan import TargetKey
from program_gen.standard_trim.function_blocks import render_standard_trim
from program_gen.workbook import TableModel, WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class TrimPatternSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)

    def _workbook_with_recipe(self, recipe):
        flow = self.workbook.dataframe("FLOW")
        self.assertEqual(flow.at[10, "CP NO"], "CP1")
        self.assertEqual(flow.at[10, "item"], "Hsi_8M")
        flow.at[10, "Recipe"] = recipe
        tables = tuple(
            TableModel.from_dataframe(table.title, flow)
            if table.title == "FLOW" else table
            for table in self.workbook.tables
        )
        return replace(self.workbook, tables=tables)

    @staticmethod
    def _spec(compilation, cp):
        return next(
            spec for spec in compilation.plan.catalogs.trim_specs.values()
            if spec.cp == cp and spec.item == "Hsi_8M"
        )

    def test_cp1_pattern_selection_changes_all_dac_consumers_without_touching_cp3(self):
        compilation = ProductCompiler().compile(self._workbook_with_recipe(
            "ENTER(PATTERN=enter_hsi_16m,WAIT=3MS)\n"
            "DEPEND(Hsi_Vrega)\n"
            "TRIM(PATTERN=set_hsi_16m_dac,FWAIT=5MS,SWAIT=20US)\n"
            "DAC_ADJ(<1.16:+1,FWAIT=2MS,SWAIT=1MS)\n"
            "JUDGE(FWAIT=3MS,SWAIT=4MS)"
        )).require_success()

        cp1 = self._spec(compilation, "CP1")
        cp3 = self._spec(compilation, "CP3")
        self.assertEqual(cp1.operations[0].reference, "enter_hsi_16m")
        self.assertEqual(cp1.operations[0].wait.canonical, "3MS")
        self.assertEqual(cp1.dac.pattern_name, "set_hsi_16m_dac")
        self.assertEqual(cp1.dac.helper_name, "set_hsi_16m_trim_data")
        self.assertEqual(
            [operation.reference for operation in cp1.operations
             if operation.kind in ("TRIM", "DAC_ADJ", "JUDGE")],
            ["set_hsi_16m_dac"] * 3,
        )
        self.assertEqual(cp3.operations[0].reference, "enter_hsi_8m")
        self.assertEqual(cp3.dac.pattern_name, "set_hsi_8m_dac")
        baseline = self._spec(
            ProductCompiler().compile(self.workbook).require_success(), "CP1"
        )
        self.assertEqual(cp1.dependencies, baseline.dependencies)

        source = "\n".join(
            fragment.content.decode("gbk")
            for fragment in render_standard_trim(
                cp1,
                TargetKey("chroma", "CP1", "lab", "TRIM_PATTERN_CP1"),
                compilation.for_cp("CP1").canonical_schedule,
            )
        )
        self.assertIn("enter_hsi_16m", source)
        self.assertIn("set_hsi_16m_trim_data", source)
        self.assertNotIn("set_hsi_8m_trim_data", source)

        target = TargetKey("chroma", "CP1", "lab", "TRIM_PATTERN_CP1")
        plan = build_standard_trim_program_plan(
            compilation,
            target,
            specs=(cp1,),
            platform_facts=compile_platform_program_facts(
                self._workbook_with_recipe(
                    "ENTER(PATTERN=enter_hsi_16m,WAIT=3MS)\n"
                    "DEPEND(Hsi_Vrega)\n"
                    "TRIM(PATTERN=set_hsi_16m_dac,FWAIT=5MS,SWAIT=20US)\n"
                    "DAC_ADJ(<1.16:+1,FWAIT=2MS,SWAIT=1MS)\n"
                    "JUDGE(FWAIT=3MS,SWAIT=4MS)"
                ),
                target,
            ),
            pattern_producer=GeneratedPatternProducer.from_compilation(
                compilation,
                "chroma",
                fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma"),
            ),
        )
        paths = {artifact.relative_path for artifact in plan.artifacts}
        self.assertIn("pat/set_hsi_16m_dac.pat", paths)
        self.assertNotIn("pat/set_hsi_8m_dac.pat", paths)

    def test_two_items_sharing_a_dac_pattern_emit_one_helper(self):
        from types import SimpleNamespace
        from program_gen.standard_trim.support import compile_standard_trim_support
        compilation = ProductCompiler().compile(self._workbook_with_recipe(
            "ENTER\nDEPEND(Hsi_Vrega)\nTRIM(PATTERN=set_hsi_16m_dac)\nJUDGE"
        )).require_success()
        specs = tuple(s for s in compilation.plan.catalogs.trim_specs.values()
                      if s.cp == "CP1" and s.item in ("Hsi_8M", "Hsi_16M"))
        self.assertEqual(len(specs), 2)
        support = compile_standard_trim_support(
            TargetKey("chroma", "CP1", "lab", "SHARED_DAC"), specs,
            {"set_hsi_16m_dac": SimpleNamespace(base_label="b_data")})
        source = "".join(s.content.decode("gbk") for s in support.sections)
        self.assertEqual(source.count("set_hsi_16m_trim_data(int* b)"), 1)
        self.assertEqual(len(support.provides), 1)

    def test_verify_explicit_enter_pattern_preserves_static_pattern_facts(self):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "Hsi_8M", "type": "verify", "sub": "/",
            "mode": "fbist",
            "Recipe": "ENTER(ROLE=VERIFY,PATTERN=enter_vrefint_verify)-JUDGE",
        }])
        enter = compile_recipe_rows(
            flow, self.workbook.dataframe("pattern")
        )[0].operations[0]

        self.assertEqual(enter.pattern_role, "verify mode")
        self.assertEqual(enter.pattern_name, "enter_vrefint_verify")
        self.assertTrue(enter.pattern_explicit)
        self.assertEqual(enter.value_source, "STATIC")

    def test_verify_explicit_enter_pattern_preserves_dynamic_pattern_facts(self):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
            "mode": "fbist",
            "Recipe": (
                "ENTER(001,ROLE=VERIFY,PATTERN=enter_mr_vddd_dc_verify)-JUDGE"
            ),
        }])
        enter = compile_recipe_rows(
            flow, self.workbook.dataframe("pattern")
        )[0].operations[0]

        self.assertEqual(enter.pattern_name, "enter_mr_vddd_dc_verify")
        self.assertTrue(enter.pattern_explicit)
        self.assertEqual(enter.value_source, "ARGUMENT")
        self.assertEqual(enter.value, "001")

    def test_verify_explicit_enter_pattern_rejects_non_fbist_modes(self):
        for mode in ("swd", "pdr"):
            with self.subTest(mode=mode):
                flow = pd.DataFrame([{
                    "CP NO": "CP1", "item": "Hsi_8M", "type": "verify",
                    "sub": "/", "mode": mode,
                    "Recipe": (
                        "ENTER(ROLE=VERIFY,PATTERN=enter_vrefint_verify)-JUDGE"
                    ),
                }])
                with self.assertRaisesRegex(FlowCompileError, "mode=fbist"):
                    compile_recipe_rows(flow, self.workbook.dataframe("pattern"))

    def test_unknown_or_role_incompatible_pattern_is_rejected(self):
        for pattern in ("missing_pattern", "enter_hsi_16m"):
            with self.subTest(pattern=pattern):
                compilation = ProductCompiler().compile(self._workbook_with_recipe(
                    "ENTER\nDEPEND(Hsi_Vrega)\n"
                    f"TRIM(PATTERN={pattern})\nJUDGE"
                ))
                self.assertFalse(compilation.is_valid)
                self.assertTrue(any(
                    "PATTERN" in diagnostic.message
                    for diagnostic in compilation.diagnostics.blocking_errors
                ))

    def test_empty_or_width_incompatible_pattern_is_rejected(self):
        with self.assertRaisesRegex(FlowCompileError, "PATTERN"):
            parse_recipe("TRIM(PATTERN=)")

        compilation = ProductCompiler().compile(self._workbook_with_recipe(
            "ENTER\nDEPEND(Hsi_Vrega)\n"
            "TRIM(PATTERN=set_iref1u_dac)\nJUDGE"
        ))
        self.assertFalse(compilation.is_valid)
        self.assertTrue(any(
            "搜索宽度" in diagnostic.message
            for diagnostic in compilation.diagnostics.blocking_errors
        ))

    def test_no_explicit_pattern_preserves_the_existing_binding(self):
        compilation = ProductCompiler().compile(self.workbook).require_success()
        cp1 = self._spec(compilation, "CP1")
        cp3 = self._spec(compilation, "CP3")
        self.assertEqual(cp1.operations[0].reference, "enter_hsi_8m")
        self.assertEqual(cp1.dac.pattern_name, "set_hsi_8m_dac")
        self.assertEqual(cp3.operations[0].reference, "enter_hsi_8m")
        self.assertEqual(cp3.dac.pattern_name, "set_hsi_8m_dac")


if __name__ == "__main__":
    unittest.main()
