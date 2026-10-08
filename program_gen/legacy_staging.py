"""Private staging adapter for the temporary legacy generators.

The adapter copies an explicit legacy input snapshot into one new request
directory, invokes an injected legacy runner there, and reports post-run file
digests for one selected target.  The returned digests are comparison evidence,
not the public pre-materialization render manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
from typing import Callable

from program_gen.render_plan import TargetKey


class LegacyStagingError(ValueError):
    """A private legacy staging request is unsafe or incomplete."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class InputRoots:
    seed: Path
    code: Path
    fbist_pattern: Path
    pat_temp: Path
    workbook: Path

    def __post_init__(self) -> None:
        for name in ("seed", "code", "fbist_pattern", "pat_temp", "workbook"):
            object.__setattr__(self, name, Path(getattr(self, name)))


@dataclass(frozen=True)
class ArtifactDigest:
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ArtifactSet:
    """Post-run evidence for one legacy target directory."""

    target: TargetKey
    target_relative_root: str
    artifacts: tuple[ArtifactDigest, ...]

    def artifact(self, relative_path: str) -> ArtifactDigest:
        for artifact in self.artifacts:
            if artifact.relative_path == relative_path:
                return artifact
        raise KeyError(relative_path)


class LegacyStagingRenderAdapter:
    """Run a legacy generator only against a copied request-private tree."""

    def __init__(self, runner: Callable[[Path], object]):
        if not callable(runner):
            raise TypeError("runner must be callable")
        self._runner = runner

    def render(
        self,
        *,
        inputs: InputRoots,
        staging: str | Path,
        target: TargetKey,
    ) -> ArtifactSet:
        staging_path = Path(staging)
        relative_root = _target_relative_root(target)
        _validate_inputs(inputs)
        _reject_staging_links(staging_path)
        _reject_input_overlap(inputs, staging_path)
        if staging_path.is_dir() and any(staging_path.iterdir()):
            raise LegacyStagingError(
                "LS.STAGING.NOT_EMPTY",
                f"staging directory is not empty: {staging_path}",
            )
        if staging_path.exists() or staging_path.is_symlink():
            raise LegacyStagingError(
                "LS.STAGING.EXISTS", f"staging path already exists: {staging_path}"
            )

        shutil.copytree(inputs.seed, staging_path, ignore=_exclude_explicit_roots)
        shutil.copytree(inputs.code, staging_path / "code")
        shutil.copytree(inputs.fbist_pattern, staging_path / "fbist_pattern")
        shutil.copytree(inputs.pat_temp, staging_path / "pat_temp")
        workbook_dir = staging_path / "test_data"
        workbook_dir.mkdir()
        shutil.copy2(inputs.workbook, workbook_dir / inputs.workbook.name)

        base_dir = staging_path.resolve(strict=True)
        self._runner(base_dir)

        target_dir = base_dir.joinpath(*relative_root.split("/"))
        _reject_target_links(base_dir, target_dir)
        if not target_dir.is_dir():
            raise LegacyStagingError(
                "LS.TARGET.MISSING", f"legacy target directory is missing: {relative_root}"
            )
        artifacts = tuple(
            ArtifactDigest(
                relative_path=path.relative_to(target_dir).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                size=path.stat().st_size,
            )
            for path in sorted(
                (item for item in target_dir.rglob("*") if item.is_file()),
                key=lambda item: (
                    item.relative_to(target_dir).as_posix().casefold(),
                    item.relative_to(target_dir).as_posix(),
                ),
            )
        )
        return ArtifactSet(target, relative_root, artifacts)


def _validate_inputs(inputs: InputRoots) -> None:
    for name in ("seed", "code", "fbist_pattern", "pat_temp"):
        path = getattr(inputs, name)
        if not path.is_dir():
            raise LegacyStagingError(
                "LS.INPUT.DIRECTORY_MISSING", f"{name} directory is missing: {path}"
            )
        _reject_links(name, path)
    if not inputs.workbook.is_file():
        raise LegacyStagingError(
            "LS.INPUT.WORKBOOK_MISSING", f"workbook is missing: {inputs.workbook}"
        )
    _reject_links("workbook", inputs.workbook)


def _reject_staging_links(staging: Path) -> None:
    absolute = staging.absolute()
    for candidate in (absolute, *absolute.parents):
        if _is_link(candidate):
            raise LegacyStagingError(
                "LS.STAGING.SYMLINK",
                f"staging path cannot traverse a symlink or junction: {candidate}",
            )


def _reject_input_overlap(inputs: InputRoots, staging: Path) -> None:
    staging_absolute = staging.absolute()
    for name in ("seed", "code", "fbist_pattern", "pat_temp"):
        source = getattr(inputs, name).resolve(strict=True)
        if (
            staging_absolute == source
            or staging_absolute.is_relative_to(source)
            or source.is_relative_to(staging_absolute)
        ):
            raise LegacyStagingError(
                "LS.STAGING.OVERLAPS_INPUT",
                f"staging path overlaps {name}: {staging_absolute}",
            )


def _reject_target_links(base_dir: Path, target_dir: Path) -> None:
    current = base_dir
    for part in target_dir.relative_to(base_dir).parts:
        current /= part
        if _is_link(current):
            raise LegacyStagingError(
                "LS.TARGET.SYMLINK",
                f"legacy target cannot traverse a symlink or junction: {current}",
            )
    if not target_dir.is_dir():
        return
    for directory, names, filenames in os.walk(target_dir, followlinks=False):
        for entry in (*names, *filenames):
            candidate = Path(directory) / entry
            if _is_link(candidate):
                raise LegacyStagingError(
                    "LS.TARGET.SYMLINK",
                    f"legacy target contains a symlink or junction: {candidate}",
                )


def _reject_links(name: str, root: Path) -> None:
    absolute = root.absolute()
    for candidate in (absolute, *absolute.parents):
        if _is_link(candidate):
            raise LegacyStagingError(
                "LS.INPUT.SYMLINK",
                f"{name} cannot traverse a symlink or junction: {candidate}",
            )
    if root.is_file():
        return
    for directory, names, filenames in os.walk(root, followlinks=False):
        for entry in (*names, *filenames):
            candidate = Path(directory) / entry
            if _is_link(candidate):
                raise LegacyStagingError(
                    "LS.INPUT.SYMLINK",
                    f"{name} contains a symlink or junction: {candidate}",
                )


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _exclude_explicit_roots(directory: str, names: list[str]) -> set[str]:
    del directory
    excluded = {"code", "fbist_pattern", "pat_temp"}
    return {name for name in names if name.casefold() in excluded}


def _target_relative_root(target: TargetKey) -> str:
    platform = target.platform.strip()
    platform_key = platform.casefold()
    if platform_key not in ("chroma", "s100"):
        if (
            "/" in platform
            or "\\" in platform
            or ":" in platform
            or platform in (".", "..")
        ):
            raise LegacyStagingError(
                "LS.TARGET.PATH_ESCAPE",
                f"target platform is not one safe path component: {platform!r}",
            )
        raise LegacyStagingError(
            "LS.TARGET.PLATFORM_UNSUPPORTED",
            f"legacy staging does not support platform {target.platform!r}",
        )
    variant = target.variant.strip().casefold()
    if variant == "lab":
        return f"LAB/{platform_key.upper()}/{target.program_name}"
    if variant == "production":
        return target.program_name
    raise LegacyStagingError(
        "LS.TARGET.VARIANT_UNSUPPORTED",
        f"legacy staging does not support variant {target.variant!r}",
    )
