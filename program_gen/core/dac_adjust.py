"""Platform-neutral, position-based DAC_ADJ facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import operator
from types import MappingProxyType

from program_gen.core.fbist_pattern_plan import (
    FbistPatternGenerationPlan,
    compile_fbist_label_catalog,
)
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_key
from program_gen.core.result_use_def import parse_dac_adj_consumer
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan,
    SetVpospSnapshot,
    compile_set_vposp_plan,
)


class DacAdjustCompileError(ValueError):
    pass


class DacAdjustActionPlanError(ValueError):
    pass


class DacAdjustTargetSourceKind(str, Enum):
    DAC_FINAL = "DAC_FINAL"
    ADDR_MAP = "ADDR_MAP"


@dataclass(frozen=True, slots=True)
class DacAdjustTargetSource:
    kind: DacAdjustTargetSourceKind
    symbol: str
    register_symbol: str | None = None
    bit_lsb: int | None = None
    bit_width: int | None = None
    page: str | None = None
    restored_at_excel_row: int | None = None
    produced_at_excel_row: int | None = None


@dataclass(frozen=True, slots=True)
class DacAdjustCondition:
    source_symbol: str
    unit: str
    operator: str
    threshold: float

    def matches(self, value: float) -> bool:
        try:
            return {"<": operator.lt, "<=": operator.le, ">": operator.gt,
                    ">=": operator.ge}[self.operator](value, self.threshold)
        except KeyError as error:
            raise DacAdjustCompileError(
                f"DAC_ADJ.CONDITION.OPERATOR: unsupported {self.operator!r}"
            ) from error


@dataclass(frozen=True, slots=True)
class DacAdjustChangeSet:
    values: tuple[int, ...]
    invalidated_items: frozenset[str]


@dataclass(frozen=True, slots=True)
class DacAdjustModulePlan:
    """A RAW condition and a target DAC's actual ordered code domain."""

    condition: DacAdjustCondition
    target_symbol: str
    codes: tuple[int, ...]
    delta: int
    target_source: DacAdjustTargetSource | None = None

    def __post_init__(self) -> None:
        if not str(self.condition.source_symbol).strip() or not str(self.condition.unit).strip():
            raise DacAdjustCompileError("DAC_ADJ.CONDITION.RAW_REQUIRED")
        if self.condition.operator not in ("<", "<=", ">", ">="):
            raise DacAdjustCompileError(
                f"DAC_ADJ.CONDITION.OPERATOR: unsupported {self.condition.operator!r}"
            )
        if not str(self.target_symbol).strip() or not self.codes:
            raise DacAdjustCompileError("DAC_ADJ.TARGET.MISSING")
        if len(set(self.codes)) != len(self.codes):
            raise DacAdjustCompileError("DAC_ADJ.DOMAIN.DUPLICATE_CODE")
        if (
            self.target_source is not None
            and self.target_source.symbol != self.target_symbol
        ):
            raise DacAdjustCompileError("DAC_ADJ.TARGET.SOURCE_SYMBOL_MISMATCH")

    def apply(self, raw_values, dac_values) -> tuple[int, ...]:
        """Apply the positional delta per site, clamping to both domain ends."""
        if len(raw_values) != len(dac_values):
            raise DacAdjustCompileError("DAC_ADJ.SITE.COUNT_MISMATCH")
        positions = {code: index for index, code in enumerate(self.codes)}
        result = []
        for raw, code in zip(raw_values, dac_values):
            try:
                index = positions[code]
            except KeyError as error:
                raise DacAdjustCompileError(
                    f"DAC_ADJ.TARGET.CODE_OUTSIDE_DOMAIN: {code!r}"
                ) from error
            if self.condition.matches(raw):
                index = min(max(index + self.delta, 0), len(self.codes) - 1)
            result.append(self.codes[index])
        return tuple(result)

    def apply_change_set(self, raw_values, dac_values, *, invalidates=()):
        """Return changed DAC values and explicit downstream snapshot invalidations."""
        return DacAdjustChangeSet(
            self.apply(raw_values, dac_values),
            frozenset(str(item).strip().casefold() for item in invalidates),
        )


@dataclass(frozen=True, slots=True)
class DacAdjustActionStep:
    module: str
    source_operation_index: int
    module_plan: object


@dataclass(frozen=True, slots=True)
class DacAdjustActionPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: object
    effective_recipe: tuple[str, ...]
    steps: tuple[DacAdjustActionStep, ...]


def compile_dac_adjust_action_plans(
    operations,
    recipe_rows,
    export_plans_by_cp,
    trim_specs,
    addr_map,
    persistence_plans,
    fbist_plan,
    commit_rows,
):
    """Compile the first single-input DAC_ADJUST action shape."""
    if not isinstance(fbist_plan, FbistPatternGenerationPlan):
        raise TypeError("DAC_ADJUST requires FbistPatternGenerationPlan")
    plans = {}
    for operation in operations:
        if operation.typed_kind != "DAC_ADJUST":
            continue
        recipe_row = recipe_rows.get(operation.row)
        recipe_operations = tuple(getattr(recipe_row, "operations", ()))
        modules = tuple(item.name for item in recipe_operations)
        if modules != ("DAC_ADJ", "SETVPOSP", "COMMIT"):
            adjustment_count = modules.count("DAC_ADJ")
            code = (
                "DAC_ADJUST.RECIPE.SINGLE_ADJUST_REQUIRED"
                if adjustment_count != 1
                else "DAC_ADJUST.RECIPE.SHAPE_UNSUPPORTED"
            )
            raise DacAdjustActionPlanError(
                f"{code}: FLOW row {operation.row + 2} requires "
                "DAC_ADJ-SETVPOSP-COMMIT"
            )
        consumer = parse_dac_adj_consumer(
            recipe_operations[0].value, operation.row
        )
        if consumer is None:
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.RECIPE.ARGUMENT_INVALID: FLOW row {operation.row + 2}"
            )
        export = _source_export(
            export_plans_by_cp, operation.cp, consumer.source_item, operation.row
        )
        target_specs = tuple(
            spec for spec in trim_specs.values()
            if logical_item_key(spec.item) == logical_item_key(consumer.target_item)
        )
        if not target_specs:
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.TARGET.DOMAIN_MISSING: {consumer.target_item!r}"
            )
        domains = {tuple(spec.search.codes) for spec in target_specs}
        if len(domains) != 1:
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.TARGET.DOMAIN_AMBIGUOUS: {consumer.target_item!r}"
            )
        target_symbol = logical_dac_final_symbol(consumer.target_item)
        target_source = _target_source(
            operation, consumer.target_item, target_symbol, target_specs,
            addr_map, persistence_plans,
        )
        adjust = DacAdjustModulePlan(
            DacAdjustCondition(
                export.symbol, export.unit, consumer.operator, consumer.threshold
            ),
            target_symbol,
            next(iter(domains)),
            consumer.delta,
            target_source,
        )
        if logical_item_key(consumer.target_item) not in {
            logical_item_key(item) for item in fbist_plan.pump_items
        }:
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.TARGET.NOT_PUMP: {consumer.target_item!r}"
            )
        aggregate = fbist_plan.pump_aggregate.pattern_name
        run_pattern = RunPatternPlan(
            PatternResourceRef(
                aggregate, f"pattern:{aggregate}", ("START", "END")
            ),
            PatternSpan.full(),
            "TS_5MHZ",
        )
        target_key = logical_item_key(consumer.target_item)
        transition = compile_set_vposp_plan(
            (PumpDacPlan(consumer.target_item, target_symbol),),
            compile_fbist_label_catalog(fbist_plan),
            SetVpospSnapshot(
                prepared_items=frozenset((target_key,)),
                dirty_items=frozenset((target_key,)),
            ),
            swd_pin=fbist_plan.swd_pin,
            run_pattern=run_pattern,
        )
        commits = tuple(commit_rows.get(operation.row, ()))
        if len(commits) != 1:
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.COMMIT.PLAN_MISSING: FLOW row {operation.row + 2}"
            )
        commit = commits[0]
        if not commit.writes or any(
            write.value.kind != "VARIABLE"
            or write.value.token != target_symbol
            for write in commit.writes
        ):
            raise DacAdjustActionPlanError(
                f"DAC_ADJUST.COMMIT.CHANGE_SET_MISMATCH: FLOW row {operation.row + 2}"
            )
        module_plans = (adjust, transition.plan, commit)
        plans[operation.row] = DacAdjustActionPlan(
            operation.row,
            operation.row + 2,
            operation.cp,
            operation.item,
            operation.provenance,
            modules,
            tuple(
                DacAdjustActionStep(module, index, module_plans[index])
                for index, module in enumerate(modules)
            ),
        )
    return MappingProxyType(plans)


def _source_export(export_plans_by_cp, cp, item, consumer_row):
    matches = tuple(
        export
        for candidate_cp, plan_set in export_plans_by_cp.items()
        if str(candidate_cp).casefold() == str(cp).casefold()
        for export in plan_set.plans
        if logical_item_key(export.item) == logical_item_key(item)
    )
    if len(matches) != 1:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.SOURCE.EXPORT_AMBIGUOUS: {cp}/{item}"
        )
    export = matches[0]
    if export.flow_row_index >= consumer_row:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.SOURCE.EXPORT_ORDER: {cp}/{item}"
        )
    if str(export.format).upper() != "RAW" or str(export.c_type).casefold() != "double":
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.SOURCE.RAW_DOUBLE_REQUIRED: {cp}/{item}"
        )
    if not str(export.unit).strip():
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.SOURCE.UNIT_MISSING: {cp}/{item}"
        )
    return export


def _target_source(
    operation, target_item, target_symbol, target_specs, addr_map,
    persistence_plans,
):
    produced = tuple(
        spec.flow_row_index
        for spec in target_specs
        if str(spec.cp).casefold() == str(operation.cp).casefold()
        and spec.flow_row_index < operation.row
    )
    if produced:
        return DacAdjustTargetSource(
            DacAdjustTargetSourceKind.DAC_FINAL,
            target_symbol,
            produced_at_excel_row=max(produced) + 2,
        )
    candidates = addr_map.selected_storage_fields("trim", target_item)
    fields = tuple(
        field for field in (candidates if candidates is not None else addr_map.fields)
        if field.register_layout.applies_to(operation.cp)
        and addr_map.matches_trim(operation.cp, target_item, field)
    )
    explicit_mapping = addr_map.has_trim_storage_mapping(target_item)
    if not explicit_mapping:
        fields = tuple(field for field in fields if field.page.casefold() != "uid")
    if not explicit_mapping and len(fields) != 1:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.TARGET.ADDR_MAP_AMBIGUOUS: {target_item!r} "
            f"resolves to {len(fields)} mapped fields"
        )
    if not fields:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.TARGET.ADDR_MAP_AMBIGUOUS: {target_item!r} resolves to 0 mapped fields"
        )
    available = tuple(
        (field, _restored_at(persistence_plans, operation.cp, operation.row, field.page))
        for field in fields
    )
    available = tuple((field, row) for field, row in available if row is not None)
    if not available:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.TARGET.NOT_RESTORED: {target_item!r} mapped copies"
        )
    if len({field.width for field in fields}) != 1:
        raise DacAdjustActionPlanError(
            f"DAC_ADJUST.TARGET.MULTI_COPY_INCOMPATIBLE: {target_item!r}"
        )
    field, restored_at = min(
        available,
        key=lambda candidate: (
            candidate[0].page.casefold(), candidate[0].register.casefold(),
            candidate[0].lsb, candidate[0].name.casefold(), candidate[1],
        ),
    )
    register = field.register.upper()
    if not register.startswith("REG_"):
        register = "REG_" + register
    return DacAdjustTargetSource(
        DacAdjustTargetSourceKind.ADDR_MAP,
        target_symbol,
        register,
        field.lsb,
        field.width,
        field.page,
        restored_at_excel_row=restored_at,
    )


def _restored_at(persistence_plans, cp, consumer_row, page):
    if persistence_plans is None:
        return None
    matches = tuple(
        operation.excel_row
        for row, row_plan in persistence_plans.rows.items()
        if row < consumer_row and str(row_plan.cp).casefold() == str(cp).casefold()
        for operation in row_plan.operations
        if operation.module == "READOTPMAP"
        and any(
            str(candidate).casefold() == str(page).casefold()
            for candidate in (*operation.requested_pages, *operation.effective_pages)
        )
    )
    return max(matches) if matches else None


__all__ = [
    "DacAdjustActionPlan", "DacAdjustActionPlanError", "DacAdjustActionStep",
    "DacAdjustChangeSet", "DacAdjustCompileError", "DacAdjustCondition",
    "DacAdjustModulePlan", "DacAdjustTargetSource", "DacAdjustTargetSourceKind",
    "compile_dac_adjust_action_plans",
]
