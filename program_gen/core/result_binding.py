"""Product-level identities and persistence bindings for exported results."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.core.logical_item import logical_item_key


class ResultBindingCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ResultIdentity:
    source_cp: str
    item: str
    sub: str
    role: str

    @property
    def canonical(self) -> str:
        return ":".join((self.source_cp, self.item, self.sub, self.role))


@dataclass(frozen=True, slots=True)
class PersistedResultTarget:
    destination: str
    page: str
    field: str
    register: str
    lsb: int
    width: int
    encoding: str


@dataclass(frozen=True, slots=True)
class ProductResultBinding:
    identity: ResultIdentity
    producer_row: int
    symbol: str
    c_type: str
    encoding: str
    targets: tuple[PersistedResultTarget, ...]


@dataclass(frozen=True, slots=True)
class ProductResultBindingPlan:
    bindings: tuple[ProductResultBinding, ...]

    def for_symbol(self, cp: str, symbol: str) -> ProductResultBinding:
        cp_key = str(cp).strip().casefold()
        symbol_key = str(symbol).strip().casefold()
        matches = tuple(
            binding for binding in self.bindings
            if binding.identity.source_cp.casefold() == cp_key
            and binding.symbol.casefold() == symbol_key
        )
        if len(matches) != 1:
            raise KeyError((cp, symbol))
        return matches[0]


@dataclass(frozen=True, slots=True)
class PersistedResultConsumer:
    consumer_cp: str
    result_identity: ResultIdentity
    consumer_order: int


@dataclass(frozen=True, slots=True)
class TrustedPageImageRead:
    cp: str
    page: str
    producer_order: int
    operation_identity: str


@dataclass(frozen=True, slots=True)
class PersistedResultImportPlan:
    consumer_cp: str
    result_identity: ResultIdentity
    symbol: str
    c_type: str
    target: PersistedResultTarget
    restore_order: int
    operation_identity: str


@dataclass(frozen=True, slots=True)
class PersistedResultImportPlanSet:
    imports: tuple[PersistedResultImportPlan, ...]

    def for_cp(self, cp: str) -> tuple[PersistedResultImportPlan, ...]:
        key = str(cp).strip().casefold()
        return tuple(plan for plan in self.imports
                     if plan.consumer_cp.casefold() == key)


def compile_product_result_bindings(
    export_plans_by_cp,
    persistence_plans,
    *,
    explicitly_unlinked_verify_items=(),
) -> ProductResultBindingPlan:
    """Bind typed EXPORT producers to explicit persistence field writes."""
    unlinked_verify_items = {logical_item_key(item) for item in explicitly_unlinked_verify_items}
    writes_by_symbol: dict[tuple[str, str], list] = {}
    for _row, row_plan in sorted(getattr(persistence_plans, "rows", {}).items()):
        cp = str(row_plan.cp).strip().upper()
        for operation in row_plan.operations:
            for write in operation.field_writes:
                if str(write.value.kind).strip().upper() != "VARIABLE":
                    continue
                key = (cp.casefold(), str(write.value.token).strip().casefold())
                writes_by_symbol.setdefault(key, []).append(write)

    bindings = []
    symbols: dict[tuple[str, str], ResultIdentity] = {}
    target_owners: dict[tuple[str, str, str], ResultIdentity] = {}
    for cp, plan_set in export_plans_by_cp.items():
        canonical_cp = str(cp).strip().upper()
        for export in plan_set.plans:
            role = (
                "TRIM_DAC_EXPORT"
                if export.source_kind == "DAC_FINAL"
                else "VERIFY_RESULT"
            )
            identity = ResultIdentity(
                canonical_cp,
                str(export.item).strip(),
                str(export.sub).strip() or "/",
                role,
            )
            symbol_key = (canonical_cp.casefold(), export.symbol.casefold())
            previous_identity = symbols.get(symbol_key)
            if previous_identity is not None and previous_identity != identity:
                raise ResultBindingCompileError(
                    "RB.SYMBOL.CONFLICT",
                    f"{canonical_cp} symbol {export.symbol!r} belongs to both "
                    f"{previous_identity.canonical} and {identity.canonical}",
                )
            symbols[symbol_key] = identity

            targets = []
            for write in writes_by_symbol.get(symbol_key, ()):
                destination = "UID" if write.page.casefold() == "uid" else "OTP"
                _validate_width(export.format, write.width, identity)
                target = PersistedResultTarget(
                    destination=destination,
                    page=write.page,
                    field=write.field,
                    register=write.register,
                    lsb=write.lsb,
                    width=write.width,
                    encoding=export.format,
                )
                owner_key = (
                    target.page.casefold(), target.register.casefold(),
                    target.field.casefold(),
                )
                previous_owner = target_owners.get(owner_key)
                if previous_owner is not None and previous_owner != identity:
                    raise ResultBindingCompileError(
                        "RB.FIELD.CONFLICT",
                        f"field {target.page}.{target.field} belongs to both "
                        f"{previous_owner.canonical} and {identity.canonical}",
                    )
                target_owners[owner_key] = identity
                if target not in targets:
                    targets.append(target)

            # Trim persistence deliberately remains on DAC_FINAL until the
            # latest platform example settles that separate policy decision.
            if export.source_kind != "DAC_FINAL" and logical_item_key(export.item) not in unlinked_verify_items:
                required = set()
                if getattr(export, "persist_to_uid", False):
                    required.add("UID")
                if getattr(export, "persist_to_otp", False):
                    required.add("OTP")
                actual = {target.destination for target in targets}
                missing = tuple(sorted(required - actual))
                if missing:
                    raise ResultBindingCompileError(
                        "RB.TARGET.MISSING",
                        f"{identity.canonical} has no persisted {missing[0]} field",
                    )
            bindings.append(ProductResultBinding(
                identity=identity,
                producer_row=int(export.flow_row_index),
                symbol=export.symbol,
                c_type=export.c_type,
                encoding=export.format,
                targets=tuple(targets),
            ))
    return ProductResultBindingPlan(tuple(bindings))


def compile_persisted_result_imports(
    binding_plan: ProductResultBindingPlan,
    consumers,
    trusted_page_reads,
) -> PersistedResultImportPlanSet:
    """Attach imports only to upper-plan facts that establish trusted pages."""
    bindings = {binding.identity: binding for binding in binding_plan.bindings}
    reads = tuple(trusted_page_reads)
    imports = []
    local_symbols: dict[tuple[str, str], ResultIdentity] = {}
    for consumer in tuple(consumers):
        try:
            binding = bindings[consumer.result_identity]
        except KeyError as error:
            raise ResultBindingCompileError(
                "RB.IMPORT.BINDING_MISSING",
                f"unknown result {consumer.result_identity.canonical}",
            ) from error
        uid_targets = tuple(target for target in binding.targets
                            if target.destination == "UID")
        if len(uid_targets) != 1:
            raise ResultBindingCompileError(
                "RB.IMPORT.UID_FIELD_INVALID",
                f"{binding.identity.canonical} has {len(uid_targets)} UID fields",
            )
        target = uid_targets[0]
        matching_reads = tuple(
            read for read in reads
            if read.cp.casefold() == consumer.consumer_cp.casefold()
            and read.page.casefold() == target.page.casefold()
        )
        available = tuple(
            read for read in matching_reads
            if read.producer_order < consumer.consumer_order
        )
        if not available:
            code = (
                "RB.IMPORT.BEFORE_RESTORE"
                if matching_reads else "RB.IMPORT.MISSING"
            )
            raise ResultBindingCompileError(
                code,
                f"{consumer.consumer_cp} consumes {binding.symbol} before a trusted "
                f"{target.page} Page Image exists",
            )
        read = max(available, key=lambda item: item.producer_order)
        local_key = (consumer.consumer_cp.casefold(), binding.symbol.casefold())
        previous = local_symbols.get(local_key)
        if previous is not None and previous != binding.identity:
            raise ResultBindingCompileError(
                "RB.IMPORT.SYMBOL_CONFLICT",
                f"{consumer.consumer_cp} local symbol {binding.symbol!r} maps to "
                "different product results",
            )
        local_symbols[local_key] = binding.identity
        imports.append(PersistedResultImportPlan(
            consumer_cp=str(consumer.consumer_cp).strip().upper(),
            result_identity=binding.identity,
            symbol=binding.symbol,
            c_type=binding.c_type,
            target=target,
            restore_order=read.producer_order,
            operation_identity=read.operation_identity,
        ))
    return PersistedResultImportPlanSet(tuple(imports))


def _validate_width(encoding: str, width: int, identity: ResultIdentity) -> None:
    required = {"BCD16_MV": 16, "ADC12_3V3": 12}.get(str(encoding).upper())
    if required is not None and int(width) < required:
        raise ResultBindingCompileError(
            "RB.ENCODING.WIDTH_MISMATCH",
            f"{identity.canonical} encoding {encoding} requires {required} bits, "
            f"field provides {width}",
        )


__all__ = [
    "PersistedResultConsumer",
    "PersistedResultImportPlan",
    "PersistedResultImportPlanSet",
    "PersistedResultTarget",
    "ProductResultBinding",
    "ProductResultBindingPlan",
    "ResultBindingCompileError",
    "ResultIdentity",
    "TrustedPageImageRead",
    "compile_persisted_result_imports",
    "compile_product_result_bindings",
]
