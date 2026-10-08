"""Typed force actions used by generic firmware RUN_SEQUENCE phases."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from program_gen.core.encoding import calc_limit


_FREQUENCY_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*):([0-9]+(?:\.[0-9]+)?)\s*(Hz|kHz|MHz)$",
    re.IGNORECASE,
)
_FREQUENCY_SCALE = {"hz": 1.0, "khz": 1_000.0, "mhz": 1_000_000.0}


class FirmwareForceCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class SupplyForceAction:
    rail: str
    voltage: str
    current_compliance: float
    current_unit: str


@dataclass(frozen=True, slots=True)
class ClockSignal:
    pin: str
    frequency_hz: float


@dataclass(frozen=True, slots=True)
class ClockForceAction:
    signals: tuple[ClockSignal, ...]


@dataclass(frozen=True, slots=True)
class ClockStopAction:
    signals: tuple[ClockSignal, ...]


@dataclass(frozen=True, slots=True)
class VoltageForcePoint:
    pin: str
    voltage: str


@dataclass(frozen=True, slots=True)
class ForceVoltageAction:
    points: tuple[VoltageForcePoint, ...]


FirmwareForceAction = SupplyForceAction | ClockForceAction | ForceVoltageAction


def compile_firmware_force_action(
    record: pd.Series, *, row: int
) -> FirmwareForceAction:
    """Classify one explicit F token from already-selected generic KEIL data."""
    force = _text(record.get("FV/FI"))
    lines = tuple(line.strip() for line in force.splitlines() if line.strip())
    clock_matches = tuple(_FREQUENCY_RE.fullmatch(line) for line in lines)
    if lines and all(match is not None for match in clock_matches):
        return ClockForceAction(tuple(
            ClockSignal(
                match.group(1),
                float(match.group(2))
                * _FREQUENCY_SCALE[match.group(3).casefold()],
            )
            for match in clock_matches
            if match is not None
        ))

    pin = _text(record.get("meas pin"))
    unit = _text(record.get("UNIT"))
    if pin.upper().startswith("VCC") and unit.casefold().endswith("a"):
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
            compliance = max(abs(target), abs(low_limit), abs(high_limit))
        except (TypeError, ValueError) as exc:
            raise FirmwareForceCompileError(
                "FW.FORCE.COMPLIANCE_INVALID",
                row,
                "supply force target must be a numeric current compliance",
            ) from exc
        if not force or force == "/" or compliance <= 0:
            raise FirmwareForceCompileError(
                "FW.FORCE.SUPPLY_FACT_INVALID",
                row,
                "supply force requires voltage and positive current compliance",
            )
        return SupplyForceAction(pin, force, compliance, unit)

    if unit.casefold().endswith("v") and lines:
        points = []
        for segment in force.split("+"):
            if ":" not in segment:
                raise FirmwareForceCompileError(
                    "FW.FORCE.VOLTAGE_PIN_REQUIRED",
                    row,
                    "voltage force requires explicit <pin>:<voltage>",
                )
            force_pin, voltage = (part.strip() for part in segment.split(":", 1))
            if not force_pin or not voltage:
                raise FirmwareForceCompileError(
                    "FW.FORCE.VOLTAGE_FACT_INVALID",
                    row,
                    "voltage force pin and value must be non-empty",
                )
            points.append(VoltageForcePoint(force_pin, voltage))
        return ForceVoltageAction(tuple(points))

    raise FirmwareForceCompileError(
        "FW.FORCE.SHAPE_UNSUPPORTED",
        row,
        "F is neither a clock cell nor a supported supply-rail force",
    )


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = [
    "ClockForceAction",
    "ClockSignal",
    "ClockStopAction",
    "ForceVoltageAction",
    "FirmwareForceAction",
    "FirmwareForceCompileError",
    "SupplyForceAction",
    "VoltageForcePoint",
    "compile_firmware_force_action",
]
