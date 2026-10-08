"""Stable, platform-neutral diagnostics produced by ProductCompiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ERROR = "ERROR"
WARN = "WARN"
ENFORCED = "ENFORCED"
SHADOW = "SHADOW"


@dataclass(frozen=True, slots=True)
class WorkbookProvenance:
    sheet: str
    coordinate: str = ""
    workbook_identity: str = ""
    source_sha256: str = ""

    @property
    def location(self) -> str:
        return f"{self.sheet}!{self.coordinate}" if self.coordinate else self.sheet


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    provenance: WorkbookProvenance
    remediation: str
    source: str = "PRODUCT_COMPILER"
    category: str = "Compiler"
    enforcement: str = ENFORCED

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip().upper():
            raise ValueError("diagnostic code must be a non-empty uppercase token")
        if self.severity not in (ERROR, WARN):
            raise ValueError(f"unsupported diagnostic severity: {self.severity!r}")
        if self.enforcement not in (ENFORCED, SHADOW):
            raise ValueError(f"unsupported diagnostic enforcement: {self.enforcement!r}")
        if not self.remediation.strip():
            raise ValueError("diagnostic remediation must be non-empty")


@dataclass(frozen=True, slots=True)
class Diagnostics:
    items: tuple[Diagnostic, ...] = ()

    @classmethod
    def from_iterable(cls, items: Iterable[Diagnostic]) -> "Diagnostics":
        return cls(tuple(items))

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.items if item.severity == ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.items if item.severity == WARN)

    @property
    def blocking_errors(self) -> tuple[Diagnostic, ...]:
        return tuple(
            item for item in self.items
            if item.severity == ERROR and item.enforcement == ENFORCED
        )

    @property
    def shadow(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.items if item.enforcement == SHADOW)

    @property
    def is_valid(self) -> bool:
        return not self.blocking_errors
