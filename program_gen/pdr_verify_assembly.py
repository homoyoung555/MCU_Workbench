"""PDR_VERIFY typed plan to Skeleton V2 assembly Adapter."""

from __future__ import annotations

from program_gen.core.pdr_verify_contribution import compile_pdr_verify_contribution
from program_gen.pdr_voltage_support import compile_pdr_voltage_support
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    SectionFragment,
    SymbolProvision,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_pdr_verify_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("PDR_VERIFY")

    compilation = context.compilation
    compilation.require_success()
    target = context.target
    facts = context.platform_facts
    platform = target.platform.casefold()
    cp_plan = compilation.for_cp(target.cp)
    contributions = []
    bodies = []
    result_provisions = []

    for plan in plans:
        _require_declared_relay(plan, facts, target)
        _require_voltage_profile(plan)
        contribution = compile_pdr_verify_contribution(
            plan, target, cp_plan.canonical_schedule
        )
        entry = next(
            item for item in cp_plan.canonical_schedule.entries
            if item.identity == contribution.schedule_entries[0].identity
        )
        if platform == "chroma":
            from program_gen.platforms.chroma.pdr_verify_renderer import (
                render_pdr_verify_body,
            )

            body = render_pdr_verify_body(
                plan,
                power_rails=tuple(facts.force_rails),
                test_number=plan.test_number,
            )
            extension = ".pln"
        elif platform == "s100":
            from program_gen.platforms.s100.pdr_verify_renderer import (
                render_pdr_verify_body,
            )

            body = render_pdr_verify_body(
                plan,
                power_rails=tuple(facts.force_rails),
                reject_bin=entry.bin_binding.hardware_bin,
            )
            extension = ".prg"
        else:
            raise ValueError(f"TK.PDR_VERIFY.PLATFORM: {target.platform!r}")

        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        fragment = SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"pdr-verify:{target.identity}:{entry.definition_id}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=contribution.schedule_entries[0].ordinal,
        )
        result_requirement = next(
            requirement for requirement in contribution.requires
            if requirement.ref.namespace.casefold() == "result"
        )
        result_provisions.append(SymbolProvision(
            result_requirement.ref,
            result_requirement.ref.semantic_key,
            result_requirement.value_type,
            result_requirement.bit_width,
            result_requirement.scope,
        ))
        contributions.append(contribution)
        bodies.append(SkeletonBody(ref, fragment))

    profiles = {
        (plan.pdr_min_voltage, plan.pdr_target_voltage, plan.pdr_max_voltage)
        for plan in plans
    }
    if len(profiles) != 1:
        raise ValueError("TK.PDR_VERIFY.VOLTAGE_CONFLICT")
    minimum, target_voltage, maximum = profiles.pop()
    voltage_support = compile_pdr_voltage_support(
        target,
        minimum=minimum,
        target_voltage=target_voltage,
        maximum=maximum,
    )
    runtime_support = ProgramContribution(
        identity=f"pdr-verify:runtime:{target.identity}",
        target=target,
        provides=tuple(result_provisions),
    )
    return TypedKindAssembly(
        "PDR_VERIFY",
        (*contributions, voltage_support, runtime_support),
        tuple(bodies),
    )


def _require_voltage_profile(plan) -> None:
    if any(value is None for value in (
        plan.pdr_min_voltage,
        plan.pdr_max_voltage,
    )):
        raise ValueError("TK.PDR_VERIFY.VOLTAGE_PROFILE_MISSING")


def _require_declared_relay(plan, facts, target) -> None:
    if plan.relay in ("", "/"):
        return
    declared = {pin.name.casefold() for pin in facts.relay_pins}
    if facts.kp_channel:
        declared.add("kp")
    if plan.relay.casefold() not in declared:
        raise ValueError(
            f"PDR_VERIFY.RELAY.UNDECLARED: {plan.relay!r} is not declared for "
            f"{target.platform}/{target.cp}/{target.variant}"
        )


__all__ = ["compile_pdr_verify_assembly"]
