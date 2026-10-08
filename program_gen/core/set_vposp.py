"""Platform-neutral SETVPOSP snapshot transition plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from program_gen.core.fbist_pattern_plan import FbistFieldLabel
from program_gen.core.run_pattern import RunPatternPlan


class SetVpospCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _key(value: object) -> str:
    return str(value).strip().casefold()


class SetVpospPurpose(str, Enum):
    APPLY_FOR_TEST_CONDITION = "APPLY_FOR_TEST_CONDITION"
    PREPARE_FOR_FLASH = "PREPARE_FOR_FLASH"


@dataclass(frozen=True, slots=True)
class PumpDacPlan:
    item: str
    symbol: str


@dataclass(frozen=True, slots=True)
class SetVpospSnapshot:
    prepared_items: frozenset[str] = frozenset()
    dirty_items: frozenset[str] = frozenset()

    def invalidate(self, items) -> "SetVpospSnapshot":
        return SetVpospSnapshot(
            self.prepared_items,
            self.dirty_items | frozenset(_key(item) for item in items),
        )


@dataclass(frozen=True, slots=True)
class SetVpospFieldUpdate:
    pump: PumpDacPlan
    label: FbistFieldLabel


@dataclass(frozen=True, slots=True)
class SetVpospPlan:
    updates: tuple[SetVpospFieldUpdate, ...]
    swd_pin: str
    run_pattern: RunPatternPlan
    purpose: SetVpospPurpose = SetVpospPurpose.APPLY_FOR_TEST_CONDITION

    @property
    def should_run(self) -> bool:
        return (
            self.purpose is SetVpospPurpose.APPLY_FOR_TEST_CONDITION
            and not self.updates
        )


@dataclass(frozen=True, slots=True)
class SetVpospTransition:
    plan: SetVpospPlan
    snapshot: SetVpospSnapshot


def compile_set_vposp_plan(
    pumps: tuple[PumpDacPlan, ...],
    label_catalog: tuple[FbistFieldLabel, ...],
    snapshot: SetVpospSnapshot,
    *,
    swd_pin: str,
    run_pattern: RunPatternPlan,
    purpose: SetVpospPurpose = SetVpospPurpose.APPLY_FOR_TEST_CONDITION,
) -> SetVpospTransition:
    pumps_by_item = {_key(pump.item): pump for pump in pumps}
    required = frozenset(pumps_by_item)
    dirty = (required - snapshot.prepared_items) | (snapshot.dirty_items & required)
    labeled = frozenset(
        _key(label.item) for label in label_catalog if label.dynamic
    )
    missing = required - labeled
    if missing:
        item = pumps_by_item[next(iter(missing))].item
        raise SetVpospCompileError(
            "SETVPOSP.LABEL.MISSING",
            f"Pump {item!r} has no dynamic FbistFieldLabel",
        )
    wrong_pattern = next((
        label.pattern_identity
        for label in label_catalog
        if label.dynamic
        and _key(label.item) in required
        and label.pattern_identity != run_pattern.pattern.name
    ), None)
    if wrong_pattern is not None:
        raise SetVpospCompileError(
            "SETVPOSP.PATTERN.MISMATCH",
            f"catalog Pattern {wrong_pattern!r} does not match "
            f"RUN Pattern {run_pattern.pattern.name!r}",
        )
    updates = tuple(
        SetVpospFieldUpdate(pumps_by_item[_key(label.item)], label)
        for label in label_catalog
        if label.dynamic and _key(label.item) in dirty
    )
    plan = SetVpospPlan(
        updates,
        str(swd_pin).strip(),
        run_pattern,
        SetVpospPurpose(purpose),
    )
    if not dirty:
        return SetVpospTransition(plan, snapshot)
    return SetVpospTransition(
        plan,
        SetVpospSnapshot(
            snapshot.prepared_items | dirty,
            snapshot.dirty_items - dirty,
        ),
    )


__all__ = [
    "PumpDacPlan",
    "SetVpospCompileError",
    "SetVpospFieldUpdate",
    "SetVpospPlan",
    "SetVpospPurpose",
    "SetVpospSnapshot",
    "SetVpospTransition",
    "compile_set_vposp_plan",
]
