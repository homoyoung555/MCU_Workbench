import pandas as pd
from openpyxl import Workbook

from program_gen.core.input_normalization import normalize_flow_table, worksheet_by_name
from program_gen.platforms.chroma.dc_scan_writer import is_dc_scan_item as chroma_is_dc_scan_item
from program_gen.platforms.s100.dc_scan_writer import is_dc_scan_item as s100_is_dc_scan_item
from preflight import schema
from preflight.reader import Cell
from preflight.report import WARN
from preflight.rules import check_char_hygiene
import analog_sweep


def test_flow_semantic_values_are_canonicalized_at_input_boundary():
    flow = pd.DataFrame(
        {
            "type": [" VERIFY ", "vt"],
            "mode": [" KEIL ", "/"],
            "OTP": [" YES ", "/"],
            "UID": [" no ", "/"],
            "PUMP": [" Yes ", "/"],
            "PE": [" PROGRAM ", "/"],
            "Bisection": [" BOTH_M ", "/"],
            "UNIT": [" UA ", "khz"],
        }
    )

    normalized = normalize_flow_table(flow)

    assert normalized.loc[0].to_dict() == {
        "type": "verify",
        "mode": "keil",
        "OTP": "yes",
        "UID": "no",
        "PUMP": "yes",
        "PE": "PROGRAM",
        "Bisection": "both_m",
        "UNIT": "uA",
    }
    assert normalized.loc[1, "type"] == "VT"
    assert normalized.loc[1, "UNIT"] == "KHz"
    assert flow.loc[0, "type"] == " VERIFY "  # input is not mutated


def test_flow_normalization_preserves_blank_cells():
    flow = pd.DataFrame({"type": [None, float("nan")], "UNIT": [pd.NA, None]})

    normalized = normalize_flow_table(flow)

    assert normalized["type"].isna().all()
    assert normalized["UNIT"].isna().all()


def test_worksheet_lookup_ignores_case_and_outer_spaces():
    workbook = Workbook()
    workbook.active.title = " dac "

    assert worksheet_by_name(workbook, "DAC").title == " dac "


def test_dc_family_classification_uses_normalized_item_name():
    for predicate in (chroma_is_dc_scan_item, s100_is_dc_scan_item):
        assert predicate(" dc_leakage_test ")
        assert predicate("DC_RPDRPU_TEST")
        assert not predicate("unrelated_test")


def test_preflight_constrains_semantic_flow_tokens_case_insensitively():
    expected = {
        "type": "verify",
        "mode": "keil",
        "OTP": "yes",
        "UID": "no",
        "PUMP": "yes",
        "PE": "program",
        "Bisection": "both_m",
        "UNIT": "uA",
    }
    for column, value in expected.items():
        spec = schema.spec_for("FLOW", column)
        assert spec["type"] == schema.ENUM
        assert spec["ci"] is True
        assert value.casefold() in {allowed.casefold() for allowed in spec["enum"]}


def test_referenced_sweep_sheet_must_exist_and_contain_rows():
    workbook = Workbook()
    workbook.active.title = "FLOW"

    try:
        analog_sweep.read_sweep_sheet(workbook, "DAC", required=True)
    except ValueError as exc:
        assert "DAC sheet" in str(exc)
    else:
        raise AssertionError("missing referenced DAC sheet must not be silently ignored")


def test_preflight_warns_but_does_not_block_normalizable_outer_spaces():
    cell = Cell("FLOW", 2, 1, "type", " VERIFY ", "s", "General")

    class Reader:
        @staticmethod
        def has_sheet(sheet):
            return sheet == "FLOW"

        @staticmethod
        def column_cells(sheet, column):
            return [cell] if (sheet, column) == ("FLOW", "type") else []

    findings = []
    check_char_hygiene(Reader(), findings)

    assert len(findings) == 1
    assert findings[0].severity == WARN
