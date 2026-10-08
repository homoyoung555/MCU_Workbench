"""Compile dedicated status-transition trim protocols.

Dedicated trims are not variants of target-driven analogue/frequency TrimSpec.
This module keeps their protocol identity explicit and refuses to infer a PDR
implementation for another item such as BOR.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

import pandas as pd

from program_gen.core.input_normalization import normalize_flow_table
from program_gen.core.recipe_trim import (
    recipe_pattern_name,
    trim_data_helper_name,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class DedicatedTrimCompileError(ValueError):
    """A dedicated trim row does not satisfy its registered protocol."""

    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW!A{row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class DedicatedTrimPlan:
    flow_row_index: int
    cp: str
    item: str
    typed_kind: str
    effective_recipe: tuple[str, ...]
    search_variant: str
    dac_bits: int
    search_codes: tuple[int, ...]
    initial_vcc: str
    relay: str | None
    test_number: int
    pdr_min_voltage: str
    pdr_target_voltage: str
    pdr_max_voltage: str
    dac_pattern_name: str
    helper_name: str
    write_pin: str
    provenance: WorkbookProvenance


def compile_dedicated_trim_plans(
    flow_frame: pd.DataFrame,
    flow_operations: Sequence[FlowOperation],
    *,
    pattern_frame: pd.DataFrame,
    version_frame: pd.DataFrame,
) -> Mapping[int, DedicatedTrimPlan]:
    """Return immutable dedicated plans keyed by zero-based FLOW data row."""
    flow = normalize_flow_table(flow_frame)
    plans: dict[int, DedicatedTrimPlan] = {}
    for operation in flow_operations:
        if operation.source_type != "trim":
            continue
        if operation.typed_kind == "STANDARD_TRIM":
            continue
        row = operation.row
        if operation.typed_kind != "PDR_TRIM" or operation.item.casefold() != "pdr_trim":
            raise DedicatedTrimCompileError(
                "DT.KIND.UNSUPPORTED",
                row,
                f"dedicated trim item {operation.item!r} has no registered protocol",
            )
        record = flow.loc[row]
        search = str(record.get("Bisection", "")).strip().casefold()
        if search != "yes":
            raise DedicatedTrimCompileError(
                "DT.PDR.SEARCH", row, "Pdr_Trim requires Bisection=yes"
            )
        try:
            dac_bits = int(record.get("DAC bit"))
        except (TypeError, ValueError) as exc:
            raise DedicatedTrimCompileError(
                "DT.PDR.DAC_BITS", row, "Pdr_Trim requires DAC bit=4"
            ) from exc
        if dac_bits != 4:
            raise DedicatedTrimCompileError(
                "DT.PDR.DAC_BITS", row, "Pdr_Trim requires DAC bit=4"
            )
        search_codes = _search_codes(record.get("step"), row)
        initial_vcc = _required_text(
            record.get("Vcc"), "DT.PDR.VCC", row, "Pdr_Trim requires Vcc"
        )
        initial_vcc = initial_vcc.upper()
        if initial_vcc not in {"VCC_MIN", "VCC_TYP", "VCC_MAX"}:
            raise DedicatedTrimCompileError(
                "DT.PDR.VCC",
                row,
                f"unsupported Pdr_Trim initial Vcc symbol {initial_vcc!r}",
            )
        version = _version_row(version_frame, operation.cp, row)
        pdr_min = _voltage(version.get("pdr min"), "MIN", row)
        pdr_target = _voltage(version.get("pdr target"), "TARGET", row)
        pdr_max = _voltage(version.get("pdr max"), "MAX", row)
        if not pdr_min < pdr_target < pdr_max:
            raise DedicatedTrimCompileError(
                "DT.PDR.VOLTAGE.ORDER",
                row,
                "PDR voltages must satisfy min < target < max",
            )
        write_pin = _required_text(
            version.get("SWD PIN"),
            "DT.PDR.WRITE_PIN",
            row,
            "Pdr_Trim requires VERSION.SWD PIN",
        )
        dac_pattern_name = recipe_pattern_name(operation.item, "trim dac")
        _require_pattern_role(pattern_frame, operation.item, "trim dac", row)
        plans[row] = DedicatedTrimPlan(
            flow_row_index=row,
            cp=operation.cp,
            item=operation.item,
            typed_kind=operation.typed_kind,
            effective_recipe=("PDR_TRIM",),
            search_variant="PDR_STATUS_TRANSITION",
            dac_bits=dac_bits,
            search_codes=search_codes,
            initial_vcc=initial_vcc,
            relay=operation.relay,
            test_number=_test_number(
                flow_frame, pattern_frame, operation.cp, operation.item, row
            ),
            pdr_min_voltage=f"{pdr_min:g}",
            pdr_target_voltage=f"{pdr_target:g}",
            pdr_max_voltage=f"{pdr_max:g}",
            dac_pattern_name=dac_pattern_name,
            helper_name=trim_data_helper_name(operation.item),
            write_pin=write_pin,
            provenance=operation.provenance,
        )
    return MappingProxyType(plans)


_PDR_SEARCH_CODES = (8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7)


def _search_codes(value: object, row: int) -> tuple[int, ...]:
    try:
        codes = tuple(int(token.strip()) for token in str(value).split(","))
    except (TypeError, ValueError) as exc:
        raise DedicatedTrimCompileError(
            "DT.PDR.SEARCH_CODES", row, "Pdr_Trim step must be 16 integer DAC codes"
        ) from exc
    if codes != _PDR_SEARCH_CODES:
        raise DedicatedTrimCompileError(
            "DT.PDR.SEARCH_CODES",
            row,
            f"Pdr_Trim requires the frozen DAC sequence {_PDR_SEARCH_CODES!r}",
        )
    return codes


def _version_row(version: pd.DataFrame, cp: str, row: int):
    if "CP num" not in version.columns:
        raise DedicatedTrimCompileError(
            "DT.PDR.VERSION", row, "VERSION lacks CP num"
        )
    matches = version[
        version["CP num"].astype(str).str.strip().str.casefold() == cp.casefold()
    ]
    if len(matches) != 1:
        raise DedicatedTrimCompileError(
            "DT.PDR.VERSION",
            row,
            f"expected one VERSION row for {cp}, found {len(matches)}",
        )
    return matches.iloc[0]


def _voltage(value: object, role: str, row: int) -> float:
    try:
        voltage = float(_required_text(
            value,
            f"DT.PDR.VOLTAGE.{role}",
            row,
            f"Pdr_Trim requires PDR {role.lower()} voltage",
        ))
    except ValueError as exc:
        if isinstance(exc, DedicatedTrimCompileError):
            raise
        raise DedicatedTrimCompileError(
            f"DT.PDR.VOLTAGE.{role}", row, f"invalid PDR {role.lower()} voltage"
        ) from exc
    if voltage <= 0:
        raise DedicatedTrimCompileError(
            f"DT.PDR.VOLTAGE.{role}", row, f"PDR {role.lower()} voltage must be positive"
        )
    return voltage


def _required_text(value: object, code: str, row: int, message: str) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    if not text or text == "/":
        raise DedicatedTrimCompileError(code, row, message)
    return text


def _require_pattern_role(
    pattern: pd.DataFrame, item: str, role: str, row: int
) -> None:
    required = {"item", "pattern"}
    if not required.issubset(pattern.columns):
        raise DedicatedTrimCompileError(
            "DT.PDR.PATTERN", row, "PATTERN lacks item/pattern columns"
        )
    matches = pattern[
        pattern["item"].astype(str).str.strip().str.casefold() == item.casefold()
    ]
    roles = {
        str(value).strip().casefold()
        for value in matches["pattern"]
        if not pd.isna(value)
    }
    if role.casefold() not in roles:
        raise DedicatedTrimCompileError(
            "DT.PDR.PATTERN", row, f"{item} lacks PATTERN role {role!r}"
        )


def _test_number(
    flow: pd.DataFrame,
    pattern: pd.DataFrame,
    cp: str,
    item: str,
    row: int,
) -> int:
    names: list[str] = []
    current_item = ""
    pattern_items = pattern["item"]
    pattern_values = pattern["pattern"]
    flow_types = flow["type"]
    flow_cps = flow["CP NO"]
    flow_items = flow["item"]
    for index in range(len(pattern_items)):
        raw_item = pattern_items.iloc[index]
        if isinstance(raw_item, str):
            current_item = raw_item
        raw_pattern = pattern_values.iloc[index]
        if not isinstance(raw_pattern, str) or raw_pattern == "reuse dac":
            continue
        for flow_index in range(len(flow_types)):
            if (
                flow_cps.iloc[flow_index] == cp
                and flow_types.iloc[flow_index] not in ("os", "shmoo")
                and flow_items.iloc[flow_index] == current_item
            ):
                names.append(current_item)
    try:
        return (names.index(item) + 1) * 50
    except ValueError as exc:
        raise DedicatedTrimCompileError(
            "DT.PDR.TEST_NUMBER", row, f"cannot resolve PATTERN order for {item!r}"
        ) from exc
