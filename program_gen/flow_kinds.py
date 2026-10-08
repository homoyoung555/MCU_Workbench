"""Platform-neutral classification of current FLOW rows.

This module records the business routing already implemented by the two
platform ``main.py`` files.  It intentionally stops at a high-level kind: it
does not infer the unapproved internals of VT, ID, Main, or Firmware bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Mapping

import pandas as pd

from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.diagnostics import WorkbookProvenance
from program_gen.workbook import WorkbookModel


RowPredicate = Callable[[Mapping[str, object]], bool]


class FlowKindCompileError(ValueError):
    """One FLOW row cannot be assigned exactly one confirmed typed kind."""

    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW!A{row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class FlowOperation:
    """The immutable high-level classification of one valid FLOW row.

    ``row`` deliberately retains the legacy zero-based FLOW data index so the
    existing renderers can be migrated one call site at a time.  Provenance is
    the authoritative Excel location, therefore its coordinate is one-based.
    """

    row: int
    cp: str
    item: str
    source_type: str
    mode: str
    typed_kind: str
    family: str
    relay: str | None
    provenance: WorkbookProvenance


def _field_equals(field: str, expected: str) -> RowPredicate:
    return lambda row: _text(row.get(field)).upper() == expected


def _item_equals(expected: str) -> RowPredicate:
    expected_key = token_key(expected)
    return lambda row: token_key(row.get("item")) == expected_key


def _adc_family(row: Mapping[str, object]) -> bool:
    return bool(re.fullmatch(r"ADC\d+", _text(row.get("FV/FI")), re.IGNORECASE))


def _opa_family(row: Mapping[str, object]) -> bool:
    return _text(row.get("Recipe")).upper() == "OPA_TEST"


def _dac_family(row: Mapping[str, object]) -> bool:
    return _text(row.get("Recipe")).upper() == "DAC_TEST"


@dataclass(frozen=True, slots=True)
class FlowKindClassifiers:
    """Injectable equivalents of the legacy platform-family predicates.

    Default predicates use only confirmed FLOW fields and item identities.  A
    caller that has an established adapter-specific predicate may inject it
    without giving this compiler a dependency on platform modules or ``G``.
    """

    adc: RowPredicate = _adc_family
    comp: RowPredicate = _field_equals("FV/FI", "COMP")
    opa: RowPredicate = _opa_family
    dac: RowPredicate = _dac_family
    freq: RowPredicate = _field_equals("FV/FI", "FREQ")
    pvd: RowPredicate = _field_equals("FV/FI", "PVD")
    dc_leakage: RowPredicate = _item_equals("DC_Leakage_Test")
    dc_rpd_rpu: RowPredicate = _item_equals("DC_RPDRPU_Test")
    dc_vol_voh: RowPredicate = _item_equals("DC_VOLVOH_Test")
    vih_vil: RowPredicate = _item_equals("DC_VIHVIL_Test")


_SIMPLE_KINDS = {
    "os": ("OS", "OS", {"/"}),
    "trim": ("TRIM", "TRIM", {"fbist"}),
    "wake": ("FLASH_WINDOW", "FLASH_WINDOW", {"/"}),
    "data": ("TRIMDATA_WRITE", "TRIMDATA_WRITE", {"/"}),
    "shmoo": ("SHMOO", "SHMOO", {"fbist"}),
    "main": ("MAIN", "MAIN", {"/"}),
    "margin": ("MARGIN", "MARGIN", {"/"}),
    "VT": ("VT", "VT", {"/"}),
    "write": ("TRIMDATA_WRITE", "TRIMDATA_WRITE", {"/"}),
    "uid": ("UID", "UID", {"/"}),
    "id": ("ID", "ID", {"/"}),
    "read": ("TRIMDATA_READ", "TRIMDATA_READ", {"/"}),
    "adjust": ("DAC_ADJUST", "DAC_ADJUST", {"/"}),
}
_VERIFY_MODES = frozenset(("fbist", "hex", "keil", "swd", "scan", "mbist"))


def compile_flow_operations(
    workbook: WorkbookModel,
    *,
    classifiers: FlowKindClassifiers | None = None,
) -> tuple[FlowOperation, ...]:
    """Compile the canonical workbook's valid FLOW rows in workbook order."""
    if not isinstance(workbook, WorkbookModel):
        raise TypeError("compile_flow_operations expects WorkbookModel")
    return compile_flow_rows(
        workbook.dataframe("FLOW"),
        workbook_identity=workbook.identity,
        source_sha256=workbook.source_sha256,
        classifiers=classifiers,
    )


def compile_flow_rows(
    flow: pd.DataFrame,
    *,
    workbook_identity: str,
    source_sha256: str,
    classifiers: FlowKindClassifiers | None = None,
) -> tuple[FlowOperation, ...]:
    """Compile a FLOW table; kept public for focused family classification tests."""
    required = {"CP NO", "item", "type", "mode", "FV/FI"}
    missing = sorted(required.difference(flow.columns))
    if missing:
        raise ValueError(f"FK.COLUMN.MISSING: FLOW lacks {', '.join(missing)}")

    normalized = normalize_flow_table(flow)
    active_classifiers = classifiers or FlowKindClassifiers()
    operations = []
    for row_index, (_, series) in enumerate(normalized.iterrows()):
        row = series.to_dict()
        source_type = _source_type(row["type"])
        if not source_type:
            continue
        mode = _text(row["mode"]).casefold()
        provenance = WorkbookProvenance(
            sheet="FLOW",
            coordinate=f"A{row_index + 2}",
            workbook_identity=workbook_identity,
            source_sha256=source_sha256,
        )
        typed_kind, family = _classify_row(
            row_index,
            source_type,
            mode,
            row,
            active_classifiers,
        )
        operations.append(FlowOperation(
            row=row_index,
            cp=_text(row["CP NO"]),
            item=_text(row["item"]),
            source_type=source_type,
            mode=mode,
            typed_kind=typed_kind,
            family=family,
            relay=_relay(row.get("relay")),
            provenance=provenance,
        ))
    return tuple(operations)


def _classify_row(
    row_index: int,
    source_type: str,
    mode: str,
    row: Mapping[str, object],
    classifiers: FlowKindClassifiers,
) -> tuple[str, str]:
    if source_type == "verify":
        return _classify_verify(row_index, mode, row, classifiers)
    if source_type == "trim":
        item_key = token_key(row.get("item"))
        if item_key == token_key("Pdr_Trim"):
            if mode != "fbist":
                raise FlowKindCompileError(
                    "FK.MODE.UNKNOWN",
                    row_index,
                    f"PDR_TRIM does not support mode {mode!r}",
                )
            return "PDR_TRIM", "PDR"
        if item_key == token_key("Bor_Trim"):
            return "BOR_TRIM", "BOR"
        return "STANDARD_TRIM", "TRIM"
    try:
        typed_kind, family, allowed_modes = _SIMPLE_KINDS[source_type]
    except KeyError as exc:
        raise FlowKindCompileError(
            "FK.TYPE.UNKNOWN", row_index, f"unsupported FLOW type {source_type!r}",
        ) from exc
    if mode not in allowed_modes:
        raise FlowKindCompileError(
            "FK.MODE.UNKNOWN",
            row_index,
            f"type {source_type!r} does not support mode {mode!r}",
        )
    return typed_kind, family


def _classify_verify(
    row_index: int,
    mode: str,
    row: Mapping[str, object],
    classifiers: FlowKindClassifiers,
) -> tuple[str, str]:
    if mode not in _VERIFY_MODES:
        raise FlowKindCompileError(
            "FK.MODE.UNKNOWN", row_index, f"verify does not support mode {mode!r}",
        )
    if token_key(row.get("item")) == token_key("Pdr_Verify"):
        if mode != "fbist":
            raise FlowKindCompileError(
                "FK.MODE.UNKNOWN",
                row_index,
                f"PDR_VERIFY does not support mode {mode!r}",
            )
        return "PDR_VERIFY", "PDR"
    if token_key(row.get("item")) == token_key("Bor_Verify"):
        if mode != "fbist":
            raise FlowKindCompileError(
                "FK.MODE.UNKNOWN",
                row_index,
                f"BOR_VERIFY does not support mode {mode!r}",
            )
        return "BOR_VERIFY", "BOR"
    if mode == "fbist":
        return "STANDARD_VERIFY", "FBIST"
    if mode in {"hex", "scan", "mbist"}:
        return f"VERIFY_{mode.upper()}", mode.upper()

    matches = [
        ("ADC", "ADC_TEST", classifiers.adc),
        ("COMP", "VERIFY_COMP", classifiers.comp),
        ("OPA", "OPA_TEST", classifiers.opa),
        ("DAC", "DAC_TEST", classifiers.dac),
        ("FREQ", "FREQ_TEST", classifiers.freq),
        ("PVD", "PVD_TEST", classifiers.pvd),
        ("DC_LEAKAGE", "DC_PARAMETRIC_TEST", classifiers.dc_leakage),
        ("DC_RPD_RPU", "DC_PARAMETRIC_TEST", classifiers.dc_rpd_rpu),
        ("DC_VOL_VOH", "DC_PARAMETRIC_TEST", classifiers.dc_vol_voh),
        ("VIH_VIL", "DC_VIH_VIL", classifiers.vih_vil),
    ]
    matched = [(family, kind) for family, kind, predicate in matches if predicate(row)]
    if len(matched) > 1:
        names = ", ".join(family for family, _ in matched)
        raise FlowKindCompileError(
            "FK.VERIFY.AMBIGUOUS_FAMILY", row_index, f"multiple families match: {names}",
        )
    if matched:
        family, kind = matched[0]
        if family == "PVD" and mode == "swd":
            raise FlowKindCompileError(
                "FK.PVD.SWD_UNSUPPORTED", row_index, "PVD only supports mode='keil'",
            )
        return kind, family
    return f"VERIFY_{mode.upper()}", "GENERIC"


def _source_type(value: object) -> str:
    key = token_key(value)
    if not key or key == "nan":
        return ""
    return "VT" if key == "vt" else key


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _relay(value: object) -> str | None:
    relay = _text(value)
    return None if not relay or relay == "/" else relay
