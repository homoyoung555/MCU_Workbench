"""Compile PVD hysteresis cases into platform-neutral test actions."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.core.run_sequence import (
    NativeRunSequenceAction,
    RunSequenceCompileError,
    parse_run_sequence_step,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class PvdTestCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class PvdPoint:
    voltage: float
    expected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PvdCase:
    case_id: str
    source_rows: tuple[int, int]
    entry_actions: tuple[NativeRunSequenceAction, ...]
    points: tuple[PvdPoint, PvdPoint, PvdPoint, PvdPoint]


@dataclass(frozen=True, slots=True)
class PvdTestPlan:
    row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    power_profile: str
    compare_pins: tuple[str, str]
    cases: tuple[PvdCase, ...]
    typed_kind: str = "PVD_TEST"
    effective_recipe: tuple[str, ...] = ("PVD_TEST",)

    @property
    def row_indices(self) -> tuple[int, ...]:
        return (self.row,)

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return (self.row + 2,)


def compile_pvd_test_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    pvd: pd.DataFrame,
    version: pd.DataFrame,
    *,
    disabled_pvd_rows: frozenset[int] = frozenset(),
) -> Mapping[int, PvdTestPlan]:
    candidates = tuple(
        operation for operation in operations
        if operation.typed_kind == "PVD_TEST"
    )
    if not candidates:
        return MappingProxyType({})
    cases = _compile_cases(pvd, disabled_pvd_rows)
    default_pins = _default_pins(version)
    plans = {}
    for operation in candidates:
        executable = recipe_rows.get(operation.row)
        recipe = tuple(
            call.name for call in getattr(executable, "operations", ())
        )
        if recipe not in ((), ("PVD_TEST",)):
            raise PvdTestCompileError(
                "PVD.RECIPE.INVALID",
                operation.row,
                "PVD row requires Recipe=PVD_TEST",
            )
        record = flow.iloc[operation.row]
        pins = tuple(
            pin.strip()
            for pin in _required(
                record.get("meas pin"), operation.row, "meas pin"
            ).split("+")
            if pin.strip()
        )
        if len(pins) != 2 or len({pin.casefold() for pin in pins}) != 2:
            raise PvdTestCompileError(
                "PVD.COMPARE.PINS_INVALID",
                operation.row,
                "PVD requires two distinct meas pins separated by '+'",
            )
        cp = operation.cp.upper()
        if cp not in default_pins:
            raise PvdTestCompileError(
                "PVD.VERSION.GET_PIN_MISSING",
                operation.row,
                f"VERSION GET PIN is missing for {cp}",
            )
        try:
            compiled_cases = tuple(
                PvdCase(
                    case_id,
                    source_rows,
                    tuple(parse_run_sequence_step(
                        record.get("step"),
                        default_pins[cp],
                        dynamic_code=code,
                    )),
                    tuple(
                        PvdPoint(voltage, tuple(expected))
                        for voltage, expected in points
                    ),
                )
                for case_id, code, source_rows, points in cases
            )
        except RunSequenceCompileError as exc:
            raise PvdTestCompileError(exc.code, operation.row, str(exc)) from exc
        if any(
            len(point.expected) != len(pins)
            for case in compiled_cases
            for point in case.points
        ):
            raise PvdTestCompileError(
                "PVD.CASE.EXPECT_ARITY",
                operation.row,
                "PVD sheet expect width must match FLOW meas pin count",
            )
        plans[operation.row] = PvdTestPlan(
            operation.row,
            operation.cp,
            operation.item,
            operation.provenance,
            _required(record.get("Vcc"), operation.row, "Vcc").upper(),
            pins,
            compiled_cases,
        )
    return MappingProxyType(plans)


def _compile_cases(pvd: pd.DataFrame, disabled: frozenset[int]):
    by_case: dict[str, dict[str, tuple[int, pd.Series]]] = {}
    for row, record in pvd.iterrows():
        row = int(row)
        if row in disabled:
            continue
        case_id = _text(record.get("case"))
        direction = _text(record.get("up/down")).casefold()
        if not case_id or direction not in ("up", "down"):
            continue
        pair = by_case.setdefault(case_id, {})
        if direction in pair:
            raise PvdTestCompileError(
                "PVD.CASE.DIRECTION_DUPLICATE", 0,
                f"PVD case {case_id!r} has duplicate {direction!r} rows",
            )
        pair[direction] = (row, record)

    compiled = []
    for case_id in sorted(by_case, key=_case_sort_key):
        pair = by_case[case_id]
        if set(pair) != {"up", "down"}:
            if _pair_has_data(pair):
                raise PvdTestCompileError(
                    "PVD.CASE.PAIR_INCOMPLETE", 0,
                    f"PVD case {case_id!r} requires one up and one down row",
                )
            continue
        up_row, up = pair["up"]
        down_row, down = pair["down"]
        if not _pair_has_data(pair):
            continue
        d_min, d_max = _number(down.get("min")), _number(down.get("max"))
        u_min, u_max = _number(up.get("min")), _number(up.get("max"))
        d_guard = _voltage_delta(down.get("limit"))
        u_guard = _voltage_delta(up.get("limit"))
        d_expected = _state(down.get("expect"))
        u_expected = _state(up.get("expect"))
        if None in (d_min, d_max, u_min, u_max, d_guard, u_guard) or not d_expected or not u_expected:
            raise PvdTestCompileError(
                "PVD.CASE.FACT_MISSING", 0,
                f"PVD case {case_id!r} has an incomplete threshold row",
            )
        if len(d_expected) != len(u_expected):
            raise PvdTestCompileError(
                "PVD.CASE.EXPECT_ARITY", 0,
                f"PVD case {case_id!r} up/down expect widths differ",
            )
        if not (d_min <= d_max and u_min <= u_max):
            raise PvdTestCompileError(
                "PVD.CASE.RANGE_INVALID", 0,
                f"PVD case {case_id!r} requires min <= max",
            )
        p1, p2 = d_max - d_guard, d_min + d_guard
        p3, p4 = u_min + u_guard, u_max - u_guard
        if not (p1 > p2 < p3 < p4):
            raise PvdTestCompileError(
                "PVD.CASE.GUARD_INVALID", 0,
                f"PVD case {case_id!r} guard consumes its threshold range",
            )
        steps = {
            _text(record.get("step"))
            for _row, record in pair.values()
            if _text(record.get("step")) not in ("", "/")
        }
        if len(steps) != 1:
            raise PvdTestCompileError(
                "PVD.CASE.STEP_INVALID", 0,
                f"PVD case {case_id!r} requires one shared integer step",
            )
        step = next(iter(steps))
        if not step.isdigit() or not 0 <= int(step) <= 255:
            raise PvdTestCompileError(
                "PVD.CASE.STEP_INVALID", 0,
                f"PVD case {case_id!r} step must be 0..255",
            )
        points = (
            (_rounded(p1), _opposite(d_expected)),
            (_rounded(p2), d_expected),
            (_rounded(p3), _opposite(u_expected)),
            (_rounded(p4), u_expected),
        )
        compiled.append((
            case_id,
            int(step),
            (up_row + 2, down_row + 2),
            points,
        ))
    if not compiled:
        raise PvdTestCompileError(
            "PVD.CASES.EMPTY", 0, "PVD sheet has no active complete cases"
        )
    return tuple(compiled)


def _pair_has_data(pair) -> bool:
    fields = ("min", "max", "limit", "expect", "step")
    return any(
        _text(record.get(field)) not in ("", "/")
        for _row, record in pair.values()
        for field in fields
    )


def _number(value: object) -> float | None:
    text = _text(value)
    if text in ("", "/"):
        return None
    if text.casefold().endswith("v"):
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _voltage_delta(value: object) -> float | None:
    text = _text(value)
    if text in ("", "/"):
        return None
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mV|V)?", text, re.I
    )
    if match is None:
        return None
    number = float(match.group(1))
    if not math.isfinite(number) or number < 0:
        return None
    return number / 1000 if (match.group(2) or "V").casefold() == "mv" else number


def _state(value: object) -> str:
    state = _text(value).upper()
    return state if state and all(bit in "HL" for bit in state) else ""


def _opposite(state: str) -> str:
    return "".join("L" if bit == "H" else "H" for bit in state)


def _rounded(value: float) -> float:
    return round(value, 12)


def _case_sort_key(value: str):
    try:
        return 0, float(value)
    except ValueError:
        return 1, value


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _required(value: object, row: int, name: str) -> str:
    text = _text(value)
    if text in ("", "/"):
        raise PvdTestCompileError(
            "PVD.FLOW.FACT_MISSING", row, f"{name} is required"
        )
    return text


def _default_pins(version: pd.DataFrame) -> Mapping[str, str]:
    result = {}
    for _row, record in version.iterrows():
        cp = _text(record.get("CP num")).upper()
        pin = _text(record.get("GET PIN"))
        if cp and pin and pin != "/":
            result[cp] = pin
    return MappingProxyType(result)


__all__ = [
    "PvdCase",
    "PvdPoint",
    "PvdTestCompileError",
    "PvdTestPlan",
    "compile_pvd_test_plans",
]
