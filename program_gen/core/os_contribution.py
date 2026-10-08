"""Compile an OS plan into render-graph metadata and contracts.

This is deliberately a pure bridge: it consumes the already-compiled OS plan
and the canonical schedule owned by ``CpProgramPlan``.  It neither renders a
tester body nor discovers pins, relays, power rails, or workbook data.  Those
target-owned facilities are explicit symbol requirements for a renderer-side
provider to close.
"""

from __future__ import annotations

from program_gen.core.os_plan import (
    DEFAULT_OS_RECIPE,
    OsPlan,
    OsPlatformProfile,
    OsSafetyAction,
)
from program_gen.program_plan import CpProgramPlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


class OsContributionError(ValueError):
    """An OS plan cannot be closed to the target's canonical schedule."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


_PROFILE_ACTIONS = {
    OsPlatformProfile.CHROMA: (
        OsSafetyAction.ORDINARY_IO,
        OsSafetyAction.TP,
        OsSafetyAction.POWER_RAIL,
    ),
    OsPlatformProfile.S100: (
        OsSafetyAction.ORDINARY_IO,
        OsSafetyAction.TP,
    ),
}


def compile_os_contribution(
    plan: OsPlan,
    target: TargetKey,
    cp_plan: CpProgramPlan,
) -> ProgramContribution:
    """Return the metadata-only contribution for one typed OS operation.

    The canonical definition and schedule identities are selected, never
    reconstructed.  ``OS_ENVIRONMENT`` requirements are symbolic contracts,
    rather than ``ResourceRequirement`` instances, because RenderPlan
    resources are materializable file artifacts and this core owns no bytes or
    source identity for pin/relay/power facilities.
    """
    _validate_plan(plan)
    target_profile = _target_profile(target)
    if target_profile is not plan.platform_profile:
        raise OsContributionError(
            "OC.TARGET.PROFILE_MISMATCH",
            f"OS plan profile {plan.platform_profile.value!r} does not match "
            f"target platform {target.platform!r}",
        )
    if target.cp.casefold() != plan.cp.casefold():
        raise OsContributionError(
            "OC.TARGET.CP_MISMATCH",
            f"OS plan belongs to {plan.cp!r}, not target {target.cp!r}",
        )
    if cp_plan.cp.casefold() != plan.cp.casefold():
        raise OsContributionError(
            "OC.CP_PLAN.MISMATCH",
            f"CP plan belongs to {cp_plan.cp!r}, not OS plan {plan.cp!r}",
        )
    schedule = cp_plan.canonical_schedule
    if schedule is None:
        raise OsContributionError(
            "OC.SCHEDULE.MISSING",
            f"CP plan {cp_plan.cp!r} has no canonical schedule",
        )
    if schedule.cp.casefold() != plan.cp.casefold():
        raise OsContributionError(
            "OC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not OS plan {plan.cp!r}",
        )

    definition = _canonical_definition(schedule, plan)
    schedule_entry = _canonical_entry(schedule, definition.identity)
    schedule_ordinal = next(
        ordinal
        for ordinal, entry in enumerate(schedule.entries)
        if entry.identity.casefold() == schedule_entry.identity.casefold()
    )
    contribution_identity = f"os:{target.identity}:{definition.identity}"
    requirements = (
        SymbolRequirement(
            RenderSymbolRef(
                "TEST_BODY", f"{target_profile.value}:{schedule_entry.identity}"
            ),
            "SECTION",
            None,
            "TARGET",
        ),
        *(
            SymbolRequirement(
                RenderSymbolRef(
                    "OS_ENVIRONMENT", f"{target_profile.value}:{action.value}"
                ),
                "SAFETY_ACTION",
                None,
                "TARGET",
            )
            for action in plan.safety_actions
        ),
    )
    return ProgramContribution(
        identity=contribution_identity,
        target=target,
        definitions=(TestDefinitionContribution(
            identity=definition.identity,
            typed_kind="OS",
            owner_id=contribution_identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            identity=schedule_entry.identity,
            definition_identity=definition.identity,
            ordinal=schedule_ordinal,
            enabled=schedule_entry.enabled,
        ),),
        requires=requirements,
    )


def _validate_plan(plan: OsPlan) -> None:
    if plan.item.casefold() != "os_test":
        raise OsContributionError(
            "OC.PLAN.UNSUPPORTED",
            f"OS contribution only supports os_test, got {plan.item!r}",
        )
    if plan.effective_recipe != DEFAULT_OS_RECIPE:
        raise OsContributionError(
            "OC.PLAN.RECIPE",
            f"OS plan recipe must be {DEFAULT_OS_RECIPE!r}",
        )
    expected_actions = _PROFILE_ACTIONS.get(plan.platform_profile)
    if expected_actions is None:
        raise OsContributionError(
            "OC.PLAN.PROFILE",
            f"unsupported OS plan profile {plan.platform_profile!r}",
        )
    if plan.safety_actions != expected_actions:
        raise OsContributionError(
            "OC.PLAN.SAFETY_ACTIONS",
            f"OS plan safety actions do not match {plan.platform_profile.value!r}",
        )


def _target_profile(target: TargetKey) -> OsPlatformProfile:
    try:
        return OsPlatformProfile(target.platform.casefold())
    except ValueError as exc:
        raise OsContributionError(
            "OC.TARGET.PLATFORM",
            f"unsupported OS target platform {target.platform!r}",
        ) from exc


def _canonical_definition(schedule, plan: OsPlan):
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == (plan.row + 2,)
    )
    if len(definitions) != 1:
        raise OsContributionError(
            "OC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} OS definitions "
            f"for FLOW row {plan.row}",
        )
    return definitions[0]


def _canonical_entry(schedule, definition_identity: str):
    entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    if len(entries) != 1:
        raise OsContributionError(
            "OC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(entries)} OS entries for "
            f"definition {definition_identity!r}",
        )
    return entries[0]
