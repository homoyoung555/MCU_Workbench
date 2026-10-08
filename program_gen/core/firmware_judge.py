"""Platform-neutral JUDGE plans for generic KEIL firmware phases."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from program_gen.core.encoding import calc_limit
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation
from program_gen.core.sram_capture import SramCapturePlan


class FirmwareJudgeCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class ScalarMeasurementJudgePlan:
    kind: JudgeMeasurementKind
    pin: str
    low_limit: float
    high_limit: float
    unit: str
    sub: str
    provenance: WorkbookProvenance


@dataclass(frozen=True, slots=True)
class DigitalCompareJudgePlan:
    pins: tuple[str, ...]
    expected: tuple[str, ...]
    unit: str
    sub: str
    provenance: WorkbookProvenance


@dataclass(frozen=True, slots=True)
class SramValueJudgePlan:
    capture: SramCapturePlan
    index: int
    low_limit: float
    high_limit: float
    sub: str
    provenance: WorkbookProvenance


FirmwareJudgePlan = ScalarMeasurementJudgePlan | DigitalCompareJudgePlan | SramValueJudgePlan


def compile_firmware_judge_plans(
    operations: tuple[FlowOperation, ...],
    flow: pd.DataFrame,
) -> Mapping[int, FirmwareJudgePlan]:
    plans = {}
    for operation in operations:
        if operation.typed_kind != "VERIFY_KEIL":
            continue
        if operation.row < 0 or operation.row >= len(flow.index):
            raise FirmwareJudgeCompileError(
                "FW.JUDGE.ROW_MISSING",
                operation.row,
                "classified FLOW row is absent from the table",
            )
        plans[operation.row] = compile_firmware_judge_plan(
            operation, flow.iloc[operation.row]
        )
    return MappingProxyType(plans)


def compile_firmware_judge_plan(
    operation: FlowOperation,
    record: pd.Series,
) -> FirmwareJudgePlan:
    """Compile one JUDGE without coupling it to a particular typed KEIL family."""
    unit = _text(record.get("UNIT"))
    target_text = _text(record.get("target")).upper()
    if re.fullmatch(r"[HL]+", target_text):
        if unit != "/":
            raise FirmwareJudgeCompileError(
                "FW.JUDGE.DIGITAL_UNIT_INVALID",
                operation.row,
                "digital compare UNIT must be /",
            )
        pins = tuple(
            pin.strip()
            for pin in _required_text(
                record.get("meas pin"), operation.row, "meas pin"
            ).split("+")
        )
        expected = tuple(target_text)
        if not all(pins) or len(pins) != len(expected):
            raise FirmwareJudgeCompileError(
                "FW.JUDGE.DIGITAL_ARITY",
                operation.row,
                "digital compare pins and H/L expected states must align",
            )
        return DigitalCompareJudgePlan(
            pins=pins,
            expected=expected,
            unit=unit,
            sub=_required_text(record.get("sub"), operation.row, "sub"),
            provenance=operation.provenance,
        )
    if unit == "/":
        raise FirmwareJudgeCompileError(
            "FW.JUDGE.DIGITAL_TARGET_INVALID",
            operation.row,
            "digital compare target must contain only H/L states",
        )
    normalized_unit = unit.casefold()
    if normalized_unit.endswith("a"):
        measurement_kind = JudgeMeasurementKind.CURRENT
    elif normalized_unit.endswith("v"):
        measurement_kind = JudgeMeasurementKind.VOLTAGE
    else:
        raise FirmwareJudgeCompileError(
            "FW.JUDGE.UNIT_UNSUPPORTED",
            operation.row,
            f"generic KEIL scalar JUDGE does not support UNIT {unit!r}",
        )
    try:
        target = float(record.get("target"))
        low_limit = calc_limit(
            target,
            record.get("low_range(%)"),
            record.get("high_range(%)"),
            True,
        )
        high_limit = calc_limit(
            target,
            record.get("low_range(%)"),
            record.get("high_range(%)"),
            False,
        )
    except (TypeError, ValueError) as exc:
        raise FirmwareJudgeCompileError(
            "FW.JUDGE.LIMIT_INVALID",
            operation.row,
            "target/low_range/high_range cannot form scalar limits",
        ) from exc
    return ScalarMeasurementJudgePlan(
        kind=measurement_kind,
        pin=_required_text(record.get("meas pin"), operation.row, "meas pin"),
        low_limit=low_limit,
        high_limit=high_limit,
        unit=unit,
        sub=_required_text(record.get("sub"), operation.row, "sub"),
        provenance=operation.provenance,
    )


def _required_text(value: object, row: int, field: str) -> str:
    text = _text(value)
    if not text or text == "/":
        raise FirmwareJudgeCompileError(
            "FW.JUDGE.FACT_MISSING", row, f"{field} is required"
        )
    return text


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = [
    "DigitalCompareJudgePlan",
    "FirmwareJudgeCompileError",
    "FirmwareJudgePlan",
    "ScalarMeasurementJudgePlan",
    "compile_firmware_judge_plan",
    "compile_firmware_judge_plans",
]
