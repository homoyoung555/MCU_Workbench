"""Compile shared DAC_WRITE Recipe facts without workbook or renderer access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from program_gen.core.fbist_pattern_plan import (
    FbistPatternGenerationPlan,
    compile_fbist_writable_field_catalog,
)
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan


class DacWriteCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class DacWriteSourceKind(str, Enum):
    DAC_FINAL = "DAC_FINAL"
    ADDR_MAP = "ADDR_MAP"
    ARGUMENT = "ARGUMENT"


@dataclass(frozen=True, slots=True)
class DacWriteSource:
    kind: DacWriteSourceKind
    symbol: str
    bit_width: int
    register_symbol: str | None = None
    bit_lsb: int | None = None
    literal: int | None = None
    page: str | None = None
    restored_at_excel_row: int | None = None
    produced_at_excel_row: int | None = None


@dataclass(frozen=True, slots=True)
class DacWriteTarget:
    pattern: PatternResourceRef
    bit_width: int
    chroma_start_label: str
    s100_start_label: str
    s100_end_label: str


@dataclass(frozen=True, slots=True)
class DacWriteModulePlan:
    source: DacWriteSource
    target: DacWriteTarget
    swd_pin: str
    run_pattern: RunPatternPlan
    execute_pattern: bool = True


def compile_dac_write_module_plans(
    plan_set, addr_map, fbist_plan, cp: str, persistence_plans=None,
    dac_final_producers=None,
):
    """Bind existing Recipe decisions to typed source and Pattern facts."""
    if not isinstance(fbist_plan, FbistPatternGenerationPlan):
        raise TypeError("DAC_WRITE requires FbistPatternGenerationPlan")
    writable = compile_fbist_writable_field_catalog(fbist_plan)
    compiled = {}
    for plan in plan_set.plans:
        labels = tuple(
            label for label in writable
            if label.pattern_identity == plan.pattern_name
        )
        if len(labels) != 1:
            raise DacWriteCompileError(
                "DAC_WRITE.PATTERN.FIELD_INVALID",
                f"{plan.pattern_name!r} requires exactly one dynamic field",
            )
        label = labels[0]
        if label.bit_width != plan.field_width:
            raise DacWriteCompileError(
                "DAC_WRITE.PATTERN.WIDTH_MISMATCH",
                f"{plan.pattern_name!r} field width differs from Recipe binding",
            )
        pattern = PatternResourceRef(
            plan.pattern_name,
            f"pattern:{plan.pattern_name}",
            ("START", "END"),
        )
        target = DacWriteTarget(
            pattern,
            label.bit_width,
            label.chroma_start_label,
            label.s100_start_label,
            label.s100_end_label,
        )
        source = _compile_source(
            plan, addr_map, cp, persistence_plans, dac_final_producers
        )
        compiled[plan.flow_row_index] = DacWriteModulePlan(
            source,
            target,
            fbist_plan.swd_pin,
            RunPatternPlan(pattern, PatternSpan.full(), "TS_5MHZ"),
        )
    return MappingProxyType(compiled)


def _compile_source(
    plan, addr_map, cp: str, persistence_plans, dac_final_producers
) -> DacWriteSource:
    try:
        kind = DacWriteSourceKind(plan.value_source)
    except ValueError as error:
        raise DacWriteCompileError(
            "DAC_WRITE.SOURCE.UNSUPPORTED",
            f"{plan.item!r} uses unsupported source {plan.value_source!r}",
        ) from error
    if kind is DacWriteSourceKind.ADDR_MAP:
        candidates = addr_map.selected_storage_fields("trim", plan.item)
        fields = tuple(
            field for field in (candidates if candidates is not None else addr_map.fields)
            if field.register_layout.applies_to(cp)
            and addr_map.matches_trim(cp, plan.item, field)
        )
        explicit_mapping = addr_map.has_trim_storage_mapping(plan.item)
        if not explicit_mapping and len(fields) != 1:
            raise DacWriteCompileError(
                "DAC_WRITE.SOURCE.ADDR_MAP_AMBIGUOUS",
                f"{plan.item!r} resolves to {len(fields)} ADDR_MAP fields in {cp}",
            )
        if not fields:
            raise DacWriteCompileError(
                "DAC_WRITE.SOURCE.ADDR_MAP_AMBIGUOUS",
                f"{plan.item!r} resolves to 0 ADDR_MAP fields in {cp}",
            )
        restored = tuple(
            (field, _restored_at(persistence_plans, cp, plan.flow_row_index, field.page))
            for field in fields
        )
        available = tuple((field, row) for field, row in restored if row is not None)
        if not available:
            pages = "、".join(sorted({field.page for field in fields}))
            raise DacWriteCompileError(
                "DAC_WRITE.SOURCE.NOT_RESTORED",
                f"{plan.item!r} consumes mapped pages {pages!r} before READOTPMAP",
            )
        widths = {field.width for field in fields}
        if len(widths) != 1:
            raise DacWriteCompileError(
                "DAC_WRITE.SOURCE.MULTI_COPY_INCOMPATIBLE",
                f"{plan.item!r} has restored copies with different widths in {cp}",
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
        return DacWriteSource(
            kind,
            plan.dac_symbol,
            field.width,
            register,
            field.lsb,
            page=field.page,
            restored_at_excel_row=restored_at,
        )
    if kind is DacWriteSourceKind.ARGUMENT:
        literal = int(plan.value, 2)
        if literal >= 1 << plan.field_width:
            raise DacWriteCompileError(
                "DAC_WRITE.SOURCE.ARGUMENT_RANGE",
                f"{plan.item!r} argument exceeds {plan.field_width} bits",
            )
        return DacWriteSource(kind, plan.dac_symbol, plan.field_width, literal=literal)
    produced = tuple(
        row for row in (dac_final_producers or {}).get(plan.dac_symbol, ())
        if row < plan.flow_row_index
    )
    if not produced:
        raise DacWriteCompileError(
            "DAC_WRITE.SOURCE.DAC_FINAL_UNAVAILABLE",
            f"{plan.item!r} consumes DAC_FINAL before its Trim producer",
        )
    return DacWriteSource(
        kind,
        plan.dac_symbol,
        plan.field_width,
        produced_at_excel_row=max(produced) + 2,
    )


def _restored_at(persistence_plans, cp: str, consumer_row: int, page: str):
    if persistence_plans is None:
        return None
    matches = []
    for row, row_plan in persistence_plans.rows.items():
        if row >= consumer_row or str(row_plan.cp).casefold() != str(cp).casefold():
            continue
        for operation in row_plan.operations:
            if operation.module != "READOTPMAP":
                continue
            pages = (*operation.requested_pages, *operation.effective_pages)
            if any(str(item).casefold() == str(page).casefold() for item in pages):
                matches.append(operation.excel_row)
    return max(matches) if matches else None


__all__ = [
    "DacWriteCompileError",
    "DacWriteModulePlan",
    "DacWriteSource",
    "DacWriteSourceKind",
    "DacWriteTarget",
    "compile_dac_write_module_plans",
]
