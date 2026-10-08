"""Platform-neutral SRAM capture grammar and layout contracts.

Captured values are unsigned low-bit slices of a little-endian byte stream.
"""

from dataclasses import dataclass
import re

from program_gen.core.result_binding import ResultIdentity
from program_gen.diagnostics import WorkbookProvenance


class SramCaptureCompileError(ValueError):
    """The SRAM_CAPTURE Recipe argument cannot form a safe capture layout."""


@dataclass(frozen=True, slots=True)
class SramCaptureArgument:
    """Typed, canonical SRAM_CAPTURE Recipe argument."""

    base: int
    count: int
    width: int
    stride: int

    def __post_init__(self) -> None:
        for field_name in ("base", "count", "width", "stride"):
            if type(getattr(self, field_name)) is not int:
                raise SramCaptureCompileError(
                    f"SRAM_CAPTURE {field_name} 必须为整数"
                )
        if not 0 <= self.base <= 0xFFFF:
            raise SramCaptureCompileError(
                "SRAM_CAPTURE base 必须位于 16-bit pattern 窗口 0X0000..0XFFFF"
            )
        if self.count <= 0:
            raise SramCaptureCompileError("SRAM_CAPTURE count 必须大于 0")
        if not 1 <= self.width <= 32:
            raise SramCaptureCompileError("SRAM_CAPTURE width 必须位于 1..32 bit")
        if self.stride <= 0:
            raise SramCaptureCompileError("SRAM_CAPTURE stride 必须大于 0")
        value_bytes = (self.width + 7) // 8
        final_byte = self.base + (self.count - 1) * self.stride + value_bytes - 1
        if final_byte > 0xFFFF:
            raise SramCaptureCompileError(
                "SRAM_CAPTURE 最后一个 value 的 byte 覆盖范围越过 0XFFFF"
            )

    @property
    def canonical_spec(self) -> str:
        return f"0X{self.base:X},{self.count}x{self.width}@{self.stride}"


@dataclass(frozen=True, slots=True)
class SramCaptureValueLayout:
    """READ32 locations needed to extract one unsigned little-endian value."""

    index: int
    value_address: int
    read32_address: int
    bit_offset: int
    crosses_word: bool
    second_read32_address: int | None


@dataclass(frozen=True, slots=True)
class SramCaptureLayout:
    """Pure SRAM value layout, independent of workbook and tester resources."""

    argument: SramCaptureArgument
    values: tuple[SramCaptureValueLayout, ...]

    @property
    def base(self) -> int:
        return self.argument.base

    @property
    def count(self) -> int:
        return self.argument.count

    @property
    def width(self) -> int:
        return self.argument.width

    @property
    def stride(self) -> int:
        return self.argument.stride

    @property
    def canonical_spec(self) -> str:
        return self.argument.canonical_spec

    @property
    def byte_order(self) -> str:
        return "little"

    @property
    def signed(self) -> bool:
        return False

    @property
    def value_mask(self) -> int:
        return (1 << self.width) - 1


@dataclass(frozen=True, slots=True)
class SramCapturePlan:
    """Adapter-ready capture plan with all non-platform facts attached."""

    layout: SramCaptureLayout
    result_identity: ResultIdentity
    provenance: WorkbookProvenance
    capture_pin: str

    def __post_init__(self) -> None:
        if not isinstance(self.layout, SramCaptureLayout):
            raise SramCaptureCompileError(
                "SRAM_CAPTURE layout 必须为 SramCaptureLayout"
            )
        if not isinstance(self.result_identity, ResultIdentity):
            raise SramCaptureCompileError(
                "SRAM_CAPTURE result_identity 必须为 ResultIdentity"
            )
        if not isinstance(self.provenance, WorkbookProvenance):
            raise SramCaptureCompileError(
                "SRAM_CAPTURE provenance 必须为 WorkbookProvenance"
            )
        if (
            not isinstance(self.capture_pin, str)
            or _SAFE_IDENTIFIER_RE.fullmatch(self.capture_pin) is None
        ):
            raise SramCaptureCompileError(
                "SRAM_CAPTURE capture_pin 必须为非空安全标识符"
            )

    @property
    def result_symbol(self) -> str:
        identity = re.sub(
            r"[^A-Za-z0-9_]+", "_", self.result_identity.canonical
        ).strip("_").upper()
        return f"SRAM_CAPTURE_{identity}"


_ARGUMENT_RE = re.compile(
    r"^\s*(?P<base>[+-]?(?:0[xX][0-9A-Fa-f]+|\d+))\s*,\s*"
    r"(?P<count>[+-]?\d+)\s*[xX]\s*(?P<width>[+-]?\d+)\s*"
    r"(?:@\s*(?P<stride>[+-]?\d+))?\s*$"
)
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_sram_capture_argument(spec: object) -> SramCaptureArgument:
    """Parse one complete SRAM_CAPTURE argument without platform facts."""

    text = "" if spec is None else str(spec)
    match = _ARGUMENT_RE.fullmatch(text)
    if match is None:
        raise SramCaptureCompileError(
            "SRAM_CAPTURE 参数必须为 base,countxwidth[@stride]"
        )
    base_token = match.group("base")
    base = int(base_token, 16 if "x" in base_token.casefold() else 10)
    return SramCaptureArgument(
        base=base,
        count=int(match.group("count")),
        width=int(match.group("width")),
        stride=int(match.group("stride") or 4),
    )


def compile_sram_capture_layout(
    spec: str | SramCaptureArgument,
) -> SramCaptureLayout:
    """Compile an SRAM_CAPTURE argument into aligned READ32 operations."""

    argument = (
        spec if isinstance(spec, SramCaptureArgument)
        else parse_sram_capture_argument(spec)
    )
    values = []
    for index in range(argument.count):
        value_address = argument.base + index * argument.stride
        read32_address = value_address & ~0x3
        bit_offset = (value_address - read32_address) * 8
        crosses_word = bit_offset + argument.width > 32
        values.append(SramCaptureValueLayout(
            index=index,
            value_address=value_address,
            read32_address=read32_address,
            bit_offset=bit_offset,
            crosses_word=crosses_word,
            second_read32_address=(read32_address + 4 if crosses_word else None),
        ))
    return SramCaptureLayout(argument=argument, values=tuple(values))


def compile_sram_capture_plan(
    argument: SramCaptureArgument,
    *,
    result_identity: ResultIdentity,
    provenance: WorkbookProvenance,
    capture_pin: str,
) -> SramCapturePlan:
    """Attach upper-layer result and resource facts to a pure SRAM layout."""

    if not isinstance(argument, SramCaptureArgument):
        raise SramCaptureCompileError(
            "SRAM_CAPTURE production plan 必须接收已解析的 typed argument"
        )
    return SramCapturePlan(
        layout=compile_sram_capture_layout(argument),
        result_identity=result_identity,
        provenance=provenance,
        capture_pin=capture_pin,
    )
