"""Compile ordinary VT once; downstream receives detached, immutable plans."""

from dataclasses import dataclass
import math
import re
from types import MappingProxyType

from program_gen.core.flash_read import bind_flash_read_session, validate_flash_read_gate_schedule
from program_gen.core.id_module import IdModulePlan
from program_gen.core.run_pattern import RunPatternPlan


class VtTestCompileError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class VtTestPlan:
    power_profile: str
    enter: RunPatternPlan
    enter_vt: RunPatternPlan
    read: RunPatternPlan
    voltage: float
    retry_failed: bool
    gate: IdModulePlan | None = None


@dataclass(frozen=True, slots=True)
class VtPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    test_number: int
    test: VtTestPlan


def compile_vt_plans(operations, recipe_rows, flow, version, requests, fbist_plan, id_plans,
                     *, flash_label_plan=None):
    """ProductCompiler owns all FLOW/VERSION reads and producer resolution."""
    plans = {}
    for operation in operations:
        if operation.typed_kind != "VT":
            continue
        location = f"FLOW!A{operation.row + 2}"
        calls = tuple(getattr(recipe_rows.get(operation.row), "operations", ()))
        if (len(calls) != 1 or calls[0].name != "VT_TEST"
                or calls[0].parameters or calls[0].assignments):
            raise VtTestCompileError("VT.RECIPE.INVALID", location)
        # The exact item protocol is resolved here, never in platform adapters.
        match = re.fullmatch(r"(VTE|VTP)_(FF|00|CKB|CKBB)(_BAKE)?_VERIFY",
                             operation.item, re.I)
        if match is None:
            raise VtTestCompileError("VT.ITEM.UNSUPPORTED", f"{location}: {operation.item}")
        mode, background, bake = match.groups()
        mode = mode.upper()
        session = bind_flash_read_session(operation, mode, background, bake, flow, requests,
            fbist_plan, id_plans, kind="VT", error_type=VtTestCompileError,
            read_target=calls[0].argument, flash_label_plan=flash_label_plan)
        column = f"{mode}{' bake' if bake else ''} target"
        try:
            rows = version[version["CP num"].astype(str).str.strip().str.upper() == operation.cp.upper()]
            if len(rows) != 1:
                raise ValueError("expected one CP row")
            value = rows.iloc[0][column]
            voltage = float(value)
            if isinstance(value, bool) or not math.isfinite(voltage):
                raise ValueError("expected finite voltage")
        except (ValueError, TypeError, KeyError) as error:
            raise VtTestCompileError("VT.VOLTAGE.INVALID",
                                     f"{location}: VERSION {operation.cp}/{column}") from error
        plans[operation.row] = VtPlan(operation.row, operation.row + 2, operation.cp,
            operation.item, (operation.row + 1) * 100,
            VtTestPlan(session.power_profile, session.enter, session.enter_vt,
                       session.read, voltage, mode == "VTE", session.gate))
    return MappingProxyType(plans)


def validate_vt_gate_schedule(plans, id_plans, cp_plans):
    validate_flash_read_gate_schedule(plans, id_plans, cp_plans,
                                     kind="VT", error_type=VtTestCompileError)
