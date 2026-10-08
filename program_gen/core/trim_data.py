"""Compile FLOW trim rows into shared cross-platform trim-data bindings."""

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd

from program_gen.core.logical_item import (
    logical_dac_final_symbol,
    logical_item_key,
    logical_item_name,
)


def trim_data_reference_matches(item: str, addr_map_reference: str) -> bool:
    """Match logical identity without treating a Verify field as Trim data."""
    token = str(addr_map_reference).strip().split("[", 1)[0].strip()
    if token.casefold().endswith("_verify"):
        return False
    item_key = logical_item_key(item)
    token_key = logical_item_key(token)
    # Existing flash fields use the hardware prefix TRM_ while FLOW keeps the
    # logical test-item name (for example Pclk -> TRM_PCLK).
    if token_key.startswith("trm_"):
        token_key = token_key[4:]
    return item_key == token_key


class TrimDataCompileError(ValueError):
    """FLOW/ADDR_MAP item identity is ambiguous or incomplete."""


@dataclass(frozen=True)
class TrimDataBinding:
    item: str
    cp: str
    dac_bits: int
    pump: bool

    @property
    def addr_map_name(self) -> str:
        return logical_item_name(self.item) + "_Trim"

    @property
    def dac_final_symbol(self) -> str:
        return logical_dac_final_symbol(self.item)

    def reference(self, site_index: str) -> str:
        return f"{self.dac_final_symbol}[{site_index}]"

    def matches_addr_map(self, reference: str) -> bool:
        return trim_data_reference_matches(self.item, reference)


@dataclass(frozen=True)
class TrimDataPlan:
    bindings: Tuple[TrimDataBinding, ...]
    _by_key: Dict[str, TrimDataBinding]

    def resolve(self, reference: str) -> TrimDataBinding:
        key = logical_item_key(reference)
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise TrimDataCompileError(
                f"ADDR_MAP reference {reference!r} has no FLOW trim item"
            ) from exc

    def for_cp(self, cp: str) -> Tuple[TrimDataBinding, ...]:
        normalized = str(cp).strip().casefold()
        return tuple(binding for binding in self.bindings if binding.cp.casefold() == normalized)

    def resolve_dac_symbol(self, reference: str) -> TrimDataBinding:
        symbol = str(reference).strip().split("[", 1)[0].upper()
        matches = [binding for binding in self._by_key.values()
                   if binding.dac_final_symbol == symbol]
        if len(matches) != 1:
            raise TrimDataCompileError(
                f"DAC symbol {reference!r} does not resolve to one FLOW trim item"
            )
        return matches[0]


def compile_trim_data_plan(flow_frame: pd.DataFrame) -> TrimDataPlan:
    bindings = []
    by_key: Dict[str, TrimDataBinding] = {}
    for _, row in flow_frame.iterrows():
        if str(row.get("type", "")).strip().casefold() != "trim":
            continue
        item = logical_item_name(row.get("item", ""))
        if not item:
            continue
        binding = TrimDataBinding(
            item=item,
            cp=str(row.get("CP NO", "")).strip(),
            dac_bits=int(row.get("DAC bit")),
            pump=str(row.get("PUMP", "")).strip().casefold() == "yes",
        )
        key = logical_item_key(item)
        previous = by_key.get(key)
        if previous is not None and previous.dac_bits != binding.dac_bits:
            raise TrimDataCompileError(
                f"logical item {item!r} has conflicting DAC widths "
                f"{previous.dac_bits} and {binding.dac_bits}"
            )
        if previous is None:
            by_key[key] = binding
        bindings.append(binding)
    return TrimDataPlan(tuple(bindings), by_key)
