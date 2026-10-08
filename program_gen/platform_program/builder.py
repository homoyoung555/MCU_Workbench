"""Generic complete-program builder above every typed business kind."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

from program_gen.platform_program.contracts import ProgramAssemblyInput
from program_gen.platform_program.runtime_declarations import (
    compile_runtime_declaration_contribution,
)
from program_gen.render_plan import ProgramAssembler, ProgramContribution, RenderPlan
from program_gen.skeleton import (
    LifecyclePlan,
    SkeletonInput,
    SkeletonPlatformProfile,
    SkeletonProducer,
)


class PlatformProgramBuilder:
    """Close contributions into one deterministic multi-file RenderPlan.

    The public Interface is intentionally one ``build`` method.  Platform
    syntax and project-file variation stay behind the two concrete adapters;
    typed kinds only contribute definitions, bodies, symbols and resources.
    """

    def __init__(self, pattern_producer) -> None:
        if not callable(getattr(pattern_producer, "produce", None)):
            raise TypeError("platform program builder requires a PatternProducer")
        self._pattern_producer = pattern_producer

    def build(self, request: ProgramAssemblyInput):
        target = request.target
        facts = request.platform_facts
        contributions = _unique_contributions(request.contributions)
        platform = target.platform.strip().casefold()
        if (
            str(getattr(facts, "platform", "")).casefold() != platform
            or str(getattr(facts, "cp", "")).casefold() != target.cp.casefold()
        ):
            raise ValueError("PP.FACTS.TARGET_MISMATCH")

        schedule_entries = tuple(
            entry
            for contribution in contributions
            for entry in contribution.schedule_entries
        )
        canonical_entries = _select_canonical_entries(
            request.canonical_schedule, schedule_entries
        )
        requirements = _unique_requirements(contributions)
        pattern_producer = self._pattern_producer
        bind_target = getattr(pattern_producer, "for_target", None)
        if callable(bind_target):
            pattern_producer = bind_target(facts)

        if platform == "chroma":
            from program_gen.platform_program.chroma import (
                CHROMA_REQUIRED_STRUCTURES,
                CHROMA_SECTION_ORDER,
                ChromaSkeletonSyntax,
                project_contribution,
            )

            profile = SkeletonPlatformProfile(
                "chroma", ".pln", CHROMA_SECTION_ORDER,
                CHROMA_REQUIRED_STRUCTURES,
            )
            syntax = ChromaSkeletonSyntax(
                facts, canonical_entries, request.canonical_schedule
            )
            bodies = syntax.normalize_bodies(request.bodies)
            project = project_contribution(target, facts)
        elif platform == "s100":
            from program_gen.platform_program.s100 import (
                S100_REQUIRED_STRUCTURES,
                S100_SECTION_ORDER,
                S100SkeletonSyntax,
                project_contribution,
            )

            profile = SkeletonPlatformProfile(
                "s100", ".prg", S100_SECTION_ORDER,
                S100_REQUIRED_STRUCTURES,
            )
            syntax = S100SkeletonSyntax(facts, canonical_entries)
            bodies = syntax.normalize_bodies(request.bodies)
            timing_fragments = tuple(
                fragment
                for contribution in contributions
                for fragment in contribution.timing_fragments
            )
            prepare_timing = getattr(pattern_producer, "prepare_s100_timing", None)
            if callable(prepare_timing):
                pattern_producer, timing_fragments = prepare_timing(timing_fragments)
            project = project_contribution(
                target,
                facts,
                _s100_pattern_names(contributions, requirements),
                tuple(
                    entry.bin_binding.hardware_bin
                    for entry in canonical_entries
                    if entry.bin_binding.hardware_bin not in (None, "")
                ) + tuple(
                    "16" for entry in canonical_entries
                    if entry.placement == "SYSTEM_UNBOOKED"
                ),
                tuple(sorted(set(pattern_producer.timing_sets(requirements)) | {
                    "G3_1"
                    for contribution in contributions
                    for resource in contribution.resources
                    if "TS_FORCE_CLK" in resource.purpose
                })),
                timing_fragments,
            )
        else:
            raise ValueError(f"PP.TARGET.PLATFORM: {target.platform!r}")

        skeleton_input = SkeletonInput(
            target=target,
            profile=profile,
            lifecycle=LifecyclePlan.for_profile(
                profile,
                tuple(
                    action
                    for contribution in contributions
                    for action in contribution.lifecycle_actions
                ),
            ),
            schedule_entries=schedule_entries,
            bodies=bodies,
        )
        skeleton = SkeletonProducer(syntax).produce(skeleton_input)
        runtime_declarations = (
            () if request.runtime_declarations is None else
            (compile_runtime_declaration_contribution(
                target, request.runtime_declarations
            ),)
        )
        patterns = ProgramContribution(
            identity=f"native-patterns:{target.identity}",
            target=target,
            resources=tuple(
                pattern_producer.produce(requirement)
                for requirement in requirements
            ),
        )
        rendered = ProgramAssembler(section_order=profile.section_order).assemble(
            target,
            (*contributions, *runtime_declarations, skeleton, patterns, project),
        )
        if platform == "s100":
            from program_gen.core.s100_indent import format_s100
            return RenderPlan.from_artifacts(target, (
                replace(artifact, content=format_s100(artifact.content.decode("latin-1")).encode("latin-1"))
                if artifact.relative_path == f"{target.program_name}.prg" else artifact
                for artifact in rendered.artifacts
            ))
        return rendered


def _select_canonical_entries(canonical_schedule, schedule_entries):
    requested = {entry.identity.casefold() for entry in schedule_entries}
    selected = tuple(
        entry for entry in canonical_schedule.entries
        if entry.identity.casefold() in requested
    )
    actual = {entry.identity.casefold() for entry in selected}
    missing = tuple(sorted(requested - actual))
    if missing:
        raise ValueError(
            f"PP.SCHEDULE.CANONICAL_MISSING: {missing[0]!r}"
        )
    return selected


def _unique_contributions(contributions):
    """Coalesce one shared contribution requested by multiple typed kinds."""
    by_identity = {}
    order = []
    for contribution in contributions:
        key = contribution.identity.casefold()
        previous = by_identity.get(key)
        if previous is not None:
            if previous != contribution:
                raise ValueError(
                    f"PP.CONTRIBUTION.CONFLICT: {contribution.identity!r}"
                )
            continue
        by_identity[key] = contribution
        order.append(key)
    return tuple(by_identity[key] for key in order)


def _unique_requirements(contributions):
    by_identity = {}
    scan_by_path = {}
    for contribution in contributions:
        for requirement in contribution.resource_requires:
            key = requirement.logical_identity.casefold()
            if key.startswith("scan:"):
                path_key = requirement.relative_path.replace("\\", "/").casefold()
                previous_scan = scan_by_path.get(path_key)
                if previous_scan is not None and previous_scan.spec_identity != requirement.spec_identity:
                    raise ValueError(
                        f"SCAN.BINDING.RESOURCE_CONFLICT: {requirement.relative_path}; "
                        "同名关联必须使用同一冻结转换成品"
                    )
                scan_by_path[path_key] = requirement
                key = f"scan-resource:{path_key}:{requirement.spec_identity}"
            previous = by_identity.get(key)
            if previous is not None and (
                previous.relative_path != requirement.relative_path
                or previous.spec_identity != requirement.spec_identity
            ):
                raise ValueError(
                    f"PP.PATTERN.CONFLICT: {requirement.logical_identity}"
                )
            by_identity[key] = requirement
    return tuple(by_identity[key] for key in sorted(by_identity))


def _s100_pattern_names(contributions, requirements):
    """List external and generated SD resources in the S100 project."""
    names = [
        PurePosixPath(requirement.relative_path.replace("\\", "/")).stem
        for requirement in requirements
    ]
    names.extend(
        (
            resource.relative_path.replace("\\", "/")
            if resource.relative_path.casefold().endswith(".sr")
            else resource.relative_path[:-3].replace("\\", "/")
        )
        for contribution in contributions
        for resource in contribution.resources
        if resource.relative_path.casefold().endswith((".sd", ".sr"))
    )
    unique = {}
    for name in names:
        unique.setdefault(name.casefold(), name)
    return tuple(unique.values())


__all__ = ["PlatformProgramBuilder"]
