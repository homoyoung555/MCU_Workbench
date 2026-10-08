from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from preflight import ERROR, WARN, check_master
from program_gen import state
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class WorkbookReaderFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = WorkbookReader().read(FORMAL_MASTER)

    def test_formal_master_identity_sheet_order_and_dimensions(self):
        self.assertEqual(
            self.model.source_sha256,
            "EC90D9FF5D20CF96DB0A6CE78DCE961676AF77F36CE289BF8F64B8C714289003",
        )
        self.assertEqual(
            self.model.sheetnames,
            [
                "VERSION",
                "FLOW",
                "ADDR_MAP",
                "PIN DEC",
                "KP RELAY",
                "NM_pattern",
                "FLASH_EPR",
                "pattern",
                "PIN DEC SINGEL",
                "IOMUX",
                "OPA",
                "PVD",
                "DAC",
                "ADC",
                "FREQ",
            ],
        )

    def test_formal_sram_trigger_uses_the_supported_get_pin(self):
        flow = self.model["FLOW"]
        expected = "PA13:HL-W500\nPA13:HL-W100"

        self.assertEqual(flow["L81"].value, expected)
        self.assertEqual(flow["L153"].value, expected)
        self.assertEqual(flow["V81"].value, "/")
        self.assertEqual(flow["V153"].value, "/")
        self.assertEqual(
            {
                sheet.title: (sheet.max_row, sheet.max_column)
                for sheet in self.model.worksheets
            },
            {
                "VERSION": (4, 33),
                "FLOW": (207, 25),
                "ADDR_MAP": (449, 12),
                "PIN DEC": (3961, 8),
                "KP RELAY": (65, 4),
                "NM_pattern": (32, 3),
                "FLASH_EPR": (16, 15),
                "pattern": (245, 4),
                "PIN DEC SINGEL": (65, 5),
                "IOMUX": (71, 10),
                "OPA": (12, 9),
                "PVD": (17, 8),
                "DAC": (34, 5),
                "ADC": (45, 5),
                "FREQ": (15, 7),
            },
        )

    def test_all_formulas_keep_formula_text_and_cached_values(self):
        formula_cells = [
            cell
            for sheet in self.model.worksheets
            for row in sheet.rows
            for cell in row
            if cell.formula is not None
        ]

        self.assertEqual(len(formula_cells), 15442)
        self.assertTrue(all(cell.cached_value is not None for cell in formula_cells))

    def test_format_markers_and_merged_ranges_are_preserved(self):
        self.assertEqual(len(self.model["pattern"].merged_cells.ranges), 89)
        self.assertEqual(
            {str(cell_range) for cell_range in self.model["IOMUX"].merged_cells.ranges},
            {"B1:F1", "G1:H1", "I1:J1"},
        )
        self.assertEqual(
            {str(cell_range) for cell_range in self.model["ADC"].merged_cells.ranges},
            {"A2:A23", "A24:A45", "E2:E23", "E24:E45"},
        )
        self.assertEqual(
            {str(cell_range) for cell_range in self.model["FREQ"].merged_cells.ranges},
            {"A2:A5", "A7:A15"},
        )
        for coordinate in ("B4", "B5"):
            cell = self.model["FLOW"][coordinate]
            self.assertEqual(cell.fill.fgColor.type, "rgb")
            self.assertEqual(cell.fill.fgColor.rgb, "FFFFFF00")

    def test_sheet_facade_supports_the_legacy_read_only_subset(self):
        flow = self.model.sheet("FLOW")

        self.assertEqual(self.model["FLOW"].title, flow.title)
        self.assertEqual(flow.cell(row=4, column=2).coordinate, "B4")
        self.assertEqual(flow["B4"].value, flow.cell(row=4, column=2).value)
        self.assertEqual(flow["B"][3].coordinate, "B4")
        self.assertEqual(flow[4][1].coordinate, "B4")
        self.assertEqual(
            next(
                flow.iter_rows(
                    min_row=4,
                    max_row=4,
                    min_col=2,
                    max_col=3,
                    values_only=True,
                )
            ),
            (flow["B4"].value, flow["C4"].value),
        )

    def test_repeat_read_is_deterministic_loads_bytes_once_and_writes_nothing(self):
        calls = []

        def load_bytes(path):
            calls.append(path)
            return path.read_bytes()

        def directory_snapshot(root):
            return {
                path.relative_to(root).as_posix(): (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                for path in root.rglob("*")
                if path.is_file()
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copied_master = root / FORMAL_MASTER.name
            shutil.copy2(FORMAL_MASTER, copied_master)
            before = directory_snapshot(root)

            repeated = WorkbookReader(byte_loader=load_bytes).read(copied_master)

            self.assertEqual(calls, [copied_master.resolve()])
            self.assertEqual(directory_snapshot(root), before)
            self.assertEqual(repeated.source_sha256, self.model.source_sha256)
            self.assertEqual(repeated.identity, self.model.identity)

    def test_dataframe_projection_matches_pandas_for_the_eight_legacy_tables(self):
        table_names = [
            "VERSION",
            "FLOW",
            "ADDR_MAP",
            "PIN DEC",
            "KP RELAY",
            "NM_pattern",
            "FLASH_EPR",
            "pattern",
        ]
        expected = pd.read_excel(
            FORMAL_MASTER,
            sheet_name=table_names,
            dtype=object,
        )

        for title in table_names:
            with self.subTest(sheet=title):
                pd.testing.assert_frame_equal(
                    self.model.dataframe(title),
                    expected[title],
                    check_dtype=True,
                    check_exact=True,
                )

    def test_preflight_accepts_the_model_without_reopening_the_workbook(self):
        with patch("preflight.reader.WorkbookReader") as reader:
            findings = check_master(self.model)

        reader.assert_not_called()
        self.assertEqual(sum(item.severity == ERROR for item in findings), 0)
        self.assertEqual(sum(item.severity == WARN for item in findings), 27)

    def test_state_projection_uses_the_supplied_model_without_calling_reader(self):
        with tempfile.TemporaryDirectory() as base_dir:
            with patch("program_gen.state.WorkbookReader") as reader:
                state.init(
                    base_dir=base_dir,
                    platform="s100",
                    mode="production",
                    master="must-not-be-read.xlsx",
                    workbook_model=self.model,
                )

        reader.assert_not_called()
        self.assertEqual(state.wb.identity, self.model.identity)
        self.assertEqual(state.ws.title, "FLOW")
        self.assertEqual(state.wc.title, "pattern")
        pd.testing.assert_frame_equal(
            state.VERSION,
            self.model.dataframe("VERSION"),
            check_dtype=True,
            check_exact=True,
        )


if __name__ == "__main__":
    unittest.main()
