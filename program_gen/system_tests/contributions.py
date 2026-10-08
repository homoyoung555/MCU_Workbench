"""Project mandatory system read specs into generic ProgramContribution."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.system_tests.function_blocks import render_system_read_body


@dataclass(frozen=True, slots=True)
class SystemReadAssemblySlice:
    contributions: tuple[ProgramContribution, ...]
    bodies: tuple[SkeletonBody, ...]


def compile_system_read_assembly(specs, target: TargetKey, canonical_schedule):
    contributions = []
    bodies = []
    for spec in (specs.otp_read, specs.nm_data_read):
        definition = next(
            item for item in canonical_schedule.definitions
            if item.identity.casefold() == spec.definition_identity.casefold()
        )
        entry = next(
            item for item in canonical_schedule.entries
            if item.definition_id.casefold() == definition.identity.casefold()
        )
        ordinal = next(
            index for index, item in enumerate(canonical_schedule.entries)
            if item.identity.casefold() == entry.identity.casefold()
        )
        owner = f"system-read:{spec.typed_kind.casefold()}:{target.identity}"
        body_ref = RenderSymbolRef(
            "TEST_BODY", f"{target.platform.casefold()}:{entry.identity}"
        )
        fragment = SectionFragment(
            f"{target.program_name}{'.pln' if target.platform.casefold() == 'chroma' else '.prg'}",
            "TESTS",
            f"{owner}:body",
            render_system_read_body(spec, target).encode("gbk"),
            # Keep system-read bodies in the typed Debug category after the
            # Skeleton-owned Debug Flow seam, independent of canonical order.
            order=100000 + ordinal,
        )
        pattern_names = _pattern_names(spec, target.platform)
        extension = ".pat" if target.platform.casefold() == "chroma" else ".sd"
        prefix = "pat/" if target.platform.casefold() == "chroma" else ""
        contribution = ProgramContribution(
            identity=owner,
            target=target,
            definitions=(TestDefinitionContribution(
                definition.identity, spec.typed_kind, owner
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled
            ),),
            requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),),
            resource_requires=tuple(
                ResourceRequirement(
                    f"pattern:{name}",
                    f"{prefix}{name}{extension}",
                    f"v13.pattern/1:{target.platform.casefold()}:{name}",
                    f"{spec.typed_kind} pattern",
                )
                for name in pattern_names
            ),
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(body_ref, fragment))
    return SystemReadAssemblySlice(tuple(contributions), tuple(bodies))


def _pattern_names(spec, platform: str) -> tuple[str, ...]:
    if spec.typed_kind == "SYSTEM_OTP_READ":
        own = ("otp_read",)
    elif platform.casefold() == "chroma":
        own = ("nm_read",)
    else:
        own = tuple(
            f"fbist_capture_nm_bank{bank}" for bank in range(spec.bank_count)
        )
    return ("enter_fbist_mode", *own, "exit_fbist_mode")


__all__ = ["SystemReadAssemblySlice", "compile_system_read_assembly"]
