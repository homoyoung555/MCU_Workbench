"""OS typed plans to native Skeleton V2 assembly without workbook access."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.core.os_contribution import compile_os_contribution
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    SectionFragment,
    SymbolProvision,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


@dataclass(frozen=True, slots=True)
class OsRenderContext:
    kp_relay: bool
    power_pins: tuple[str, ...]
    force_rails: str
    site_groups: tuple[tuple[tuple[int, ...], str], ...]


def compile_os_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("OS")

    compilation = context.compilation
    compilation.require_success()
    target = context.target
    facts = context.platform_facts
    cp_plan = compilation.for_cp(target.cp)
    schedule = cp_plan.canonical_schedule
    platform = target.platform.casefold()
    contributions = []
    bodies = []

    for plan in plans:
        _require_declared_relay(plan, facts, target)
        contribution = compile_os_contribution(plan, target, cp_plan)
        entry = next(
            item for item in schedule.entries
            if item.identity == contribution.schedule_entries[0].identity
        )
        if platform == "chroma":
            from program_gen.platforms.chroma.os_renderer import render_os_body

            body = render_os_body(
                plan,
                context=_chroma_context(facts),
                test_number=(plan.row + 1) * 100,
            )
            extension = ".pln"
        elif platform == "s100":
            from program_gen.platforms.s100.os_renderer import render_os_body

            body = render_os_body(
                plan,
                power_pins=tuple(facts.force_rails),
                reject_bin=entry.bin_binding.hardware_bin,
            )
            extension = ".prg"
        else:
            raise ValueError(f"TK.OS.PLATFORM: {target.platform!r}")

        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        fragment = SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"os:{target.identity}:{entry.definition_id}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=contribution.schedule_entries[0].ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(ref, fragment))

    environment_refs = tuple(dict.fromkeys(
        requirement.ref
        for contribution in contributions
        for requirement in contribution.requires
        if requirement.ref.namespace == "OS_ENVIRONMENT"
    ))
    support = ProgramContribution(
        identity=f"os:environment:{target.identity}",
        target=target,
        provides=tuple(
            SymbolProvision(
                ref,
                f"platform-facts:{ref.semantic_key}",
                "SAFETY_ACTION",
                None,
                "TARGET",
            )
            for ref in environment_refs
        ),
    )
    return TypedKindAssembly("OS", (*contributions, support), tuple(bodies))


def _chroma_context(facts) -> OsRenderContext:
    sites = tuple(range(facts.site_count))
    return OsRenderContext(
        kp_relay=bool(facts.kp_channel),
        power_pins=tuple(facts.force_rails),
        force_rails="+".join(facts.force_rails),
        site_groups=(
            (tuple(site for site in sites if site % 2 == 0), "F0/S0"),
            (tuple(site for site in sites if site % 2 == 1), "F1/S1"),
        ),
    )


def _require_declared_relay(plan, facts, target) -> None:
    if plan.relay is None:
        return
    declared = {pin.name.casefold() for pin in facts.relay_pins}
    if facts.kp_channel:
        declared.add("kp")
    if plan.relay.casefold() not in declared:
        raise ValueError(
            f"OS.RELAY.UNDECLARED: {plan.relay!r} is not declared for "
            f"{target.platform}/{target.cp}/{target.variant}"
        )

__all__ = ["OsRenderContext", "compile_os_assembly"]
