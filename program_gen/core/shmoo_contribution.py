"""Project ordinary typed Shmoo plans into pure render contracts."""

from __future__ import annotations

from program_gen.core.commit_shmoo import CommitShmooPlan
from program_gen.core.schedule_plan import CanonicalSchedulePlan
from program_gen.core.shmoo import ShmooPlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


class ShmooContributionError(ValueError):
    """An ordinary Shmoo plan cannot bind to its canonical target."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_shmoo_contribution(
    plan: ShmooPlan,
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
) -> ProgramContribution:
    """Preserve one grouped Shmoo definition and its global schedule order."""
    if isinstance(plan, CommitShmooPlan):
        raise ShmooContributionError(
            "SHC.PLAN.COMMIT_UNSUPPORTED",
            "CommitShmooPlan lacks closed page-pattern and result identities",
        )
    if not isinstance(plan, ShmooPlan):
        raise ShmooContributionError(
            "SHC.PLAN.UNSUPPORTED",
            "only ordinary ENTER/JUDGE Shmoo plans are supported",
        )
    if plan.mode.casefold() != "fbist":
        raise ShmooContributionError(
            "SHC.PLAN.MODE",
            f"ordinary Shmoo requires FBIST mode, got {plan.mode!r}",
        )
    if target.cp.casefold() != plan.cp.casefold():
        raise ShmooContributionError(
            "SHC.TARGET.CP_MISMATCH",
            f"Shmoo plan belongs to {plan.cp!r}, not target {target.cp!r}",
        )
    if schedule.cp.casefold() != plan.cp.casefold():
        raise ShmooContributionError(
            "SHC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {plan.cp!r}",
        )
    source_rows = tuple(dict.fromkeys(
        point.flow_row_index + 2 for point in plan.points
    ))
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == source_rows
    )
    if len(definitions) != 1:
        raise ShmooContributionError(
            "SHC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} matching definitions",
        )
    definition = definitions[0]
    entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition.identity.casefold()
    )
    if len(entries) != 1:
        raise ShmooContributionError(
            "SHC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(entries)} matching entries",
        )
    entry = entries[0]
    ordinal = next(
        index
        for index, candidate in enumerate(schedule.entries)
        if candidate.identity.casefold() == entry.identity.casefold()
    )
    platform = target.platform.casefold()
    if platform == "chroma":
        prefix, extension = "pat/", ".pat"
    elif platform == "s100":
        prefix, extension = "", ".sd"
    else:
        raise ShmooContributionError(
            "SHC.TARGET.PLATFORM",
            f"unsupported ordinary Shmoo target platform {target.platform!r}",
        )
    identity = f"shmoo:{target.identity}:{definition.identity}"
    pattern_roles = (
        ("ENTER", "enter_fbist_mode"),
        ("STEP", plan.pattern_name),
        ("EXIT", "exit_fbist_mode"),
    )
    return ProgramContribution(
        identity=identity,
        target=target,
        definitions=(TestDefinitionContribution(
            definition.identity,
            "SHMOO",
            identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            entry.identity,
            definition.identity,
            ordinal,
            entry.enabled,
        ),),
        requires=(
            *(
                SymbolRequirement(
                    RenderSymbolRef(
                        "RESULT", f"{platform}:{point.log_name}"
                    ),
                    "FLOAT",
                    None,
                    "SITE",
                )
                for point in plan.points
            ),
            SymbolRequirement(
                RenderSymbolRef(
                    "HELPER", f"set_{plan.pattern_name}_data"
                ),
                "CALLABLE",
                None,
                "TARGET",
            ),
            SymbolRequirement(
                RenderSymbolRef(
                    "TEST_BODY", f"{platform}:{definition.identity}"
                ),
                "SECTION",
                None,
                "TARGET",
            ),
        ),
        resource_requires=tuple(
            ResourceRequirement(
                f"pattern:{name}",
                f"{prefix}{name}{extension}",
                f"v13.pattern/1:{platform}:{name}",
                f"SHMOO {role} pattern",
            )
            for role, name in pattern_roles
        ),
    )
