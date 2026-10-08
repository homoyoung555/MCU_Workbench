"""Typed mandatory Program Skeleton seam.

The skeleton owns mandatory lifecycle structure and placement of already
rendered test bodies.  Platform syntax is injected through ``SkeletonSyntax``;
this module neither reads a workbook nor supplies platform/business defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from program_gen.render_plan import (
    LifecycleAction,
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolProvision,
    TargetKey,
)


@dataclass(frozen=True, slots=True)
class LifecycleHook:
    identity: str
    actions: tuple[LifecycleAction, ...] = ()

    def __post_init__(self) -> None:
        identity = str(self.identity).strip().upper()
        if not identity:
            raise ValueError("SK.LIFECYCLE.IDENTITY_MISSING: hook identity is empty")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "actions", tuple(self.actions))


@dataclass(frozen=True, slots=True)
class LifecyclePlan:
    hooks: tuple[LifecycleHook, ...]

    def __post_init__(self) -> None:
        hooks = tuple(self.hooks)
        identities = tuple(hook.identity for hook in hooks)
        duplicates = tuple(
            identity for identity in identities if identities.count(identity) > 1
        )
        if duplicates:
            raise ValueError(
                f"SK.LIFECYCLE.DUPLICATE: duplicate hook {duplicates[0]!r}"
            )
        object.__setattr__(self, "hooks", hooks)

    @classmethod
    def empty_for(cls, profile: "SkeletonPlatformProfile") -> "LifecyclePlan":
        return cls(tuple(
            LifecycleHook(identity) for identity in profile.required_structures
        ))

    @classmethod
    def for_profile(
        cls,
        profile: "SkeletonPlatformProfile",
        actions: tuple[LifecycleAction, ...],
    ) -> "LifecyclePlan":
        by_identity: dict[str, LifecycleAction] = {}
        for action in actions:
            key = action.identity.casefold()
            previous = by_identity.get(key)
            if previous is not None:
                code = "DUPLICATE" if previous == action else "CONFLICT"
                raise ValueError(
                    f"SK.LIFECYCLE.ACTION_{code}: action {action.identity!r} "
                    "has more than one owner"
                )
            by_identity[key] = action
        unknown = tuple(
            action.hook for action in by_identity.values()
            if action.hook not in profile.required_structures
        )
        if unknown:
            raise ValueError(
                f"SK.LIFECYCLE.ACTION_HOOK_UNKNOWN: hook {unknown[0]!r}"
            )
        ordered = tuple(sorted(
            by_identity.values(),
            key=lambda action: (action.order, action.identity.casefold()),
        ))
        return cls(tuple(
            LifecycleHook(
                identity,
                tuple(action for action in ordered if action.hook == identity),
            )
            for identity in profile.required_structures
        ))

    def actions_for(self, identity: str) -> tuple[LifecycleAction, ...]:
        key = str(identity).strip().upper()
        return next(hook.actions for hook in self.hooks if hook.identity == key)


@dataclass(frozen=True, slots=True)
class SkeletonPlatformProfile:
    platform: str
    program_extension: str
    section_order: tuple[str, ...]
    required_structures: tuple[str, ...]

    def __post_init__(self) -> None:
        platform = str(self.platform).strip().casefold()
        if platform not in ("chroma", "s100"):
            raise ValueError(f"SK.PLATFORM.UNSUPPORTED: {self.platform!r}")
        if not str(self.program_extension).startswith("."):
            raise ValueError("SK.PROGRAM.EXTENSION: extension must start with '.'")
        if not self.section_order:
            raise ValueError("SK.SECTION.ORDER_MISSING: section order is empty")
        required = tuple(
            str(identity).strip().upper() for identity in self.required_structures
        )
        if not required or any(not identity for identity in required):
            raise ValueError(
                "SK.STRUCTURE.REQUIRED_MISSING: required structures are empty"
            )
        if len(set(required)) != len(required):
            raise ValueError(
                "SK.STRUCTURE.DUPLICATE: required structures contain duplicates"
            )
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "section_order", tuple(self.section_order))
        object.__setattr__(self, "required_structures", required)


@dataclass(frozen=True, slots=True)
class SkeletonBody:
    ref: RenderSymbolRef
    fragment: SectionFragment


@dataclass(frozen=True, slots=True)
class SkeletonInput:
    target: TargetKey
    profile: SkeletonPlatformProfile
    lifecycle: LifecyclePlan
    schedule_entries: tuple[ScheduleEntryContribution, ...]
    bodies: tuple[SkeletonBody, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "schedule_entries", tuple(self.schedule_entries))
        object.__setattr__(self, "bodies", tuple(self.bodies))
        actual = tuple(hook.identity for hook in self.lifecycle.hooks)
        required = self.profile.required_structures
        missing = tuple(identity for identity in required if identity not in actual)
        if missing:
            raise ValueError(
                "SK.LIFECYCLE.MISSING: mandatory structure(s) " + ", ".join(missing)
            )
        unknown = tuple(identity for identity in actual if identity not in required)
        if unknown:
            raise ValueError(
                "SK.LIFECYCLE.UNKNOWN: unknown structure(s) " + ", ".join(unknown)
            )

    @classmethod
    def for_test_bodies(
        cls,
        *,
        target: TargetKey,
        profile: SkeletonPlatformProfile,
        lifecycle: LifecyclePlan,
        schedule_entries: tuple[ScheduleEntryContribution, ...],
        bodies: tuple[tuple[RenderSymbolRef, SectionFragment], ...],
    ) -> "SkeletonInput":
        return cls(
            target,
            profile,
            lifecycle,
            tuple(schedule_entries),
            tuple(SkeletonBody(ref, fragment) for ref, fragment in bodies),
        )

    @property
    def required_provisions(self) -> tuple[SymbolProvision, ...]:
        return tuple(
            SymbolProvision(body.ref, body.fragment.identity, "SECTION", None, "TARGET")
            for body in self.bodies
        )


@dataclass(frozen=True, slots=True)
class SkeletonRender:
    sections: tuple[SectionFragment, ...]
    provides: tuple[SymbolProvision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "provides", tuple(self.provides))


class SkeletonSyntax(Protocol):
    platform: str

    def render(self, plan: SkeletonInput) -> SkeletonRender:
        ...


class SkeletonProducer:
    """Validate a typed skeleton input and return one structural contribution."""

    def __init__(self, syntax: SkeletonSyntax) -> None:
        if not callable(getattr(syntax, "render", None)):
            raise TypeError("skeleton syntax must expose render(plan)")
        self._syntax = syntax

    def produce(self, plan: SkeletonInput) -> ProgramContribution:
        platform = plan.target.platform.strip().casefold()
        if platform != plan.profile.platform or platform != str(self._syntax.platform).casefold():
            raise ValueError(
                "SK.TARGET.PLATFORM_MISMATCH: target, profile and syntax differ"
            )
        program_path = f"{plan.target.program_name}{plan.profile.program_extension}"
        expected_body_keys = {
            f"{platform}:{entry.identity}".casefold()
            for entry in plan.schedule_entries
        }
        actual_body_keys = {body.ref.semantic_key.casefold() for body in plan.bodies}
        missing = tuple(sorted(expected_body_keys - actual_body_keys))
        if missing:
            raise ValueError(
                f"SK.TEST_BODY.MISSING: schedule body {missing[0]!r} has no provider"
            )
        extra = tuple(sorted(actual_body_keys - expected_body_keys))
        if extra:
            raise ValueError(
                f"SK.TEST_BODY.UNSCHEDULED: body {extra[0]!r} has no schedule entry"
            )
        for body in plan.bodies:
            if body.ref.namespace.casefold() != "test_body":
                raise ValueError(
                    f"SK.TEST_BODY.NAMESPACE: {body.ref.identity!r} is not TEST_BODY"
                )
            if body.fragment.artifact_path != program_path:
                raise ValueError(
                    "SK.TEST_BODY.ARTIFACT_MISMATCH: body targets another program"
                )
            if body.fragment.section.casefold() != "tests":
                raise ValueError("SK.TEST_BODY.SECTION: body must use TESTS")

        rendered = self._syntax.render(plan)
        rendered_provisions = {
            provision.ref.identity.casefold(): provision
            for provision in rendered.provides
        }
        for provision in plan.required_provisions:
            if rendered_provisions.get(provision.ref.identity.casefold()) != provision:
                raise ValueError(
                    f"SK.TEST_BODY.PROVISION_MISSING: {provision.ref.identity!r}"
                )
        sections = tuple(rendered.sections) + tuple(
            body.fragment for body in plan.bodies
        )
        if any(section.artifact_path != program_path for section in sections):
            raise ValueError("SK.SECTION.ARTIFACT_MISMATCH: skeleton split across programs")
        return ProgramContribution(
            identity=f"skeleton:{plan.target.identity}",
            target=plan.target,
            sections=sections,
            provides=rendered.provides,
        )


__all__ = [
    "LifecycleHook",
    "LifecyclePlan",
    "SkeletonBody",
    "SkeletonInput",
    "SkeletonPlatformProfile",
    "SkeletonProducer",
    "SkeletonRender",
    "SkeletonSyntax",
]
