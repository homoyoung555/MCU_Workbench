"""Compile CP runtime and register-image declarations from typed plans only.

Declaration ownership follows semantic references already closed by the
Product Compiler.  Runtime values come from ``RuntimeSymbol``; register images
come from persistence page operations and MemoryWakeup's explicit AddrMap
bindings.  No FLOW row, item-name convention, or platform writer is consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from program_gen.core.addr_map import AddrMapCatalog, AddrMapCompileError
from program_gen.program_plan import (
    SymbolCardinality,
    SymbolLifetime,
    SymbolRef,
)


class DeclarationCompileError(ValueError):
    """Typed declaration requirements are missing, inconsistent, or conflicting."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class DeclarationKind(str, Enum):
    DAC_FINAL = "DAC_FINAL"
    EXPORT = "EXPORT"
    BUILD_UID = "BUILD_UID"
    RUNTIME = "RUNTIME"
    REGISTER_IMAGE = "REGISTER_IMAGE"


@dataclass(frozen=True)
class Declaration:
    name: str
    kind: DeclarationKind
    value_type: str
    bit_width: int | None
    cardinality: SymbolCardinality
    lifetime: SymbolLifetime
    semantic_ref: SymbolRef | None = None
    register: str | None = None
    page: str | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeDeclarationPlan:
    cp: str
    declarations: tuple[Declaration, ...]
    identity: str

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.declarations)

    @property
    def dac_final(self) -> tuple[Declaration, ...]:
        return self._of_kind(DeclarationKind.DAC_FINAL)

    @property
    def exports(self) -> tuple[Declaration, ...]:
        return self._of_kind(DeclarationKind.EXPORT)

    @property
    def build_uid(self) -> tuple[Declaration, ...]:
        return self._of_kind(DeclarationKind.BUILD_UID)

    @property
    def register_images(self) -> tuple[Declaration, ...]:
        return self._of_kind(DeclarationKind.REGISTER_IMAGE)

    def require(self, name: str) -> Declaration:
        key = str(name).strip().casefold()
        for declaration in self.declarations:
            if declaration.name.casefold() == key:
                return declaration
        raise KeyError(name)

    def _of_kind(self, kind: DeclarationKind) -> tuple[Declaration, ...]:
        return tuple(item for item in self.declarations if item.kind is kind)


_PAGE_REGISTER_MODULES = frozenset((
    "BUILDMAP",
    "READOTPMAP",
    "LOADMAP",
    "COMMIT",
    "CHECKOTP",
    "PGMOTP",
    "BUILDUID",
))


DeclarationPlan = RuntimeDeclarationPlan


def compile_declaration_plan(cp_plan, catalogs) -> RuntimeDeclarationPlan:
    """Close all declarations required by one already-compiled CP plan."""
    cp = str(getattr(cp_plan, "cp", "")).strip().upper()
    return compile_runtime_declaration_plan(
        cp, getattr(cp_plan, "runtime_state", None), catalogs
    )


def compile_runtime_declaration_plan(cp, runtime_state, catalogs) -> RuntimeDeclarationPlan:
    """Close declarations while a CP plan's runtime group is being assembled."""
    cp = str(cp).strip().upper()
    if not cp:
        raise DeclarationCompileError(
            "DP.CP.MISSING", "CP plan does not expose a canonical CP identity"
        )
    catalog = getattr(catalogs, "addr_map", None)
    if not isinstance(catalog, AddrMapCatalog):
        raise DeclarationCompileError(
            "DP.CATALOG.ADDR_MAP_MISSING",
            "Product catalogs do not contain a typed AddrMapCatalog",
        )
    if runtime_state is None:
        raise DeclarationCompileError(
            "DP.RUNTIME_STATE.MISSING", "CP plan has no typed runtime state"
        )

    declarations: dict[str, Declaration] = {}
    for symbol in getattr(runtime_state, "symbols", ()):
        if str(symbol.ref.cp).strip().casefold() != cp.casefold():
            raise DeclarationCompileError(
                "DP.RUNTIME_SYMBOL.CROSS_CP",
                f"{cp} cannot declare runtime symbol from {symbol.ref.cp}",
            )
        if not getattr(symbol, "declaration_required", True):
            continue
        kind = _runtime_kind(symbol.ref.namespace, symbol.name)
        _add_declaration(declarations, Declaration(
            name=symbol.name,
            kind=kind,
            value_type=str(symbol.value_type).upper(),
            bit_width=symbol.bit_width,
            cardinality=symbol.cardinality,
            lifetime=symbol.lifetime,
            semantic_ref=symbol.ref,
            sources=(
                f"RUNTIME:{symbol.ref.namespace}:{symbol.producer_order}",
            ),
        ))
    for import_plan in getattr(runtime_state, "result_import_plans", ()):
        if import_plan.consumer_cp.casefold() != cp.casefold():
            raise DeclarationCompileError(
                "DP.RESULT_IMPORT.CROSS_CP",
                f"{cp} cannot declare import owned by {import_plan.consumer_cp}",
            )
        _add_declaration(declarations, Declaration(
            name=import_plan.symbol,
            kind=DeclarationKind.EXPORT,
            value_type=str(import_plan.c_type).upper(),
            bit_width=import_plan.target.width,
            cardinality=SymbolCardinality.SITE,
            lifetime=SymbolLifetime.CP,
            semantic_ref=SymbolRef(cp, "RESULT", import_plan.symbol),
            sources=(
                "RESULT_IMPORT:"
                f"{import_plan.result_identity.canonical}:"
                f"{import_plan.operation_identity}",
            ),
        ))
    _add_trim_data_dac_final(
        declarations, cp, getattr(catalogs, "trim_data", None)
    )
    _add_trimdata_read_dac_final(
        declarations,
        cp,
        getattr(runtime_state, "trimdata_read_plans", {}),
    )
    _add_dac_adjust_targets(
        declarations, cp, getattr(catalogs, "dac_adjust_plans", {})
    )

    _add_persistence_registers(
        declarations,
        cp,
        catalog,
        getattr(runtime_state, "persistence_rows", {}),
    )
    _add_memory_wakeup_registers(
        declarations,
        cp,
        catalog,
        getattr(runtime_state, "memory_wakeup_plan", None),
    )
    _add_flash_window_registers(
        declarations,
        cp,
        catalog,
        getattr(runtime_state, "flash_window_plans", {}),
    )
    ordered = tuple(sorted(
        declarations.values(),
        key=lambda item: (item.kind.value, item.name.casefold(), item.name),
    ))
    payload = {
        "cp": cp,
        "declarations": [_canonical(item) for item in ordered],
    }
    return RuntimeDeclarationPlan(cp, ordered, _hash(payload))


def _add_trim_data_dac_final(declarations, cp: str, trim_data_plan) -> None:
    if trim_data_plan is None:
        return
    for binding in trim_data_plan.for_cp(cp):
        symbol = binding.dac_final_symbol
        previous = declarations.get(symbol.casefold())
        # RuntimeSymbol owns the declaration contract when present.  TrimData's
        # DAC bits describe the search algorithm and can legitimately differ
        # from a destination field width; retain that fact as provenance rather
        # than treating it as a second C declaration width.  TrimData is the
        # typed fallback only for dedicated producers not yet in RuntimeSymbol.
        bit_width = int(binding.dac_bits)
        semantic_ref = SymbolRef(cp, "RESULT", symbol)
        if previous is not None:
            if (
                previous.kind is not DeclarationKind.DAC_FINAL
                or previous.value_type.casefold() != "int"
                or previous.cardinality is not SymbolCardinality.SITE
                or previous.lifetime is not SymbolLifetime.CP
            ):
                raise DeclarationCompileError(
                    "DP.DECLARATION.CONFLICT",
                    f"declaration {symbol!r} conflicts with its TrimData producer",
                )
            bit_width = previous.bit_width
            semantic_ref = previous.semantic_ref
        _add_declaration(declarations, Declaration(
            name=symbol,
            kind=DeclarationKind.DAC_FINAL,
            value_type="INT",
            bit_width=bit_width,
            cardinality=SymbolCardinality.SITE,
            lifetime=SymbolLifetime.CP,
            semantic_ref=semantic_ref,
            sources=(f"TRIM_DATA:{binding.item}:DAC_BITS:{binding.dac_bits}",),
        ))


def _add_trimdata_read_dac_final(declarations, cp: str, plans) -> None:
    for plan in plans.values():
        if str(plan.cp).strip().casefold() != cp.casefold():
            raise DeclarationCompileError(
                "DP.TRIMDATA_READ.CROSS_CP",
                f"{cp} contains TRIMDATA_READ plan owned by {plan.cp}",
            )
        for step in plan.steps:
            if str(step.module).strip().upper() != "READOTPMAP":
                continue
            for pump in step.module_plan.pumps:
                source = next((
                    item
                    for item in pump.sources
                    if str(getattr(item.kind, "value", item.kind)).upper()
                    == "CURRENT_DAC_FINAL"
                ), None)
                if source is None or not source.symbol:
                    raise DeclarationCompileError(
                        "DP.TRIMDATA_READ.DAC_FINAL_MISSING",
                        f"FLOW {plan.excel_row} Pump {pump.item!r} has no DAC_FINAL target",
                    )
                symbol = source.symbol
                previous = declarations.get(symbol.casefold())
                bit_width = int(pump.field.width)
                semantic_ref = None
                if previous is not None:
                    bit_width = previous.bit_width
                    semantic_ref = previous.semantic_ref
                _add_declaration(declarations, Declaration(
                    name=symbol,
                    kind=DeclarationKind.DAC_FINAL,
                    value_type="INT",
                    bit_width=bit_width,
                    cardinality=SymbolCardinality.SITE,
                    lifetime=SymbolLifetime.CP,
                    semantic_ref=semantic_ref,
                    sources=(
                        f"TRIMDATA_READ:FLOW:{plan.excel_row}:PUMP:{pump.item}",
                    ),
                ))


def _add_dac_adjust_targets(declarations, cp: str, plans) -> None:
    for plan in plans.values():
        if str(plan.cp).casefold() != cp.casefold():
            continue
        adjust = plan.steps[0].module_plan
        symbol = adjust.target_symbol
        previous = declarations.get(symbol.casefold())
        bit_width = max(1, max(adjust.codes).bit_length())
        semantic_ref = SymbolRef(cp, "RESULT", symbol)
        if previous is not None:
            if (
                previous.kind is not DeclarationKind.DAC_FINAL
                or previous.value_type.casefold() != "int"
                or previous.cardinality is not SymbolCardinality.SITE
                or previous.lifetime is not SymbolLifetime.CP
            ):
                raise DeclarationCompileError(
                    "DP.DECLARATION.CONFLICT",
                    f"declaration {symbol!r} conflicts with DAC_ADJUST target",
                )
            bit_width = previous.bit_width
            semantic_ref = previous.semantic_ref
        _add_declaration(declarations, Declaration(
            name=symbol,
            kind=DeclarationKind.DAC_FINAL,
            value_type="INT",
            bit_width=bit_width,
            cardinality=SymbolCardinality.SITE,
            lifetime=SymbolLifetime.CP,
            semantic_ref=semantic_ref,
            sources=(f"DAC_ADJUST:FLOW:{plan.excel_row}:TARGET:{plan.item}",),
        ))


def _runtime_kind(namespace: str, name: str) -> DeclarationKind:
    namespace_key = str(namespace).strip().casefold()
    if namespace_key == "build_uid":
        return DeclarationKind.BUILD_UID
    if namespace_key == "dac" or str(name).strip().upper().endswith("_DAC_FINAL"):
        return DeclarationKind.DAC_FINAL
    if namespace_key == "result":
        return DeclarationKind.EXPORT
    return DeclarationKind.RUNTIME


def _add_persistence_registers(
    declarations: dict[str, Declaration],
    cp: str,
    catalog: AddrMapCatalog,
    persistence_rows,
) -> None:
    for _row, row_plan in sorted(persistence_rows.items()):
        row_cp = str(getattr(row_plan, "cp", "")).strip().upper()
        if row_cp != cp:
            raise DeclarationCompileError(
                "DP.PERSISTENCE.CROSS_CP",
                f"{cp} contains persistence operations owned by {row_cp or '?'}",
            )
        for operation in getattr(row_plan, "operations", ()):
            module = str(operation.module).strip().upper()
            if module not in _PAGE_REGISTER_MODULES:
                continue
            pages = tuple(dict.fromkeys((
                *getattr(operation, "requested_pages", ()),
                *getattr(operation, "effective_pages", ()),
                *(write.page for write in getattr(operation, "field_writes", ())),
            )))
            for page in pages:
                matches = tuple(
                    register
                    for register in catalog.registers
                    if register.page.casefold() == str(page).strip().casefold()
                    and register.applies_to(cp)
                )
                if not matches:
                    raise DeclarationCompileError(
                        "DP.PERSISTENCE.PAGE_UNRESOLVED",
                        f"FLOW {operation.excel_row} {module} references page {page!r} "
                        f"without an AddrMap register for {cp}",
                    )
                source = (
                    f"PERSISTENCE:FLOW:{operation.excel_row}:{module}:PAGE:{page}"
                )
                for register in matches:
                    _add_register(declarations, register, source)
            for write in getattr(operation, "field_writes", ()):
                register = _resolve_register(catalog, write.register)
                if register.page.casefold() != str(write.page).casefold():
                    raise DeclarationCompileError(
                        "DP.PERSISTENCE.FIELD_REGISTER_MISMATCH",
                        f"field {write.field!r} page/register provenance is inconsistent",
                    )
                _add_register(
                    declarations,
                    register,
                    f"PERSISTENCE:FLOW:{operation.excel_row}:{module}:FIELD:{write.field}",
                )


def _add_memory_wakeup_registers(
    declarations: dict[str, Declaration],
    cp: str,
    catalog: AddrMapCatalog,
    memory_plan,
) -> None:
    if memory_plan is None:
        return
    memory_cp = str(getattr(memory_plan, "cp", "")).strip().upper()
    if memory_cp != cp:
        raise DeclarationCompileError(
            "DP.MEMORY_WAKEUP.CROSS_CP",
            f"{cp} contains MemoryWakeup plan owned by {memory_cp or '?'}",
        )
    for binding in getattr(getattr(memory_plan, "build_map", None), "field_bindings", ()):
        register = _resolve_register(catalog, binding.field.register)
        _add_register(
            declarations,
            register,
            "MEMORY_WAKEUP:BUILDMAP:"
            f"{binding.item}:{binding.field.page}:{binding.field.register}",
        )
    for pump in getattr(getattr(memory_plan, "set_vposp", None), "pumps", ()):
        field_register = _resolve_register(catalog, pump.field.register)
        _add_register(
            declarations,
            field_register,
            f"MEMORY_WAKEUP:SETVPOSP:FIELD:{pump.item}:{pump.field.register}",
        )
        for source in getattr(pump, "restored_sources", ()):
            if not source.register:
                raise DeclarationCompileError(
                    "DP.MEMORY_WAKEUP.REGISTER_MISSING",
                    f"Pump {pump.item!r} has a restored source without register identity",
                )
            register = _resolve_register(catalog, source.register)
            _add_register(
                declarations,
                register,
                f"MEMORY_WAKEUP:SETVPOSP:RESTORED_REG:{pump.item}:{source.register}",
            )


def _add_flash_window_registers(
    declarations: dict[str, Declaration],
    cp: str,
    catalog: AddrMapCatalog,
    plans,
) -> None:
    for plan in plans.values():
        if str(getattr(plan, "cp", "")).strip().upper() != cp:
            raise DeclarationCompileError(
                "DP.FLASH_WINDOW.CROSS_CP",
                f"{cp} contains FLASH_WINDOW plan owned by {getattr(plan, 'cp', '?')}",
            )
        for step in getattr(plan, "steps", ()):
            if str(getattr(step, "module", "")).upper() != "BUILDMAP":
                continue
            for register_plan in getattr(step.module_plan, "registers", ()):
                register = _resolve_register(catalog, register_plan.register)
                _add_register(
                    declarations,
                    register,
                    f"FLASH_WINDOW:FLOW:{plan.excel_row}:BUILDMAP:{register.page}:{register.register}",
                )


def _resolve_register(catalog: AddrMapCatalog, name: str):
    try:
        return catalog.resolve_register(name)
    except AddrMapCompileError as error:
        raise DeclarationCompileError(
            "DP.REGISTER.UNRESOLVED", str(error)
        ) from error


def _add_register(declarations, register, source: str) -> None:
    raw_name = str(register.register).strip()
    rendered_name = raw_name.upper()
    if not rendered_name.startswith("REG_"):
        rendered_name = "REG_" + rendered_name
    _add_declaration(declarations, Declaration(
        name=rendered_name,
        kind=DeclarationKind.REGISTER_IMAGE,
        value_type="INT",
        bit_width=16,
        cardinality=SymbolCardinality.SITE,
        lifetime=SymbolLifetime.CP,
        register=raw_name,
        page=str(register.page),
        sources=(source,),
    ))


def _add_declaration(
    declarations: dict[str, Declaration], declaration: Declaration
) -> None:
    key = declaration.name.casefold()
    previous = declarations.get(key)
    if previous is None:
        declarations[key] = declaration
        return
    if _contract(previous) != _contract(declaration):
        raise DeclarationCompileError(
            "DP.DECLARATION.CONFLICT",
            f"declaration {declaration.name!r} has incompatible typed owners",
        )
    sources = tuple(sorted(
        set(previous.sources) | set(declaration.sources),
        key=lambda item: (item.casefold(), item),
    ))
    declarations[key] = Declaration(
        name=previous.name,
        kind=previous.kind,
        value_type=previous.value_type,
        bit_width=previous.bit_width,
        cardinality=previous.cardinality,
        lifetime=previous.lifetime,
        semantic_ref=previous.semantic_ref,
        register=previous.register,
        page=previous.page,
        sources=sources,
    )


def _contract(declaration: Declaration) -> tuple:
    return (
        declaration.kind,
        declaration.value_type.casefold(),
        declaration.bit_width,
        declaration.cardinality,
        declaration.lifetime,
        declaration.semantic_ref,
        None if declaration.register is None else declaration.register.casefold(),
        None if declaration.page is None else declaration.page.casefold(),
    )


def _canonical(declaration: Declaration) -> dict:
    ref = declaration.semantic_ref
    return {
        "name": declaration.name,
        "kind": declaration.kind.value,
        "value_type": declaration.value_type,
        "bit_width": declaration.bit_width,
        "cardinality": declaration.cardinality.value,
        "lifetime": declaration.lifetime.value,
        "semantic_ref": None if ref is None else {
            "cp": ref.cp,
            "namespace": ref.namespace,
            "semantic_key": ref.semantic_key,
        },
        "register": declaration.register,
        "page": declaration.page,
        "sources": declaration.sources,
    }


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()
