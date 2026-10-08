"""Compile FLASH_WINDOW Recipe facts into shared immutable plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from program_gen.core.fbist_pattern_plan import (
    compile_fbist_label_catalog,
)
from program_gen.core.flash_compare_plan import (
    BulkCoverage,
    BulkStrategy,
    DataKind,
    FlashCompareRequest,
    Operation,
    Scope,
)
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_key
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan,
    SetVpospPurpose,
    SetVpospSnapshot,
    compile_set_vposp_plan,
)


class FlashWindowCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class NmLoopPatternRole(str, Enum):
    ERASE = "ERASE"
    PROGRAM_00 = "PROGRAM_00"
    PROGRAM_PCKB = "PROGRAM_PCKB"
    READ_PCKB = "READ_PCKB"
    PROGRAM_NCKB = "PROGRAM_NCKB"
    READ_NCKB = "READ_NCKB"
    PROGRAM_FF = "PROGRAM_FF"
    READ_FF = "READ_FF"


@dataclass(frozen=True, slots=True)
class BuildMapFieldWrite:
    field: str
    symbol: str
    lsb: int
    width: int


@dataclass(frozen=True, slots=True)
class BuildMapTerm:
    lsb: int
    value: int | None = None
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class BuildMapRegisterPlan:
    page: str
    register: str
    description: str
    default_storage_word: int
    default_value: int
    terms: tuple[BuildMapTerm, ...]
    writes: tuple[BuildMapFieldWrite, ...]


@dataclass(frozen=True, slots=True)
class BuildMapPlan:
    cp: str
    registers: tuple[BuildMapRegisterPlan, ...]


@dataclass(frozen=True, slots=True)
class NmLoopRun:
    pattern: RunPatternPlan


@dataclass(frozen=True, slots=True)
class NmLoopRepeat:
    count: int
    runs: tuple[NmLoopRun, ...]


@dataclass(frozen=True, slots=True)
class NmLoopPowerOn:
    profile: str


@dataclass(frozen=True, slots=True)
class NmLoopPowerOff:
    pass


@dataclass(frozen=True, slots=True)
class NmLoopPlan:
    cp: str
    instructions: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class FlashWindowStep:
    module: str
    module_plan: object


@dataclass(frozen=True, slots=True)
class FlashWindowPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: object
    effective_recipe: tuple[str, ...]
    steps: tuple[FlashWindowStep, ...]
    test_number: int


@dataclass(frozen=True, slots=True)
class FlashWindowWarning:
    code: str
    excel_row: int
    message: str


@dataclass(frozen=True, slots=True)
class FlashWindowPlanSet:
    plans: Mapping[int, FlashWindowPlan]
    warnings: tuple[FlashWindowWarning, ...]
    vposp_snapshots: Mapping[int, SetVpospSnapshot] = field(
        default_factory=lambda: MappingProxyType({})
    )


def compile_flash_window_plans(
    operations,
    recipe_rows,
    flow_frame,
    trim_specs,
    addr_map,
    fbist_plan,
    required_flash_requests,
    dac_adjust_plans=MappingProxyType({}),
    persistence_plans=None,
    result_bindings=None,
) -> FlashWindowPlanSet:
    """Compile all CPs in FLOW order while maintaining one VPOSP snapshot per CP."""
    plans = {}
    warnings = []
    snapshots = {}
    labels = compile_fbist_label_catalog(fbist_plan)
    pumps = tuple(
        PumpDacPlan(item, logical_dac_final_symbol(item))
        for item in fbist_plan.pump_items
    )
    operations_by_cp = {}
    for operation in operations:
        operations_by_cp.setdefault(operation.cp.upper(), []).append(operation)

    for cp, cp_operations in operations_by_cp.items():
        snapshot = SetVpospSnapshot()
        for operation in cp_operations:
            if (
                operation.source_type.casefold() == "trim"
                and logical_item_key(operation.item)
                in {logical_item_key(item.item) for item in pumps}
            ):
                snapshot = snapshot.invalidate((operation.item,))
            adjust_plan = dac_adjust_plans.get(operation.row)
            if adjust_plan is not None:
                target_symbol = adjust_plan.steps[0].module_plan.target_symbol
                adjusted = next(
                    (pump.item for pump in pumps if pump.symbol == target_symbol),
                    None,
                )
                if adjusted is not None:
                    snapshot = snapshot.invalidate((adjusted,))
            snapshots[operation.row] = snapshot
            recipe_row = recipe_rows.get(operation.row)
            calls = tuple(getattr(recipe_row, "operations", ()))
            modules = tuple(call.name for call in calls)
            if operation.typed_kind != "FLASH_WINDOW":
                if "SETVPOSP" in modules:
                    snapshot = compile_set_vposp_plan(
                        pumps,
                        labels,
                        snapshot,
                        swd_pin=fbist_plan.swd_pin,
                        run_pattern=_run("set_all_final_vposp"),
                    ).snapshot
                continue

            modules = modules or ("SETVPOSP", "NMLOOP")
            _validate_recipe(operation, modules)
            steps = []
            for module in modules:
                if module == "BUILDMAP":
                    build_map, build_warnings = _compile_build_map(
                        operation, flow_frame, addr_map,
                        persistence_plans, result_bindings,
                    )
                    steps.append(FlashWindowStep(module, build_map))
                    warnings.extend(build_warnings)
                elif module == "SETVPOSP":
                    transition = compile_set_vposp_plan(
                        pumps,
                        labels,
                        snapshot,
                        swd_pin=fbist_plan.swd_pin,
                        run_pattern=_run("set_all_final_vposp"),
                        purpose=SetVpospPurpose.PREPARE_FOR_FLASH,
                    )
                    snapshot = transition.snapshot
                    steps.append(FlashWindowStep(module, transition.plan))
                else:
                    _require_vposp_ready(operation, pumps, snapshot)
                    profile = str(flow_frame.iloc[operation.row].get("Vcc", "")).strip()
                    if not profile:
                        raise FlashWindowCompileError(
                            "FLASH_WINDOW.VCC.MISSING",
                            f"FLOW row {operation.row + 2} requires Vcc",
                        )
                    steps.append(FlashWindowStep(
                        module,
                        compile_nm_loop_plan(cp, profile, required_flash_requests),
                    ))
            plans[operation.row] = FlashWindowPlan(
                operation.row,
                operation.row + 2,
                cp,
                operation.item,
                operation.provenance,
                modules,
                tuple(steps),
                (operation.row + 1) * 100,
            )
    return FlashWindowPlanSet(MappingProxyType(plans), tuple(warnings), MappingProxyType(snapshots))


def compile_nm_loop_plan(
    cp: str,
    power_profile: str,
    required_flash_requests: tuple[FlashCompareRequest, ...],
) -> NmLoopPlan:
    cp = str(cp).strip().upper()
    if cp not in ("CP1", "CP2"):
        raise FlashWindowCompileError(
            "NMLOOP.CP.UNSUPPORTED", f"NMLOOP does not support {cp}"
        )
    identities = _nm_loop_pattern_identities(cp, required_flash_requests)

    def role(value):
        try:
            return NmLoopRun(_run(identities[value]))
        except KeyError as error:
            raise FlashWindowCompileError(
                "NMLOOP.PATTERN.BINDING_MISSING", f"{cp} lacks {value.value}"
            ) from error

    enter = NmLoopRun(_run("enter_fbist_mode"))
    set_vposp = NmLoopRun(_run("set_all_final_vposp"))
    erase = role(NmLoopPatternRole.ERASE)
    pckb = role(NmLoopPatternRole.PROGRAM_PCKB)
    nckb = role(NmLoopPatternRole.PROGRAM_NCKB)
    return NmLoopPlan(cp, (
        NmLoopPowerOn(power_profile), enter, set_vposp,
        NmLoopRepeat(100, (erase, role(NmLoopPatternRole.PROGRAM_00))),
        erase,
        NmLoopPowerOff(),
        NmLoopPowerOn(power_profile), enter, set_vposp,
        NmLoopRepeat(49, (erase, pckb, erase, nckb)),
        erase, pckb, role(NmLoopPatternRole.READ_PCKB),
        erase, nckb, role(NmLoopPatternRole.READ_NCKB),
        NmLoopRepeat(100, (erase, role(NmLoopPatternRole.PROGRAM_FF))),
        role(NmLoopPatternRole.READ_FF),
        NmLoopPowerOff(),
    ))


def _nm_loop_pattern_identities(cp, requests):
    write_coverage = (
        BulkCoverage.NM_PLUS_SM if cp == "CP1" else BulkCoverage.NM_ONLY
    )
    all_pages_strategy = (
        BulkStrategy.ALL_PAGES if cp == "CP1" else BulkStrategy.EVEN_ODD
    )
    specifications = {
        NmLoopPatternRole.ERASE: (
            Operation.ERASE, None, None, write_coverage,
        ),
        NmLoopPatternRole.PROGRAM_00: (
            Operation.PROGRAM, DataKind.ZERO, all_pages_strategy, write_coverage,
        ),
        NmLoopPatternRole.PROGRAM_PCKB: (
            Operation.PROGRAM, DataKind.PCKB, BulkStrategy.EVEN_ODD, write_coverage,
        ),
        NmLoopPatternRole.READ_PCKB: (
            Operation.READ, DataKind.PCKB, None, BulkCoverage.NM_ONLY,
        ),
        NmLoopPatternRole.PROGRAM_NCKB: (
            Operation.PROGRAM, DataKind.NCKB, BulkStrategy.EVEN_ODD, write_coverage,
        ),
        NmLoopPatternRole.READ_NCKB: (
            Operation.READ, DataKind.NCKB, None, BulkCoverage.NM_ONLY,
        ),
        NmLoopPatternRole.PROGRAM_FF: (
            Operation.PROGRAM, DataKind.ONE, all_pages_strategy, write_coverage,
        ),
        NmLoopPatternRole.READ_FF: (
            Operation.READ, DataKind.ONE, None, BulkCoverage.NM_ONLY,
        ),
    }
    identities = {}
    for role, specification in specifications.items():
        operation, data_kind, strategy, coverage = specification
        matches = tuple(
            request for request in requests
            if request.scope is Scope.BULK
            and request.operation is operation
            and (None if request.data is None else request.data.kind) is data_kind
            and request.bulk_strategy is strategy
            and (request.bulk_coverage or BulkCoverage.NM_ONLY) is coverage
        )
        if len(matches) != 1:
            code = (
                "NMLOOP.PATTERN.BINDING_MISSING"
                if not matches else "NMLOOP.PATTERN.BINDING_AMBIGUOUS"
            )
            raise FlashWindowCompileError(
                code,
                f"{cp} {role.value} requires exactly one Required Flash Pattern; "
                f"found {len(matches)}",
            )
        identities[role] = matches[0].output_identity
    return MappingProxyType(identities)


def _compile_build_map(
    operation, flow_frame, addr_map, persistence_plans, result_bindings
):
    trim_producers = tuple(
        (
            int(row),
            str(record.get("item", "")).strip(),
            logical_dac_final_symbol(record.get("item", "")),
        )
        for row, record in flow_frame.iterrows()
        if str(record.get("CP NO", "")).strip().casefold() == operation.cp.casefold()
        and str(record.get("type", "")).strip().casefold() == "trim"
        and str(record.get("item", "")).strip()
    )
    prior_specs = tuple(item for item in trim_producers if item[0] < operation.row)
    later_specs = tuple(item for item in trim_producers if item[0] > operation.row)
    deferred_registers = _deferred_registers(
        operation, persistence_plans, result_bindings
    )
    registers = []
    for register in addr_map.registers:
        if not register.applies_to(operation.cp):
            continue
        if (register.page.casefold(), register.register.casefold()) in deferred_registers:
            continue
        writes = tuple(
            BuildMapFieldWrite(field.name, symbol, field.lsb, field.width)
            for _row, item, symbol in prior_specs
            for field in (
                addr_map.selected_storage_fields("trim", item)
                if addr_map.has_trim_storage_mapping(item)
                else register.fields
            )
            if field.register_layout is register
            and field.register_layout.applies_to(operation.cp)
            and addr_map.matches_trim(operation.cp, item, field)
        )
        latest_writes = {
            (write.lsb, write.width): write for write in writes
        }
        segments = register.storage_segments if any(
            field.source == "description"
            for _row, item, _symbol in prior_specs
            for field in (addr_map.selected_storage_fields("trim", item) or ())
            if field.register_layout is register
        ) else register.segments
        terms = tuple(
            BuildMapTerm(
                segment.lsb,
                symbol=latest_writes[(segment.lsb, segment.width)].symbol,
            )
            if (segment.lsb, segment.width) in latest_writes
            else BuildMapTerm(
                segment.lsb,
                value=(
                    segment.literal_value
                    if segment.literal_value is not None
                    else (register.default_real_value >> segment.lsb)
                    & ((1 << segment.width) - 1)
                ),
            )
            for segment in sorted(
                segments, key=lambda item: item.lsb, reverse=True
            )
        )
        if not terms:
            terms = (BuildMapTerm(0, value=register.default_real_value),)
        registers.append(BuildMapRegisterPlan(
            register.page,
            register.register,
            register.description or (
                "{" + register.map_expression.strip("{} ") + "}"
                if register.map_expression
                else f"{{{register.register}[15:0]}}"
            ),
            register.default_storage_word,
            register.default_real_value,
            terms,
            writes,
        ))
    warnings = tuple(
        FlashWindowWarning(
            "BUILDMAP.TRIM.PRODUCER_AFTER_CONSUMER",
            operation.row + 2,
            f"{operation.cp} Trim {item!r} is after BUILDMAP; ADDR_MAP default is retained",
        )
        for _row, item, _symbol in later_specs
        if any(
            addr_map.matches_trim(operation.cp, item, field)
            for register in addr_map.registers
            if register.applies_to(operation.cp)
            for field in (addr_map.selected_storage_fields("trim", item)
                          if addr_map.has_trim_storage_mapping(item) else register.fields)
        )
    )
    return BuildMapPlan(operation.cp.upper(), tuple(registers)), warnings


def _deferred_registers(operation, persistence_plans, result_bindings):
    if persistence_plans is None or result_bindings is None:
        return frozenset()
    rows = getattr(persistence_plans, "rows", {})
    deferred = set()
    for binding in getattr(result_bindings, "bindings", ()):
        if (
            binding.identity.source_cp.casefold() != operation.cp.casefold()
            or binding.identity.role != "VERIFY_RESULT"
            or binding.producer_row <= operation.row
        ):
            continue
        for target in binding.targets:
            if target.lsb != 0 or target.width != 16:
                continue
            commits = tuple(
                row
                for row, row_plan in rows.items()
                if row > binding.producer_row
                and row_plan.cp.casefold() == operation.cp.casefold()
                and any(
                    persisted.module == "COMMIT"
                    and any(
                        write.page.casefold() == target.page.casefold()
                        and write.register.casefold() == target.register.casefold()
                        and write.lsb == 0 and write.width == 16
                        and write.value.kind == "VARIABLE"
                        and write.value.token.casefold() == binding.symbol.casefold()
                        for write in persisted.field_writes
                    )
                    for persisted in row_plan.operations
                )
            )
            if not commits:
                continue
            commit_row = min(commits)
            consumed_earlier = any(
                operation.row < row < commit_row
                and row_plan.cp.casefold() == operation.cp.casefold()
                and any(
                    (
                        persisted.module in ("CHECKOTP", "PGMOTP")
                        and any(
                            page.casefold() == target.page.casefold()
                            for page in persisted.effective_pages
                        )
                    )
                    or (
                        persisted.module == "COMMIT"
                        and any(
                            write.page.casefold() == target.page.casefold()
                            and write.register.casefold() == target.register.casefold()
                            for write in persisted.field_writes
                        )
                    )
                    for persisted in row_plan.operations
                )
                for row, row_plan in rows.items()
            )
            if not consumed_earlier:
                deferred.add((target.page.casefold(), target.register.casefold()))
    return frozenset(deferred)


def _validate_recipe(operation, modules):
    allowed = {"BUILDMAP", "SETVPOSP", "NMLOOP"}
    unsupported = next((module for module in modules if module not in allowed), None)
    if unsupported:
        raise FlashWindowCompileError(
            "FLASH_WINDOW.RECIPE.MODULE_UNSUPPORTED",
            f"FLOW row {operation.row + 2} does not allow {unsupported}",
        )
    if modules.count("NMLOOP") != 1 or modules[-1] != "NMLOOP":
        raise FlashWindowCompileError(
            "FLASH_WINDOW.RECIPE.NMLOOP_REQUIRED",
            f"FLOW row {operation.row + 2} requires one final NMLOOP",
        )
    duplicate = next(
        (module for module in ("BUILDMAP", "SETVPOSP") if modules.count(module) > 1),
        None,
    )
    if duplicate:
        raise FlashWindowCompileError(
            "FLASH_WINDOW.RECIPE.MODULE_DUPLICATE",
            f"FLOW row {operation.row + 2} repeats {duplicate}",
        )
    order = {"BUILDMAP": 0, "SETVPOSP": 1, "NMLOOP": 2}
    if tuple(order[module] for module in modules) != tuple(sorted(order[module] for module in modules)):
        raise FlashWindowCompileError(
            "FLASH_WINDOW.RECIPE.ORDER_INVALID",
            f"FLOW row {operation.row + 2} Recipe order is invalid",
        )


def _require_vposp_ready(operation, pumps, snapshot):
    required = frozenset(logical_item_key(pump.item) for pump in pumps)
    missing = required - snapshot.prepared_items
    dirty = required & snapshot.dirty_items
    if missing or dirty:
        item = sorted(missing or dirty)[0]
        state = "unprepared" if missing else "dirty"
        raise FlashWindowCompileError(
            "NMLOOP.SETVPOSP.NOT_READY",
            f"FLOW row {operation.row + 2} Pump {item!r} is {state}",
        )


def _run(name: str) -> RunPatternPlan:
    return RunPatternPlan(
        PatternResourceRef(name, f"pattern:{name}", ("START", "END")),
        PatternSpan.full(),
        "TS_5MHZ",
    )


__all__ = [
    "BuildMapPlan",
    "BuildMapTerm",
    "FlashWindowCompileError",
    "FlashWindowPlan",
    "FlashWindowPlanSet",
    "NmLoopPlan",
    "NmLoopPowerOff",
    "NmLoopPowerOn",
    "NmLoopRepeat",
    "NmLoopRun",
    "SetVpospPurpose",
    "compile_flash_window_plans",
    "compile_nm_loop_plan",
]
