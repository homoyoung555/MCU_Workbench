from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import replace
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from program_gen.compiler import ProductCompiler
from program_gen.core.pdr_verify import PdrVerifyPlatform
from program_gen.platforms.chroma import main as chroma_main
from program_gen.platforms.chroma import writers
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class ChromaPdrVerifyTypedRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.adapter = cls.compilation.adapter_view("CP1", "chroma")
        cls.operation = next(
            item
            for item in cls.adapter.flow_operations
            if item.row == 41
        )
        cls.plan = cls.adapter.pdr_verify_plans[41]

    def test_route_fetches_the_same_row_plan_and_passes_it_to_legacy_protocol(self):
        stream = io.StringIO()
        code_name = ["V_TEST_CP1"]
        with (
            patch.object(chroma_main.G, "compiled_adapter", self.adapter),
            patch.object(chroma_main.G, "OUT_DIR", "isolated"),
            patch.object(chroma_main.G, "i", 0),
            patch.object(
                chroma_main.G,
                "col",
                side_effect=AssertionError("typed route must not inspect raw FLOW"),
            ),
            patch.object(chroma_main, "verify_item_write") as legacy_protocol,
        ):
            chroma_main._write_typed_verify(
                self.operation,
                code_name,
                stream,
                41,
                recipe_rows=self.adapter.recipe_rows,
                dac_write_plans=self.adapter.dac_write_plans,
                result_export_plans=self.adapter.result_export_plans,
            )

        legacy_protocol.assert_called_once_with(
            code_name,
            stream,
            41,
            pdr_verify_plan=self.plan,
        )

    def test_route_blocks_missing_or_mismatched_typed_plan_before_writer(self):
        cases = (
            ({}, "CHROMA.PDR_VERIFY.PLAN_MISSING"),
            ({41: replace(self.plan, cp="CP2")}, "CHROMA.PDR_VERIFY.CP_MISMATCH"),
            ({41: replace(self.plan, item="Other")}, "CHROMA.PDR_VERIFY.ITEM_MISMATCH"),
            (
                {41: replace(
                    self.plan,
                    provenance=replace(self.plan.provenance, coordinate="A999"),
                )},
                "CHROMA.PDR_VERIFY.PROVENANCE_MISMATCH",
            ),
            (
                {41: replace(self.plan, platform=PdrVerifyPlatform.S100)},
                "CHROMA.PDR_VERIFY.PROFILE_MISMATCH",
            ),
        )
        for plans, code in cases:
            adapter = SimpleNamespace(cp="CP1", pdr_verify_plans=plans)
            with (
                self.subTest(code=code),
                patch.object(chroma_main.G, "compiled_adapter", adapter),
                patch.object(chroma_main.G, "OUT_DIR", "isolated"),
                patch.object(chroma_main.G, "i", 0),
                patch.object(chroma_main, "verify_item_write") as protocol,
                self.assertRaisesRegex(ValueError, code),
            ):
                chroma_main._write_typed_verify(
                    self.operation,
                    ["V_TEST_CP1"],
                    io.StringIO(),
                    41,
                    recipe_rows=self.adapter.recipe_rows,
                    dac_write_plans=self.adapter.dac_write_plans,
                    result_export_plans=self.adapter.result_export_plans,
                )
            protocol.assert_not_called()

    def test_other_cp_row_is_valid_but_writer_skips_it_from_typed_cp(self):
        cp2_operation = next(
            operation
            for operation in self.adapter.flow_operations
            if operation.row == 113
        )
        cp2_plan = self.adapter.pdr_verify_plans[113]
        stream = io.StringIO()
        with (
            patch.object(chroma_main.G, "compiled_adapter", self.adapter),
            patch.object(chroma_main.G, "OUT_DIR", "isolated"),
            patch.object(chroma_main.G, "i", 0),
            patch.object(
                chroma_main.G,
                "col",
                side_effect=AssertionError("other-CP typed row must not inspect raw FLOW"),
            ),
        ):
            chroma_main._write_typed_verify(
                cp2_operation,
                ["V_TEST_CP1"],
                stream,
                113,
                recipe_rows=self.adapter.recipe_rows,
                dac_write_plans=self.adapter.dac_write_plans,
                result_export_plans=self.adapter.result_export_plans,
            )

        self.assertEqual(cp2_plan.cp, "CP2")
        self.assertEqual(stream.getvalue(), "")

    def test_writer_selects_pdr_protocol_from_plan_even_if_raw_mode_item_are_poisoned(self):
        columns = {
            ("VERSION", "page word"): [1],
            ("FLOW", "CP NO"): ["CP1"],
            ("FLOW", "item"): ["Not_Pdr_Verify"],
            ("FLOW", "type"): ["verify"],
            ("FLOW", "mode"): ["hex"],
            ("FLOW", "Vcc"): ["VCC_TYP"],
        }

        def fake_col(sheet, column):
            try:
                return columns[(sheet, column)]
            except KeyError as exc:
                raise AssertionError(f"unexpected raw access: {sheet}.{column}") from exc

        output = io.StringIO()
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "trash", []),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers, "copy_file"),
            patch.object(writers, "flow_relay", return_value="/"),
            patch.object(writers, "vcc_rails_str", return_value="VCC"),
        ):
            writers.verify_item_write(
                ["V_TEST_CP1"], output, 0, pdr_verify_plan=self.plan
            )

        generated = output.getvalue()
        self.assertIn("LEVELS(PDR_MAX_LVL, 3mS)", generated)
        self.assertIn("LEVELS(PDR_MIN_LVL, 3mS)", generated)
        self.assertIn("JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode)", generated)
        self.assertNotIn("borDac", generated)


if __name__ == "__main__":
    unittest.main()
