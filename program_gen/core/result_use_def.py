"""CP-local EXPORT producer/consumer closure for Recipe facts."""

from __future__ import annotations

from dataclasses import dataclass
import re


class ResultUseDefError(ValueError):
    pass


_DAC_ADJ = re.compile(
    r"\s*(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<operator><=|>=|<|>)\s*(?P<threshold>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"\s*:\s*(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<delta>[+-]\d+)\s*\Z"
)


@dataclass(frozen=True, slots=True)
class DacAdjConsumer:
    flow_row_index: int
    source_item: str
    target_item: str
    operator: str
    threshold: float
    delta: int


def parse_dac_adj_consumer(value: object, flow_row_index: int) -> DacAdjConsumer | None:
    match = _DAC_ADJ.fullmatch(str(value or "").strip())
    if match is None:
        return None
    return DacAdjConsumer(
        flow_row_index, match.group("source"), match.group("target"),
        match.group("operator"), float(match.group("threshold")),
        int(match.group("delta")),
    )


def validate_export_use_def(
    export_plans_by_cp,
    recipe_rows,
    *,
    allowed_unconsumed=frozenset(),
) -> tuple[DacAdjConsumer, ...]:
    """Require every EXPORT to feed CP-local persistence or a later RAW DAC_ADJ."""
    allowed_unconsumed = frozenset(
        (str(cp).casefold(), str(item).casefold())
        for cp, item in allowed_unconsumed
    )
    consumers = tuple(
        consumer
        for row, executable in recipe_rows.items()
        for operation in executable.operations
        if operation.name == "DAC_ADJ"
        for consumer in (parse_dac_adj_consumer(operation.value, row),)
        if consumer is not None
    )
    producers = {}
    for cp, plan_set in export_plans_by_cp.items():
        for export in plan_set.plans:
            key = (str(cp).casefold(), str(export.item).casefold())
            if key in producers:
                raise ResultUseDefError(
                    f"EXPORT.USE_DEF.AMBIGUOUS: {cp}/{export.item} has multiple producers"
                )
            producers[key] = (cp, export)

    consumed = set()
    for consumer in consumers:
        consumer_cp = executable_cp(recipe_rows[consumer.flow_row_index])
        key = (str(consumer_cp).casefold(), consumer.source_item.casefold())
        producer = producers.get(key)
        if producer is None:
            exists_in_other_cp = any(
                item == consumer.source_item.casefold()
                for cp, item in producers
                if cp != str(consumer_cp).casefold()
            )
            code = "CROSS_CP" if exists_in_other_cp else "PRODUCER_MISSING"
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.{code}: {consumer_cp}/{consumer.source_item} "
                "has no CP-local EXPORT producer"
            )
        cp, export = producer
        if consumer.flow_row_index <= export.flow_row_index:
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.ORDER: {cp}/{export.item} consumer precedes producer"
            )
        if str(export.format).upper() != "RAW":
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.RAW_REQUIRED: {cp}/{export.item} DAC_ADJ requires RAW"
            )
        if str(export.c_type).casefold() != "double":
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.TYPE_INCOMPATIBLE: {cp}/{export.item} "
                f"RAW DAC_ADJ requires double, actual {export.c_type!r}"
            )
        if not str(export.unit).strip():
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.UNIT_MISSING: {cp}/{export.item} DAC_ADJ source has no unit"
            )
        consumed.add(key)

    for key, (cp, export) in producers.items():
        persisted = bool(export.persist_to_otp or export.persist_to_uid)
        if key not in consumed and not persisted and key not in allowed_unconsumed:
            raise ResultUseDefError(
                f"EXPORT.USE_DEF.UNCONSUMED: {cp}/{export.item} has no OTP/UID/DAC_ADJ consumer"
            )
    return consumers


def executable_cp(executable) -> str:
    return executable.flow.cp


__all__ = [
    "DacAdjConsumer", "ResultUseDefError", "parse_dac_adj_consumer",
    "validate_export_use_def",
]
