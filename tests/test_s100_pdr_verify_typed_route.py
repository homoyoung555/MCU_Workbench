from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import replace
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from program_gen.compiler import ProductCompiler
from program_gen.core.pdr_verify import (
    PdrVerifyPlatform,
    PdrVoltageApplication,
)
from program_gen.platforms.s100 import main as s100_main
from program_gen.platforms.s100 import writers
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class S100PdrVerifyTypedRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.adapter = cls.compilation.adapter_view("CP1", "s100")
        cls.operation = next(
            item for item in cls.adapter.flow_operations if item.row == 41
        )
        cls.plan = cls.adapter.pdr_verify_plans[41]

    def test_route_fetches_same_row_plan_and_passes_it_to_tester_protocol(self):
        stream = io.StringIO()
        code_name = ["V_TEST_CP1"]
        with (
            patch.object(s100_main.G, "compiled_adapter", self.adapter),
            patch.object(s100_main.G, "OUT_DIR", "isolated"),
            patch.object(s100_main.G, "i", 0),
            patch.object(
                s100_main.G,
                "col",
                side_effect=AssertionError("typed route must not inspect raw FLOW"),
            ),
            patch.object(s100_main, "verify_item_write") as tester_protocol,
        ):
            s100_main._write_typed_verify(
                self.operation,
                code_name,
                stream,
                41,
                recipe_rows=self.adapter.recipe_rows,
                dac_write_plans=self.adapter.dac_write_plans,
                result_export_plans=self.adapter.result_export_plans,
            )

        tester_protocol.assert_called_once_with(
            code_name,
            stream,
            41,
            pdr_verify_plan=self.plan,
        )

    def test_route_blocks_missing_or_mismatched_plan_before_writer(self):
        cases = (
            ({}, "S100.PDR_VERIFY.PLAN_MISSING"),
            ({41: replace(self.plan, cp="CP2")}, "S100.PDR_VERIFY.CP_MISMATCH"),
            (
                {41: replace(self.plan, item="Other")},
                "S100.PDR_VERIFY.ITEM_MISMATCH",
            ),
            (
                {
                    41: replace(
                        self.plan,
                        provenance=replace(
                            self.plan.provenance, coordinate="A999"
                        ),
                    )
                },
                "S100.PDR_VERIFY.PROVENANCE_MISMATCH",
            ),
            (
                {41: replace(self.plan, platform=PdrVerifyPlatform.CHROMA)},
                "S100.PDR_VERIFY.PROFILE_MISMATCH",
            ),
            (
                {
                    41: replace(
                        self.plan,
                        voltage_application=(
                            PdrVoltageApplication.CHROMA_REGISTERED_LEVEL_AND_MLDPS
                        ),
                    )
                },
                "S100.PDR_VERIFY.PROFILE_MISMATCH",
            ),
            (
                {41: replace(self.plan, typed_kind="STANDARD_VERIFY")},
                "S100.PDR_VERIFY.KIND_MISMATCH",
            ),
        )
        for plans, code in cases:
            adapter = SimpleNamespace(pdr_verify_plans=plans)
            with (
                self.subTest(code=code),
                patch.object(s100_main.G, "compiled_adapter", adapter),
                patch.object(s100_main.G, "OUT_DIR", "isolated"),
                patch.object(s100_main.G, "i", 0),
                patch.object(s100_main, "verify_item_write") as protocol,
                self.assertRaisesRegex(ValueError, code),
            ):
                s100_main._write_typed_verify(
                    self.operation,
                    ["V_TEST_CP1"],
                    io.StringIO(),
                    41,
                    recipe_rows=self.adapter.recipe_rows,
                    dac_write_plans=self.adapter.dac_write_plans,
                    result_export_plans=self.adapter.result_export_plans,
                )
            protocol.assert_not_called()

    def test_writer_uses_plan_when_raw_mode_and_item_are_unavailable(self):
        hbin = [None] * 42
        hbin[41] = 7

        def fake_col(sheet, column):
            if (sheet, column) == ("FLOW", "Hbin"):
                return hbin
            raise AssertionError(f"unexpected raw access: {sheet}.{column}")

        output = io.StringIO()
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "trash", []),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers, "copy_file") as copy_file,
            patch.object(
                writers,
                "flow_relay",
                side_effect=AssertionError("typed PDR must use its plan relay"),
            ),
            patch.object(writers, "prj_power_pins", return_value=("VDD", "VCC")),
        ):
            writers.verify_item_write(
                ["V_TEST_CP1"],
                output,
                41,
                pdr_verify_plan=self.plan,
            )

        generated = output.getvalue()
        self.assertIn("@@PLAN Pdr_Verify", generated)
        self.assertIn("CALL_MACRO POWER_ON(_C_VCC_TYP)", generated)
        self.assertIn(
            "LOGIC_FORCE_DPS(VDD, _C_VCC_PDR_MAX, 500MA, I7, WAIT=0.5MS)",
            generated,
        )
        self.assertIn(
            "LOGIC_FORCE_DPS(VCC, _C_VCC_PDR_MIN, 500MA, I7, WAIT=0.5MS)",
            generated,
        )
        self.assertIn("if(Sys_DriverResult[T_SOCKET] > 0.5)", generated)
        self.assertIn("if(Sys_DriverResult[T_SOCKET] < 0.5)", generated)
        self.assertNotIn("borDac", generated)
        copied_sources = tuple(call.args[0] for call in copy_file.call_args_list)
        self.assertEqual(
            copied_sources,
            (
                "base\\pat_temp\\enter_pdr_verify.sd",
                "base\\pat_temp\\read_status_mode.sd",
            ),
        )


if __name__ == "__main__":
    unittest.main()
