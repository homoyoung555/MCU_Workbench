"""External runtime workspace for the source-only V1.4 repository.

Callers provide one workspace root.  This Module owns the complete directory
layout for mutable inputs, toolchains, Golden evidence, staging and outputs;
no caller needs to reconstruct those paths from the source checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceLayoutError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    source_root: Path | None = None

    def __post_init__(self) -> None:
        root = Path(self.root).resolve()
        source = Path(self.source_root).resolve() if self.source_root else None
        if source is not None and (
            root == source
            or root.is_relative_to(source)
            or source.is_relative_to(root)
        ):
            raise WorkspaceLayoutError(
                "WS.ROOT.OVERLAPS_SOURCE",
                f"workspace and source trees must be disjoint: {root} / {source}",
            )
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "source_root", source)

    @property
    def workbook_root(self) -> Path:
        return self.root / "input" / "workbook"

    def platform_input(self, platform: str) -> Path:
        return self.root / "input" / self._platform(platform)

    def platform_output(self, platform: str) -> Path:
        return self.root / "outputs" / self._platform(platform)

    def toolchain(self, platform: str) -> Path:
        return self.root / "toolchains" / self._platform(platform)

    @property
    def managed_directories(self) -> tuple[Path, ...]:
        platform_inputs = tuple(
            self.platform_input(platform) / name
            for platform in ("chroma", "s100")
            for name in ("code", "fbist_pattern", "pat_temp")
        )
        return (
            self.workbook_root,
            *platform_inputs,
            self.root / "input" / "scan",
            self.root / "input" / "mbist",
            self.root / "input" / "hex",
            self.toolchain("chroma"),
            self.toolchain("s100"),
            self.root / "toolchains" / "other",
            self.root / "golden",
            self.root / "scratch",
            self.root / "staging",
            self.platform_output("chroma"),
            self.platform_output("s100"),
            self.root / "logs",
            self.root / "cache",
        )

    def create(self) -> "WorkspaceLayout":
        for directory in self.managed_directories:
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def find_master(self, name: str | None = None) -> Path | None:
        if name is not None:
            requested = Path(name)
            if requested.is_absolute() or requested.name != name:
                raise WorkspaceLayoutError(
                    "WS.WORKBOOK.NAME",
                    "workbook name must be a filename relative to input/workbook",
                )
            candidate = self.workbook_root / requested
            return candidate if candidate.is_file() else None
        if not self.workbook_root.is_dir():
            return None
        candidates = sorted(
            (
                path
                for path in self.workbook_root.iterdir()
                if path.is_file()
                and not path.name.startswith("~$")
                and path.suffix.casefold() in (".xlsx", ".xlsm")
            ),
            key=lambda path: (path.name.casefold(), path.name),
        )
        return candidates[0] if candidates else None

    @staticmethod
    def _platform(platform: str) -> str:
        normalized = str(platform).strip().casefold()
        if normalized not in ("chroma", "s100"):
            raise WorkspaceLayoutError(
                "WS.PLATFORM.UNSUPPORTED", f"unsupported platform {platform!r}"
            )
        return normalized
