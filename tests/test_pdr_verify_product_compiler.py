from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from program_gen.compiler import ProductCompiler
from program_gen.core.pdr_verify import PdrVerifyPlanError
from program_gen.flow_kinds import (
    FlowKindCompileError,
    compile_flow_rows,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class PdrVerifyProductCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_pdr_and_bor_are_excluded_from_standard_verify(self):
        operations = compile_flow_rows(
            pd.DataFrame((
                _row(" Pdr_Verify ", "fbist"),
                _row("Bor_Verify", "fbist"),
                _row("Ordinary_Verify", "fbist"),
            )),
            workbook_identity="workbook-id",
            source_sha256="source-sha",
        )

        self.assertEqual(
            tuple((item.typed_kind, item.family) for item in operations),
            (
                ("PDR_VERIFY", "PDR"),
                ("BOR_VERIFY", "BOR"),
                ("STANDARD_VERIFY", "FBIST"),
            ),
        )
        with self.assertRaises(FlowKindCompileError) as caught:
            compile_flow_rows(
                pd.DataFrame((_row("Pdr_Verify", "hex"),)),
                workbook_identity="workbook-id",
                source_sha256="source-sha",
            )
        self.assertEqual(caught.exception.code, "FK.MODE.UNKNOWN")

    def test_catalog_and_adapter_views_expose_both_platform_typed_plans(self):
        catalogs = self.compilation.plan.catalogs
        self.assertEqual(tuple(catalogs.pdr_verify_plans), ("chroma", "s100"))
        self.assertEqual(
            tuple(catalogs.pdr_verify_plans["chroma"]),
            (41, 113),
        )
        self.assertEqual(
            tuple(catalogs.pdr_verify_plans["s100"]),
            (41, 113),
        )

        operations = {
            operation.row: operation
            for operation in catalogs.flow_operations
            if operation.typed_kind == "PDR_VERIFY"
        }
        self.assertEqual(tuple(operations), (41, 113))
        for platform in ("chroma", "s100"):
            plans = catalogs.pdr_verify_plans[platform]
            for row, plan in plans.items():
                with self.subTest(platform=platform, row=row):
                    self.assertEqual(plan.platform.value, platform)
                    self.assertEqual(plan.typed_kind, "PDR_VERIFY")
                    self.assertEqual(plan.provenance, operations[row].provenance)
                    self.assertEqual(plan.row, row)
            view = self.compilation.adapter_view("CP1", platform)
            self.assertIs(view.pdr_verify_plans, plans)

        for cp, expected_row in (("CP1", 41), ("CP2", 113)):
            definition = next(
                item
                for item in self.compilation.for_cp(cp).definitions
                if item.item.casefold() == "pdr_verify"
            )
            self.assertEqual(definition.typed_kind, "PDR_VERIFY")
            self.assertEqual(definition.effective_recipe, ("PDR_VERIFY",))
            self.assertEqual(definition.source_rows, (expected_row + 2,))

    def test_platform_plan_serialization_and_product_identity_are_deterministic(self):
        repeated = ProductCompiler().compile(self.workbook).require_success()

        self.assertEqual(repeated.identity, self.compilation.identity)
        self.assertEqual(
            repeated.plan.canonical_json(),
            self.compilation.plan.canonical_json(),
        )
        self.assertEqual(
            dict(repeated.plan.catalogs.pdr_verify_plans["chroma"]),
            dict(self.compilation.plan.catalogs.pdr_verify_plans["chroma"]),
        )
        self.assertEqual(
            dict(repeated.plan.catalogs.pdr_verify_plans["s100"]),
            dict(self.compilation.plan.catalogs.pdr_verify_plans["s100"]),
        )

    def test_pdr_plan_compile_error_keeps_its_stable_diagnostic_code(self):
        error = PdrVerifyPlanError("PV.TEST.CONTRACT", "broken PDR plan")
        with patch(
            "program_gen.compiler.compile_pdr_verify_plan",
            side_effect=error,
        ):
            compilation = ProductCompiler().compile(self.workbook)

        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            tuple(item.code for item in compilation.diagnostics.errors),
            ("PV.TEST.CONTRACT",),
        )


def _row(item: str, mode: str) -> dict[str, str]:
    return {
        "CP NO": "CP1",
        "item": item,
        "type": "verify",
        "mode": mode,
        "FV/FI": "/",
    }


if __name__ == "__main__":
    unittest.main()
