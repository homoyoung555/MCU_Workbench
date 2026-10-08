"""Reusable complete platform-program composition interface."""

from __future__ import annotations

from pathlib import Path

from program_gen.render_plan import (
    ArtifactMaterializer,
)
from program_gen.platform_program.builder import PlatformProgramBuilder
from program_gen.platform_program.contracts import ProgramAssemblyInput
from program_gen.platform_program.native_target import (
    NativeTargetCompositionError,
    build_native_target_plan,
)
from program_gen.system_tests import compile_system_read_assembly
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.pin_dec import (
    PinMapGenerationPlan,
    compile_pin_map_generation_plan,
    generate_pin_dec,
    generate_s100_prj_resources,
)
from program_gen.platform_program.pattern import (
    PatternProducer,
    WorkspacePatternProducer,
)


def build_standard_trim_program_plan(
    compilation,
    target,
    *,
    specs,
    platform_facts,
    pattern_producer: PatternProducer,
):
    """Return a complete multi-file native RenderPlan without materializing it."""
    from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY

    compilation.require_success()
    specs = tuple(specs)
    if not specs:
        raise ValueError("STN.SPECS.EMPTY")
    if any(spec.cp.casefold() != target.cp.casefold() for spec in specs):
        raise ValueError("STN.SPECS.CP_MISMATCH")
    cp_plan = compilation.for_cp(target.cp)
    schedule = cp_plan.canonical_schedule
    facts = platform_facts
    if facts.platform != target.platform.casefold() or facts.cp.casefold() != target.cp.casefold():
        raise ValueError("PP.FACTS.TARGET_MISMATCH")
    if target.platform.casefold() not in ("chroma", "s100"):
        raise ValueError(f"STN.TARGET.PLATFORM: {target.platform!r}")

    assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
        "STANDARD_TRIM",
        specs,
        TypedKindContext(
            compilation=compilation,
            target=target,
            platform_facts=facts,
            pattern_producer=pattern_producer,
        ),
    )
    system_reads = compile_system_read_assembly(
        compilation.system_read_specs(target.cp), target, schedule
    )
    return PlatformProgramBuilder(pattern_producer).build(ProgramAssemblyInput(
        target=target,
        platform_facts=facts,
        canonical_schedule=schedule,
        contributions=(
            *assembly.contributions,
            *system_reads.contributions,
        ),
        bodies=(*assembly.bodies, *system_reads.bodies),
        runtime_declarations=cp_plan.runtime_state.declarations,
    ))


class StandardTrimProgramStagingRenderer:
    """Orchestrator-compatible native renderer for an explicit spec selection."""

    def __init__(
        self,
        facts_for_target,
        pattern_roots,
        *,
        select_specs,
        materializer=None,
    ) -> None:
        self._facts_for_target = facts_for_target
        self._pattern_roots = {
            str(platform).casefold(): Path(root)
            for platform, root in pattern_roots.items()
        }
        self._select_specs = select_specs
        self._materializer = materializer or ArtifactMaterializer()

    def __call__(self, compilation, context):
        platform = context.target.platform.casefold()
        try:
            pattern_root = self._pattern_roots[platform]
        except KeyError as error:
            raise ValueError(f"STN.PATTERN.ROOT_MISSING: {platform}") from error
        specs = tuple(self._select_specs(compilation, context.target))
        plan = build_standard_trim_program_plan(
            compilation,
            context.target,
            specs=specs,
            platform_facts=self._facts_for_target(context.target),
            pattern_producer=WorkspacePatternProducer(pattern_root),
        )
        staging = Path(context.staging_directory)
        staging.mkdir(parents=True, exist_ok=False)
        return self._materializer.materialize(plan, staging)


__all__ = [
    "NativeTargetCompositionError", "PatternProducer", "PlatformProgramBuilder",
    "ProgramAssemblyInput", "build_native_target_plan",
    "StandardTrimProgramStagingRenderer",
    "WorkspacePatternProducer", "build_standard_trim_program_plan",
    "PinMapGenerationPlan", "compile_pin_map_generation_plan",
    "compile_platform_program_facts", "generate_pin_dec",
    "generate_s100_prj_resources",
]
