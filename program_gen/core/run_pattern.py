"""Platform-neutral plan for the global RUN Pattern Module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class RunPatternCompileError(ValueError):
    """A RUN plan cannot be proven valid from its compiled Pattern facts."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PatternSpanKind(str, Enum):
    FULL = "FULL"
    SEGMENT = "SEGMENT"


@dataclass(frozen=True, slots=True)
class PatternResourceRef:
    name: str
    logical_identity: str
    ordered_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise RunPatternCompileError(
                "RUN.PATTERN.NAME_INVALID",
                f"invalid Pattern tester symbol {self.name!r}",
            )
        logical_identity = str(self.logical_identity).strip()
        if not logical_identity:
            raise RunPatternCompileError(
                "RUN.PATTERN.IDENTITY_MISSING",
                f"pattern {name!r} requires a stable logical identity",
            )
        labels = tuple(str(label).strip() for label in self.ordered_labels)
        invalid_label = next(
            (
                label
                for label in labels
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label)
            ),
            None,
        )
        if invalid_label is not None:
            raise RunPatternCompileError(
                "RUN.PATTERN.LABEL_INVALID",
                f"pattern {name!r} has invalid label {invalid_label!r}",
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "logical_identity", logical_identity)
        object.__setattr__(self, "ordered_labels", labels)


@dataclass(frozen=True, slots=True)
class PatternSpan:
    kind: PatternSpanKind
    start_label: str
    end_label: str

    def __post_init__(self) -> None:
        kind = PatternSpanKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is PatternSpanKind.FULL and (
            self.start_label,
            self.end_label,
        ) != ("START", "END"):
            raise RunPatternCompileError(
                "RUN.SPAN.FULL_INVALID",
                "FULL Pattern span must be START to END",
            )

    @classmethod
    def full(cls) -> "PatternSpan":
        return cls(PatternSpanKind.FULL, "START", "END")

    @classmethod
    def segment(cls, start_label: str, end_label: str) -> "PatternSpan":
        return cls(PatternSpanKind.SEGMENT, start_label, end_label)


@dataclass(frozen=True, slots=True)
class RunPatternPlan:
    pattern: PatternResourceRef
    span: PatternSpan
    timing_profile: str

    def __post_init__(self) -> None:
        timing_profile = str(self.timing_profile).strip()
        if not timing_profile:
            raise RunPatternCompileError(
                "RUN.EXECUTION.TIMING_MISSING",
                f"pattern {self.pattern.name!r} requires an upstream timing profile",
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", timing_profile):
            raise RunPatternCompileError(
                "RUN.EXECUTION.TIMING_INVALID",
                f"invalid timing profile symbol {self.timing_profile!r}",
            )
        object.__setattr__(self, "timing_profile", timing_profile)
        labels = self.pattern.ordered_labels
        missing = tuple(
            label
            for label in (self.span.start_label, self.span.end_label)
            if label not in labels
        )
        if missing:
            raise RunPatternCompileError(
                "RUN.SPAN.LABEL_MISSING",
                f"pattern {self.pattern.name!r} does not declare label {missing[0]!r}",
            )
        if labels.index(self.span.start_label) >= labels.index(self.span.end_label):
            raise RunPatternCompileError(
                "RUN.SPAN.ORDER_INVALID",
                f"pattern {self.pattern.name!r} span must follow its declared label order",
            )


__all__ = [
    "PatternResourceRef",
    "PatternSpan",
    "PatternSpanKind",
    "RunPatternCompileError",
    "RunPatternPlan",
]
