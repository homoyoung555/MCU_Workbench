"""Platform-neutral plan for the shared EXPORT Recipe Module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class ResultExportFormat(str, Enum):
    RAW = "RAW"
    BCD16_MV = "BCD16_MV"
    ADC12_3V3 = "ADC12_3V3"


@dataclass(frozen=True, slots=True)
class ResultExportModulePlan:
    semantic_identity: str
    symbol: str
    source_judge_ordinal: int
    source_pin: str
    format: ResultExportFormat
    c_type: str

    def __post_init__(self) -> None:
        if not str(self.semantic_identity).strip():
            raise ValueError("EXPORT.IDENTITY.MISSING")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(self.symbol)):
            raise ValueError("EXPORT.SYMBOL.INVALID")
        if int(self.source_judge_ordinal) < 1:
            raise ValueError("EXPORT.JUDGE.INVALID")
        if not str(self.source_pin).strip():
            raise ValueError("EXPORT.SOURCE_PIN.MISSING")
        object.__setattr__(self, "format", ResultExportFormat(self.format))
        expected_type = "double" if self.format is ResultExportFormat.RAW else "int"
        if str(self.c_type).strip().casefold() != expected_type:
            raise ValueError("EXPORT.TYPE.MISMATCH")

    @property
    def value_type(self) -> str:
        return self.c_type.upper()

    @property
    def bit_width(self) -> int | None:
        if self.format is ResultExportFormat.BCD16_MV:
            return 16
        if self.format is ResultExportFormat.ADC12_3V3:
            return 12
        return None


__all__ = ["ResultExportFormat", "ResultExportModulePlan"]
