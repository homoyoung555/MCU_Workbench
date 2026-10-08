"""Compile one ordinary trim into pure render dependency contracts.

The compiler consumes the already typed ``TrimSpec`` and canonical schedule.
It neither renders tester source nor resolves pattern bytes.

Single resource ownership: the canonical Recipe (``TrimSpec.protocol`` /
``operations`` / ``dac``) declares pattern identities, the CP resource closure
owns them, and this projection only references closure-owned identities.  The
FBIST protocol patterns (``enter_fbist_mode`` / ``exit_fbist_mode``) come from
the typed ``TrimSpec.protocol`` — never from item names, legacy writers,
Golden output, platform extensions, or historical defaults.
"""

from __future__ import annotations

import re
from typing import Sequence

from program_gen.core.schedule_plan import CanonicalSchedulePlan
from program_gen.core.trim_spec import TrimSpec
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


class StandardTrimContributionError(ValueError):
    """The typed trim cannot be projected onto the requested target."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_standard_trim_contribution(
    spec: TrimSpec,
    target: TargetKey,
    schedule: CanonicalSchedulePlan,
    *,
    resource_closure: Sequence[str],
) -> ProgramContribution:
    """Project one standard trim while preserving canonical identities.

    ``resource_closure`` is the CP resource closure (``CpProgramPlan.resources``
    identities, platform-neutral logical pattern names).  Every pattern this
    recipe declares must be owned by that closure; a Recipe-declared resource
    the closure does not own blocks with ``SC.RESOURCE.CLOSURE_MISSING``.
    """
    item_key = re.sub(r"[^a-z0-9]+", "_", spec.item.casefold()).strip("_")
    if item_key in ("pdr_trim", "bor_trim"):
        raise StandardTrimContributionError(
            "SC.SPEC.DEDICATED_TRIM",
            f"{spec.item!r} requires a dedicated trim protocol",
        )
    if target.cp.casefold() != spec.cp.casefold():
        raise StandardTrimContributionError(
            "SC.TARGET.CP_MISMATCH",
            f"trim spec belongs to {spec.cp!r}, not target {target.cp!r}",
        )
    if schedule.cp.casefold() != spec.cp.casefold():
        raise StandardTrimContributionError(
            "SC.SCHEDULE.CP_MISMATCH",
            f"canonical schedule belongs to {schedule.cp!r}, not {spec.cp!r}",
        )
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == spec.cp.casefold()
        and definition.item.casefold() == spec.item.casefold()
        and definition.source_rows == (spec.flow_row_index + 2,)
    )
    if len(definitions) != 1:
        raise StandardTrimContributionError(
            "SC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} matching definitions",
        )
    definition = definitions[0]
    entries = tuple(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition.identity.casefold()
    )
    entry_ordinals = {
        entry.identity.casefold(): ordinal
        for ordinal, entry in enumerate(schedule.entries)
    }
    expected_variants = tuple(variant.kind for variant in spec.search.variants)
    actual_variants = tuple(entry.variant for entry in entries)
    actual_orders = tuple(entry.variant_order for entry in entries)
    if (
        actual_variants != expected_variants
        or actual_orders != tuple(range(len(expected_variants)))
    ):
        raise StandardTrimContributionError(
            "SC.SCHEDULE.VARIANTS",
            f"canonical variants {actual_variants!r} do not match {expected_variants!r}",
        )
    platform = target.platform.casefold()
    if platform == "s100":
        pattern_prefix, pattern_extension = "", ".sd"
    elif platform == "chroma":
        pattern_prefix, pattern_extension = "pat/", ".pat"
    else:
        raise StandardTrimContributionError(
            "SC.TARGET.PLATFORM",
            f"unsupported STANDARD_TRIM target platform: {target.platform!r}",
        )
    identity = f"standard-trim:{target.identity}:{definition.identity}"
    body_requirements = tuple(
        SymbolRequirement(
            RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}"),
            "SECTION",
            None,
            "TARGET",
        )
        for entry in entries
    )
    pattern_names = standard_trim_pattern_names(spec)
    _validate_resource_closure(spec.item, pattern_names, resource_closure)
    return ProgramContribution(
        identity=identity,
        target=target,
        definitions=(TestDefinitionContribution(
            definition.identity,
            "STANDARD_TRIM",
            identity,
        ),),
        schedule_entries=tuple(
            ScheduleEntryContribution(
                entry.identity,
                definition.identity,
                entry_ordinals[entry.identity.casefold()],
                entry.enabled,
            )
            for entry in entries
        ),
        provides=(
            SymbolProvision(
                RenderSymbolRef("RESULT", spec.dac_final_symbol),
                spec.dac_final_symbol,
                "INT",
                spec.dac.field_width,
                "SITE",
            ),
            *((SymbolProvision(
                RenderSymbolRef("RESULT", spec.dac_export_symbol),
                spec.dac_export_symbol,
                "INT",
                spec.dac.field_width,
                "SITE",
            ),) if spec.dac_export_symbol else ()),
        ),
        requires=(
            SymbolRequirement(
                RenderSymbolRef("HELPER", spec.dac.helper_name),
                "CALLABLE",
                None,
                "TARGET",
            ),
            *body_requirements,
        ),
        resource_requires=tuple(
            ResourceRequirement(
                logical_identity=f"pattern:{name}",
                relative_path=f"{pattern_prefix}{name}{pattern_extension}",
                spec_identity=f"v13.pattern/1:{platform}:{name}",
                purpose="STANDARD_TRIM pattern",
            )
            for name in pattern_names
        ),
    )


def standard_trim_pattern_names(spec: TrimSpec) -> tuple[str, ...]:
    """The canonical pattern identities one STANDARD_TRIM recipe declares.

    Reads only typed Recipe fields: the FBIST protocol enter/exit patterns,
    ordered operation references, and the DAC pattern.  No item-name
    derivation, no platform extensions, no Golden, no defaults.
    """
    names: list[str] = []
    seen: set[str] = set()
    operations = (*spec.operations, *spec.search.per_point_actions)
    for value in (
        spec.protocol.enter_pattern,
        *(operation.reference for operation in operations),
        spec.dac.pattern_name,
        spec.protocol.exit_pattern,
    ):
        name = "" if value is None else str(value).strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return tuple(names)


def _validate_resource_closure(
    item: str,
    pattern_names: Sequence[str],
    resource_closure: Sequence[str],
) -> None:
    """Block when a Recipe-declared pattern is not owned by the CP closure.

    The closure is the single ownership authority: every pattern the canonical
    Recipe declares (including the FBIST protocol enter/exit patterns) must be
    present in ``CpProgramPlan.resources``.  A missing identity means a Recipe
    resource declaration was dropped and the projection must not continue.
    """
    owned = {str(name).strip().casefold() for name in resource_closure if name}
    missing = [name for name in pattern_names if name.casefold() not in owned]
    if missing:
        raise StandardTrimContributionError(
            "SC.RESOURCE.CLOSURE_MISSING",
            f"STANDARD_TRIM {item!r} requires recipe-owned pattern(s) "
            f"{', '.join(missing)} that the CP resource closure does not own",
        )
