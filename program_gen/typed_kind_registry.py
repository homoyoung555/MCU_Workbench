"""Registry seam from typed business plans to native program assembly inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from program_gen.render_plan import ProgramContribution, TargetKey
from program_gen.skeleton import SkeletonBody


class TypedKindRegistryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class TypedKindContext:
    compilation: object
    target: TargetKey
    platform_facts: object
    pattern_producer: object
    scan_bindings: object | None = None


@dataclass(frozen=True, slots=True)
class TypedKindAssembly:
    typed_kind: str
    contributions: tuple[ProgramContribution, ...] = ()
    bodies: tuple[SkeletonBody, ...] = ()

    def __post_init__(self) -> None:
        kind = _kind(self.typed_kind)
        contributions = tuple(self.contributions)
        bodies = tuple(self.bodies)
        object.__setattr__(self, "typed_kind", kind)
        object.__setattr__(self, "contributions", contributions)
        object.__setattr__(self, "bodies", bodies)


TypedKindCompiler = Callable[
    [Sequence[object], TypedKindContext], TypedKindAssembly
]


class TypedKindRegistry:
    """Compile registered typed plans without exposing family implementation."""

    def __init__(
        self,
        registrations: Iterable[tuple[str, TypedKindCompiler]],
    ) -> None:
        compilers: dict[str, TypedKindCompiler] = {}
        for raw_kind, compiler in registrations:
            kind = _kind(raw_kind)
            if kind in compilers:
                raise TypedKindRegistryError(
                    "TK.REGISTRY.DUPLICATE", f"typed kind {kind!r} is duplicated"
                )
            if not callable(compiler):
                raise TypeError(f"typed kind compiler for {kind!r} must be callable")
            compilers[kind] = compiler
        self._compilers = compilers

    @property
    def registered_kinds(self) -> tuple[str, ...]:
        return tuple(self._compilers)

    def compile(
        self,
        typed_kind: str,
        plans: Sequence[object],
        context: TypedKindContext,
    ) -> TypedKindAssembly:
        kind = _kind(typed_kind)
        try:
            compiler = self._compilers[kind]
        except KeyError as error:
            raise TypedKindRegistryError(
                "TK.REGISTRY.UNREGISTERED", f"typed kind {kind!r} is not registered"
            ) from error
        assembly = compiler(tuple(plans), context)
        if not isinstance(assembly, TypedKindAssembly):
            raise TypedKindRegistryError(
                "TK.REGISTRY.RESULT_INVALID",
                f"typed kind {kind!r} did not return TypedKindAssembly",
            )
        if assembly.typed_kind != kind:
            raise TypedKindRegistryError(
                "TK.REGISTRY.KIND_MISMATCH",
                f"requested {kind!r}, got {assembly.typed_kind!r}",
            )
        if any(item.target != context.target for item in assembly.contributions):
            raise TypedKindRegistryError(
                "TK.REGISTRY.TARGET_MISMATCH",
                f"typed kind {kind!r} returned a contribution for another target",
            )
        return assembly


def _kind(value: object) -> str:
    kind = str(value).strip().upper()
    if not kind:
        raise TypedKindRegistryError(
            "TK.REGISTRY.KIND_EMPTY", "typed kind cannot be empty"
        )
    return kind


__all__ = [
    "TypedKindAssembly",
    "TypedKindContext",
    "TypedKindRegistry",
    "TypedKindRegistryError",
]
