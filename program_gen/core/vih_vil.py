"""Compile protocol variants of the VIH/VIL threshold test."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.core.run_sequence import NativeRunSequenceAction, parse_run_sequence_step
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class VihVilCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class VihVilPlan:
    row: int
    row_indices: tuple[int, ...]
    cp: str
    item: str
    provenance: WorkbookProvenance
    power_profile: str
    product_name: str
    typed_kind: str = "DC_VIH_VIL"
    effective_recipe: tuple[str, ...] = ("VIH_VIL_TEST",)

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return tuple(row + 2 for row in self.row_indices)


@dataclass(frozen=True, slots=True)
class SwdVihVilPlan(VihVilPlan):
    config_pattern: str = ""
    capture_patterns: tuple[str, ...] = ()
    cases: tuple[str, ...] = ("LL", "HH", "HL", "LH")
    shared_power_session: bool = True

    @property
    def patterns(self) -> tuple[str, ...]:
        return (self.config_pattern, *self.capture_patterns)


@dataclass(frozen=True, slots=True)
class KeilVihVilVariant:
    row: int
    sub: str
    variant: int
    entry_actions: tuple[NativeRunSequenceAction, ...]
    pattern: str
    independent_power_session: bool = True


@dataclass(frozen=True, slots=True)
class KeilVihVilPlan(VihVilPlan):
    variants: tuple[KeilVihVilVariant, KeilVihVilVariant] = ()


@dataclass(frozen=True, slots=True)
class VihVilVectors:
    pins: tuple[str, ...]
    case_a_input: str
    case_a_full: str
    case_b_input: str
    case_b_full: str


def build_vih_vil_vectors(pins: tuple[str, ...], variant: int) -> VihVilVectors:
    real = tuple(sorted(
        (pin for pin in pins if re.fullmatch(r"P[A-F]\d+", pin, re.I)),
        key=lambda pin: (pin[1].upper(), int(pin[2:])),
    ))
    if variant not in (1, 2) or len(real) < 2:
        raise ValueError("VIHVIL.VECTOR.FACTS_INVALID")
    ascending, descending = real, tuple(reversed(real))
    upper_source, lower_source = (
        (ascending, descending) if variant == 1 else (descending, ascending)
    )
    middle = len(real) // 2
    if len(real) % 2 == 0:
        upper, lower = upper_source[:middle], lower_source[:middle]
    elif variant == 1:
        upper, lower = upper_source[:middle + 1], lower_source[:middle]
    else:
        upper, lower = upper_source[:middle], lower_source[:middle + 1]
    upper_a = ["1" if index % 2 == 0 else "0" for index in range(len(upper))]
    if len(upper) > len(lower):
        upper_a[-1] = upper_a[-2]
    lower_a = [
        "H" if upper_a[index] == "1" else "L"
        for index in range(min(len(lower), len(upper_a)))
    ]
    while len(lower_a) < len(lower):
        lower_a.append(lower_a[-1])
    upper_b = ["0" if value == "1" else "1" for value in upper_a]
    lower_b = ["L" if value == "H" else "H" for value in lower_a]
    return VihVilVectors(
        tuple((*upper, *lower)),
        "".join((*upper_a, *("X" for _ in lower))),
        "".join((*upper_a, *lower_a)),
        "".join((*upper_b, *("X" for _ in lower))),
        "".join((*upper_b, *lower_b)),
    )


def compile_vih_vil_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    version: pd.DataFrame,
) -> Mapping[int, VihVilPlan]:
    candidates = tuple(op for op in operations if op.typed_kind == "DC_VIH_VIL")
    if not candidates:
        return MappingProxyType({})
    versions = _version_facts(version)
    grouped: dict[tuple[str, str], list[FlowOperation]] = {}
    for operation in candidates:
        grouped.setdefault((operation.cp.casefold(), operation.item.casefold()), []).append(operation)
    plans = {}
    for group in grouped.values():
        first = group[0]
        if any(operation.mode != first.mode for operation in group):
            raise VihVilCompileError("VIHVIL.MODE.MIXED", first.row, "one item cannot mix SWD and KEIL")
        try:
            product_name, get_pin = versions[first.cp.upper()]
        except KeyError as exc:
            raise VihVilCompileError("VIHVIL.VERSION.MISSING", first.row, first.cp) from exc
        records = tuple(flow.iloc[operation.row] for operation in group)
        powers = tuple(_required(record.get("Vcc"), operation.row, "Vcc").upper() for operation, record in zip(group, records))
        if len(set(powers)) != 1:
            raise VihVilCompileError("VIHVIL.POWER.MISMATCH", first.row, "all rows must share Vcc")
        for operation, record in zip(group, records):
            _validate_common(operation, recipe_rows, record)
        if first.mode == "swd":
            if len(group) != 1:
                raise VihVilCompileError("VIHVIL.SWD.GROUP_INVALID", first.row, "SWD requires one row")
            step = _text(records[0].get("step")).upper()
            if step not in ("", "/", "T"):
                raise VihVilCompileError("VIHVIL.SWD.STEP_INVALID", first.row, "SWD step must be '/' (legacy T is migration-only)")
            plan = SwdVihVilPlan(
                first.row, (first.row,), first.cp, first.item, first.provenance,
                powers[0], product_name,
                config_pattern=f"{product_name}_SWD_VILVIH_Test",
                capture_patterns=tuple(f"{product_name}_VILVIH_CAP_{case}" for case in ("LL", "HH", "HL", "LH")),
            )
        elif first.mode == "keil":
            if len(group) != 2 or group[1].row != group[0].row + 1:
                raise VihVilCompileError("VIHVIL.KEIL.GROUP_INVALID", first.row, "KEIL requires two contiguous variants")
            variants = []
            for index, (operation, record) in enumerate(zip(group, records), start=1):
                try:
                    actions = parse_run_sequence_step(record.get("step"), get_pin)
                except ValueError as exc:
                    raise VihVilCompileError("VIHVIL.KEIL.STEP_INVALID", operation.row, str(exc)) from exc
                if not actions:
                    raise VihVilCompileError("VIHVIL.KEIL.ENTRY_EMPTY", operation.row, "KEIL variant requires entry actions")
                variants.append(KeilVihVilVariant(
                    operation.row, _required(record.get("sub"), operation.row, "sub"),
                    index, actions, f"{product_name}_VILVIH{index}",
                ))
            plan = KeilVihVilPlan(
                first.row, tuple(operation.row for operation in group), first.cp,
                first.item, first.provenance, powers[0], product_name,
                variants=tuple(variants),
            )
        else:
            raise VihVilCompileError("VIHVIL.MODE.INVALID", first.row, first.mode)
        plans[first.row] = plan
    return MappingProxyType(dict(sorted(plans.items())))


def _validate_common(operation, recipe_rows, record):
    recipe = tuple(call.name for call in getattr(recipe_rows.get(operation.row), "operations", ()))
    if recipe not in ((), ("VIH_VIL_TEST",)):
        raise VihVilCompileError("VIHVIL.RECIPE.INVALID", operation.row, repr(recipe))
    if _required(record.get("meas pin"), operation.row, "meas pin").casefold() != "dc":
        raise VihVilCompileError("VIHVIL.MEAS_PIN.INVALID", operation.row, "meas pin must be DC")


def _version_facts(version):
    result = {}
    for _, row in version.iterrows():
        cp = _text(row.get("CP num")).upper()
        product = _text(row.get("product name"))
        if cp and product and product != "/":
            result[cp] = (product, _text(row.get("GET PIN")))
    return MappingProxyType(result)


def _required(value, row, field):
    text = _text(value)
    if text in ("", "/"):
        raise VihVilCompileError("VIHVIL.FACT.MISSING", row, f"{field} is required")
    return text


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = [
    "KeilVihVilPlan", "KeilVihVilVariant", "SwdVihVilPlan", "VihVilCompileError",
    "VihVilPlan", "compile_vih_vil_plans",
    "VihVilVectors", "build_vih_vil_vectors",
]
