"""Compile FREQ sheet cases into immutable frequency-test plans."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.core.encoding import calc_limit
from program_gen.core.run_sequence import (
    LevelSequenceAction, SendCodeAction, WaitAction, RepowerAction,
    RunSequenceCompileError, parse_run_sequence_step, parse_run_sequence_template,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class FreqTestCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class ExternalClockPlan:
    pin: str
    frequency_hz: float


@dataclass(frozen=True, slots=True)
class FreqCase:
    sheet_row: int
    source: str
    multiplier: float
    divider: float
    target: float
    unit: str
    low_limit: float
    high_limit: float
    config_pattern: str | None
    external_clock: ExternalClockPlan | None
    repower_before: bool
    actions: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class FreqTestPlan:
    row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    power_profile: str
    measurement_pin: str
    cases: tuple[FreqCase, ...]
    protocol: str = "swd"
    entry_actions: tuple[object, ...] = ()
    exit_actions: tuple[object, ...] = ()
    typed_kind: str = "FREQ_TEST"
    effective_recipe: tuple[str, ...] = ("FREQ_TEST",)

    @property
    def row_indices(self):
        return (self.row,)

    @property
    def excel_rows(self):
        return (self.row + 2,)

    @property
    def session_count(self):
        return 1 + sum(case.repower_before for case in self.cases[1:])

    @property
    def config_patterns(self):
        return tuple(case.config_pattern for case in self.cases if case.config_pattern)


_SOURCE_RE = re.compile(r"^(?P<family>[A-Za-z][A-Za-z0-9]*)_(?P<number>\d+(?:P\d+)?)(?P<scale>[KMG]?)(?:HZ)?$", re.I)
_SCALE = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}
_EXTERNAL_ROLE = {"HSE": "OSCIN", "LSE": "OSC32IN"}


def compile_freq_test_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    freq: pd.DataFrame,
    iomux: pd.DataFrame,
    version: pd.DataFrame,
) -> Mapping[int, FreqTestPlan]:
    candidates = tuple(operation for operation in operations if operation.typed_kind == "FREQ_TEST")
    if not candidates:
        return MappingProxyType({})
    products = _products(version)
    rows = _sheet_rows(freq)
    plans = {}
    for operation in candidates:
        record = flow.iloc[operation.row]
        if operation.mode not in ("swd", "keil"):
            raise FreqTestCompileError("FREQ.MODE.INVALID", operation.row, "mode must be swd or keil")
        recipe = tuple(call.name for call in getattr(recipe_rows.get(operation.row), "operations", ()))
        if recipe not in ((), ("FREQ_TEST",)):
            raise FreqTestCompileError("FREQ.RECIPE.INVALID", operation.row, repr(recipe))
        if _required(record.get("FV/FI"), operation.row, "FV/FI").upper() != "FREQ":
            raise FreqTestCompileError("FREQ.MARKER.INVALID", operation.row, "FV/FI must be FREQ")
        if operation.mode == "swd" and _text(record.get("step")).upper() not in ("", "/", "T"):
            raise FreqTestCompileError("FREQ.FLOW.STEP.INVALID", operation.row, "FLOW step must be '/' (legacy T is migration-only)")
        try:
            product = products[operation.cp.upper()]
        except KeyError as exc:
            raise FreqTestCompileError("FREQ.VERSION.MISSING", operation.row, operation.cp) from exc
        group = tuple(row for row in rows if row[0].casefold() == operation.item.casefold())
        if not group:
            raise FreqTestCompileError("FREQ.GROUP.MISSING", operation.row, operation.item)
        get_pin = next((_text(row.get("GET PIN")) for _, row in version.iterrows()
                        if _text(row.get("CP num")).upper() == operation.cp.upper()), "")
        entry_actions, exit_actions = (), ()
        if operation.mode == "keil":
            text = _text(record.get("step"))
            try:
                entry_actions, exit_actions = parse_run_sequence_template(text, get_pin)
            except RunSequenceCompileError as exc:
                if exc.code == "RUN_SEQUENCE.TEMPLATE_X_REQUIRED" and not re.search(r"(?:^|[-:\s])X(?:$|[-\s])", text, re.I):
                    entry_actions = _parse_actions(text, get_pin, operation.row, "FLOW step")
                else:
                    raise FreqTestCompileError("FREQ.FLOW.STEP.INVALID", operation.row, str(exc)) from exc
            _validate_actions(entry_actions + exit_actions, operation.row, "FLOW step")
        cases = tuple(_case(operation.row, product, entry, iomux, operation.mode, get_pin) for entry in group)
        if cases[0].repower_before:
            raise FreqTestCompileError("FREQ.RP.FIRST_CASE", operation.row, "first case cannot start with RP")
        plans[operation.row] = FreqTestPlan(
            operation.row, operation.cp, operation.item, operation.provenance,
            _required(record.get("Vcc"), operation.row, "Vcc").upper(),
            _required(record.get("meas pin"), operation.row, "meas pin"), cases,
            protocol=operation.mode, entry_actions=entry_actions, exit_actions=exit_actions,
        )
    return MappingProxyType(dict(sorted(plans.items())))


def _sheet_rows(frame):
    required = ("FREQ", "source", "mul", "div", "down_limit", "up_limit", "step")
    missing = tuple(name for name in required if name not in frame.columns)
    if missing:
        raise FreqTestCompileError("FREQ.SHEET.COLUMN_MISSING", 0, ", ".join(missing))
    current, rows = "", []
    for index, record in frame.iterrows():
        group = _text(record.get("FREQ"))
        if group:
            current = group
        if not current or not _text(record.get("source")):
            continue
        rows.append((current, int(index) + 2, record))
    return tuple(rows)


def _case(flow_row, product, entry, iomux, protocol="swd", default_pin=""):
    _group, sheet_row, record = entry
    source = _required(record.get("source"), flow_row, "FREQ.source").upper()
    match = _SOURCE_RE.fullmatch(source)
    if not match:
        raise FreqTestCompileError("FREQ.SOURCE.INVALID", flow_row, source)
    family = match.group("family").upper()
    number = float(match.group("number").upper().replace("P", "."))
    scale = match.group("scale").upper()
    multiplier = _factor(record.get("mul"), flow_row, "mul")
    divider = _factor(record.get("div"), flow_row, "div")
    target_hz = number * _SCALE[scale] * multiplier / divider
    target, unit = _engineering_frequency(target_hz)
    low = float(calc_limit(target, _required(record.get("down_limit"), flow_row, "down_limit"), _required(record.get("up_limit"), flow_row, "up_limit"), True))
    high = float(calc_limit(target, _required(record.get("down_limit"), flow_row, "down_limit"), _required(record.get("up_limit"), flow_row, "up_limit"), False))
    external = None
    if family in _EXTERNAL_ROLE:
        external = ExternalClockPlan(
            _iomux_pin(iomux, _EXTERNAL_ROLE[family], flow_row),
            number * _SCALE[scale],
        )
    step = _text(record.get("step"))
    actions, repower = (), False
    pattern = None
    if protocol == "keil":
        location = f"FREQ row {sheet_row} step"
        parsed = _parse_actions(step, default_pin, flow_row, location)
        repowers = tuple(i for i, action in enumerate(parsed) if isinstance(action, RepowerAction))
        if repowers and repowers != (0,):
            raise FreqTestCompileError("FREQ.RP.POSITION_INVALID", flow_row, location)
        repower = bool(repowers)
        actions = parsed[1:] if repower else parsed
        if not actions:
            raise FreqTestCompileError("FREQ.CASE.STEP.EMPTY", flow_row, location)
        _validate_actions(actions, flow_row, location)
    else:
        # Shared FREQ groups keep their KEIL steps; SWD only consumes the power boundary.
        tokens = tuple(token for part in re.split(r"[-\r\n]+", step)
                       if (token := part.rsplit(":", 1)[-1].strip().upper()))
        repowers = tuple(i for i, token in enumerate(tokens) if token == "RP")
        if repowers and repowers != (0,):
            raise FreqTestCompileError("FREQ.RP.POSITION_INVALID", flow_row, f"FREQ row {sheet_row}")
        repower = bool(repowers)
        token = lambda value: format(float(value), ".12g").replace(".", "p")
        pattern = f"{product}_SWD_FREQ_{source}_M{token(multiplier)}_D{token(divider)}"
    return FreqCase(
        sheet_row, source, multiplier, divider, target, unit, low, high,
        pattern, external, repower, actions,
    )


def _parse_actions(text, pin, row, location):
    try:
        return parse_run_sequence_step(text, pin)
    except RunSequenceCompileError as exc:
        raise FreqTestCompileError("FREQ.CASE.STEP.INVALID", row, f"{location}: {exc}") from exc


def _validate_actions(actions, row, location):
    for action in actions:
        if not isinstance(action, (LevelSequenceAction, SendCodeAction, WaitAction)):
            raise FreqTestCompileError("FREQ.ACTION.INVALID", row, f"{location}: {type(action).__name__}")



def _iomux_pin(frame, role, flow_row):
    wanted = re.sub(r"[^A-Za-z0-9]+", "", role).upper()
    matches = []
    for _, row in frame.iterrows():
        pin = _text(row.get("pin"))
        if not pin:
            continue
        if any(wanted in tuple(re.sub(r"[^A-Za-z0-9]+", "", part).upper() for part in _text(value).split("/")) for value in row.iloc[1:] if _text(value)):
            base = pin.split("-", 1)[0]
            match = re.fullmatch(r"(P[A-FY])0*(\d+)", base, re.I)
            matches.append(f"{match.group(1).upper()}{match.group(2)}" if match else base)
    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise FreqTestCompileError("FREQ.IOMUX.ROLE_UNRESOLVED", flow_row, role)
    return unique[0]


def _engineering_frequency(value):
    if value >= 1e6:
        return round(value / 1e6, 12), "MHz"
    if value >= 1e3:
        return round(value / 1e3, 12), "KHz"
    return round(value, 12), "Hz"


def _factor(value, row, field):
    text = _text(value)
    if text == "/":
        return 1.0
    try:
        result = float(text)
    except ValueError as exc:
        raise FreqTestCompileError("FREQ.FACTOR.INVALID", row, field) from exc
    if not math.isfinite(result) or result <= 0:
        raise FreqTestCompileError("FREQ.FACTOR.INVALID", row, field)
    return result


def _products(version):
    return MappingProxyType({_text(row.get("CP num")).upper(): _text(row.get("product name")) for _, row in version.iterrows() if _text(row.get("CP num")) and _text(row.get("product name")) not in ("", "/")})


def _required(value, row, field):
    text = _text(value)
    if text in ("", "/"):
        raise FreqTestCompileError("FREQ.FACT.MISSING", row, field)
    return text


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = ["ExternalClockPlan", "FreqCase", "FreqTestCompileError", "FreqTestPlan", "compile_freq_test_plans"]
