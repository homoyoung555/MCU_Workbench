"""Assemble DAC_TEST plans into native platform bodies."""

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.render_plan import ProgramContribution, RenderSymbolRef, ScheduleEntryContribution, SectionFragment, SymbolRequirement, TestDefinitionContribution
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_dac_test_assembly(plans, context: TypedKindContext, renderer=None):
    plans = tuple(plans)
    if not plans: return TypedKindAssembly("DAC_TEST")
    context.compilation.require_success()
    platform = context.target.platform.casefold()
    render = renderer or _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions, bodies = [], []
    for plan in plans:
        definitions = tuple(d for d in schedule.definitions if d.cp.casefold() == plan.cp.casefold() and d.item.casefold() == plan.item.casefold() and d.source_rows == plan.excel_rows)
        if len(definitions) != 1: raise ValueError(f"DAC.ASSEMBLY.DEFINITION_UNRESOLVED: {len(definitions)}")
        definition = definitions[0]
        entries = tuple(e for e in schedule.entries if e.definition_id.casefold() == definition.identity.casefold())
        if len(entries) != 1: raise ValueError(f"DAC.ASSEMBLY.SCHEDULE_UNRESOLVED: {len(entries)}")
        entry = entries[0]
        ordinal = next(i for i, candidate in enumerate(schedule.entries) if candidate.identity.casefold() == entry.identity.casefold())
        owner = f"dac-test:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        rendered = render(plan, definition.render_name, entry.bin_binding.hardware_bin, context.platform_facts)
        if not isinstance(rendered, FirmwareBodyRender): raise TypeError("DAC renderer must return FirmwareBodyRender")
        contributions.append(ProgramContribution(identity=owner, target=context.target, resources=rendered.resources, resource_requires=rendered.resource_requires, definitions=(TestDefinitionContribution(definition.identity, "DAC_TEST", owner),), schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),), requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),)))
        bodies.append(SkeletonBody(body_ref, SectionFragment(f"{context.target.program_name}{extension}", "TESTS", f"{owner}:body", rendered.content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"), ordinal)))
    return TypedKindAssembly("DAC_TEST", tuple(contributions), tuple(bodies))


def _renderer_for(platform):
    if platform == "chroma": from program_gen.platforms.chroma.dac_test_renderer import render_dac_test
    elif platform == "s100": from program_gen.platforms.s100.dac_test_renderer import render_dac_test
    else: raise ValueError(f"DAC.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_dac_test


__all__ = ["compile_dac_test_assembly"]
