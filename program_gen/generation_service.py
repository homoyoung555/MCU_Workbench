"""One-call request service for staged native generation.

The legacy renderer remains available only as an explicitly injected fallback.
This module owns only the request-to-orchestration seam: it never reads a
workbook, recompiles a product, calls platform writers, or introduces a second
request/result representation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from program_gen.native_target_renderer import NativeTargetRenderer
from program_gen.orchestrator import GenerationOrchestrator, OrchestrationResult
from program_gen.publisher import TransactionalLegacyPublisher
from program_gen.request_factory import GenerationRoots, build_generation_request
from program_gen.validation import TargetValidator


class GenerationService:
    """Build, stage, validate, then transactionally publish one compiled request."""

    def __init__(
        self,
        *,
        renderer_factory: Callable | None = None,
        validator=None,
        publisher=None,
    ) -> None:
        if renderer_factory is None:
            renderer_factory = NativeTargetRenderer
        if not callable(renderer_factory):
            raise TypeError("renderer_factory must create a staging renderer")
        self._renderer_factory = renderer_factory
        self._validator = validator or TargetValidator()
        self._publisher = publisher or TransactionalLegacyPublisher()

    def execute(
        self,
        workbook,
        compilation,
        roots: GenerationRoots,
        *,
        tools_root: str | Path,
        toolchain_roots: Mapping[str, str | Path] | None = None,
        platform_roots: Mapping[str, str | Path],
        platforms: tuple[str, ...] = ("chroma", "s100"),
        cps: tuple[str, ...] = ("CP1", "CP2", "CP3"),
        variants: tuple[str, ...] = ("lab", "production"),
        allow_stub_publication: bool = False,
    ) -> OrchestrationResult:
        """Execute the explicit target matrix from one supplied compilation.

        ``workbook`` and ``compilation`` are already-constructed public models;
        this service forwards the same objects to the existing request factory,
        legacy renderer and orchestrator without re-reading or recompiling.
        """
        request = build_generation_request(
            compilation,
            workbook,
            roots,
            tools_root=Path(tools_root),
            toolchain_roots=toolchain_roots,
            platforms=platforms,
            cps=cps,
            variants=variants,
        )
        renderer = self._renderer_factory(workbook, platform_roots)
        return GenerationOrchestrator(
            staging_renderer=renderer,
            validator=self._validator,
            publisher=self._publisher,
            allow_stub_publication=allow_stub_publication,
        ).execute(request, compilation)
