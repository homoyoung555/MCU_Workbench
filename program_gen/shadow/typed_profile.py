"""STANDARD_TRIM remaining full-artifact gap declaration.

This module is NOT a typed profile and provides NO projection.  It declares
which STANDARD_TRIM domain models are MISSING and blocks any attempt to
project, assemble, register, or render STANDARD_TRIM through them.

The function-block contracts and the structural ``SkeletonProducer`` exist.
The remaining gaps are the authoritative facts needed by concrete Chroma/S100
skeleton syntax and complete project resources; this module still provides no
projection.

Constraints honored here:
- no workbook / G / Golden / legacy-writer / filesystem access
- no directory scanning, no manifest back-inference
- no default values, no guessing rules from item names
- no ``ProgramContribution``, ``SectionFragment``, TEST_BODY, HELPER,
  resources, or tester text are ever produced
"""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.render_plan import TargetKey
from program_gen.shadow.profile import TargetPlatformProfile


class StandardTrimGapError(ValueError):
    """A STANDARD_TRIM request is blocked because domain models are missing."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


# The domain models STANDARD_TRIM still needs.  Each entry is the name of a
# type that does NOT exist yet; nothing here fabricates them.
MISSING_DOMAIN_MODELS = (
    "PlatformLifecycleFacts",
    "PlatformElectricalFacts",
    "PlatformProjectResources",
)


@dataclass(frozen=True, slots=True)
class StandardTrimGap:
    """One platform's STANDARD_TRIM gap declaration (no business facts).

    This is a scaffold, not a profile: it carries only file-level naming
    facts lifted from a target profile and explicitly declares that every
    STANDARD_TRIM domain model is missing for this platform.
    """

    platform: str
    pattern_prefix: str
    pattern_extension: str
    program_extension: str
    section_order: tuple[str, ...]
    missing_domain_models: tuple[str, ...] = MISSING_DOMAIN_MODELS

    @classmethod
    def from_target_profile(
        cls, profile: TargetPlatformProfile
    ) -> "StandardTrimGap":
        """Lift file-level naming facts; domain models remain missing."""
        return cls(
            platform=profile.platform,
            pattern_prefix=profile.pattern_prefix,
            pattern_extension=profile.pattern_extension,
            program_extension=profile.program_extension,
            section_order=profile.section_order,
        )

    def require_target(self, target: TargetKey) -> None:
        if str(target.platform).strip().casefold() != self.platform:
            raise StandardTrimGapError(
                "SG.TARGET.PLATFORM_MISMATCH",
                f"gap declared for {self.platform!r} cannot serve target "
                f"{target.platform!r}",
            )

    def require_projection_available(self) -> None:
        """Block any projection: every STANDARD_TRIM domain model is missing."""
        raise StandardTrimGapError(
            "SG.PROJECTION.UNAVAILABLE",
            f"STANDARD_TRIM projection is unavailable for {self.platform!r}: "
            f"missing domain models {', '.join(self.missing_domain_models)}",
        )

    def pattern_path(self, name: str) -> str:
        """Return the file-level pattern naming fact only (no tester text)."""
        name = str(name).strip()
        if not name:
            raise StandardTrimGapError(
                "SG.PATTERN.EMPTY", "pattern name cannot be empty"
            )
        return f"{self.pattern_prefix}{name}{self.pattern_extension}"


def gap_for(platform: str) -> StandardTrimGap:
    """Return the STANDARD_TRIM gap scaffold for a platform.

    This is a gap declaration only: it lists the missing domain models and
    provides no projection, no profile, no renderer, and no tester text.
    """
    from program_gen.shadow.profile import CHROMA_PROFILE, S100_PROFILE

    key = str(platform).strip().casefold()
    if key == "chroma":
        return StandardTrimGap.from_target_profile(CHROMA_PROFILE)
    if key == "s100":
        return StandardTrimGap.from_target_profile(S100_PROFILE)
    raise StandardTrimGapError(
        "SG.PLATFORM.UNSUPPORTED",
        f"no STANDARD_TRIM gap scaffold for platform {platform!r}",
    )
