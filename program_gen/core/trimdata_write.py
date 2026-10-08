"""Compile native TRIMDATA_WRITE rows into shared Recipe Module plans."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from program_gen.core.commit_module import CommitModulePlan
from program_gen.core.flash_label_plan import FlashLabelContract
from program_gen.core.otp_program import (
    LoadMapWordWrite,
    OtpProgramPlanError,
    PagePatternPlan,
    compile_load_map_module_plan,
    compile_pgm_otp_module_plan,
)


class TrimdataWriteCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class TrimdataWriteStep:
    module: str
    module_plan: object


@dataclass(frozen=True, slots=True)
class TrimdataWritePlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: object
    effective_recipe: tuple[str, ...]
    steps: tuple[TrimdataWriteStep, ...]
    test_number: int


def compile_write_page_scopes(flow_frame, recipe_rows, catalog):
    """Resolve LOADMAP-write scopes before persistence/use-def compilation."""
    scopes = {}
    for row, recipe in recipe_rows.items():
        if recipe.flow.flow_type not in ("data", "write"):
            continue
        if not any(call.name == "LOADMAP" for call in recipe.operations):
            continue
        cp = recipe.flow.cp
        has_trim = bool(_uid_trim_registers(flow_frame, cp, row, catalog))
        scopes[recipe.flow.excel_row] = tuple(
            page for page in catalog.pages if page.casefold() != "uid" or has_trim
        )
    return MappingProxyType(scopes)


def _uid_trim_registers(flow_frame, cp, row, catalog):
    prior_trims = tuple(
        record.get("item", "")
        for index, record in flow_frame.iterrows()
        if index < row
        and str(record.get("CP NO", "")).strip().casefold() == cp.casefold()
        and str(record.get("type", "")).strip().casefold() == "trim"
    )
    registers = set()
    for item in prior_trims:
        candidates = catalog.selected_storage_fields("trim", item)
        for field in (candidates if candidates is not None else catalog.fields):
            if (field.page.casefold() == "uid" and field.register_layout.applies_to(cp)
                    and catalog.matches_trim(cp, item, field)):
                registers.add(field.register.casefold())
    return registers


def compile_trimdata_write_plans(
    flow_operations,
    persistence_plans,
    commit_modules: Mapping[int, tuple[CommitModulePlan, ...]],
    flow_frame,
    flash_labels: FlashLabelContract,
    *,
    catalog,
    swd_pin: str,
    recipe_rows,
):
    plans = {}
    for operation in flow_operations:
        if operation.typed_kind != "TRIMDATA_WRITE":
            continue
        try:
            persistence = persistence_plans.rows[operation.row]
        except KeyError as error:
            raise TrimdataWriteCompileError(
                "TRIMDATA_WRITE.PERSISTENCE.MISSING",
                f"FLOW row {operation.row + 2} has no persistence plan",
            ) from error
        modules = tuple(item.module for item in persistence.operations)
        recipe_modules = tuple(call.name for call in recipe_rows[operation.row].operations)
        if (
            modules != recipe_modules
            or any(module not in ("LOADMAP", "COMMIT", "PGMOTP") for module in modules)
            or not modules or modules[-1] != "PGMOTP"
            or modules[0] not in ("LOADMAP", "COMMIT")
        ):
            raise TrimdataWriteCompileError(
                "TRIMDATA_WRITE.RECIPE.INVALID",
                f"FLOW row {operation.row + 2} requires LOADMAP/COMMIT before PGMOTP, got {recipe_modules!r}",
            )
        commits = tuple(commit_modules.get(operation.row, ()))
        if len(commits) != modules.count("COMMIT"):
            raise TrimdataWriteCompileError(
                "TRIMDATA_WRITE.COMMIT.PLAN_INVALID",
                f"FLOW row {operation.row + 2} requires a plan for each COMMIT",
            )
        steps = []
        commit_index = 0
        uid_prepared = False
        for persisted in persistence.operations:
            if persisted.module == "COMMIT":
                module_plan = commits[commit_index]
                commit_index += 1
            else:
                page_patterns = tuple(
                    _page_pattern(page, flash_labels, operation.cp)
                    for page in persisted.effective_pages
                )
                has_uid = any(page.is_uid for page in page_patterns)
                if persisted.module == "LOADMAP":
                    uid_trims = _uid_trim_registers(flow_frame, operation.cp, operation.row, catalog)
                    word_writes = ()
                    if has_uid:
                        names = flash_labels.uid_variant(operation.cp)
                        word_writes = tuple(
                            LoadMapWordWrite(
                                "uid", word, 0xFFFFFFFF,
                                names.program_pattern, names.read_pattern, spans,
                            )
                            for word, spans in flash_labels.uid_pass_fields(operation.cp)
                        )
                        if not word_writes:
                            raise TrimdataWriteCompileError(
                                "TRIMDATA_WRITE.PASS_ID.MISSING", "UID early write requires PASS ID labels",
                            )
                    module_plan = compile_load_map_module_plan(
                        page_patterns, catalog, flash_labels, cp=operation.cp,
                        swd_pin=swd_pin, image_source="PAGE_IMAGE",
                        word_writes=word_writes,
                        registers=tuple(
                            register for register in catalog.registers
                            if register.page.casefold() != "uid"
                            or register.register.casefold() in uid_trims
                        ),
                    )
                    uid_prepared = has_uid or uid_prepared
                else:
                    if has_uid and not uid_prepared:
                        raise TrimdataWriteCompileError(
                            "TRIMDATA_WRITE.PGMOTP.UID_UNPREPARED",
                            f"FLOW row {operation.row + 2} needs LOADMAP with suppressed PASS ID before UID programming",
                        )
                    try:
                        module_plan = compile_pgm_otp_module_plan(
                            page_patterns, cp=operation.cp,
                            power_profile=str(flow_frame.iloc[operation.row].get("Vcc", "")),
                            reerase_uid_on_failure=False,
                        )
                    except OtpProgramPlanError as error:
                        raise TrimdataWriteCompileError(
                            "TRIMDATA_WRITE.PGMOTP.PLAN_INVALID",
                            f"FLOW row {operation.row + 2}: {error}",
                        ) from error
            steps.append(TrimdataWriteStep(persisted.module, module_plan))
        plans[operation.row] = TrimdataWritePlan(
            operation.row,
            operation.row + 2,
            operation.cp.upper(),
            operation.item,
            operation.provenance,
            modules,
            tuple(steps),
            (operation.row + 1) * 100,
        )
    return MappingProxyType(plans)


def _page_pattern(page: str, contract: FlashLabelContract, cp: str) -> PagePatternPlan:
    try:
        names = next(
            item for item in contract.pages if item.page.casefold() == page.casefold()
        )
    except StopIteration as error:
        raise TrimdataWriteCompileError(
            "TRIMDATA_WRITE.PATTERN.PAGE_MISSING", f"{page} has no Flash Label contract",
        ) from error
    variant = contract.uid_variant(cp) if page.casefold() == "uid" else names
    if not names.erase_pattern or not variant.program_pattern or not variant.read_pattern:
        raise TrimdataWriteCompileError(
            "TRIMDATA_WRITE.PATTERN.INCOMPLETE",
            f"{page} requires erase/program/read Pattern identities",
        )
    return PagePatternPlan(
        names.page, names.erase_pattern, variant.program_pattern, variant.read_pattern,
        is_uid=page.casefold() == "uid",
    )


__all__ = [
    "TrimdataWriteCompileError",
    "TrimdataWritePlan",
    "TrimdataWriteStep",
    "compile_trimdata_write_plans",
]
