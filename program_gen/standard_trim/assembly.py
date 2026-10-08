"""Pure STANDARD_TRIM body-to-skeleton assembly bridge."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from program_gen.core.standard_trim_contribution import (
    compile_standard_trim_contribution,
)
from program_gen.core.trim_spec import TrimSpec
from program_gen.render_plan import ProgramContribution, RenderSymbolRef, TargetKey
from program_gen.skeleton import (
    LifecyclePlan,
    SkeletonInput,
    SkeletonPlatformProfile,
)
from program_gen.standard_trim.function_blocks import render_standard_trim


@dataclass(frozen=True, slots=True)
class StandardTrimAssemblySlice:
    skeleton_input: SkeletonInput
    business_contributions: tuple[ProgramContribution, ...]


def compile_standard_trim_assembly_slice(
    specs: Sequence[TrimSpec],
    target: TargetKey,
    schedule,
    *,
    profile: SkeletonPlatformProfile,
    lifecycle: LifecyclePlan,
    resource_closure: Sequence[str],
) -> StandardTrimAssemblySlice:
    """Bind native bodies to canonical TEST_BODY identities without I/O."""
    contributions: list[ProgramContribution] = []
    bodies: list[tuple[RenderSymbolRef, object]] = []
    for spec in specs:
        contribution = compile_standard_trim_contribution(
            spec,
            target,
            schedule,
            resource_closure=resource_closure,
        )
        fragments = render_standard_trim(spec, target, schedule)
        by_variant = {
            fragment.identity.rsplit(":", 1)[-1].casefold(): fragment
            for fragment in fragments
        }
        for entry in contribution.schedule_entries:
            canonical = next(
                item for item in schedule.entries
                if item.identity.casefold() == entry.identity.casefold()
            )
            try:
                fragment = replace(
                    by_variant[canonical.variant.casefold()],
                    order=entry.ordinal,
                )
            except KeyError as error:
                raise ValueError(
                    f"SC.TEST_BODY.VARIANT_MISSING: {canonical.variant!r}"
                ) from error
            bodies.append((
                RenderSymbolRef(
                    "TEST_BODY",
                    f"{target.platform.casefold()}:{entry.identity}",
                ),
                fragment,
            ))
        contributions.append(contribution)
    skeleton_input = SkeletonInput.for_test_bodies(
        target=target,
        profile=profile,
        lifecycle=lifecycle,
        schedule_entries=tuple(
            entry for contribution in contributions
            for entry in contribution.schedule_entries
        ),
        bodies=tuple(bodies),
    )
    return StandardTrimAssemblySlice(skeleton_input, tuple(contributions))


__all__ = [
    "StandardTrimAssemblySlice",
    "compile_standard_trim_assembly_slice",
]
