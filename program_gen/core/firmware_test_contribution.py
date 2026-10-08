"""Platform-neutral contribution tracer for compiled firmware tests.

This seam binds compiler-owned firmware plans to canonical schedule identities.
It declares body and Pattern dependencies without rendering tester source or
resolving Pattern bytes.
"""

from __future__ import annotations

from program_gen.core.firmware_test import (
    DownloadPhase,
    FirmwareTestPlan,
    KeilPhase,
)
from program_gen.core.schedule_plan import CanonicalSchedulePlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


class FirmwareTestContributionError(ValueError):
    """A firmware plan cannot be bound to one canonical test identity."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_firmware_test_contribution(
    plan: FirmwareTestPlan,
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
) -> ProgramContribution:
    """Declare one firmware Definition, Schedule Entry, body, and resources."""
    expected_kind = _expected_typed_kind(plan)
    if plan.typed_kind != expected_kind:
        raise FirmwareTestContributionError(
            "FWC.PLAN.TYPED_KIND_MISMATCH",
            f"phase composition requires {expected_kind}, not {plan.typed_kind!r}",
        )
    if target.cp.casefold() != plan.cp.casefold():
        raise FirmwareTestContributionError(
            "FWC.TARGET.CP_MISMATCH",
            f"firmware plan belongs to {plan.cp!r}, not target {target.cp!r}",
        )
    platform = target.platform.strip().casefold()
    if platform not in ("chroma", "s100"):
        raise FirmwareTestContributionError(
            "FWC.TARGET.PLATFORM_UNSUPPORTED",
            f"unsupported firmware target platform: {target.platform!r}",
        )
    if schedule.cp.casefold() != plan.cp.casefold():
        raise FirmwareTestContributionError(
            "FWC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {plan.cp!r}",
        )

    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == plan.excel_rows
    )
    if len(definitions) != 1:
        raise FirmwareTestContributionError(
            "FWC.DEFINITION.IDENTITY_UNRESOLVED",
            "canonical schedule contains "
            f"{len(definitions)} definitions matching {plan.cp}/{plan.item} "
            f"and source rows {plan.excel_rows}",
        )
    definition = definitions[0]
    entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition.identity.casefold()
    )
    if len(entries) != 1:
        raise FirmwareTestContributionError(
            "FWC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(entries)} entries for "
            f"definition {definition.identity!r}",
        )
    entry = entries[0]
    ordinal = next(
        index
        for index, candidate in enumerate(schedule.entries)
        if candidate.identity.casefold() == entry.identity.casefold()
    )
    identity = f"firmware-test:{target.identity}:{definition.identity}"

    return ProgramContribution(
        identity=identity,
        target=target,
        definitions=(TestDefinitionContribution(
            identity=definition.identity,
            typed_kind=plan.typed_kind,
            owner_id=identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            identity=entry.identity,
            definition_identity=definition.identity,
            ordinal=ordinal,
            enabled=entry.enabled,
        ),),
        resource_requires=_download_requirements(plan, platform),
        requires=(SymbolRequirement(
            RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}"),
            "SECTION",
            None,
            "TARGET",
        ),),
    )


def _expected_typed_kind(plan: FirmwareTestPlan) -> str:
    if not plan.phases:
        raise FirmwareTestContributionError(
            "FWC.PLAN.PHASES_MISSING",
            "firmware plan must contain at least one phase",
        )
    has_download = any(isinstance(phase, DownloadPhase) for phase in plan.phases)
    has_keil = any(isinstance(phase, KeilPhase) for phase in plan.phases)
    if any(
        not isinstance(phase, (DownloadPhase, KeilPhase))
        for phase in plan.phases
    ):
        raise FirmwareTestContributionError(
            "FWC.PLAN.PHASE_UNSUPPORTED",
            "firmware plan contains an unsupported phase type",
        )
    if has_download and has_keil:
        return "FIRMWARE_FUNCTION_TEST"
    if has_download:
        return "CODE_DOWNLOAD"
    return "FIRMWARE_RUN_TEST"


def _download_requirements(
    plan: FirmwareTestPlan,
    platform: str,
) -> tuple[ResourceRequirement, ...]:
    patterns = tuple(dict.fromkeys(
        phase.pattern
        for phase in plan.phases
        if isinstance(phase, DownloadPhase)
    ))
    identities: dict[str, object] = {}
    for pattern in patterns:
        previous = identities.setdefault(pattern.logical_identity, pattern)
        if previous != pattern:
            raise FirmwareTestContributionError(
                "FWC.RESOURCE.IDENTITY_CONFLICT",
                f"logical Pattern {pattern.logical_identity!r} has conflicting facts",
            )
    if platform == "chroma":
        path = lambda name: f"pat/{name}.pat"
    else:
        path = lambda name: f"{name}.sd"
    return tuple(
        ResourceRequirement(
            logical_identity=pattern.logical_identity,
            relative_path=path(pattern.name),
            spec_identity=f"v13.pattern/1:{platform}:{pattern.name}",
            purpose="Firmware download pattern",
        )
        for pattern in patterns
    )


__all__ = [
    "FirmwareTestContributionError",
    "compile_firmware_test_contribution",
]
