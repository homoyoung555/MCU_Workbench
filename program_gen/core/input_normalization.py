"""Normalize user-facing workbook tokens at the workbook input boundary."""

import pandas as pd


def token_key(value):
    """Return the comparison key used for case-insensitive workbook tokens."""
    return str(value).strip().casefold()


def worksheet_by_name(workbook, expected, required=True):
    """Resolve a worksheet name case-insensitively after trimming outer spaces."""
    wanted = token_key(expected)
    matches = [sheet for sheet in workbook.worksheets if token_key(sheet.title) == wanted]
    if len(matches) > 1:
        names = ", ".join(repr(sheet.title) for sheet in matches)
        raise ValueError(f"sheet 名称归一化后冲突: {names}")
    if matches:
        return matches[0]
    if required:
        raise KeyError(f"缺少 sheet: {expected}")
    return None


_LOWER_COLUMNS = {"mode", "OTP", "UID", "PUMP", "Bisection"}
_UNIT_CANONICAL = {
    "/": "/",
    "a": "A",
    "ma": "mA",
    "ua": "uA",
    "na": "nA",
    "v": "V",
    "mv": "mV",
    "hz": "Hz",
    "khz": "KHz",
    "mhz": "MHz",
    "ghz": "GHz",
    "pat": "pat",
    "cap": "cap",
}


def _normalize_type(value):
    key = token_key(value)
    return "VT" if key == "vt" else key


def _normalize_pe(value):
    key = token_key(value)
    return key.upper() if key in {"erase", "program"} else key


def _normalize_unit(value):
    key = token_key(value)
    return _UNIT_CANONICAL.get(key, str(value).strip())


def _map_present(value, normalizer):
    return value if pd.isna(value) else normalizer(value)


def normalize_flow_table(flow):
    """Return a copy whose semantic FLOW tokens use generator canonical forms."""
    normalized = flow.copy()
    for column in _LOWER_COLUMNS.intersection(normalized.columns):
        normalized[column] = normalized[column].map(
            lambda value: _map_present(value, token_key)
        )
    if "type" in normalized.columns:
        normalized["type"] = normalized["type"].map(
            lambda value: _map_present(value, _normalize_type)
        )
    if "PE" in normalized.columns:
        normalized["PE"] = normalized["PE"].map(
            lambda value: _map_present(value, _normalize_pe)
        )
    if "UNIT" in normalized.columns:
        normalized["UNIT"] = normalized["UNIT"].map(
            lambda value: _map_present(value, _normalize_unit)
        )
    return normalized
