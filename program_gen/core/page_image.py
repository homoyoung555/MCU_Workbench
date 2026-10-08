"""Platform-neutral runtime page images and persistence value bindings."""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Tuple

from program_gen.core.logical_item import logical_item_key


class PageImageError(ValueError):
    """A page update cannot preserve the current physical image."""


class IncompletePageImageError(PageImageError):
    """COMMIT was requested before a full page image was established."""


@dataclass(frozen=True)
class FieldTarget:
    field: str
    page: str
    register: str
    lsb: int
    width: int
    destination: str


@dataclass(frozen=True)
class FieldWrite:
    target: FieldTarget
    value: int


@dataclass(frozen=True)
class ValueTarget:
    destination: str
    field: str


@dataclass(frozen=True)
class ValueBinding:
    item: str
    flow_type: str
    source_kind: str
    encoding: str
    targets: Tuple[ValueTarget, ...]

    def encode(self, value: float | int) -> int:
        if self.encoding == "FINAL_DAC":
            return int(value)
        if self.encoding == "ADC12_3V3":
            return int(float(value) / 3.3 * 4096)
        if self.encoding == "BCD16_MV":
            millivolts = int(float(value) * 1000 + 0.5)
            return (
                ((millivolts // 1000) % 10) << 12
                | ((millivolts // 100) % 10) << 8
                | ((millivolts // 10) % 10) << 4
                | millivolts % 10
            )
        raise PageImageError(f"unsupported value encoding {self.encoding}")

    def values_by_target(self, value: float | int) -> Tuple[int, ...]:
        encoded = self.encode(value)
        return tuple(encoded for _ in self.targets)


def compile_value_binding(
    *,
    item: str,
    flow_type: str,
    otp_targets: Iterable[str] = (),
    uid_targets: Iterable[str] = (),
) -> ValueBinding:
    normalized_type = str(flow_type).strip().casefold()
    if normalized_type == "trim":
        source_kind = "DAC_FINAL"
        encoding = "FINAL_DAC"
    elif normalized_type == "verify":
        source_kind = "MEASUREMENT"
        encoding = "ADC12_3V3" if "ts" in logical_item_key(item) else "BCD16_MV"
    else:
        raise PageImageError(f"unsupported persistent value type {flow_type!r}")
    targets = tuple(
        [ValueTarget("OTP", str(field)) for field in otp_targets]
        + [ValueTarget("UID", str(field)) for field in uid_targets]
    )
    return ValueBinding(
        item=str(item),
        flow_type=normalized_type,
        source_kind=source_kind,
        encoding=encoding,
        targets=targets,
    )


class PageImageStore:
    """Own complete runtime register values and apply field-level writes."""

    def __init__(self) -> None:
        self._registers: Dict[str, Dict[str, int]] = {}
        self._sources: Dict[str, str] = {}
        self._complete_pages: Dict[str, None] = {}
        self._dirty_pages: Dict[str, None] = {}

    @property
    def dirty_pages(self) -> Tuple[str, ...]:
        return tuple(self._dirty_pages)

    def has_complete_page(self, page: str) -> bool:
        return page in self._complete_pages

    def page_source(self, page: str) -> str:
        try:
            return self._sources[page]
        except KeyError as exc:
            raise IncompletePageImageError(f"page {page} has no complete Page Image") from exc

    def establish_page(
        self,
        page: str,
        registers: Mapping[str, int],
        *,
        source: str,
        complete: bool = True,
    ) -> None:
        if not str(source).strip():
            raise PageImageError(f"page {page} requires a source")
        self._registers[page] = dict(registers)
        self._sources[page] = str(source).strip()
        if complete:
            self._complete_pages[page] = None
        else:
            self._complete_pages.pop(page, None)
        self._dirty_pages.pop(page, None)

    def register_value(self, page: str, register: str) -> int:
        try:
            return self._registers[page][register]
        except KeyError as exc:
            raise IncompletePageImageError(
                f"page {page} has no complete value for register {register}"
            ) from exc

    def commit(self, writes: Iterable[FieldWrite]) -> Tuple[str, ...]:
        requested = tuple(writes)
        missing = tuple(dict.fromkeys(
            write.target.page
            for write in requested
            if not self.has_complete_page(write.target.page)
        ))
        if missing:
            raise IncompletePageImageError(
                "COMMIT requires a complete Page Image before updating "
                + ", ".join(missing)
            )
        missing_registers = tuple(dict.fromkeys(
            (write.target.page, write.target.register)
            for write in requested
            if write.target.register not in self._registers[write.target.page]
        ))
        if missing_registers:
            missing_text = ", ".join(
                f"{page}.{register}" for page, register in missing_registers
            )
            raise IncompletePageImageError(
                f"COMMIT requires complete register values for {missing_text}"
            )
        for write in requested:
            target = write.target
            if target.width <= 0 or target.lsb < 0:
                raise PageImageError(f"field {target.field} has an invalid bit range")
            if write.value < 0 or write.value >= (1 << target.width):
                raise PageImageError(
                    f"field {target.field} value {write.value} exceeds {target.width} bit"
                )
        affected: Dict[str, None] = {}
        for write in requested:
            target = write.target
            real_value = self.register_value(target.page, target.register)
            mask = ((1 << target.width) - 1) << target.lsb
            self._registers[target.page][target.register] = (
                (real_value & ~mask) | (write.value << target.lsb)
            )
            affected[target.page] = None
            self._dirty_pages[target.page] = None
        return tuple(affected)
