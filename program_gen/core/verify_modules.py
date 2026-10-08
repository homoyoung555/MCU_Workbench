"""Shared ENTER and JUDGE Recipe Module plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from program_gen.core.run_pattern import PatternResourceRef, RunPatternPlan


class VerifyModulePlanError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class JudgeMeasurementKind(str, Enum):
    FREQUENCY = "FREQUENCY"
    VOLTAGE = "VOLTAGE"
    CURRENT = "CURRENT"


class PeWindowKind(str, Enum):
    ERASE = "ERASE"
    PROGRAM = "PROGRAM"


@dataclass(frozen=True, slots=True)
class JudgePeWindowPlan:
    kind: PeWindowKind
    before: RunPatternPlan
    after: RunPatternPlan

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PeWindowKind):
            raise VerifyModulePlanError(
                "VM.JUDGE.PE_KIND_INVALID", "JUDGE PE window kind is invalid"
            )
        if not isinstance(self.before, RunPatternPlan) or not isinstance(
            self.after, RunPatternPlan
        ):
            raise VerifyModulePlanError(
                "VM.JUDGE.PE_RUN_INVALID", "JUDGE PE window requires RUN plans"
            )
        if (
            self.before.pattern != self.after.pattern
            or (
                self.before.span.start_label,
                self.before.span.end_label,
                self.after.span.start_label,
                self.after.span.end_label,
            ) != ("START", "pe_1", "pe_1", "END")
            or self.before.timing_profile != self.after.timing_profile
        ):
            raise VerifyModulePlanError(
                "VM.JUDGE.PE_WINDOW_INVALID",
                "JUDGE PE runs must share one Pattern and the pe_1 boundary",
            )


@dataclass(frozen=True, slots=True)
class EnterPlan:
    pattern: PatternResourceRef
    timing_profile: str = "TS_5MHZ"

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, PatternResourceRef):
            raise VerifyModulePlanError(
                "VM.ENTER.PATTERN_INVALID", "ENTER requires PatternResourceRef"
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.timing_profile):
            raise VerifyModulePlanError(
                "VM.ENTER.TIMING_INVALID", "ENTER timing profile is unsafe"
            )


@dataclass(frozen=True, slots=True)
class JudgeMeasurementPlan:
    kind: JudgeMeasurementKind
    pin: str
    force: str
    low_limit: float
    high_limit: float
    unit: str
    gate: str
    settle: str
    alias: str
    limit_source: str = "FLOW"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, JudgeMeasurementKind):
            raise VerifyModulePlanError(
                "VM.JUDGE.KIND_INVALID", "JUDGE measurement kind is invalid"
            )
        for field in ("pin", "unit", "settle", "alias", "limit_source"):
            if not str(getattr(self, field)).strip():
                raise VerifyModulePlanError(
                    "VM.JUDGE.FACT_MISSING", f"JUDGE {field} is empty"
                )
        if float(self.low_limit) > float(self.high_limit):
            raise VerifyModulePlanError(
                "VM.JUDGE.LIMIT_ORDER", "JUDGE low limit exceeds high limit"
            )

    @property
    def requires_zero_reset(self) -> bool:
        if self.kind is JudgeMeasurementKind.FREQUENCY:
            return False
        unit = "V" if self.kind is JudgeMeasurementKind.CURRENT else "uA"
        text = str(self.force).strip()
        if not text.casefold().endswith(unit.casefold()):
            return True
        try:
            return float(text[:-len(unit)].strip()) != 0
        except ValueError:
            return True


@dataclass(frozen=True, slots=True)
class JudgeDacFinalPlan:
    symbol: str
    max_code: int
    alias: str

    def __post_init__(self) -> None:
        if not str(self.symbol).strip() or not str(self.alias).strip():
            raise VerifyModulePlanError(
                "VM.JUDGE.DAC_FACT_MISSING", "JUDGE DAC final facts are empty"
            )
        if int(self.max_code) < 0:
            raise VerifyModulePlanError(
                "VM.JUDGE.DAC_RANGE", "JUDGE DAC max code is negative"
            )


@dataclass(frozen=True, slots=True)
class JudgePlan:
    item: str
    measurement: JudgeMeasurementPlan
    dac_final: JudgeDacFinalPlan | None = None
    pe_window: JudgePeWindowPlan | None = None

    def __post_init__(self) -> None:
        if not str(self.item).strip():
            raise VerifyModulePlanError(
                "VM.JUDGE.ITEM_MISSING", "JUDGE item is empty"
            )
        if not isinstance(self.measurement, JudgeMeasurementPlan):
            raise VerifyModulePlanError(
                "VM.JUDGE.MEASUREMENT_INVALID", "JUDGE measurement plan is invalid"
            )
        if self.dac_final is not None and not isinstance(
            self.dac_final, JudgeDacFinalPlan
        ):
            raise VerifyModulePlanError(
                "VM.JUDGE.DAC_INVALID", "JUDGE DAC final plan is invalid"
            )
        if self.pe_window is not None and not isinstance(
            self.pe_window, JudgePeWindowPlan
        ):
            raise VerifyModulePlanError(
                "VM.JUDGE.PE_INVALID", "JUDGE PE window plan is invalid"
            )


__all__ = [
    "EnterPlan",
    "JudgeDacFinalPlan",
    "JudgeMeasurementKind",
    "JudgeMeasurementPlan",
    "JudgePeWindowPlan",
    "JudgePlan",
    "PeWindowKind",
    "VerifyModulePlanError",
]
