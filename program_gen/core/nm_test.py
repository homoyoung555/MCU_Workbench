"""Upstream MAIN compilation; immutable plans are the only renderer input."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from flow_recipe import RecipeCall
from program_gen.core.fbist_pattern_plan import compile_fbist_label_catalog
from program_gen.core.flash_compare_plan import BulkCoverage, BulkStrategy, DataKind, Operation, Scope
from program_gen.core.flash_window import _run
from program_gen.core.logical_item import logical_dac_final_symbol
from program_gen.core.run_pattern import RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan, SetVpospPurpose, SetVpospSnapshot, compile_set_vposp_plan,
)


class NmTestCompileError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


class NmTestMode(str, Enum):
    NORMAL = "normal"
    REPAIR = "repair"


@dataclass(frozen=True, slots=True)
class NmTestRun:
    operation: Operation
    pattern: RunPatternPlan


@dataclass(frozen=True, slots=True)
class NmTestPlan:
    mode: NmTestMode
    power_profile: str
    enter: RunPatternPlan
    vposp: RunPatternPlan
    runs: tuple[NmTestRun, ...]


@dataclass(frozen=True, slots=True)
class MainStep:
    module: str
    module_plan: object


@dataclass(frozen=True, slots=True)
class MainPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    test_number: int
    effective_recipe: tuple[str, ...]
    steps: tuple[MainStep, ...]


# Exact product item identities select business profiles, never Pattern filenames.
_PROFILES = {
    "chip_erase_read": ((DataKind.ONE,), 0),
    "initialization": ((DataKind.ONE,), 0),
    "chip_pgm00_read": ((DataKind.ZERO,), 1),
    "chip_pgmckb_read": ((DataKind.PCKB,), 1),
    "chip_pgmckbb_read": ((DataKind.NCKB,), 1),
    "disturb_ff": ((DataKind.ONE,), 2),
    "disturb_ckb_ckbb": ((DataKind.PCKB, DataKind.NCKB), 2),
}


def compile_main_plans(operations, recipe_rows, flow, flash_requests, fbist_plan, snapshots):
    """Called only by ProductCompiler, with its already-read FLOW and catalogs."""
    plans = {}
    operations = tuple(operation for operation in operations if operation.typed_kind == "MAIN")
    if not operations:
        return MappingProxyType(plans)
    pumps = tuple(PumpDacPlan(item, logical_dac_final_symbol(item))
                  for item in fbist_plan.pump_items)
    for operation in operations:
        calls = tuple(getattr(recipe_rows.get(operation.row), "operations", ())) or (RecipeCall("NM_TEST"),)
        modules = tuple(call.name for call in calls)
        if modules not in (("NM_TEST",), ("SETVPOSP", "NM_TEST")):
            raise NmTestCompileError("MAIN.RECIPE.INVALID", f"FLOW!A{operation.row + 2}: {modules}")
        snapshot = snapshots.get(operation.row, SetVpospSnapshot())
        steps = []
        for call in calls:
            if call.name == "SETVPOSP":
                transition = compile_set_vposp_plan(
                    pumps, compile_fbist_label_catalog(fbist_plan), snapshot,
                    swd_pin=fbist_plan.swd_pin, run_pattern=_run("set_all_final_vposp"),
                    purpose=SetVpospPurpose.PREPARE_FOR_FLASH,
                )
                snapshot = transition.snapshot
                steps.append(MainStep(call.name, transition.plan))
                continue
            required = frozenset(pump.item.strip().casefold() for pump in pumps)
            if required - snapshot.prepared_items or required & snapshot.dirty_items:
                raise NmTestCompileError("NM_TEST.SETVPOSP.NOT_READY", f"FLOW!A{operation.row + 2}")
            module_plan = compile_nm_test_plan(
                operation.item, flow.iloc[operation.row].get("Vcc", ""),
                flash_requests, mode=call.argument or "normal",
            )
            steps.append(MainStep(call.name, module_plan))
        plans[operation.row] = MainPlan(
            operation.row, operation.row + 2, operation.cp, operation.item,
            (operation.row + 1) * 100, modules, tuple(steps),
        )
    return MappingProxyType(plans)


def compile_nm_test_plan(item, power_profile, requests, *, mode="normal"):
    try:
        mode = NmTestMode(str(mode).strip().casefold())
    except ValueError as error:
        raise NmTestCompileError("NM_TEST.MODE.INVALID", repr(mode)) from error
    profile = str(power_profile).strip().upper()
    if profile not in ("VCC_MIN", "VCC_TYP", "VCC_MAX"):
        raise NmTestCompileError("NM_TEST.VCC.INVALID", repr(power_profile))
    try:
        backgrounds, count = _PROFILES[str(item).strip().casefold()]
    except KeyError as error:
        raise NmTestCompileError("NM_TEST.ITEM.UNSUPPORTED", repr(item)) from error

    def bind(action, background=None):
        strategy = BulkStrategy.EVEN_ODD if action is Operation.PROGRAM else None
        matches = tuple(request for request in requests
            if request.scope is Scope.BULK and request.operation is action
            and (None if request.data is None else request.data.kind) is background
            and request.bulk_strategy is strategy
            and (request.bulk_coverage or BulkCoverage.NM_ONLY) is BulkCoverage.NM_ONLY)
        if len(matches) != 1:
            raise NmTestCompileError("NM_TEST.PATTERN.BINDING_INVALID",
                f"{item}: {action.value}/{background}: expected one NM_ONLY Pattern, found {len(matches)}")
        return NmTestRun(action, _run(matches[0].output_identity))

    runs = []
    for background in backgrounds:
        runs.append(bind(Operation.ERASE))
        runs.extend(bind(Operation.PROGRAM, background) for _ in range(count))
        runs.append(bind(Operation.READ, background))
    return NmTestPlan(mode, profile, _run("enter_fbist_mode"), _run("set_all_final_vposp"), tuple(runs))
