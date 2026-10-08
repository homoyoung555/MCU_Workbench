"""STANDARD_TRIM gap: platform file-level naming facts only.

``TargetPlatformProfile`` carries ONLY file-level naming facts (pattern
prefix/extension, program extension, section order).  It is the input
scaffold for the missing-domain-model declaration; it contains no business
facts, no skeleton, no tester text, and no projection.  Plain frozen
dataclass graph; no DataFrame, workbook, or global state.
"""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.render_plan import TargetKey


class ProfileError(ValueError):
    """A platform profile is incomplete or used for the wrong target."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class TargetPlatformProfile:
    """One platform's file-level naming facts (no pandas, no skeleton)."""

    platform: str
    pattern_prefix: str
    pattern_extension: str
    program_extension: str
    section_order: tuple[str, ...]

    def __post_init__(self) -> None:
        platform = str(self.platform).strip().casefold()
        if platform not in ("chroma", "s100"):
            raise ProfileError(
                "PR.PLATFORM.UNSUPPORTED",
                f"unsupported shadow-slice platform {self.platform!r}",
            )
        if not self.pattern_extension.startswith("."):
            raise ProfileError(
                "PR.PATTERN.EXTENSION",
                f"pattern extension must start with '.': {self.pattern_extension!r}",
            )
        if not self.program_extension.startswith("."):
            raise ProfileError(
                "PR.PROGRAM.EXTENSION",
                f"program extension must start with '.': {self.program_extension!r}",
            )
        if not self.section_order:
            raise ProfileError(
                "PR.SECTION.EMPTY",
                "platform profile requires a non-empty section order",
            )

    def require_target(self, target: TargetKey) -> None:
        if str(target.platform).strip().casefold() != self.platform:
            raise ProfileError(
                "PR.TARGET.PLATFORM_MISMATCH",
                f"profile for {self.platform!r} cannot project target "
                f"{target.platform!r}",
            )

    def pattern_path(self, name: str) -> str:
        name = str(name).strip()
        if not name:
            raise ProfileError("PR.PATTERN.EMPTY", "pattern name cannot be empty")
        return f"{self.pattern_prefix}{name}{self.pattern_extension}"

    def program_path(self, program_name: str) -> str:
        name = str(program_name).strip()
        if not name:
            raise ProfileError("PR.PROGRAM.EMPTY", "program name cannot be empty")
        return f"{name}{self.program_extension}"


CHROMA_PROFILE = TargetPlatformProfile(
    platform="chroma",
    pattern_prefix="pat/",
    pattern_extension=".pat",
    program_extension=".pln",
    section_order=("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW"),
)

S100_PROFILE = TargetPlatformProfile(
    platform="s100",
    pattern_prefix="",
    pattern_extension=".sd",
    program_extension=".prg",
    section_order=("HEADER", "GLOBALS", "TESTS", "FLOW"),
)

PROFILES = {
    "chroma": CHROMA_PROFILE,
    "s100": S100_PROFILE,
}


def profile_for(platform: str) -> TargetPlatformProfile:
    key = str(platform).strip().casefold()
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise ProfileError(
            "PR.PLATFORM.UNSUPPORTED",
            f"no shadow-slice profile for platform {platform!r}",
        ) from exc
