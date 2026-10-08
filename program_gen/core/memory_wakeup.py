"""Platform-neutral CP1 Memory_Wakeup execution plan.

The plan keeps the historical three operations explicit so platform adapters do
not have to infer responsibilities from the test-item name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from program_gen.core.addr_map import AddrMapCatalog, AddrMapField
from program_gen.core.trim_data import TrimDataPlan


class MemoryWakeupOperationKind(str, Enum):
    BUILDMAP = "BUILDMAP"
    SETVPOSP = "SETVPOSP"
    NMLOOP = "NMLOOP"


class MemoryWakeupCompileError(ValueError):
    """Memory_Wakeup cannot obtain an unambiguous cross-platform binding."""


class DacValueSourceKind(str, Enum):
    CURRENT_DAC_FINAL = "CURRENT_DAC_FINAL"
    RESTORED_REG = "RESTORED_REG"


@dataclass(frozen=True, slots=True)
class BuildMapFieldBinding:
    item: str
    dac_final_symbol: str
    field: AddrMapField


@dataclass(frozen=True, slots=True)
class DacValueSource:
    kind: DacValueSourceKind
    symbol: str | None = None
    register: str | None = None
    lsb: int | None = None
    width: int | None = None


@dataclass(frozen=True, slots=True)
class PumpBinding:
    item: str
    field: AddrMapField
    sources: tuple[DacValueSource, ...]

    @property
    def restored_sources(self) -> tuple[DacValueSource, ...]:
        return tuple(
            source for source in self.sources
            if source.kind == DacValueSourceKind.RESTORED_REG
        )

    def select_source(
        self,
        *,
        current_dac_final_available: bool,
        restored_reg_available: bool,
    ) -> DacValueSource:
        """Choose the already-compiled source without platform-specific guessing."""
        availability = {
            DacValueSourceKind.CURRENT_DAC_FINAL: current_dac_final_available,
            DacValueSourceKind.RESTORED_REG: restored_reg_available,
        }
        current = next(
            (source for source in self.sources
             if source.kind == DacValueSourceKind.CURRENT_DAC_FINAL),
            None,
        )
        if current is not None and current_dac_final_available:
            return current
        restored = self.restored_sources
        if restored_reg_available and len(restored) == 1:
            return restored[0]
        if restored_reg_available and len(restored) > 1:
            registers = "、".join(source.register or "?" for source in restored)
            raise MemoryWakeupCompileError(
                f"Pump {self.item} 有多个 REG fallback（{registers}）；"
                "Adapter 必须读取全部候选、确认值一致后使用"
            )
        raise MemoryWakeupCompileError(
            f"Pump {self.item} 没有可用的 current DAC_FINAL 或 restored REG"
        )

    def select_restored_source(
        self,
        restored_values: dict[str, int],
    ) -> DacValueSource:
        """Validate duplicate ADDR_MAP locations before choosing a REG fallback."""
        available = tuple(
            (source, int(restored_values[source.register]))
            for source in self.restored_sources
            if source.register in restored_values
        )
        if len(available) != len(self.restored_sources):
            missing = tuple(
                source.register for source in self.restored_sources
                if source.register not in restored_values
            )
            raise MemoryWakeupCompileError(
                f"Pump {self.item} 缺少 restored REG：{'、'.join(missing)}"
            )
        values = {value for _source, value in available}
        if len(values) != 1:
            detail = "、".join(
                f"{source.register}={value}" for source, value in available
            )
            raise MemoryWakeupCompileError(
                f"Pump {self.item} 的多个 REG fallback 值不一致：{detail}"
            )
        return available[0][0]


@dataclass(frozen=True, slots=True)
class BuildMapOperation:
    field_bindings: tuple[BuildMapFieldBinding, ...]
    kind: MemoryWakeupOperationKind = MemoryWakeupOperationKind.BUILDMAP
    loads_pattern: bool = False
    runs_pattern: bool = False


@dataclass(frozen=True, slots=True)
class SetVpospOperation:
    pumps: tuple[PumpBinding, ...]
    kind: MemoryWakeupOperationKind = MemoryWakeupOperationKind.SETVPOSP
    runs_pattern: bool = False


@dataclass(frozen=True, slots=True)
class NmLoopOperation:
    kind: MemoryWakeupOperationKind = MemoryWakeupOperationKind.NMLOOP
    runs_set_all_final_vposp: bool = False
    runs_nm_erase_program_read: bool = True


@dataclass(frozen=True, slots=True)
class MemoryWakeupPlan:
    cp: str
    build_map: BuildMapOperation
    set_vposp: SetVpospOperation
    nm_loop: NmLoopOperation

    @property
    def operations(self):
        return (self.build_map, self.set_vposp, self.nm_loop)


def compile_memory_wakeup_plan(
    trim_data_plan: TrimDataPlan,
    addr_map_catalog: AddrMapCatalog,
    *,
    cp: str,
) -> MemoryWakeupPlan:
    """Compile the fixed CP1 Memory_Wakeup operation boundary.

    The arguments are intentionally accepted at this layer because subsequent
    slices attach map bindings and VPOSP value-source choices to the same plan.
    """
    normalized_cp = str(cp).strip().upper()
    if normalized_cp != "CP1":
        raise MemoryWakeupCompileError(
            f"Memory_Wakeup typed plan 只允许 CP1，收到 {cp!r}"
        )

    field_bindings: list[BuildMapFieldBinding] = []
    pump_bindings: list[PumpBinding] = []
    for binding in trim_data_plan.for_cp(normalized_cp):
        candidates = addr_map_catalog.selected_storage_fields("trim", binding.item)
        if candidates == () and not binding.pump:
            continue  # Explicit opt-out: this temporary result has no persisted field.
        layouts = tuple(
            field_layout for field_layout in (candidates if candidates is not None else addr_map_catalog.fields)
            if field_layout.register_layout.applies_to(normalized_cp)
            and addr_map_catalog.matches_trim(normalized_cp, binding.item, field_layout)
        )
        if not layouts:
            raise MemoryWakeupCompileError(
                f"{normalized_cp} Trim {binding.item} 在 ADDR_MAP 中没有适用字段"
            )
        if addr_map_catalog.has_trim_storage_mapping(binding.item):
            layouts = tuple(sorted(
                layouts,
                key=lambda field: (field.page.casefold(), field.register.casefold(), field.lsb, field.name.casefold()),
            ))
        for field_layout in layouts:
            field_bindings.append(BuildMapFieldBinding(
                item=binding.item,
                dac_final_symbol=binding.dac_final_symbol,
                field=field_layout,
            ))
        if binding.pump:
            field_layout = layouts[0]
            pump_bindings.append(PumpBinding(
                item=binding.item,
                field=field_layout,
                sources=(
                    DacValueSource(
                        DacValueSourceKind.CURRENT_DAC_FINAL,
                        symbol=binding.dac_final_symbol,
                    ),
                    *(DacValueSource(
                        DacValueSourceKind.RESTORED_REG,
                        register=layout.register,
                        lsb=layout.lsb,
                        width=layout.width,
                    ) for layout in layouts),
                ),
            ))
    return MemoryWakeupPlan(
        cp=normalized_cp,
        build_map=BuildMapOperation(tuple(field_bindings)),
        set_vposp=SetVpospOperation(tuple(pump_bindings)),
        nm_loop=NmLoopOperation(),
    )
