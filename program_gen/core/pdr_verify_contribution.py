"""Project a typed PDR_VERIFY plan into pure render-graph contracts.

This layer reuses canonical schedule identities and plan-owned resource
identities.  It does not render tester source or resolve resource bytes.
"""

from __future__ import annotations

from program_gen.core.pdr_verify import PdrVerifyPlan
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


class PdrVerifyContributionError(ValueError):
    """A PDR_VERIFY plan cannot be closed to its canonical target."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_pdr_verify_contribution(
    plan: PdrVerifyPlan,
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
) -> ProgramContribution:
    """Declare one PDR_VERIFY definition, schedule, and dependency closure."""
    platform = target.platform.casefold()
    if platform not in {"chroma", "s100"}:
        raise PdrVerifyContributionError(
            "PVC.TARGET.PLATFORM",
            f"unsupported PDR_VERIFY target platform {target.platform!r}",
        )
    if plan.typed_kind != "PDR_VERIFY" or plan.item.casefold() != "pdr_verify":
        raise PdrVerifyContributionError(
            "PVC.PLAN.UNSUPPORTED",
            f"plan {plan.item!r} is not the registered PDR_VERIFY protocol",
        )
    if target.cp.casefold() != plan.cp.casefold():
        raise PdrVerifyContributionError(
            "PVC.TARGET.CP_MISMATCH",
            f"PDR_VERIFY plan belongs to {plan.cp!r}, not {target.cp!r}",
        )
    if target.platform.casefold() != plan.platform.value.casefold():
        raise PdrVerifyContributionError(
            "PVC.TARGET.PROFILE_MISMATCH",
            f"plan profile {plan.platform.value!r} does not match target "
            f"{target.platform!r}",
        )
    if schedule.cp.casefold() != plan.cp.casefold():
        raise PdrVerifyContributionError(
            "PVC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {plan.cp!r}",
        )
    resource_identities = tuple(
        resource.logical_identity for resource in plan.pattern_resources
    )
    if any(not identity.strip() for identity in resource_identities):
        raise PdrVerifyContributionError(
            "PVC.RESOURCE.IDENTITY_MISSING",
            "every PDR_VERIFY pattern requires a plan-owned logical identity",
        )
    if len({identity.casefold() for identity in resource_identities}) != len(
        resource_identities
    ):
        raise PdrVerifyContributionError(
            "PVC.RESOURCE.IDENTITY_CONFLICT",
            "PDR_VERIFY pattern logical identities must be unique",
        )
    result_identities = tuple(
        check.status_pattern_identity for check in plan.status_checks
    )
    if (
        not result_identities
        or any(not identity.strip() for identity in result_identities)
        or len({identity.casefold() for identity in result_identities}) != 1
    ):
        raise PdrVerifyContributionError(
            "PVC.RESULT.IDENTITY_CONFLICT",
            "all PDR_VERIFY status checks must consume one result identity",
        )
    if result_identities[0].casefold() not in {
        identity.casefold() for identity in resource_identities
    }:
        raise PdrVerifyContributionError(
            "PVC.RESULT.IDENTITY_CONFLICT",
            "PDR_VERIFY result identity must name a declared pattern resource",
        )
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == (plan.excel_row,)
    )
    if len(definitions) != 1:
        raise PdrVerifyContributionError(
            "PVC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} PDR_VERIFY definitions",
        )
    definition = definitions[0]
    entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition.identity.casefold()
    )
    if len(entries) != 1:
        raise PdrVerifyContributionError(
            "PVC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(entries)} PDR_VERIFY entries",
        )
    entry = entries[0]
    ordinal = next(
        index
        for index, candidate in enumerate(schedule.entries)
        if candidate.identity.casefold() == entry.identity.casefold()
    )
    if platform == "chroma":
        prefix, extension, result_type = "pat/", ".pat", "PASS_FAIL"
    else:
        prefix, extension, result_type = "", ".sd", "FLOAT"
    identity = f"pdr-verify:{target.identity}:{definition.identity}"
    status_identity = result_identities[0]
    return ProgramContribution(
        identity=identity,
        target=target,
        definitions=(TestDefinitionContribution(
            definition.identity,
            "PDR_VERIFY",
            identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            entry.identity,
            definition.identity,
            ordinal,
            entry.enabled,
        ),),
        requires=(
            SymbolRequirement(
                RenderSymbolRef("RESULT", f"{platform}:{status_identity}"),
                result_type,
                None,
                "SITE",
            ),
            SymbolRequirement(
                RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}"),
                "SECTION",
                None,
                "TARGET",
            ),
        ),
        resource_requires=tuple(
            ResourceRequirement(
                resource.logical_identity,
                f"{prefix}{resource.name}{extension}",
                f"v13.pattern/1:{platform}:{resource.name}",
                f"PDR_VERIFY {resource.role} pattern",
            )
            for resource in plan.pattern_resources
        ),
    )
