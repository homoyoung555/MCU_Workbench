"""Mode-specific ENTER and SET_DATA resolution for the generic Trim core."""

from dataclasses import dataclass
from typing import Optional, Protocol

from pattern_bundle import (
    PatternCatalog,
    PatternField,
    bind_dynamic_argument,
)


class TrimModeError(ValueError):
    """The requested Trim mode has no adapter or an invalid Pattern binding."""


@dataclass(frozen=True)
class TrimModeBinding:
    item: str
    mode: str
    role: str
    dynamic_field: Optional[PatternField]
    value_source: str
    value: Optional[str]


class TrimModeAdapter(Protocol):
    mode: str

    def enter(
        self,
        catalog: PatternCatalog,
        item: str,
        role: str,
        argument: Optional[str],
    ) -> TrimModeBinding:
        ...

    def set_data(
        self,
        catalog: PatternCatalog,
        item: str,
    ) -> TrimModeBinding:
        ...


class FbistTrimModeAdapter:
    mode = "fbist"

    def enter(
        self,
        catalog: PatternCatalog,
        item: str,
        role: str,
        argument: Optional[str],
    ) -> TrimModeBinding:
        step = catalog.bundle(item).step(role)
        if argument is None and not step.dynamic_fields:
            return TrimModeBinding(
                item=item,
                mode=self.mode,
                role=role,
                dynamic_field=None,
                value_source="STATIC",
                value=None,
            )
        binding = bind_dynamic_argument(catalog, item, role, argument)
        return TrimModeBinding(
            item=item,
            mode=self.mode,
            role=role,
            dynamic_field=binding.field,
            value_source="ARGUMENT" if argument is not None else "DEFAULT",
            value=binding.value,
        )

    def set_data(
        self,
        catalog: PatternCatalog,
        item: str,
    ) -> TrimModeBinding:
        role = "trim dac"
        binding = bind_dynamic_argument(catalog, item, role, None)
        return TrimModeBinding(
            item=item,
            mode=self.mode,
            role=role,
            dynamic_field=binding.field,
            value_source="DAC_VALUE",
            value=None,
        )


_ADAPTERS = {
    "fbist": FbistTrimModeAdapter(),
}


def trim_mode_adapter(mode: str) -> TrimModeAdapter:
    normalized = str(mode).strip().casefold()
    adapter = _ADAPTERS.get(normalized)
    if adapter is None:
        raise TrimModeError(f"Trim mode={normalized or '<blank>'} adapter 尚未实现")
    return adapter
