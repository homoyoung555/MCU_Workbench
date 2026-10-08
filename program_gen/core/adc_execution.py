"""Project platform-neutral ADC slots onto one target's bonded IO pins."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.core.adc_test import AdcCaptureSlot, AdcPhase, AdcSourceKind


@dataclass(frozen=True, slots=True)
class AdcDrive:
    pin: str
    voltage: float


@dataclass(frozen=True, slots=True)
class AdcExecutionSlot:
    source: AdcCaptureSlot
    force_enabled: bool
    judge_enabled: bool

    @property
    def channel(self) -> int:
        return self.source.channel


@dataclass(frozen=True, slots=True)
class AdcExecutionPhase:
    source: AdcPhase
    slots: tuple[AdcExecutionSlot, ...]
    drives: tuple[AdcDrive, ...]


def project_adc_phase(
    phase: AdcPhase,
    io_pins: tuple[str, ...],
) -> AdcExecutionPhase:
    """Resolve bonded external channels while preserving every capture slot."""
    if not isinstance(phase, AdcPhase):
        raise TypeError("ADC.EXECUTION.PHASE_INVALID: expected AdcPhase")
    present = {str(pin).strip().casefold() for pin in io_pins if str(pin).strip()}
    slots = []
    drives: dict[str, AdcDrive] = {}
    for source in phase.slots:
        internal = source.source_kind is AdcSourceKind.INTERNAL
        bonded = source.logical_pin.casefold() in present
        force_enabled = not internal and bonded
        judge_enabled = internal or bonded
        slots.append(AdcExecutionSlot(source, force_enabled, judge_enabled))
        if not force_enabled:
            continue
        voltage = source.force_voltage
        if voltage is None:
            raise ValueError(
                f"ADC.EXECUTION.FORCE_MISSING: {phase.adc_id} CH{source.channel}"
            )
        key = source.logical_pin.casefold()
        drive = AdcDrive(source.logical_pin, float(voltage))
        previous = drives.get(key)
        if previous is not None and previous.voltage != drive.voltage:
            raise ValueError(
                f"ADC.EXECUTION.FORCE_CONFLICT: {source.logical_pin}"
            )
        drives.setdefault(key, drive)
    return AdcExecutionPhase(phase, tuple(slots), tuple(drives.values()))


__all__ = [
    "AdcDrive",
    "AdcExecutionPhase",
    "AdcExecutionSlot",
    "project_adc_phase",
]
