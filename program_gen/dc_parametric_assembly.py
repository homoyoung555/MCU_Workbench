"""Assemble DC parametric plans into native platform program bodies."""

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.dc_parametric import RpdRpuPlan, VolVohPlan
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolRequirement,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_dc_parametric_assembly(
    plans, context: TypedKindContext, renderer=None
) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("DC_PARAMETRIC_TEST")
    context.compilation.require_success()
    platform = context.target.platform.strip().casefold()
    render = renderer if renderer is not None else _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions, bodies = [], []
    helper_emitted = False
    for plan in plans:
        if plan.typed_kind != "DC_PARAMETRIC_TEST":
            raise ValueError("DC.ASSEMBLY.KIND_MISMATCH")
        if plan.cp.casefold() != context.target.cp.casefold():
            raise ValueError("DC.ASSEMBLY.CP_MISMATCH")
        definition = _one_definition(schedule, plan)
        entry = _one_entry(schedule, definition.identity)
        ordinal = next(
            index for index, candidate in enumerate(schedule.entries)
            if candidate.identity.casefold() == entry.identity.casefold()
        )
        identity = f"dc-parametric:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        rendered = render(
            plan, definition.render_name, entry.bin_binding.hardware_bin,
            context.platform_facts,
        )
        if not isinstance(rendered, FirmwareBodyRender):
            raise TypeError("DC renderer must return FirmwareBodyRender")
        sections = ()
        if platform == "chroma" and isinstance(plan, (RpdRpuPlan, VolVohPlan)) and not helper_emitted:
            from program_gen.platforms.chroma.dc_parametric_renderer import dc_group_helper
            sections = (SectionFragment(
                f"{context.target.program_name}{extension}", "HELPERS",
                f"dc-parametric:{context.target.identity}:pin-group-helper",
                _encode(dc_group_helper()), 0,
            ),)
            helper_emitted = True
        contribution = ProgramContribution(
            identity=identity,
            target=context.target,
            sections=sections,
            resources=rendered.resources,
            resource_requires=rendered.resource_requires,
            definitions=(TestDefinitionContribution(
                definition.identity, "DC_PARAMETRIC_TEST", identity,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled,
            ),),
            requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),),
        )
        fragment = SectionFragment(
            f"{context.target.program_name}{extension}", "TESTS",
            f"{identity}:body", _encode(rendered.content), ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(body_ref, fragment))
    return TypedKindAssembly(
        "DC_PARAMETRIC_TEST", tuple(contributions), tuple(bodies)
    )


def _one_definition(schedule, plan):
    matches = tuple(
        definition for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == plan.excel_rows
    )
    if len(matches) != 1:
        raise ValueError(
            f"DC.ASSEMBLY.DEFINITION_UNRESOLVED: {len(matches)} matches"
        )
    return matches[0]


def _one_entry(schedule, definition_identity):
    matches = tuple(
        entry for entry in schedule.entries
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    if len(matches) != 1:
        raise ValueError(f"DC.ASSEMBLY.SCHEDULE_UNRESOLVED: {len(matches)} entries")
    return matches[0]


def _renderer_for(platform):
    if platform == "chroma":
        from program_gen.platforms.chroma.dc_parametric_renderer import render_dc_parametric
    elif platform == "s100":
        from program_gen.platforms.s100.dc_parametric_renderer import render_dc_parametric
    else:
        raise ValueError(f"DC.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_dc_parametric


def _encode(content):
    return content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


__all__ = ["compile_dc_parametric_assembly"]
