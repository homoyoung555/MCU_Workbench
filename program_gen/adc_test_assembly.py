"""Assemble native ADC plans into canonical tester program bodies."""

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.adc_test import AdcPhaseKind
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import (
    LifecycleAction,
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolRequirement,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_adc_test_assembly(
    plans,
    context: TypedKindContext,
    renderer=None,
) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("ADC_TEST")
    context.compilation.require_success()
    platform = context.target.platform.strip().casefold()
    render = renderer if renderer is not None else _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions = []
    bodies = []
    for plan in plans:
        if plan.typed_kind != "ADC_TEST":
            raise ValueError(f"ADC.ASSEMBLY.KIND_MISMATCH: {plan.typed_kind!r}")
        if plan.cp.casefold() != context.target.cp.casefold():
            raise ValueError(f"ADC.ASSEMBLY.CP_MISMATCH: {plan.cp!r}")
        definition = _one_definition(schedule, plan)
        ordinal, entry = _one_entry(schedule, definition.identity)
        owner = f"adc-test:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        emissions = {}
        module_resource_requires = []
        module_provides = []
        module_requires = []
        for phase in plan.phases:
            if phase.kind is not AdcPhaseKind.KEIL_SRAM_CAPTURE:
                continue
            if phase.sram_capture is None:
                raise ValueError(
                    f"ADC.ASSEMBLY.SRAM_CAPTURE.MISSING: {phase.adc_id}"
                )
            emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
                "SRAM_CAPTURE", phase.sram_capture, platform
            )
            emissions[phase.row] = emission
            module_resource_requires.extend(emission.resource_requires)
            module_provides.extend(emission.provides)
            module_requires.extend(emission.requires)
            module_requires.extend(
                SymbolRequirement(
                    provision.ref,
                    provision.value_type,
                    provision.bit_width,
                    provision.scope,
                )
                for provision in emission.provides
            )
        rendered = render(
            plan,
            definition.render_name,
            entry.bin_binding.hardware_bin,
            context.platform_facts,
            emissions,
        )
        if not isinstance(rendered, FirmwareBodyRender):
            raise TypeError("ADC renderer must return FirmwareBodyRender")
        lifecycle_actions = ()
        if platform == "s100":
            from program_gen.platforms.s100.adc_test_renderer import (
                render_adc_alias_startup,
            )
            startup = render_adc_alias_startup(plan, context.platform_facts)
            if startup:
                lifecycle_actions = (LifecycleAction(
                    "START_UP", f"{owner}:adc-log-aliases", startup, 50,
                ),)
        contributions.append(ProgramContribution(
            identity=owner,
            target=context.target,
            resources=rendered.resources,
            resource_requires=(
                *rendered.resource_requires,
                *module_resource_requires,
            ),
            provides=tuple(module_provides),
            definitions=(TestDefinitionContribution(
                definition.identity, "ADC_TEST", owner,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity,
                definition.identity,
                ordinal,
                entry.enabled,
            ),),
            requires=(
                SymbolRequirement(body_ref, "SECTION", None, "TARGET"),
                *module_requires,
            ),
            lifecycle_actions=lifecycle_actions,
        ))
        fragment = SectionFragment(
            f"{context.target.program_name}{extension}",
            "TESTS",
            f"{owner}:body",
            _encode(rendered.content),
            ordinal,
        )
        bodies.append(SkeletonBody(body_ref, fragment))
    return TypedKindAssembly("ADC_TEST", tuple(contributions), tuple(bodies))


def _one_definition(schedule, plan):
    matches = tuple(
        definition for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == plan.excel_rows
    )
    if len(matches) != 1:
        raise ValueError(
            "ADC.ASSEMBLY.DEFINITION_UNRESOLVED: canonical schedule has "
            f"{len(matches)} matches for {plan.cp}/{plan.item} {plan.excel_rows}"
        )
    return matches[0]


def _one_entry(schedule, definition_identity):
    matches = tuple(
        (index, entry) for index, entry in enumerate(schedule.entries)
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    if len(matches) != 1:
        raise ValueError(
            "ADC.ASSEMBLY.SCHEDULE_UNRESOLVED: canonical schedule has "
            f"{len(matches)} entries for {definition_identity!r}"
        )
    return matches[0]


def _renderer_for(platform):
    if platform == "chroma":
        from program_gen.platforms.chroma.adc_test_renderer import render_adc_test
    elif platform == "s100":
        from program_gen.platforms.s100.adc_test_renderer import render_adc_test
    else:
        raise ValueError(f"ADC.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_adc_test


def _encode(content):
    return content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


__all__ = ["compile_adc_test_assembly"]
