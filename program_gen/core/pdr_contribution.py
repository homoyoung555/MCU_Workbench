"""Pure PDR Trim contribution compiler.

The module declares PDR business ownership and its closed dependencies.  It
does not render tester source or resolve resource bytes; platform adapters and
resource providers satisfy those contracts later in assembly.
"""

from __future__ import annotations

from program_gen.core.dedicated_trim import DedicatedTrimPlan
from program_gen.core.schedule_plan import CanonicalSchedulePlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolProvision,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


_PROTOCOL_PATTERN_ROLES = (
    ("enter", "enter_fbist_mode"),
    ("set", "set_all_final_vposp"),
    ("read", "read_status_mode"),
    ("exit", "exit_fbist_mode"),
)


class PdrContributionError(ValueError):
    """A plan or target does not satisfy the PDR contribution contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_pdr_contribution(
    plan: DedicatedTrimPlan,
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
) -> ProgramContribution:
    """Compile one dedicated PDR plan into metadata and dependency contracts."""
    if plan.typed_kind != "PDR_TRIM" or plan.item.casefold() != "pdr_trim":
        raise PdrContributionError(
            "PC.PLAN.UNSUPPORTED",
            f"dedicated plan {plan.item!r} is not the registered PDR_TRIM protocol",
        )
    if plan.effective_recipe != ("PDR_TRIM",):
        raise PdrContributionError(
            "PC.PLAN.RECIPE",
            "PDR_TRIM requires the frozen PDR_TRIM effective recipe",
        )
    if plan.search_variant != "PDR_STATUS_TRANSITION":
        raise PdrContributionError(
            "PC.PLAN.SEARCH",
            "PDR_TRIM requires the PDR_STATUS_TRANSITION search",
        )
    if plan.dac_bits != 4:
        raise PdrContributionError(
            "PC.PLAN.DAC_BITS",
            "PDR_TRIM requires a 4-bit DAC result",
        )
    if plan.search_codes != (
        8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7
    ):
        raise PdrContributionError(
            "PC.PLAN.SEARCH_CODES",
            "PDR_TRIM requires the frozen status-transition DAC sequence",
        )
    if plan.helper_name != "set_pdr_trim_data" or not plan.dac_pattern_name:
        raise PdrContributionError(
            "PC.PLAN.DAC_HELPER",
            "PDR_TRIM requires its typed DAC pattern/helper contract",
        )
    if target.cp.casefold() != plan.cp.casefold():
        raise PdrContributionError(
            "PC.TARGET.CP_MISMATCH",
            f"PDR plan belongs to {plan.cp!r}, not target {target.cp!r}",
        )
    if schedule.cp.casefold() != plan.cp.casefold():
        raise PdrContributionError(
            "PC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {plan.cp!r}",
        )
    matching_definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == (plan.flow_row_index + 2,)
    )
    if len(matching_definitions) != 1:
        raise PdrContributionError(
            "PC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(matching_definitions)} PDR definitions",
        )
    definition = matching_definitions[0]
    matching_entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition.identity.casefold()
    )
    if len(matching_entries) != 1:
        raise PdrContributionError(
            "PC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(matching_entries)} PDR entries",
        )
    schedule_entry = matching_entries[0]
    schedule_ordinal = next(
        ordinal
        for ordinal, entry in enumerate(schedule.entries)
        if entry.identity.casefold() == schedule_entry.identity.casefold()
    )
    platform = target.platform.casefold()
    if platform == "s100":
        pattern_prefix, pattern_extension = "", ".sd"
    elif platform == "chroma":
        pattern_prefix, pattern_extension = "pat/", ".pat"
    else:
        raise PdrContributionError(
            "PC.TARGET.PLATFORM",
            f"unsupported PDR target platform: {target.platform!r}",
        )
    definition_identity = definition.identity
    contribution_identity = f"pdr:{target.identity}:{definition_identity}"
    pattern_roles = (
        *_PROTOCOL_PATTERN_ROLES[:2],
        ("dac", plan.dac_pattern_name),
        *_PROTOCOL_PATTERN_ROLES[2:],
    )
    resources = tuple(
        ResourceRequirement(
            logical_identity=f"pattern:{name}",
            relative_path=f"{pattern_prefix}{name}{pattern_extension}",
            spec_identity=f"v13.pattern/1:{platform}:{name}",
            purpose=f"PDR_TRIM {role} pattern",
        )
        for role, name in pattern_roles
    )
    return ProgramContribution(
        identity=contribution_identity,
        target=target,
        definitions=(TestDefinitionContribution(
            identity=definition_identity,
            typed_kind=plan.typed_kind,
            owner_id=contribution_identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            identity=schedule_entry.identity,
            definition_identity=definition_identity,
            ordinal=schedule_ordinal,
            enabled=schedule_entry.enabled,
        ),),
        resource_requires=resources,
        provides=(SymbolProvision(
            RenderSymbolRef("RESULT", "PDR_DAC_FINAL"),
            "PDR_DAC_FINAL",
            "INT",
            plan.dac_bits,
            "SITE",
        ),),
        requires=(
            SymbolRequirement(
                RenderSymbolRef("HELPER", plan.helper_name),
                "CALLABLE",
                None,
                "TARGET",
            ),
            SymbolRequirement(
                RenderSymbolRef("TEST_BODY", f"{platform}:{schedule_entry.identity}"),
                "SECTION",
                None,
                "TARGET",
            ),
        ),
    )
