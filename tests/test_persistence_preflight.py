import unittest

import pandas as pd

from preflight.report import ERROR
from preflight.rules import check_persistence_recipe


class _FrameReader:
    def __init__(self, flow, addr_map):
        self.frames = {"FLOW": flow, "ADDR_MAP": addr_map}

    def has_sheet(self, sheet):
        return sheet in self.frames

    def frame(self, sheet):
        return self.frames[sheet]


class _CellReader:
    """Exercise the same interface used by the real MasterReader."""
    def __init__(self, flow, addr_map):
        from preflight.reader import Cell
        self.frames = {"FLOW": flow, "ADDR_MAP": addr_map}
        self.Cell = Cell

    def has_sheet(self, sheet):
        return sheet in self.frames

    def header_map(self, sheet):
        return {name: index + 1 for index, name in enumerate(self.frames[sheet].columns)}

    def row_values(self, sheet, headers):
        frame = self.frames[sheet]
        for offset, (_, record) in enumerate(frame.iterrows(), start=2):
            yield {
                name: self.Cell(sheet, offset, self.header_map(sheet)[name], name,
                                record.get(name), "s", "General")
                for name in headers
            }


class PersistencePreflightTests(unittest.TestCase):
    def test_reports_missing_page_producer_before_loadmap(self):
        findings = []
        check_persistence_recipe(
            _FrameReader(_flow("LOADMAP-PGMOTP"), _addr_map()), findings
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, ERROR)
        self.assertIn("LOADMAP", findings[0].message)

    def test_accepts_cp1_build_load_program_chain(self):
        findings = []
        check_persistence_recipe(
            _FrameReader(_flow("BUILDMAP-LOADMAP-PGMOTP"), _addr_map()), findings
        )

        self.assertEqual(findings, [])

    def test_accepts_page_image_producer_in_previous_flow_node(self):
        flow = pd.DataFrame([
            {
                "CP NO": "CP1", "item": "Memory_Wakeup", "type": "pattern",
                "sub": "/", "mode": "fbist", "Recipe": "BUILDMAP",
            },
            {
                "CP NO": "CP1", "item": "Trimdata_Write_Read", "type": "data",
                "sub": "/", "mode": "fbist", "Recipe": "LOADMAP-PGMOTP",
            },
        ])
        findings = []

        check_persistence_recipe(_FrameReader(flow, _addr_map()), findings)

        self.assertEqual(findings, [])

    def test_real_reader_shape_uses_all_addr_map_columns(self):
        findings = []
        check_persistence_recipe(
            _CellReader(_flow("BUILDMAP-LOADMAP-PGMOTP"), _addr_map()), findings
        )

        self.assertEqual(findings, [])

    def test_commit_shmoo_checks_step_range_against_field_width(self):
        flow = pd.DataFrame([
            {
                "CP NO": "CP1", "item": "Trimdata_Read", "type": "read",
                "sub": "/", "mode": "fbist", "step": "/",
                "Recipe": "READOTPMAP-LOADMAP",
            },
            {
                "CP NO": "CP1", "item": "RegSweep", "type": "shmoo",
                "sub": "/", "mode": "fbist", "step": "0-8",
                "Recipe": "COMMIT(F=STEP)-PGMOTP",
            },
        ])
        findings = []

        check_persistence_recipe(_FrameReader(flow, _addr_map()), findings)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, ERROR)
        self.assertIn("exceeds field width", findings[0].message)


def _flow(recipe):
    return pd.DataFrame([{
        "CP NO": "CP1", "item": "Trimdata_Write_Read", "type": "data",
        "sub": "/", "mode": "fbist", "Recipe": recipe,
    }])


def _addr_map():
    return pd.DataFrame([{
        "Word No.": "trim1", "line": "CP1", "bit[31:16]": "complement",
        "bit[15:0]": "REG0[15:0]", "data type": "lable",
        "CP Data[31:0]": "32'hFFFF_0000",
        "CP addr map": "OTHER[12:3],F[2:0]",
    }])


if __name__ == "__main__":
    unittest.main()
