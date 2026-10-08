"""Assemble FREQ_TEST plans into native platform bodies."""

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, ScheduleEntryContribution,
    SectionFragment, SymbolRequirement, TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_freq_test_assembly(plans, context: TypedKindContext, renderer=None):
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("FREQ_TEST")
    context.compilation.require_success()
    platform = context.target.platform.casefold()
    render = renderer or _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions, bodies = [], []
    for plan in plans:
        definitions = tuple(
            definition for definition in schedule.definitions
            if definition.cp.casefold() == plan.cp.casefold()
            and definition.item.casefold() == plan.item.casefold()
            and definition.source_rows == plan.excel_rows
        )
        if len(definitions) != 1:
            raise ValueError(f"FREQ.ASSEMBLY.DEFINITION_UNRESOLVED: {len(definitions)}")
        definition = definitions[0]
        entries = tuple(
            entry for entry in schedule.entries
            if entry.definition_id.casefold() == definition.identity.casefold()
        )
        if len(entries) != 1:
            raise ValueError(f"FREQ.ASSEMBLY.SCHEDULE_UNRESOLVED: {len(entries)}")
        entry = entries[0]
        ordinal = next(
            index for index, candidate in enumerate(schedule.entries)
            if candidate.identity.casefold() == entry.identity.casefold()
        )
        owner = f"freq-test:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        rendered = render(
            plan, definition.render_name, entry.bin_binding.hardware_bin,
            context.platform_facts,
        )
        if not isinstance(rendered, FirmwareBodyRender):
            raise TypeError("FREQ renderer must return FirmwareBodyRender")
        contributions.append(ProgramContribution(
            identity=owner, target=context.target, resources=rendered.resources,
            resource_requires=rendered.resource_requires,
            definitions=(TestDefinitionContribution(definition.identity, "FREQ_TEST", owner),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled,
            ),),
            requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),),
        ))
        bodies.append(SkeletonBody(body_ref, SectionFragment(
            f"{context.target.program_name}{extension}", "TESTS", f"{owner}:body",
            rendered.content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            ordinal,
        )))
    return TypedKindAssembly("FREQ_TEST", tuple(contributions), tuple(bodies))


def _renderer_for(platform):
    if platform == "chroma":
        from program_gen.platforms.chroma.freq_test_renderer import render_freq_test
    elif platform == "s100":
        from program_gen.platforms.s100.freq_test_renderer import render_freq_test
    else:
        raise ValueError(f"FREQ.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_freq_test


__all__ = ["compile_freq_test_assembly"]
