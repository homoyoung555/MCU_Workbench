"""Compile OPA sheet sweeps into immutable native plans."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.core.run_sequence import RepowerAction, RunSequenceCompileError, parse_run_sequence_step, parse_run_sequence_template
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class OpaTestCompileError(ValueError):
    def __init__(self, code, row, message):
        self.code, self.row = code, row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class OpaCase:
    sheet_row: int
    mode: str
    inp0_voltage: float | None
    inn0_voltage: float | None
    low_limit: float
    target: float
    high_limit: float
    config_pattern: str | None
    actions: tuple[object, ...]
    repower_before: bool


@dataclass(frozen=True, slots=True)
class OpaTestPlan:
    row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    protocol: str
    power_profile: str
    init_pattern: str | None
    entry_actions: tuple[object, ...]
    exit_actions: tuple[object, ...]
    cases: tuple[OpaCase, ...]
    typed_kind: str = "OPA_TEST"
    effective_recipe: tuple[str, ...] = ("OPA_TEST",)

    @property
    def row_indices(self): return (self.row,)

    @property
    def excel_rows(self): return (self.row + 2,)

    @property
    def session_count(self): return 1 + sum(case.repower_before for case in self.cases[1:])

    @property
    def patterns(self):
        return tuple(filter(None, (self.init_pattern, *(case.config_pattern for case in self.cases))))


def compile_opa_test_plans(operations, recipe_rows: Mapping[int, ExecutableFlowRow], flow, opa, version):
    candidates = tuple(operation for operation in operations if operation.typed_kind == "OPA_TEST")
    if not candidates:
        return MappingProxyType({})
    sheet_rows = _rows(opa)
    products = {_text(row.get("CP num")).upper(): (_text(row.get("product name")), _text(row.get("GET PIN"))) for _, row in version.iterrows()}
    plans = {}
    for operation in candidates:
        record = flow.iloc[operation.row]
        recipe = tuple(call.name for call in getattr(recipe_rows.get(operation.row), "operations", ()))
        if recipe != ("OPA_TEST",):
            raise OpaTestCompileError("OPA.RECIPE.INVALID", operation.row, repr(recipe))
        if operation.mode not in ("swd", "keil"):
            raise OpaTestCompileError("OPA.MODE.INVALID", operation.row, operation.mode)
        if any(_text(record.get(field)) not in ("", "/") for field in ("FV/FI", "meas pin", "low_range(%)", "target", "high_range(%)")):
            raise OpaTestCompileError("OPA.FLOW.LEGACY_FACT", operation.row, "sheet-driven OPA requires cleared legacy facts")
        product, get_pin = products.get(operation.cp.upper(), ("", ""))
        if not product:
            raise OpaTestCompileError("OPA.VERSION.MISSING", operation.row, operation.cp)
        entry, exit = _template_actions(record.get("step"), get_pin, operation.row, operation.mode)
        cases = tuple(_case(operation.row, operation.mode, product, get_pin, sheet_row) for sheet_row in sheet_rows)
        if cases[0].repower_before:
            raise OpaTestCompileError("OPA.RP.FIRST_CASE", operation.row, "first case cannot start with RP")
        plans[operation.row] = OpaTestPlan(
            operation.row, operation.cp, operation.item, operation.provenance,
            operation.mode, _required(record.get("Vcc"), operation.row, "Vcc").upper(),
            f"{product}_OPA_GPIO_INIT" if operation.mode == "swd" else None,
            entry, exit, cases,
        )
    return MappingProxyType(dict(sorted(plans.items())))


def _rows(frame):
    required = ("mode", "inp0_force", "inn0_force", "down_limit", "target", "up_limit", "step")
    missing = tuple(field for field in required if field not in frame.columns)
    if missing:
        raise OpaTestCompileError("OPA.SHEET.COLUMN_MISSING", 0, ", ".join(missing))
    rows = tuple((int(index) + 2, row) for index, row in frame.iterrows() if _text(row.get("mode")))
    if not rows:
        raise OpaTestCompileError("OPA.SHEET.EMPTY", 0, "no cases")
    return rows


def _case(flow_row, protocol, product, default_pin, entry):
    sheet_row, record = entry
    mode = _required(record.get("mode"), flow_row, "OPA.mode").upper()
    inp0, inn0 = _voltage(record.get("inp0_force"), flow_row), _voltage(record.get("inn0_force"), flow_row)
    low, target, high = (_number(record.get(field), flow_row, field) for field in ("down_limit", "target", "up_limit"))
    if not low <= target <= high:
        raise OpaTestCompileError("OPA.LIMIT.INVALID", flow_row, f"OPA row {sheet_row}")
    actions, repower = (), False
    pattern = f"{product}_OPA_{mode}_Test" if protocol == "swd" else None
    if protocol == "keil":
        step = _required(record.get("step"), flow_row, f"OPA row {sheet_row} step")
        parsed = tuple(parse_run_sequence_step(step, default_pin))
        repowers = tuple(i for i, action in enumerate(parsed) if isinstance(action, RepowerAction))
        if repowers and repowers != (0,):
            raise OpaTestCompileError("OPA.RP.POSITION_INVALID", flow_row, f"OPA row {sheet_row}")
        repower = bool(repowers)
        actions = parsed[1:] if repower else parsed
    else:
        step = _text(record.get("step")).upper()
        if step not in ("", "/", "RP"):
            raise OpaTestCompileError("OPA.SWD.STEP.INVALID", flow_row, f"OPA row {sheet_row}: {step}")
        repower = step == "RP"
    return OpaCase(sheet_row, mode, inp0, inn0, low, target, high, pattern, actions, repower)


def _template_actions(value, default_pin, row, protocol):
    text = _text(value)
    if protocol == "swd":
        if text not in ("", "/"):
            raise OpaTestCompileError("OPA.SWD.FLOW_STEP.INVALID", row, text)
        return (), ()
    try:
        return parse_run_sequence_template(text, default_pin)
    except RunSequenceCompileError as exc:
        if exc.code == "RUN_SEQUENCE.TEMPLATE_X_REQUIRED":
            raise OpaTestCompileError("OPA.KEIL.TEMPLATE_X_REQUIRED", row, text) from exc
        raise


def _voltage(value, row):
    text = _text(value)
    if text in ("", "/"): return None
    return _number(text, row, "force")


def _number(value, row, field):
    try: result = float(_required(value, row, field))
    except ValueError as exc: raise OpaTestCompileError("OPA.NUMBER.INVALID", row, field) from exc
    if not math.isfinite(result): raise OpaTestCompileError("OPA.NUMBER.INVALID", row, field)
    return result


def _required(value, row, field):
    text = _text(value)
    if text in ("", "/"): raise OpaTestCompileError("OPA.FACT.MISSING", row, field)
    return text


def _text(value): return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = ["OpaCase", "OpaTestCompileError", "OpaTestPlan", "compile_opa_test_plans"]
