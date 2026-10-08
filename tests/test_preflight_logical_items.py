import unittest

from preflight.reader import Cell
from preflight.report import ERROR
from preflight.rules import check_logical_item_linkage


class Reader:
    def __init__(self, flow_rows, addr_values):
        self.flow_rows = flow_rows
        self.addr_values = addr_values

    def has_sheet(self, sheet):
        return sheet in {"FLOW", "ADDR_MAP"}

    def header_map(self, sheet):
        if sheet == "FLOW":
            return {"item": 1, "type": 2, "Recipe": 3}
        return {"CP addr map": 1}

    def row_values(self, sheet, headers):
        for row, values in enumerate(self.flow_rows, start=2):
            yield {
                header: Cell(sheet, row, index + 1, header, values.get(header), "s", "General")
                for index, header in enumerate(headers)
            }

    def column_cells(self, sheet, column):
        if (sheet, column) != ("ADDR_MAP", "CP addr map"):
            return []
        return [
            Cell(sheet, row, 1, column, value, "s", "General")
            for row, value in enumerate(self.addr_values, start=2)
        ]


class LogicalItemPreflightTests(unittest.TestCase):
    def test_rejects_legacy_role_suffix_in_ordinary_addr_map_reference(self):
        reader = Reader(
            [{"item": "Hsi_Vrega", "type": "trim", "Recipe": "ENTER-TRIM-JUDGE"}],
            ["Hsi_Vrega_Trim[2:0]"],
        )
        findings = []

        check_logical_item_linkage(reader, findings)

        self.assertEqual([(f.severity, f.coord) for f in findings], [(ERROR, "A2")])

    def test_keeps_dedicated_pdr_addr_map_name_outside_generic_rule(self):
        reader = Reader(
            [{"item": "Pdr", "type": "trim", "Recipe": "ENTER-TRIM-JUDGE"}],
            ["Pdr_Trim[3:0]"],
        )
        findings = []

        check_logical_item_linkage(reader, findings)

        self.assertEqual(findings, [])

    def test_rejects_depend_target_without_trim_source(self):
        reader = Reader(
            [{"item": "Hsi_8M", "type": "trim", "Recipe": "ENTER-DEPEND(Missing)-TRIM-JUDGE"}],
            ["Hsi_8M[11:0]"],
        )
        findings = []

        check_logical_item_linkage(reader, findings)

        self.assertEqual([(f.severity, f.coord) for f in findings], [(ERROR, "C2")])


if __name__ == "__main__":
    unittest.main()
