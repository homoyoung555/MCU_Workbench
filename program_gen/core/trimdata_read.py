"""Compile native TRIMDATA_READ Recipe rows into platform-neutral plans."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from program_gen.core.addr_map import AddrMapCatalog, CaptureLayoutEntry
from program_gen.core.fbist_pattern_plan import FbistPatternGenerationPlan, compile_fbist_label_catalog
from program_gen.core.flash_label_plan import FlashLabelContract
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_key
from program_gen.core.memory_wakeup import DacValueSource, DacValueSourceKind, PumpBinding
from program_gen.core.otp_program import (
    LoadMapPlan, PagePatternPlan, compile_load_map_module_plan,
)
from program_gen.core.persistence_recipe import PersistencePlan, PersistenceRowPlan
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan, SetVpospPurpose, SetVpospSnapshot, compile_set_vposp_plan,
)
from program_gen.core.trim_data import TrimDataPlan


class TrimdataReadCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ReadOtpMapPagePlan:
    page: str
    capture: RunPatternPlan
    layout: tuple[CaptureLayoutEntry, ...]
    restore_registers: tuple[str, ...] | None = None

    @property
    def byte_count(self) -> int:
        return sum(entry.slot_width for entry in self.layout)


@dataclass(frozen=True, slots=True)
class ReadOtpMapPlan:
    cp: str
    pages: tuple[ReadOtpMapPagePlan, ...]
    pumps: tuple[PumpBinding, ...]
    swd_pin: str
    read_bit: int


@dataclass(frozen=True, slots=True)
class CheckOtpPlan:
    cp: str
    set_all_final_vposp: RunPatternPlan
    page_reads: tuple[RunPatternPlan, ...]
    runs_read_compare: bool = True
    erases_page: bool = False
    programs_page: bool = False


@dataclass(frozen=True, slots=True)
class TrimdataReadStep:
    module: str
    module_plan: object
    segment: int


@dataclass(frozen=True, slots=True)
class TrimdataReadPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: object
    effective_recipe: tuple[str, ...]
    steps: tuple[TrimdataReadStep, ...]
    test_number: int
    power_profile: str

    @property
    def operations(self) -> tuple[object, ...]:
        return tuple(step.module_plan for step in self.steps)


def compile_trimdata_read_plan(
    persistence_plan: PersistencePlan | PersistenceRowPlan,
    trim_data_plan: TrimDataPlan,
    addr_map_catalog: AddrMapCatalog,
    *,
    excel_row: int,
    item: str = "Trimdata_Read",
    provenance: object = None,
    power_profile: str,
    fbist_plan: FbistPatternGenerationPlan,
    flash_labels: FlashLabelContract,
    read_bit: int,
    extra_module_plans: Mapping[int, object] = MappingProxyType({}),
) -> TrimdataReadPlan:
    """Compile one row; extra shared modules are supplied by operation position."""
    cp = str(persistence_plan.cp).strip().upper()
    if not cp or not cp.startswith("CP") or not cp[2:].isdigit():
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.CP.INVALID", f"invalid CP identity {persistence_plan.cp!r}"
        )
    operations = tuple(
        operation for operation in persistence_plan.operations
        if operation.excel_row == excel_row
    )
    modules = tuple(operation.module for operation in operations)
    segments = _segment_modules(modules, excel_row)
    pumps = _compile_pumps(trim_data_plan, addr_map_catalog, cp=cp)
    pump_plans = tuple(
        PumpDacPlan(pump.item, logical_dac_final_symbol(pump.item)) for pump in pumps
    )
    labels = compile_fbist_label_catalog(fbist_plan)
    snapshot = SetVpospSnapshot()
    steps = []
    segment_pages: dict[int, tuple[str, ...]] = {}
    for position, (operation, segment) in enumerate(zip(operations, segments)):
        module = operation.module
        if module in ("READOTPMAP", "LOADMAP", "CHECKOTP"):
            pages = _non_uid_pages(operation.requested_pages)
            previous = segment_pages.setdefault(segment, pages)
            if not pages or pages != previous:
                raise TrimdataReadCompileError(
                    "TRIMDATA_READ.PAGE_SCOPE.MISMATCH",
                    f"FLOW row {excel_row} segment {segment + 1} must use one non-UID page set",
                )
        if module == "READOTPMAP":
            page_plans = tuple(
                ReadOtpMapPagePlan(
                    page,
                    _run(_page_names(flash_labels, page).capture_pattern, "capture"),
                    addr_map_catalog.capture_layout(page, read_bit=read_bit, cp=cp),
                )
                for page in pages
            )
            module_plan = ReadOtpMapPlan(cp, page_plans, pumps, fbist_plan.swd_pin, int(read_bit))
            snapshot = snapshot.invalidate(pump.item for pump in pump_plans)
        elif module == "LOADMAP":
            page_patterns = tuple(
                PagePatternPlan(
                    page,
                    _page_names(flash_labels, page).erase_pattern,
                    _page_names(flash_labels, page).program_pattern,
                    _page_names(flash_labels, page).read_pattern,
                )
                for page in pages
            )
            module_plan = compile_load_map_module_plan(
                page_patterns, addr_map_catalog, flash_labels,
                image_source=f"READOTPMAP:FLOW:{excel_row}:SEGMENT:{segment + 1}",
                swd_pin=fbist_plan.swd_pin,
                cp=cp,
            )
        elif module == "SETVPOSP":
            transition = compile_set_vposp_plan(
                pump_plans, labels, snapshot,
                swd_pin=fbist_plan.swd_pin,
                run_pattern=_run("set_all_final_vposp"),
                purpose=SetVpospPurpose.PREPARE_FOR_FLASH,
            )
            snapshot = transition.snapshot
            module_plan = transition.plan
        elif module == "CHECKOTP":
            module_plan = CheckOtpPlan(
                cp, _run("set_all_final_vposp"),
                tuple(_run(_page_names(flash_labels, page).read_pattern) for page in pages),
            )
        else:
            try:
                module_plan = extra_module_plans[position]
            except KeyError as error:
                raise TrimdataReadCompileError(
                    "TRIMDATA_READ.MODULE.PLAN_MISSING",
                    f"FLOW row {excel_row} {module} needs a shared typed module plan",
                ) from error
        steps.append(TrimdataReadStep(module, module_plan, segment))
    profile = str(power_profile).strip()
    if not profile:
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.VCC.MISSING", f"FLOW row {excel_row} requires Vcc"
        )
    return TrimdataReadPlan(
        excel_row - 2, excel_row, cp, str(item).strip(), provenance, modules,
        tuple(steps), (excel_row - 1) * 100, profile,
    )


def _segment_modules(modules: tuple[str, ...], excel_row: int) -> tuple[int, ...]:
    required = ("READOTPMAP", "LOADMAP", "SETVPOSP", "CHECKOTP")
    expected = segment = 0
    result = []
    for module in modules:
        result.append(segment)
        if module != required[expected]:
            if module in required:
                raise TrimdataReadCompileError(
                    "TRIMDATA_READ.RECIPE.ORDER_INVALID",
                    f"FLOW row {excel_row} expected {required[expected]} before {module}",
                )
            continue
        expected += 1
        if expected == len(required):
            expected = 0
            segment += 1
    if expected or segment == 0:
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.RECIPE.SPINE_INCOMPLETE",
            f"FLOW row {excel_row} requires READOTPMAP→LOADMAP→SETVPOSP→CHECKOTP",
        )
    return tuple(result)


def _page_names(contract: FlashLabelContract, page: str):
    try:
        names = next(item for item in contract.pages if item.page.casefold() == page.casefold())
    except StopIteration as error:
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.PAGE.PATTERN_MISSING", f"{page} has no Flash Label contract"
        ) from error
    if not names.capture_pattern or not names.program_pattern or not names.read_pattern:
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.PAGE.PATTERN_INCOMPLETE", f"{page} lacks capture/program/read Pattern"
        )
    return names


def _non_uid_pages(pages) -> tuple[str, ...]:
    return tuple(page for page in pages if str(page).strip().casefold() != "uid")


def _run(name: str | None, purpose: str = "execute") -> RunPatternPlan:
    if not name:
        raise TrimdataReadCompileError(
            "TRIMDATA_READ.PATTERN.MISSING", f"missing Pattern for {purpose}"
        )
    return RunPatternPlan(
        PatternResourceRef(name, f"pattern:{name}", ("START", "END")),
        PatternSpan.full(), "TS_5MHZ",
    )


def _compile_pumps(trim_data_plan, addr_map_catalog, *, cp):
    selected = {}
    for binding in trim_data_plan.bindings:
        if not binding.pump:
            continue
        key = logical_item_key(binding.item)
        previous = selected.get(key)
        if previous is None or binding.cp.casefold() == cp.casefold():
            selected[key] = binding
    result = []
    for binding in selected.values():
        candidates = addr_map_catalog.selected_storage_fields("trim", binding.item)
        layouts = tuple(
            field for field in (candidates if candidates is not None else addr_map_catalog.fields)
            if field.register_layout.applies_to(cp)
            and addr_map_catalog.matches_trim(cp, binding.item, field)
        )
        if not layouts:
            raise TrimdataReadCompileError(
                "TRIMDATA_READ.PUMP.REG_MISSING", f"{cp} Pump {binding.item} has no REG fallback"
            )
        if addr_map_catalog.has_trim_storage_mapping(binding.item):
            layouts = tuple(sorted(
                layouts,
                key=lambda field: (field.page.casefold(), field.register.casefold(), field.lsb, field.name.casefold()),
            ))
        result.append(PumpBinding(
            binding.item, layouts[0],
            (
                DacValueSource(DacValueSourceKind.CURRENT_DAC_FINAL, symbol=binding.dac_final_symbol),
                *(DacValueSource(
                    DacValueSourceKind.RESTORED_REG, register=layout.register,
                    lsb=layout.lsb, width=layout.width,
                ) for layout in layouts),
            ),
        ))
    return tuple(result)


__all__ = [
    "CheckOtpPlan", "LoadMapPlan", "ReadOtpMapPagePlan", "ReadOtpMapPlan",
    "TrimdataReadCompileError", "TrimdataReadPlan", "TrimdataReadStep",
    "compile_trimdata_read_plan",
]
