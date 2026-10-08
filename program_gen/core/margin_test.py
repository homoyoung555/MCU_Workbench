"""Compiler-owned Margin protocol: eight per-site bisections, logging only."""

from dataclasses import dataclass
import re
from types import MappingProxyType

from program_gen.core.flash_read import bind_flash_read_session, validate_flash_read_gate_schedule
from program_gen.core.id_module import IdModulePlan
from program_gen.core.run_pattern import RunPatternPlan


class MarginTestCompileError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class MarginTestPlan:
    power_profile: str
    enter: RunPatternPlan
    enter_vt: RunPatternPlan
    read: RunPatternPlan
    start_voltage: float
    end_voltage: float
    iterations: int
    result_label: str
    gate: IdModulePlan | None = None


@dataclass(frozen=True, slots=True)
class MarginPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    test_number: int
    test: MarginTestPlan


def compile_margin_plans(operations, recipe_rows, flow, requests, fbist_plan, id_plans,
                         *, flash_label_plan=None):
    plans = {}
    for operation in operations:
        if operation.typed_kind != "MARGIN":
            continue
        location = f"FLOW!A{operation.row + 2}"
        calls = tuple(getattr(recipe_rows.get(operation.row), "operations", ()))
        if (len(calls) != 1 or calls[0].name != "MARGIN_TEST"
                or calls[0].parameters or calls[0].assignments):
            raise MarginTestCompileError("MARGIN.RECIPE.INVALID", location)
        match = re.fullmatch(r"(VTE|VTP)_(FF|00|CKB|CKBB)(_BAKE)?_MARGIN", operation.item, re.I)
        if match is None:
            raise MarginTestCompileError("MARGIN.ITEM.UNSUPPORTED", f"{location}: {operation.item}")
        mode, background, bake = match.groups()
        session = bind_flash_read_session(operation, mode, background, bake, flow, requests,
            fbist_plan, id_plans, kind="MARGIN", error_type=MarginTestCompileError,
            read_target=calls[0].argument, flash_label_plan=flash_label_plan)
        start, end = (0.0, -1.0) if mode.upper() == "VTE" else (0.2, 1.0)
        plans[operation.row] = MarginPlan(operation.row, operation.row + 2, operation.cp,
            operation.item, (operation.row + 1) * 100,
            MarginTestPlan(session.power_profile, session.enter, session.enter_vt, session.read,
                           start, end, 8, operation.item, session.gate))
    return MappingProxyType(plans)


def validate_margin_gate_schedule(plans, id_plans, cp_plans):
    validate_flash_read_gate_schedule(plans, id_plans, cp_plans,
                                     kind="MARGIN", error_type=MarginTestCompileError)
