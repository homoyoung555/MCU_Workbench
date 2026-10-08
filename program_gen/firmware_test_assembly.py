"""Assemble compiled firmware plans into native tester program bodies."""

from dataclasses import replace

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.firmware_test_contribution import (
    compile_firmware_test_contribution,
)
from program_gen.render_plan import SectionFragment
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_code_download_assembly(plans, context, renderer=None):
    return _compile("CODE_DOWNLOAD", plans, context, renderer)


def compile_firmware_function_test_assembly(plans, context, renderer=None):
    return _compile("FIRMWARE_FUNCTION_TEST", plans, context, renderer)


def compile_firmware_run_test_assembly(plans, context, renderer=None):
    return _compile("FIRMWARE_RUN_TEST", plans, context, renderer)


def _compile(
    typed_kind: str,
    plans,
    context: TypedKindContext,
    renderer=None,
) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly(typed_kind)
    context.compilation.require_success()
    platform = context.target.platform.strip().casefold()
    render = renderer if renderer is not None else _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions = []
    bodies = []

    for plan in plans:
        if plan.typed_kind != typed_kind:
            raise ValueError(
                f"FW.ASSEMBLY.KIND_MISMATCH: expected {typed_kind!r}, "
                f"got {plan.typed_kind!r}"
            )
        contribution = compile_firmware_test_contribution(
            plan,
            context.target,
            schedule,
        )
        definition = next(
            item for item in schedule.definitions
            if item.identity == contribution.definitions[0].identity
        )
        entry = next(
            item for item in schedule.entries
            if item.identity == contribution.schedule_entries[0].identity
        )
        rendered = render(
            plan,
            definition.render_name,
            entry.bin_binding.hardware_bin,
            context.platform_facts,
        )
        if not isinstance(rendered, FirmwareBodyRender):
            raise TypeError("firmware renderer must return FirmwareBodyRender")
        contribution = replace(
            contribution,
            resources=(*contribution.resources, *rendered.resources),
            resource_requires=(
                *contribution.resource_requires,
                *rendered.resource_requires,
            ),
        )
        body_ref = next(
            requirement.ref for requirement in contribution.requires
            if requirement.ref.namespace == "TEST_BODY"
        )
        ordinal = contribution.schedule_entries[0].ordinal
        fragment = SectionFragment(
            f"{context.target.program_name}{extension}",
            "TESTS",
            f"{contribution.identity}:body",
            _encode(rendered.content),
            ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(body_ref, fragment))

    return TypedKindAssembly(typed_kind, tuple(contributions), tuple(bodies))


def _renderer_for(platform):
    if platform == "chroma":
        from program_gen.platforms.chroma.firmware_test_renderer import (
            render_firmware_test,
        )
    elif platform == "s100":
        from program_gen.platforms.s100.firmware_test_renderer import (
            render_firmware_test,
        )
    else:
        raise ValueError(f"FW.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_firmware_test


def _encode(content):
    return content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


__all__ = [
    "compile_code_download_assembly",
    "compile_firmware_function_test_assembly",
    "compile_firmware_run_test_assembly",
]
