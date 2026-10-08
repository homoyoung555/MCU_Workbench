"""Resolve one logical test-item identity across FLOW, Pattern and ADDR_MAP."""

from dataclasses import dataclass
import re
from typing import Dict, FrozenSet

import pandas as pd

from pattern_bundle import compile_pattern_bundles


class LogicalItemError(ValueError):
    """A workbook reference cannot be resolved to exactly one logical item."""


def logical_item_name(reference: str) -> str:
    """Return the role-free item name used for cross-sheet identity."""
    value = str(reference).strip().split("[", 1)[0].strip()
    value = re.sub(r"(?i)_dac_final$", "", value)
    value = re.sub(r"(?i)_(?:trim|verify)$", "", value)
    return value.rstrip("_")


def logical_item_key(reference: str) -> str:
    return logical_item_name(reference).casefold()


def logical_dac_final_symbol(reference: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", logical_item_name(reference)).strip("_")
    if not slug:
        raise LogicalItemError("logical item cannot produce an empty DAC symbol")
    return slug.upper() + "_DAC_FINAL"


@dataclass(frozen=True)
class LogicalItem:
    name: str
    roles: FrozenSet[str]

    @property
    def slug(self) -> str:
        value = re.sub(r"[^A-Za-z0-9]+", "_", logical_item_name(self.name)).strip("_").lower()
        if not value:
            raise LogicalItemError("logical item cannot produce an empty name")
        return value

    @property
    def dac_final_symbol(self) -> str:
        return logical_dac_final_symbol(self.name)

    def function_name(self, stage: str) -> str:
        normalized = stage.strip().casefold()
        if normalized == "trim":
            return self.name + "_Trim"
        if normalized == "verify":
            return self.name + "_Verify"
        raise LogicalItemError(f"unsupported function stage {stage!r}")

    def pattern(self, role: str) -> str:
        normalized = role.strip().casefold()
        if normalized not in self.roles:
            raise LogicalItemError(
                f"logical item {self.name!r} has no pattern role {role!r}"
            )
        if normalized == "trim mode":
            return f"enter_{self.slug}"
        if normalized == "trim dac":
            return f"set_{self.slug}_dac"
        if normalized == "verify mode":
            return f"enter_{self.slug}_verify"
        raise LogicalItemError(f"unsupported pattern role {role!r}")


@dataclass(frozen=True)
class LogicalItemCatalog:
    _aliases: Dict[str, LogicalItem]

    @classmethod
    def compile(cls, flow_frame: pd.DataFrame, pattern_frame: pd.DataFrame):
        pattern_catalog = compile_pattern_bundles(pattern_frame)
        roles_by_name = {
            bundle.item.casefold(): frozenset(step.role.casefold() for step in bundle.steps)
            for bundle in pattern_catalog.bundles
        }
        aliases: Dict[str, LogicalItem] = {}
        canonical: Dict[str, LogicalItem] = {}
        names = [str(value).strip() for value in flow_frame["item"].dropna()]
        names.extend(
            bundle.item
            for bundle in pattern_catalog.bundles
            if bundle.item.casefold() not in {name.casefold() for name in names}
        )
        for name in names:
            if not name:
                continue
            key = name.casefold()
            if key not in canonical:
                canonical[key] = LogicalItem(name=name, roles=roles_by_name.get(key, frozenset()))
            item = canonical[key]
            for alias in (name, name + "_Trim", name + "_Verify"):
                alias_key = alias.casefold()
                previous = aliases.get(alias_key)
                if previous is not None and previous != item:
                    raise LogicalItemError(
                        f"logical item alias {alias!r} resolves to more than one item"
                    )
                aliases[alias_key] = item
        return cls(aliases)

    def resolve(self, reference: str) -> LogicalItem:
        key = str(reference).strip().casefold()
        try:
            return self._aliases[key]
        except KeyError as exc:
            raise LogicalItemError(f"unknown logical item reference {reference!r}") from exc
