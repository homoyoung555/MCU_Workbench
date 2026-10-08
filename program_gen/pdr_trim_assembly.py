"""PDR_TRIM plans to native Skeleton V2 assembly without workbook access."""

from __future__ import annotations

from program_gen.core.pdr_contribution import compile_pdr_contribution
from program_gen.pdr_trim_support import compile_pdr_trim_support
from program_gen.pdr_voltage_support import compile_pdr_voltage_support
from program_gen.render_plan import RenderSymbolRef, SectionFragment
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_pdr_trim_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("PDR_TRIM")

    compilation = context.compilation
    compilation.require_success()
    target = context.target
    facts = context.platform_facts
    cp_plan = compilation.for_cp(target.cp)
    platform = target.platform.casefold()
    contributions = []
    bodies = []

    for plan in plans:
        _require_declared_relay(plan, facts, target)
        contribution = compile_pdr_contribution(
            plan, target, cp_plan.canonical_schedule
        )
        entry = next(
            item for item in cp_plan.canonical_schedule.entries
            if item.identity == contribution.schedule_entries[0].identity
        )
        if platform == "chroma":
            from program_gen.platforms.chroma.pdr_trim_renderer import (
                render_pdr_trim_body,
            )

            body = render_pdr_trim_body(
                plan,
                power_rails="+".join(facts.force_rails),
            )
            extension = ".pln"
        elif platform == "s100":
            from program_gen.platforms.s100.pdr_trim_renderer import (
                render_pdr_trim_body,
            )

            body = render_pdr_trim_body(
                plan,
                power_rails=tuple(facts.force_rails),
                reject_bin=entry.bin_binding.hardware_bin,
            )
            extension = ".prg"
        else:
            raise ValueError(f"TK.PDR_TRIM.PLATFORM: {target.platform!r}")

        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        fragment = SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"pdr-trim:{target.identity}:{entry.definition_id}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=contribution.schedule_entries[0].ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(ref, fragment))

    if len(plans) != 1:
        raise ValueError("TK.PDR_TRIM.PLAN_COUNT: expected exactly one PDR_TRIM plan")
    plan = plans[0]
    support = compile_pdr_trim_support(
        target,
        plan,
        context.pattern_producer.write_region(plan.dac_pattern_name),
    )
    voltage_support = compile_pdr_voltage_support(
        target,
        minimum=plan.pdr_min_voltage,
        target_voltage=plan.pdr_target_voltage,
        maximum=plan.pdr_max_voltage,
    )
    return TypedKindAssembly(
        "PDR_TRIM", (*contributions, voltage_support, support), tuple(bodies)
    )


def _require_declared_relay(plan, facts, target) -> None:
    if plan.relay is None:
        return
    declared = {pin.name.casefold() for pin in facts.relay_pins}
    if facts.kp_channel:
        declared.add("kp")
    if plan.relay.casefold() not in declared:
        raise ValueError(
            f"PDR.RELAY.UNDECLARED: {plan.relay!r} is not declared for "
            f"{target.platform}/{target.cp}/{target.variant}"
        )


__all__ = ["compile_pdr_trim_assembly"]
