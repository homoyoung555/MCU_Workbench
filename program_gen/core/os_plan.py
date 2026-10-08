"""Compile typed OS FLOW operations into platform-neutral safety plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


DEFAULT_OS_RECIPE = "OS_TEST"


class OsPlanError(ValueError):
    """A typed FLOW operation cannot form an OS plan for the target platform."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class OsPlatformProfile(str, Enum):
    CHROMA = "chroma"
    S100 = "s100"


class OsSafetyAction(str, Enum):
    ORDINARY_IO = "ORDINARY_IO"
    TP = "TP"
    POWER_RAIL = "POWER_RAIL"


@dataclass(frozen=True, slots=True)
class OsPlan:
    """One OS operation, retaining FLOW identity and platform safety contract."""

    row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    platform_profile: OsPlatformProfile
    effective_recipe: str
    safety_actions: tuple[OsSafetyAction, ...]
    relay: str | None


def compile_os_plan(
    operation: FlowOperation,
    platform: str | OsPlatformProfile,
) -> OsPlan:
    """Compile one already-classified OS operation without reading workbook data."""
    if operation.typed_kind != "OS" or operation.source_type != "os":
        raise OsPlanError(
            "OS.TYPE.INVALID",
            f"FLOW row {operation.row} is not a typed OS operation",
        )
    if operation.mode != "/":
        raise OsPlanError(
            "OS.MODE.INVALID",
            f"FLOW row {operation.row} OS mode must be '/', got {operation.mode!r}",
        )

    profile = _platform_profile(platform)
    actions = (
        (OsSafetyAction.ORDINARY_IO, OsSafetyAction.TP, OsSafetyAction.POWER_RAIL)
        if profile is OsPlatformProfile.CHROMA
        else (OsSafetyAction.ORDINARY_IO, OsSafetyAction.TP)
    )
    return OsPlan(
        row=operation.row,
        cp=operation.cp,
        item=operation.item,
        provenance=operation.provenance,
        platform_profile=profile,
        effective_recipe=DEFAULT_OS_RECIPE,
        safety_actions=actions,
        relay=operation.relay,
    )


def _platform_profile(platform: str | OsPlatformProfile) -> OsPlatformProfile:
    if isinstance(platform, OsPlatformProfile):
        return platform
    try:
        return OsPlatformProfile(str(platform).strip().casefold())
    except ValueError as exc:
        raise OsPlanError(
            "OS.PLATFORM.UNKNOWN",
            f"unsupported OS platform {platform!r}",
        ) from exc
