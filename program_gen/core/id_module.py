"""Compiler-bound READID/CHECKID sessions; no workbook or Pattern lookup."""

from dataclasses import dataclass
import re

from program_gen.core.run_pattern import RunPatternPlan
from program_gen.core.uid_plan import IdItemPlan


class IdModulePlanError(ValueError):
    """The upstream ID protocol or its executable bindings are incomplete."""


@dataclass(frozen=True, slots=True)
class IdModulePlan:
    id_item: IdItemPlan
    cp: str
    power_profile: str
    enter_fbist_mode: RunPatternPlan
    check_pattern: RunPatternPlan

    @property
    def module_name(self) -> str:
        return "READID" if self.id_item.role == "PRODUCE_GATE" else "CHECKID"

    @property
    def gate_symbol(self) -> str | None:
        return self.id_item.gate_symbol

    @property
    def gate_semantic_identity(self) -> str | None:
        return f"{self.cp}:{self.gate_symbol}" if self.gate_symbol else None

    def require_module(self, module_name: str) -> None:
        if self.module_name != module_name:
            raise IdModulePlanError(f"ID.MODULE.ROLE_MISMATCH: {module_name}")


def compile_id_module_plan(
    id_item: IdItemPlan, *, cp: str, power_profile: str,
    enter_fbist_mode: RunPatternPlan, check_pattern: RunPatternPlan,
) -> IdModulePlan:
    if not isinstance(id_item, IdItemPlan):
        raise IdModulePlanError("ID.MODULE.ITEM_MISSING")
    expected_policy = {"PRODUCE_GATE": "DEFER", "HARD_CHECK": "FLOW_BIN"}
    if expected_policy.get(id_item.role) != id_item.failure_policy:
        raise IdModulePlanError("ID.MODULE.ROLE_INVALID")
    if id_item.role == "PRODUCE_GATE":
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", id_item.gate_symbol or ""):
            raise IdModulePlanError("ID.MODULE.GATE_INVALID")
    elif id_item.gate_symbol is not None:
        raise IdModulePlanError("ID.MODULE.CHECK_GATE_FORBIDDEN")
    cp = str(cp).strip().upper()
    power_profile = str(power_profile).strip().upper()
    if not re.fullmatch(r"CP\d+", cp):
        raise IdModulePlanError("ID.MODULE.CP_INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", power_profile):
        raise IdModulePlanError("ID.MODULE.POWER_INVALID")
    if not all(isinstance(run, RunPatternPlan) for run in (enter_fbist_mode, check_pattern)):
        raise IdModulePlanError("ID.MODULE.RUN_MISSING")
    return IdModulePlan(id_item, cp, power_profile, enter_fbist_mode, check_pattern)


__all__ = ["IdModulePlan", "IdModulePlanError", "compile_id_module_plan"]
