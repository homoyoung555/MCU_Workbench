"""Deterministic registry from typed Recipe Module plans to platform Adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from program_gen.render_plan import (
    ResourceRequirement,
    SymbolProvision,
    SymbolRequirement,
)


class RecipeModuleRegistryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class RecipeModuleEmission:
    statements: tuple[str, ...] = ()
    resource_requires: tuple[ResourceRequirement, ...] = ()
    provides: tuple[SymbolProvision, ...] = ()
    requires: tuple[SymbolRequirement, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", tuple(self.statements))
        object.__setattr__(self, "resource_requires", tuple(self.resource_requires))
        object.__setattr__(self, "provides", tuple(self.provides))
        object.__setattr__(self, "requires", tuple(self.requires))


RecipeModuleAdapter = Callable[[object], RecipeModuleEmission]


@dataclass(frozen=True, slots=True)
class RecipeModulePlugin:
    name: str
    plan_type: type
    adapters: tuple[tuple[str, RecipeModuleAdapter], ...]


class RecipeModuleRegistry:
    def __init__(
        self,
        plugins: Iterable[RecipeModulePlugin],
        *,
        required_platforms: tuple[str, ...] = ("chroma", "s100"),
    ) -> None:
        registered: dict[str, RecipeModulePlugin] = {}
        adapters_by_module: dict[str, dict[str, RecipeModuleAdapter]] = {}
        required = tuple(
            str(platform).strip().casefold() for platform in required_platforms
        )
        for plugin in plugins:
            name = _name(plugin.name)
            if not isinstance(plugin.plan_type, type):
                raise RecipeModuleRegistryError(
                    "RM.REGISTRY.PLAN_TYPE_INVALID",
                    f"Recipe Module {name!r} plan_type must be a type",
                )
            if name in registered:
                raise RecipeModuleRegistryError(
                    "RM.REGISTRY.DUPLICATE",
                    f"Recipe Module {name!r} is duplicated",
                )
            adapters: dict[str, RecipeModuleAdapter] = {}
            for platform, adapter in plugin.adapters:
                platform_name = str(platform).strip().casefold()
                if not callable(adapter):
                    raise RecipeModuleRegistryError(
                        "RM.REGISTRY.ADAPTER_INVALID",
                        f"Recipe Module {name!r} {platform_name!r} Adapter is not callable",
                    )
                if platform_name in adapters:
                    raise RecipeModuleRegistryError(
                        "RM.REGISTRY.ADAPTER_DUPLICATE",
                        f"Recipe Module {name!r} duplicates {platform_name!r} Adapter",
                    )
                adapters[platform_name] = adapter
            missing = tuple(
                platform for platform in required if platform not in adapters
            )
            if missing:
                raise RecipeModuleRegistryError(
                    "RM.REGISTRY.ADAPTER_MISSING",
                    f"Recipe Module {name!r} lacks {missing[0]!r} Adapter",
                )
            registered[name] = plugin
            adapters_by_module[name] = adapters
        self._plugins = registered
        self._adapters = adapters_by_module

    @property
    def registered_modules(self) -> tuple[str, ...]:
        return tuple(self._plugins)

    def emit(
        self,
        module_name: str,
        plan: object,
        platform: str,
    ) -> RecipeModuleEmission:
        name = _name(module_name)
        try:
            plugin = self._plugins[name]
        except KeyError as error:
            raise RecipeModuleRegistryError(
                "RM.REGISTRY.UNREGISTERED",
                f"Recipe Module {name!r} is not registered",
            ) from error
        if not isinstance(plan, plugin.plan_type):
            raise RecipeModuleRegistryError(
                "RM.REGISTRY.PLAN_INVALID",
                f"Recipe Module {name!r} requires {plugin.plan_type.__name__}",
            )
        platform_name = str(platform).strip().casefold()
        try:
            adapter = self._adapters[name][platform_name]
        except KeyError as error:
            raise RecipeModuleRegistryError(
                "RM.REGISTRY.PLATFORM_UNREGISTERED",
                f"Recipe Module {name!r} has no {platform_name!r} Adapter",
            ) from error
        result = adapter(plan)
        if not isinstance(result, RecipeModuleEmission):
            raise RecipeModuleRegistryError(
                "RM.REGISTRY.RESULT_INVALID",
                f"Recipe Module {name!r} Adapter did not return RecipeModuleEmission",
            )
        return result


def _name(value: object) -> str:
    name = str(value).strip().upper()
    if not name:
        raise RecipeModuleRegistryError(
            "RM.REGISTRY.NAME_EMPTY",
            "Recipe Module name cannot be empty",
        )
    return name


__all__ = [
    "RecipeModuleEmission",
    "RecipeModulePlugin",
    "RecipeModuleRegistry",
    "RecipeModuleRegistryError",
]
