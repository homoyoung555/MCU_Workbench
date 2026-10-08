"""Compile DAC sheet rows into immutable native sweep plans."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from program_gen.core.encoding import calc_dac_limits, dac_reference_voltage, dac_target_voltage, resolve_vcc_value
from program_gen.core.run_sequence import RepowerAction, RunSequenceCompileError, parse_run_sequence_step, parse_run_sequence_template


class DacTestCompileError(ValueError):
    def __init__(self, code, row, message):
        self.code, self.row = code, row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class DacCase:
    sheet_row: int
    mode: str
    code: str
    target: float
    low_limit: float
    high_limit: float
    code_pattern: str | None
    actions: tuple[object, ...]
    repower_before: bool


@dataclass(frozen=True, slots=True)
class DacTestPlan:
    row: int
    cp: str
    item: str
    provenance: object
    protocol: str
    product: str
    power_profile: str
    resolution: int
    init_pattern: str | None
    entry_actions: tuple[object, ...]
    exit_actions: tuple[object, ...]
    cases: tuple[DacCase, ...]
    # Platform projection for mode×pin output Patterns that are constructed by
    # the renderer rather than stored in a DAC sheet row.
    output_pattern_names: tuple[tuple[str, str], ...] = ()
    typed_kind: str = "DAC_TEST"
    effective_recipe: tuple[str, ...] = ("DAC_TEST",)

    @property
    def row_indices(self): return (self.row,)
    @property
    def excel_rows(self): return (self.row + 2,)
    @property
    def session_count(self): return 1 + sum(case.repower_before for case in self.cases[1:])


def compile_dac_test_plans(operations, recipe_rows, flow, dac, version):
    candidates = tuple(op for op in operations if op.typed_kind == "DAC_TEST")
    if not candidates: return MappingProxyType({})
    rows = _rows(dac)
    versions = {_text(row.get("CP num")).upper(): row for _, row in version.iterrows()}
    plans = {}
    for op in candidates:
        record = flow.iloc[op.row]
        recipe = tuple(call.name for call in getattr(recipe_rows.get(op.row), "operations", ()))
        if recipe != ("DAC_TEST",): raise DacTestCompileError("DAC.RECIPE.INVALID", op.row, repr(recipe))
        if op.mode not in ("swd", "keil"): raise DacTestCompileError("DAC.MODE.INVALID", op.row, op.mode)
        if any(_text(record.get(field)) not in ("", "/") for field in ("FV/FI", "meas pin", "low_range(%)", "high_range(%)")):
            raise DacTestCompileError("DAC.FLOW.LEGACY_FACT", op.row, "clear legacy DAC facts")
        version_row = versions.get(op.cp.upper())
        if version_row is None: raise DacTestCompileError("DAC.VERSION.MISSING", op.row, op.cp)
        product, get_pin = _text(version_row.get("product name")), _text(version_row.get("GET PIN"))
        resolution = int(float(_required(record.get("target"), op.row, "target")))
        vcc = _required(record.get("Vcc"), op.row, "Vcc").upper()
        vcc_value = resolve_vcc_value(vcc, version_row.get("vcc min"), version_row.get("vcc typ"), version_row.get("vcc max"))
        entry, exit = _template(record.get("step"), get_pin, op.row, op.mode)
        cases = tuple(_case(op.row, op.mode, product, get_pin, resolution, vcc_value, item) for item in rows)
        if cases[0].repower_before: raise DacTestCompileError("DAC.RP.FIRST_CASE", op.row, "first case cannot start with RP")
        plans[op.row] = DacTestPlan(op.row, op.cp, op.item, op.provenance, op.mode, product, vcc, resolution, f"{product}_DAC_GPIO_INIT" if op.mode == "swd" else None, entry, exit, cases)
    return MappingProxyType(dict(sorted(plans.items())))


def _rows(frame):
    required = ("mode", "code", "down_limit", "up_limit", "step")
    missing = tuple(field for field in required if field not in frame.columns)
    if missing: raise DacTestCompileError("DAC.SHEET.COLUMN_MISSING", 0, ", ".join(missing))
    rows = tuple((int(index) + 2, row) for index, row in frame.iterrows() if _text(row.get("mode")) and _text(row.get("code")))
    if not rows: raise DacTestCompileError("DAC.SHEET.EMPTY", 0, "no cases")
    return rows


def _case(flow_row, protocol, product, get_pin, resolution, vcc, entry):
    sheet_row, row = entry
    mode = _required(row.get("mode"), flow_row, "mode").upper()
    raw_code = _required(row.get("code"), flow_row, "code").upper().removeprefix("0X")
    try: code = f"{int(raw_code, 16):03X}"
    except ValueError as exc: raise DacTestCompileError("DAC.CODE.INVALID", flow_row, raw_code) from exc
    target = dac_target_voltage(code, resolution, dac_reference_voltage(mode, vcc))
    low, high = calc_dac_limits(code, resolution, vcc, _required(row.get("down_limit"), flow_row, "down_limit"), _required(row.get("up_limit"), flow_row, "up_limit"), mode=mode)
    actions, repower = (), False
    if protocol == "keil":
        parsed = tuple(parse_run_sequence_step(_required(row.get("step"), flow_row, "step"), get_pin))
        positions = tuple(i for i, action in enumerate(parsed) if isinstance(action, RepowerAction))
        if positions and positions != (0,): raise DacTestCompileError("DAC.RP.POSITION_INVALID", flow_row, f"DAC row {sheet_row}")
        repower, actions = bool(positions), parsed[1:] if positions else parsed
    else:
        step = _text(row.get("step")).upper()
        if step not in ("", "/", "RP"): raise DacTestCompileError("DAC.SWD.STEP.INVALID", flow_row, step)
        repower = step == "RP"
    return DacCase(sheet_row, mode, code, float(target), float(low), float(high), f"{product}_DAC_CODE_{code}" if protocol == "swd" else None, actions, repower)


def _template(value, pin, row, protocol):
    text = _text(value)
    if protocol == "swd":
        if text not in ("", "/"): raise DacTestCompileError("DAC.SWD.FLOW_STEP.INVALID", row, text)
        return (), ()
    try:
        return parse_run_sequence_template(text, pin)
    except RunSequenceCompileError as exc:
        if exc.code == "RUN_SEQUENCE.TEMPLATE_X_REQUIRED":
            raise DacTestCompileError("DAC.KEIL.TEMPLATE_X_REQUIRED", row, text) from exc
        raise


def _required(value, row, field):
    text = _text(value)
    if text in ("", "/"): raise DacTestCompileError("DAC.FACT.MISSING", row, field)
    return text
def _text(value): return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = ["DacCase", "DacTestCompileError", "DacTestPlan", "compile_dac_test_plans"]
