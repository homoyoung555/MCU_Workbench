"""Deterministically expand one compiled workbook into explicit target paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Mapping

from program_gen.compiler import ProductCompilation
from program_gen.orchestrator import GenerationRequest, GenerationTarget
from program_gen.render_plan import TargetKey
from program_gen.validation import ValidationCommand
from program_gen.workbook import WorkbookModel


@dataclass(frozen=True)
class GenerationRoots:
    output_root: Path
    chroma: Path
    s100: Path

    def __post_init__(self) -> None:
        for field_name in ("output_root", "chroma", "s100"):
            object.__setattr__(
                self, field_name, Path(getattr(self, field_name)).resolve()
            )


def build_generation_request(
    compilation: ProductCompilation,
    workbook: WorkbookModel,
    roots: GenerationRoots,
    *,
    tools_root: Path,
    toolchain_roots: Mapping[str, str | Path] | None = None,
    platforms: tuple[str, ...] = ("chroma", "s100"),
    cps: tuple[str, ...] = ("CP1", "CP2", "CP3"),
    variants: tuple[str, ...] = ("lab", "production"),
) -> GenerationRequest:
    """Build only targets applicable to the workbook's VERSION rows."""
    compilation.require_success()
    if compilation.workbook_identity != workbook.identity:
        raise ValueError("GR.COMPILATION.WORKBOOK_MISMATCH")
    selected_platforms = _selection(platforms, ("chroma", "s100"), "PLATFORM")
    selected_cps = _selection(cps, tuple(compilation.cp_plans), "CP")
    selected_variants = _selection(variants, ("lab", "production"), "VARIANT")
    tools_root = Path(tools_root).resolve()
    resolved_toolchains = {
        str(platform).casefold(): Path(path).resolve()
        for platform, path in (toolchain_roots or {}).items()
    }
    version = workbook.dataframe("VERSION")
    targets: list[GenerationTarget] = []
    seen: set[tuple[str, str, str]] = set()

    for row in range(len(version)):
        cp = str(version.iloc[row]["CP num"]).strip().upper()
        if cp not in selected_cps:
            continue
        production_name = str(version.iloc[row]["Program Name"]).strip()
        tester = str(version.iloc[row]["tester"]).strip().casefold()
        for platform in selected_platforms:
            platform_root = roots.chroma if platform == "chroma" else roots.s100
            for variant in selected_variants:
                if variant == "production" and tester != platform:
                    continue
                unique = (platform, cp, variant)
                if unique in seen:
                    raise ValueError(
                        f"GR.VERSION.TARGET_DUPLICATE: {platform}/{cp}/{variant}"
                    )
                seen.add(unique)
                program_name = (
                    _lab_program_name(production_name)
                    if variant == "lab"
                    else production_name
                )
                final_parent = (
                    platform_root / "LAB" / platform.upper()
                    if variant == "lab"
                    else platform_root
                )
                final = final_parent / program_name
                stage_token = compilation.identity[:12].casefold()
                staging = final_parent / f".{program_name}.stage-{stage_token}"
                tool_name = (
                    "chroma_compiler.py" if platform == "chroma"
                    else "s100_compiler.py"
                )
                targets.append(GenerationTarget(
                    key=TargetKey(platform, cp, variant, program_name),
                    staging_directory=staging,
                    final_directory=final,
                    validation_command=ValidationCommand(
                        tool_identity=(
                            "CRAFT-wrapper/1" if platform == "chroma"
                            else "YT5100-wrapper/1"
                        ),
                        command=(
                            sys.executable,
                            str(tools_root / tool_name),
                            *_toolchain_arguments(platform, resolved_toolchains),
                            "-p",
                            ".",
                        ),
                    ),
                ))
    return GenerationRequest(compilation.identity, roots.output_root, tuple(targets))


def _toolchain_arguments(
    platform: str, roots: Mapping[str, Path]
) -> tuple[str, ...]:
    root = roots.get(platform)
    if root is None:
        return ()
    option = "--craft-home" if platform == "chroma" else "--home"
    return option, str(root)


def _selection(values, allowed, label: str) -> tuple[str, ...]:
    allowed_map = {str(value).casefold(): str(value) for value in allowed}
    selected: list[str] = []
    for value in values:
        key = str(value).strip().casefold()
        if key not in allowed_map:
            raise ValueError(f"GR.TARGET.{label}: unsupported {label.lower()} {value!r}")
        normalized = allowed_map[key]
        if normalized not in selected:
            selected.append(normalized)
    if not selected:
        raise ValueError(f"GR.TARGET.{label}: selection cannot be empty")
    return tuple(selected)


def _lab_program_name(name: str) -> str:
    parts = str(name).split("_")
    if len(parts) < 2:
        raise ValueError(f"GR.VERSION.PROGRAM_NAME: invalid program name {name!r}")
    parts[-2] = "1SLAB"
    return "_".join(parts)
