"""Orchestrator adapter for complete native target RenderPlans."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from program_gen.orchestrator import TargetRenderContext
from program_gen.platform_program import (
    WorkspacePatternProducer,
    build_native_target_plan,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.core.scan_test import ScanArtifactProducer, ScanBindingSet
from program_gen.render_plan import ArtifactMaterializer, ArtifactSet, RenderPlan


class NativeTargetRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class NativeTargetRenderer:
    """Build and materialize one complete target without legacy writers."""

    def __init__(self, workbook_model, platform_roots: Mapping[str, Path], *, scan_bindings: ScanBindingSet | None = None, swd_bindings=None) -> None:
        self._workbook = workbook_model
        self._roots = {
            str(platform).casefold(): Path(root).resolve()
            for platform, root in platform_roots.items()
        }
        self._scan_bindings = scan_bindings
        self._swd_bindings = swd_bindings

    def __call__(
        self, compilation, context: TargetRenderContext
    ) -> ArtifactSet:
        plan = self.build_plan(compilation, context)
        staging = Path(context.staging_directory)
        staging.mkdir(parents=True, exist_ok=False)
        return ArtifactMaterializer().materialize(plan, staging)

    def build_plan(self, compilation, context: TargetRenderContext) -> RenderPlan:
        """Build the same target bytes without creating a staging directory."""
        if getattr(compilation, "identity", None) != context.compilation_identity:
            raise NativeTargetRenderError(
                "NR.COMPILATION.IDENTITY_MISMATCH",
                "render context and ProductCompilation identities differ",
            )
        platform = context.target.platform.casefold()
        pattern_root = self._roots.get(platform)
        if pattern_root is None or not pattern_root.is_dir():
            raise NativeTargetRenderError(
                "NR.PATTERN.ROOT_INVALID",
                f"native pattern input root is missing: {pattern_root}",
            )

        facts = compile_platform_program_facts(self._workbook, context.target)
        producer = GeneratedPatternProducer.from_compilation(
            compilation,
            platform,
            fallback=WorkspacePatternProducer(pattern_root),
        )
        if self._swd_bindings:
            from program_gen.core.swd_pattern import SwdPatternProducer
            producer = SwdPatternProducer(self._swd_bindings, producer)
        if self._scan_bindings is not None:
            producer = ScanArtifactProducer(self._scan_bindings, producer)
        return build_native_target_plan(
            compilation,
            context.target,
            facts,
            producer,
            self._scan_bindings,
        )


__all__ = ["NativeTargetRenderError", "NativeTargetRenderer"]
