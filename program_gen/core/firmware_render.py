"""Shared output contract for platform firmware body renderers."""

from __future__ import annotations

from dataclasses import dataclass

from program_gen.render_plan import ResourceRequest, ResourceRequirement


def sub_comment(sub: str, indent: str = "  ") -> tuple[str, str]:
    """Keep workbook text on one comment line without changing its spelling."""
    text = " ".join(str(sub).splitlines()).strip()
    return "", f"{indent}// ==================== sub: {text} ===================="


@dataclass(frozen=True, slots=True)
class FirmwareBodyRender:
    content: str
    resources: tuple[ResourceRequest, ...] = ()
    resource_requires: tuple[ResourceRequirement, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "resource_requires", tuple(self.resource_requires))


__all__ = ["FirmwareBodyRender", "sub_comment"]
