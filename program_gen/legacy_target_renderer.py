"""Temporary bridge from legacy platform writers to the public ArtifactSet.

The bridge is intentionally target-private and deletion-gated.  It copies only
declared generator inputs into a request scratch tree, runs one legacy target,
then re-materializes that target through the public RenderPlan contract.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping

from program_gen.orchestrator import TargetRenderContext
from program_gen.render_plan import (
    ArtifactMaterializer,
    ArtifactPlan,
    ArtifactSet,
    RenderPlan,
)


class LegacyTargetRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


LegacyRunner = Callable[[str, Path, object, object, str, str], object]


class LegacyTargetRenderer:
    """Adapt one old platform run without exposing its mutable work tree."""

    def __init__(
        self,
        workbook_model,
        platform_roots: Mapping[str, Path],
        *,
        runner: LegacyRunner | None = None,
    ):
        self._workbook = workbook_model
        self._roots = {
            str(platform).casefold(): Path(root).resolve()
            for platform, root in platform_roots.items()
        }
        self._runner = runner or _run_legacy_platform

    def __call__(self, compilation, context: TargetRenderContext) -> ArtifactSet:
        if getattr(compilation, "identity", None) != context.compilation_identity:
            raise LegacyTargetRenderError(
                "LR.COMPILATION.IDENTITY_MISMATCH",
                "render context and ProductCompilation identities differ",
            )
        platform = context.target.platform.casefold()
        source_root = self._roots.get(platform)
        if source_root is None:
            raise LegacyTargetRenderError(
                "LR.TARGET.PLATFORM", f"no input root for platform {platform!r}"
            )
        inputs = tuple(source_root / name for name in ("code", "fbist_pattern", "pat_temp"))
        for source in inputs:
            if not source.is_dir() or _is_link(source):
                raise LegacyTargetRenderError(
                    "LR.INPUT.INVALID", f"legacy input is missing or linked: {source}"
                )

        staging = Path(context.staging_directory)
        staging.parent.mkdir(parents=True, exist_ok=True)
        work_root = Path(tempfile.mkdtemp(prefix="v13lr-"))
        try:
            for source in inputs:
                _reject_tree_links(source)
                shutil.copytree(source, work_root / source.name)
            (work_root / "test_data").mkdir()
            self._runner(
                platform,
                work_root,
                compilation,
                self._workbook,
                context.target.cp,
                context.target.variant,
            )
            rendered_root = _rendered_target_root(work_root, context.target)
            if not rendered_root.is_dir() or _is_link(rendered_root):
                raise LegacyTargetRenderError(
                    "LR.TARGET.MISSING",
                    f"legacy renderer did not produce {context.target.identity}",
                )
            _reject_tree_links(rendered_root)
            artifact_plans = tuple(
                ArtifactPlan(
                    relative_path=path.relative_to(rendered_root).as_posix(),
                    content=path.read_bytes(),
                    kind=(
                        "PROGRAM"
                        if path.suffix.casefold() in (".pln", ".prg")
                        else "RESOURCE"
                    ),
                    owners=(f"legacy-adapter:{context.target.identity}",),
                )
                for path in sorted(
                    (item for item in rendered_root.rglob("*") if item.is_file()),
                    key=lambda item: (
                        item.relative_to(rendered_root).as_posix().casefold(),
                        item.relative_to(rendered_root).as_posix(),
                    ),
                )
                if path.name != ".render-manifest.json"
                and not any(part.startswith(".") for part in path.relative_to(rendered_root).parts)
            )
            if not artifact_plans:
                raise LegacyTargetRenderError(
                    "LR.TARGET.EMPTY", "legacy renderer produced no target artifacts"
                )
            plan = RenderPlan.from_artifacts(context.target, artifact_plans)
            if not staging.exists():
                staging.mkdir()
            return ArtifactMaterializer().materialize(plan, staging)
        finally:
            temp_root = Path(tempfile.gettempdir()).resolve()
            if (
                work_root.exists()
                and work_root.parent.resolve() == temp_root
                and work_root.name.startswith("v13lr-")
            ):
                shutil.rmtree(work_root)


def _run_legacy_platform(platform, base_dir, compilation, workbook, cp, variant):
    if platform == "chroma":
        from program_gen.platforms.chroma.main import run
    elif platform == "s100":
        from program_gen.platforms.s100.main import run
    else:
        raise LegacyTargetRenderError(
            "LR.TARGET.PLATFORM", f"unsupported legacy platform {platform!r}"
        )
    return run(
        str(base_dir),
        cp=cp,
        variant=variant,
        workbook_model=workbook,
        product_compilation=compilation,
    )


def _rendered_target_root(base_dir: Path, target) -> Path:
    if target.variant.casefold() == "lab":
        return base_dir / "LAB" / target.platform.upper() / target.program_name
    if target.variant.casefold() == "production":
        return base_dir / target.program_name
    raise LegacyTargetRenderError(
        "LR.TARGET.VARIANT", f"unsupported target variant {target.variant!r}"
    )


def _reject_tree_links(root: Path) -> None:
    for directory, names, filenames in os.walk(root, followlinks=False):
        for entry in (*names, *filenames):
            candidate = Path(directory) / entry
            if _is_link(candidate):
                raise LegacyTargetRenderError(
                    "LR.INPUT.SYMLINK", f"tree contains a link: {candidate}"
                )


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())
