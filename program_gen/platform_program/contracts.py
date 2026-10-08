"""Platform-neutral input contract for one complete native program package."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.render_plan import ProgramContribution, TargetKey
from program_gen.skeleton import SkeletonBody


@dataclass(frozen=True, slots=True)
class ProgramAssemblyInput:
    """Everything the generic platform-program Module needs to assemble.

    Callers compile business semantics before crossing this seam.  In
    particular, this contract deliberately contains neither a workbook nor a
    typed-kind-specific plan such as ``TrimSpec``.
    """

    target: TargetKey
    platform_facts: object
    canonical_schedule: object
    contributions: tuple[ProgramContribution, ...]
    bodies: tuple[SkeletonBody, ...]
    runtime_declarations: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "contributions", tuple(self.contributions))
        object.__setattr__(self, "bodies", tuple(self.bodies))


__all__ = ["ProgramAssemblyInput"]
