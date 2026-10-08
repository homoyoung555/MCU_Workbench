"""Code-owned policies for the mandatory platform program baseline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VtCoordinatePolicy:
    y_min_exclusive: int
    y_max_exclusive: int
    left_x_max_exclusive: int
    right_x_min_exclusive: int


_VT_POLICIES = {
    "CP1": VtCoordinatePolicy(57, 67, 30, 29),
    "CP2": VtCoordinatePolicy(57, 67, 30, 29),
    "CP3": VtCoordinatePolicy(57, 67, 30, 29),
}


_TARGET_REFERENCE_FIELDS = (
    ("VPOSE_TAR", "vpose_target"),
    ("VNEGE_TAR", "vnege_target"),
    ("VPOSP_TAR", "vposp_target"),
    ("VNEGP_TAR", "vnegp_target"),
)


def platform_baseline_target_references(facts) -> frozenset[str]:
    return frozenset(
        name for name, field in _TARGET_REFERENCE_FIELDS
        if getattr(facts, field) is not None
    )


def vt_coordinate_policy(cp: str) -> VtCoordinatePolicy:
    key = str(cp).strip().upper()
    try:
        return _VT_POLICIES[key]
    except KeyError as error:
        raise ValueError(f"PP.VT.COORDINATE_POLICY_MISSING: {key}") from error


__all__ = [
    "platform_baseline_target_references",
    "VtCoordinatePolicy",
    "vt_coordinate_policy",
]
