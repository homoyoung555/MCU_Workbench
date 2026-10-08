"""Pure contribution compiler for the first standard CP-ID persistence slice.

The compiler consumes identities and typed operations already owned by the
product compiler.  It neither renders tester source nor resolves resource
bytes.
"""

from __future__ import annotations

from program_gen.core.otp_program import PagePatternPlan
from program_gen.core.persistence_recipe import PersistenceRowPlan
from program_gen.core.schedule_plan import CanonicalSchedulePlan
from program_gen.core.uid_plan import IdItemPlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


class PersistenceContributionError(ValueError):
    """The selected row is outside the frozen standard CP-ID slice."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_persistence_id_contribution(
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
    id_plan: IdItemPlan,
    persistence_plan: PersistenceRowPlan,
    page_patterns: tuple[PagePatternPlan, ...],
) -> ProgramContribution:
    """Compile one COMMIT -> PGMOTP standard CP-ID row into contracts."""
    if id_plan.role != "COMMIT_CLOSURE" or id_plan.target.kind != "ID":
        raise PersistenceContributionError(
            "PIC.PLAN.UNSUPPORTED",
            f"{id_plan.item!r} is not a standard CP-ID commit closure",
        )
    cp = str(persistence_plan.cp).strip().upper()
    if target.cp.strip().upper() != cp:
        raise PersistenceContributionError(
            "PIC.TARGET.CP_MISMATCH",
            f"persistence row belongs to {cp}, not {target.cp!r}",
        )
    if schedule.cp.strip().upper() != cp:
        raise PersistenceContributionError(
            "PIC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {cp}",
        )
    if tuple(operation.module for operation in persistence_plan.operations) != (
        "COMMIT",
        "PGMOTP",
    ):
        raise PersistenceContributionError(
            "PIC.RECIPE.UNSUPPORTED",
            "the first CP-ID slice requires COMMIT -> PGMOTP",
        )

    platform = target.platform.strip().casefold()
    if platform == "s100":
        pattern_prefix, pattern_extension = "", ".sd"
    elif platform == "chroma":
        pattern_prefix, pattern_extension = "pat/", ".pat"
    else:
        raise PersistenceContributionError(
            "PIC.TARGET.PLATFORM",
            f"unsupported persistence target platform: {target.platform!r}",
        )

    commit_operation, pgmotp_operation = persistence_plan.operations
    required_pages = tuple(dict.fromkeys(pgmotp_operation.effective_pages))
    patterns_by_page = {
        pattern.page.casefold(): pattern for pattern in page_patterns
    }
    if len(patterns_by_page) != len(page_patterns):
        raise PersistenceContributionError(
            "PIC.PAGE_PATTERN.DUPLICATE",
            "page pattern identities must be unique by page",
        )
    if set(patterns_by_page) != {page.casefold() for page in required_pages}:
        raise PersistenceContributionError(
            "PIC.PAGE_PATTERN.CLOSURE",
            "page pattern plans must exactly cover PGMOTP effective pages",
        )
    selected_patterns = tuple(
        patterns_by_page[page.casefold()] for page in required_pages
    )
    if any(not pattern.is_uid for pattern in selected_patterns):
        raise PersistenceContributionError(
            "PIC.PAGE_PATTERN.NOT_UID",
            "standard CP-ID PGMOTP requires explicitly typed UID patterns",
        )

    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.strip().upper() == cp
        and definition.item.casefold() == id_plan.item.casefold()
        and definition.source_rows == (persistence_plan.excel_row,)
    )
    if len(definitions) != 1:
        raise PersistenceContributionError(
            "PIC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} matching definitions",
        )
    definition = definitions[0]
    entries = tuple(
        entry for entry in schedule.entries
        if entry.definition_id == definition.identity
    )
    if len(entries) != 1:
        raise PersistenceContributionError(
            "PIC.SCHEDULE.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(entries)} matching entries",
        )
    entry = entries[0]
    entry_ordinal = next(
        ordinal
        for ordinal, candidate in enumerate(schedule.entries)
        if candidate.identity.casefold() == entry.identity.casefold()
    )
    contribution_identity = (
        f"persistence-id:{target.identity}:{definition.identity}"
    )
    symbol_widths: dict[str, int] = {}
    for write in commit_operation.field_writes:
        if write.value.kind != "VARIABLE":
            continue
        previous = symbol_widths.setdefault(write.value.token, write.width)
        if previous != write.width:
            raise PersistenceContributionError(
                "PIC.RESULT.WIDTH_CONFLICT",
                f"{write.value.token!r} is consumed with {previous} and {write.width} bits",
            )
    result_requirements = tuple(
        SymbolRequirement(
            RenderSymbolRef("RESULT", name),
            "INT",
            width,
            "SITE",
        )
        for name, width in symbol_widths.items()
    )
    helper_requirements = tuple(
        SymbolRequirement(
            RenderSymbolRef("HELPER", name),
            "CALLABLE",
            None,
            "TARGET",
        )
        for name in (
            "commit_page_image",
            "program_otp_page",
            "uid_failed_site_reerase",
        )
    )
    body_requirement = SymbolRequirement(
        RenderSymbolRef("TEST_BODY", f"{platform}:{definition.identity}"),
        "SECTION",
        None,
        "TARGET",
    )
    resource_requirements = tuple(
        ResourceRequirement(
            logical_identity=f"pattern:{name}",
            relative_path=f"{pattern_prefix}{name}{pattern_extension}",
            spec_identity=f"v13.pattern/1:{platform}:{name}",
            purpose=f"UID {role} pattern",
        )
        for pattern in selected_patterns
        for role, name in (
            ("erase", pattern.erase_pattern),
            ("program", pattern.program_pattern),
            ("read", pattern.read_pattern),
        )
    )
    return ProgramContribution(
        identity=contribution_identity,
        target=target,
        definitions=(TestDefinitionContribution(
            definition.identity,
            "UID",
            contribution_identity,
        ),),
        schedule_entries=(ScheduleEntryContribution(
            entry.identity,
            definition.identity,
            entry_ordinal,
            entry.enabled,
        ),),
        resource_requires=resource_requirements,
        requires=result_requirements + helper_requirements + (body_requirement,),
    )
