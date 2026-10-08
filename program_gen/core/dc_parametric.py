"""Compile two-sub SWD DC parametric tests into immutable typed plans."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class DcParametricCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class DcForce:
    quantity: str
    value: str


@dataclass(frozen=True, slots=True)
class DcMeasurement:
    low_limit: float
    high_limit: float
    unit: str


@dataclass(frozen=True, slots=True)
class DcPhase:
    row: int
    sub: str
    force: DcForce
    measurement: DcMeasurement
    config_pattern: str


@dataclass(frozen=True, slots=True)
class DcParametricPlan:
    row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    power_profile: str
    phases: tuple[DcPhase, DcPhase]
    typed_kind: str = "DC_PARAMETRIC_TEST"
    effective_recipe: tuple[str, ...] = ("DC_TEST",)
    shared_power_session: bool = True

    @property
    def row_indices(self) -> tuple[int, ...]:
        return tuple(phase.row for phase in self.phases)

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return tuple(row + 2 for row in self.row_indices)

    @property
    def config_patterns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(phase.config_pattern for phase in self.phases))


@dataclass(frozen=True, slots=True)
class LeakagePlan(DcParametricPlan):
    pin_topology: str = "LEAKAGE_ODD_EVEN"


@dataclass(frozen=True, slots=True)
class VolVohPlan(DcParametricPlan):
    pin_topology: str = "BALANCED_GROUPS"


@dataclass(frozen=True, slots=True)
class RpdRpuPlan(DcParametricPlan):
    pin_topology: str = "BALANCED_GROUPS"


_VARIANTS = {
    frozenset(("leakage_high_test", "leakage_low_test")): (
        LeakagePlan, "VOLTAGE", "nA",
    ),
    frozenset(("vol_test", "voh_test")): (VolVohPlan, "CURRENT", "V"),
    frozenset(("rpu_test", "rpd_test")): (RpdRpuPlan, "VOLTAGE", "uA"),
}
_PATTERN_STEMS = {
    "leakage_high_test": "Leakage",
    "leakage_low_test": "Leakage",
    "vol_test": "VOL",
    "voh_test": "VOH",
    "rpu_test": "RPU",
    "rpd_test": "RPD",
}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_CURRENT_RE = re.compile(rf"^({_NUMBER})\s*(nA|uA|mA|A)$", re.I)
_VOLTAGE_RE = re.compile(rf"^({_NUMBER})\s*(mV|V)$", re.I)


def compile_dc_parametric_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    version: pd.DataFrame,
) -> Mapping[int, DcParametricPlan]:
    candidates = tuple(
        operation for operation in operations
        if operation.typed_kind == "DC_PARAMETRIC_TEST"
    )
    if not candidates:
        return MappingProxyType({})
    product_names = _product_names(version)
    grouped: dict[tuple[str, str], list[FlowOperation]] = {}
    for operation in candidates:
        grouped.setdefault(
            (operation.cp.casefold(), operation.item.casefold()), []
        ).append(operation)

    plans = {}
    for group in grouped.values():
        if len(group) != 2 or group[1].row != group[0].row + 1:
            raise DcParametricCompileError(
                "DC.GROUP.INVALID", group[0].row,
                "DC_PARAMETRIC_TEST requires two contiguous rows",
            )
        first = group[0]
        if first.cp.upper() not in product_names:
            raise DcParametricCompileError(
                "DC.VERSION.PRODUCT_NAME_MISSING", first.row,
                f"VERSION product name is missing for {first.cp}",
            )
        records = tuple(flow.iloc[operation.row] for operation in group)
        subs = tuple(_required(record.get("sub"), op.row, "sub") for op, record in zip(group, records))
        sub_keys = frozenset(sub.casefold() for sub in subs)
        try:
            plan_type, force_quantity, measure_unit = _VARIANTS[sub_keys]
        except KeyError as exc:
            raise DcParametricCompileError(
                "DC.VARIANT.UNRESOLVED", first.row,
                f"sub roles do not identify one DC variant: {subs!r}",
            ) from exc
        power_profiles = tuple(
            _required(record.get("Vcc"), operation.row, "Vcc").upper()
            for operation, record in zip(group, records)
        )
        if len(set(power_profiles)) != 1:
            raise DcParametricCompileError(
                "DC.POWER.PROFILE_MISMATCH", first.row,
                "both sub rows must share one Vcc profile",
            )
        phases = []
        for operation, record, sub in zip(group, records, subs):
            _validate_row_contract(operation, recipe_rows, record)
            force = _force(record.get("FV/FI"), operation.row)
            measurement = _measurement(record, operation.row)
            if force.quantity != force_quantity or measurement.unit != measure_unit:
                raise DcParametricCompileError(
                    "DC.VARIANT.FACT_MISMATCH", operation.row,
                    f"{sub} requires force={force_quantity}, measure={measure_unit}",
                )
            stem = _PATTERN_STEMS[sub.casefold()]
            phases.append(DcPhase(
                operation.row,
                sub,
                force,
                measurement,
                f"{product_names[first.cp.upper()]}_SWD_{stem}",
            ))
        plans[first.row] = plan_type(
            first.row,
            first.cp,
            first.item,
            first.provenance,
            power_profiles[0],
            tuple(phases),
        )
    return MappingProxyType(dict(sorted(plans.items())))


def _validate_row_contract(operation, recipe_rows, record) -> None:
    if operation.mode != "swd":
        raise DcParametricCompileError(
            "DC.MODE.INVALID", operation.row, "DC_TEST requires mode=swd"
        )
    recipe = tuple(
        call.name for call in getattr(recipe_rows.get(operation.row), "operations", ())
    )
    if recipe not in ((), ("DC_TEST",)):
        raise DcParametricCompileError(
            "DC.RECIPE.INVALID", operation.row,
            "DC row requires empty Recipe or Recipe=DC_TEST",
        )
    if _required(record.get("meas pin"), operation.row, "meas pin").casefold() != "dc":
        raise DcParametricCompileError(
            "DC.MEAS_PIN.INVALID", operation.row, "meas pin must be DC"
        )
    if _text(record.get("target")) not in ("", "/"):
        raise DcParametricCompileError(
            "DC.TARGET.INVALID", operation.row,
            "DC parametric limits are absolute; target must be blank or '/'",
        )


def _force(value: object, row: int) -> DcForce:
    text = _required(value, row, "FV/FI")
    if re.fullmatch(r"VCC_(?:MIN|TYP|MAX)", text, re.I):
        return DcForce("VOLTAGE", text.upper())
    match = _VOLTAGE_RE.fullmatch(text)
    if match:
        return DcForce("VOLTAGE", f"{match.group(1)}{match.group(2)}")
    match = _CURRENT_RE.fullmatch(text)
    if match:
        unit = {"na": "nA", "ua": "uA", "ma": "mA", "a": "A"}[match.group(2).casefold()]
        return DcForce("CURRENT", f"{match.group(1)}{unit}")
    raise DcParametricCompileError(
        "DC.FORCE.INVALID", row, f"FV/FI is not a voltage or current: {text!r}"
    )


def _measurement(record, row: int) -> DcMeasurement:
    unit_text = _required(record.get("UNIT"), row, "UNIT").casefold()
    try:
        unit = {"na": "nA", "ua": "uA", "v": "V"}[unit_text]
    except KeyError as exc:
        raise DcParametricCompileError(
            "DC.UNIT.INVALID", row, f"unsupported measurement UNIT {unit_text!r}"
        ) from exc
    low = _number(record.get("low_range(%)"), row, "low_range(%)")
    high = _number(record.get("high_range(%)"), row, "high_range(%)")
    if low > high:
        raise DcParametricCompileError(
            "DC.LIMIT.ORDER_INVALID", row, "low limit must be <= high limit"
        )
    return DcMeasurement(low, high, unit)


def _number(value: object, row: int, field: str) -> float:
    text = _required(value, row, field)
    try:
        number = float(text)
    except ValueError as exc:
        raise DcParametricCompileError(
            "DC.LIMIT.INVALID", row, f"{field} must be an absolute number"
        ) from exc
    if not math.isfinite(number):
        raise DcParametricCompileError(
            "DC.LIMIT.INVALID", row, f"{field} must be finite"
        )
    return number


def _product_names(version: pd.DataFrame) -> Mapping[str, str]:
    names = {}
    for _row, record in version.iterrows():
        cp = _text(record.get("CP num")).upper()
        product = _text(record.get("product name"))
        if cp and product and product != "/":
            names[cp] = product
    return MappingProxyType(names)


def _required(value: object, row: int, field: str) -> str:
    text = _text(value)
    if text in ("", "/"):
        raise DcParametricCompileError(
            "DC.FLOW.FACT_MISSING", row, f"{field} is required"
        )
    return text


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = [
    "DcForce", "DcMeasurement", "DcParametricCompileError",
    "DcParametricPlan", "DcPhase", "LeakagePlan", "RpdRpuPlan",
    "VolVohPlan", "compile_dc_parametric_plans",
]
