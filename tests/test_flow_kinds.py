from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

import pandas as pd

from program_gen.flow_kinds import (
    FlowKindClassifiers,
    FlowKindCompileError,
    compile_flow_operations,
    compile_flow_rows,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class FlowKindsFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.flow = cls.workbook.dataframe("FLOW")
        cls.operations = compile_flow_operations(cls.workbook)

    def test_formal_master_has_one_immutable_operation_per_valid_flow_row(self):
        valid_rows = [
            row for _, row in self.flow.iterrows()
            if str(row["type"]).strip() and str(row["type"]).strip().lower() != "nan"
        ]

        self.assertEqual(len(self.operations), len(valid_rows))
        self.assertEqual(
            tuple(operation.row for operation in self.operations),
            tuple(range(len(valid_rows))),
        )
        self.assertEqual(
            tuple(operation.cp for operation in self.operations),
            tuple(str(row["CP NO"]).strip() for row in valid_rows),
        )
        self.assertEqual({operation.cp for operation in self.operations}, {"CP1", "CP2", "CP3"})
        with self.assertRaises(FrozenInstanceError):
            self.operations[0].typed_kind = "MUTATED"

    def test_formal_master_covers_all_current_source_types_and_verify_modes(self):
        self.assertEqual(
            {operation.source_type for operation in self.operations},
            {
                "os", "trim", "wake", "data", "verify", "shmoo", "main",
                "margin", "VT", "write", "uid", "id", "read",
            },
        )
        self.assertEqual(
            {operation.mode for operation in self.operations if operation.source_type == "verify"},
            {"fbist", "hex", "keil", "swd"},
        )
        self.assertTrue(
            all(operation.provenance.workbook_identity == self.workbook.identity
                for operation in self.operations)
        )
        self.assertTrue(
            all(operation.provenance.source_sha256 == self.workbook.source_sha256
                for operation in self.operations)
        )

    def test_formal_verify_rows_have_the_confirmed_high_level_families(self):
        by_row = {operation.row: operation for operation in self.operations}

        self.assertEqual(by_row[181].typed_kind, "DC_PARAMETRIC_TEST")
        self.assertEqual(by_row[183].typed_kind, "DC_PARAMETRIC_TEST")
        self.assertEqual(by_row[185].typed_kind, "DC_PARAMETRIC_TEST")
        self.assertEqual(by_row[187].typed_kind, "DC_VIH_VIL")
        self.assertEqual(by_row[192].typed_kind, "FREQ_TEST")
        self.assertEqual(by_row[195].typed_kind, "ADC_TEST")
        self.assertEqual(by_row[197].typed_kind, "OPA_TEST")
        self.assertEqual(by_row[198].typed_kind, "DAC_TEST")
        self.assertEqual(by_row[199].typed_kind, "PVD_TEST")
        self.assertEqual(by_row[79].typed_kind, "VERIFY_KEIL")

    def test_formal_trim_rows_split_pdr_from_standard_trim(self):
        by_row = {operation.row: operation for operation in self.operations}

        self.assertEqual(by_row[7].item, "Pdr_Trim")
        self.assertEqual(by_row[7].typed_kind, "PDR_TRIM")
        self.assertEqual(by_row[7].family, "PDR")
        self.assertEqual(by_row[8].typed_kind, "STANDARD_TRIM")
        self.assertEqual(by_row[8].family, "TRIM")


class FlowKindsClassificationTests(unittest.TestCase):
    def test_write_rows_route_to_native_trimdata_write_kind(self):
        operation = compile_flow_rows(
            pd.DataFrame([_row("write", "/", cp="CP6", item="Any_Write_Name")]),
            workbook_identity="wb", source_sha256="sha",
        )[0]

        self.assertEqual((operation.typed_kind, operation.family), (
            "TRIMDATA_WRITE", "TRIMDATA_WRITE",
        ))

    def test_read_rows_route_to_native_trimdata_read_kind(self):
        operation = compile_flow_rows(
            pd.DataFrame([_row("read", "/", cp="CP6", item="Any_Read_Name")]),
            workbook_identity="wb", source_sha256="sha",
        )[0]

        self.assertEqual((operation.typed_kind, operation.family), (
            "TRIMDATA_READ", "TRIMDATA_READ",
        ))

    def test_all_verify_modes_and_families_are_classified_without_platform_imports(self):
        rows = pd.DataFrame([
            _row("verify", "fbist"),
            _row("verify", "hex"),
            _row("verify", "keil"),
            _row("verify", "swd"),
            _row("verify", "scan"),
            _row("verify", "mbist"),
            _row("verify", "swd", fv_fi="ADC2"),
            _row("verify", "keil", fv_fi="COMP"),
            _row("verify", "swd", recipe="OPA_TEST"),
            _row("verify", "keil", recipe="DAC_TEST"),
            _row("verify", "swd", fv_fi="FREQ"),
            _row("verify", "keil", fv_fi="PVD"),
            _row("verify", "swd", item="DC_Leakage_Test"),
            _row("verify", "swd", item="DC_VIHVIL_Test"),
        ])

        operations = compile_flow_rows(rows, workbook_identity="wb", source_sha256="sha")

        self.assertEqual(
            tuple(operation.typed_kind for operation in operations),
            (
                "STANDARD_VERIFY", "VERIFY_HEX", "VERIFY_KEIL", "VERIFY_SWD",
                "VERIFY_SCAN", "VERIFY_MBIST", "ADC_TEST", "VERIFY_COMP",
                "OPA_TEST", "DAC_TEST", "FREQ_TEST", "PVD_TEST",
                "DC_PARAMETRIC_TEST", "DC_VIH_VIL",
            ),
        )

    def test_injected_predicates_can_classify_an_existing_adapter_specific_family(self):
        rows = pd.DataFrame([_row("verify", "swd", fv_fi="CUSTOM")])
        classifiers = FlowKindClassifiers(
            comp=lambda row: row["item"] == "Item",
        )

        operation = compile_flow_rows(
            rows,
            workbook_identity="wb",
            source_sha256="sha",
            classifiers=classifiers,
        )[0]

        self.assertEqual(operation.typed_kind, "VERIFY_COMP")
        self.assertEqual(operation.family, "COMP")

    def test_pvd_swd_and_unknown_type_or_mode_are_stable_compile_errors(self):
        with self.assertRaisesRegex(FlowKindCompileError, "FK.PVD.SWD_UNSUPPORTED"):
            compile_flow_rows(
                pd.DataFrame([_row("verify", "swd", fv_fi="PVD")]),
                workbook_identity="wb",
                source_sha256="sha",
            )
        with self.assertRaisesRegex(FlowKindCompileError, "FK.TYPE.UNKNOWN"):
            compile_flow_rows(
                pd.DataFrame([_row("not_a_type", "/")]),
                workbook_identity="wb",
                source_sha256="sha",
            )
        with self.assertRaisesRegex(FlowKindCompileError, "FK.MODE.UNKNOWN"):
            compile_flow_rows(
                pd.DataFrame([_row("verify", "not_a_mode")]),
                workbook_identity="wb",
                source_sha256="sha",
            )


def _row(source_type, mode, *, cp="CP1", item="Item", fv_fi="/", recipe="/"):
    return {
        "CP NO": cp,
        "item": item,
        "type": source_type,
        "mode": mode,
        "FV/FI": fv_fi,
        "Recipe": recipe,
    }


if __name__ == "__main__":
    unittest.main()
