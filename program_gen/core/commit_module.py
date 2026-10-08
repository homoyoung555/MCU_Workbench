"""Workbook-free Recipe Module plan for runtime COMMIT refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from flow_recipe import RecipeValueToken

from program_gen.core.addr_map import AddrMapCatalog
from program_gen.core.flash_label_plan import FlashLabelContract, FlashLabelSpan
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
)


class CommitModuleCompileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommitPatternTarget:
    page: str
    register: str
    register_symbol: str
    program_pattern: str
    read_pattern: str
    labels: tuple[FlashLabelSpan, ...]


@dataclass(frozen=True, slots=True)
class CommitFieldValue:
    """A compiler-bound field outside the 16-bit Trim/Verify REG catalog."""

    field: str
    value: RecipeValueToken
    program_pattern: str
    read_pattern: str
    labels: tuple[FlashLabelSpan, ...]
    read_dont_care: bool = False
    write_program: bool = True
    value_type: str = "int"


@dataclass(frozen=True, slots=True)
class CommitModulePlan:
    writes: tuple[PersistenceFieldWrite, ...]
    targets: tuple[CommitPatternTarget, ...]
    swd_pin: str
    field_values: tuple[CommitFieldValue, ...] = ()


def compile_commit_module_plan(
    operation: PersistenceOperation,
    catalog: AddrMapCatalog,
    *,
    cp: str,
    swd_pin: str,
    flash_labels: FlashLabelContract,
) -> CommitModulePlan:
    if operation.module != "COMMIT":
        raise CommitModuleCompileError(
            f"COMMIT.MODULE.OPERATION: expected COMMIT, got {operation.module!r}"
        )
    targets = []
    seen = set()
    for write in operation.field_writes:
        register = catalog.resolve_register(write.register)
        if register.page.casefold() != write.page.casefold():
            raise CommitModuleCompileError(
                f"COMMIT.MODULE.PAGE_MISMATCH: {write.register} is not on {write.page}"
            )
        if not register.applies_to(cp):
            raise CommitModuleCompileError(
                f"COMMIT.MODULE.CP_MISMATCH: {write.register} does not apply to {cp}"
            )
        key = (write.page.casefold(), write.register.casefold())
        if key in seen:
            continue
        seen.add(key)
        binding = flash_labels.bind_register(write.page, write.register, cp)
        targets.append(CommitPatternTarget(
            page=write.page,
            register=write.register,
            register_symbol=f"REG_{write.register.upper()}",
            program_pattern=binding.program_pattern,
            read_pattern=binding.read_pattern,
            labels=binding.spans,
        ))
    pin = str(swd_pin).strip()
    if not pin:
        raise CommitModuleCompileError("COMMIT.MODULE.SWD_PIN_MISSING")
    return CommitModulePlan(tuple(operation.field_writes), tuple(targets), pin)


def compile_commit_module_plans(
    persistence_plans,
    catalog: AddrMapCatalog,
    *,
    swd_pin: str,
    flash_labels: FlashLabelContract,
):
    return MappingProxyType({
        row: tuple(
            compile_commit_module_plan(
                operation, catalog, cp=plan.cp, swd_pin=swd_pin,
                flash_labels=flash_labels,
            )
            for operation in plan.operations
            if operation.module == "COMMIT"
        )
        for row, plan in persistence_plans.rows.items()
        if any(operation.module == "COMMIT" for operation in plan.operations)
    })


__all__ = [
    "CommitModuleCompileError",
    "CommitModulePlan",
    "CommitPatternTarget",
    "compile_commit_module_plan",
    "compile_commit_module_plans",
]
