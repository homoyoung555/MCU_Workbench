"""ADDR_MAP 的平台无关编译模型。

这个模块只负责把母本中的寄存器、逻辑字段、页面和存储编码编译成可验证的
对象；它不生成平台代码，也不执行 Pattern。Chroma 与 S100 应共同消费这里的
结果，避免各自重复解释 ADDR_MAP。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import unicodedata
from typing import Callable, Iterable

import pandas as pd

from program_gen.core.project_mappings import StorageMapping, normalize_storage_mappings
from program_gen.core.logical_item import logical_item_key
from program_gen.core.trim_data import trim_data_reference_matches


class AddrMapCompileError(ValueError):
    """ADDR_MAP 结构或字段值不满足约束。"""


_RANGE_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\[(?P<high>\d+)(?::(?P<low>\d+))?\]$")
_CONST_RE = re.compile(r"^(?P<width>\d+)\s*['’‘]\s*[hHbBdD][0-9a-fA-F_xXzZ]+$")
_VERILOG_RE = re.compile(
    r"^(?P<width>\d+)\s*['’‘]\s*(?P<base>[hHbBdD])(?P<value>[0-9a-fA-F_xXzZ]+)$"
)
_SM_RA_RE = re.compile(
    r"\bRA(?:\s*\[[^]]+\])?\s*=\s*(0x[0-9a-fA-F]+|\d+)", re.I
)


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _without_cjk(value) -> str:
    return "".join(
        character for character in _text(value)
        if not unicodedata.name(character, "").startswith((
            "CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH",
        ))
    ).strip()


def _parse_verilog_int(value, *, context: str) -> int:
    token = _text(value).replace("_", "")
    match = _VERILOG_RE.fullmatch(token)
    if match:
        digits = match.group("value")
        if "x" in digits.lower() or "z" in digits.lower():
            raise AddrMapCompileError(f"{context} 含有未知位 x/z：{value!r}")
        base = {"h": 16, "b": 2, "d": 10}[match.group("base").lower()]
        result = int(digits, base)
        width = int(match.group("width"))
        if result >= 1 << width:
            raise AddrMapCompileError(f"{context} 超出声明的 {width} bit：{value!r}")
        return result
    try:
        return int(token, 0)
    except (TypeError, ValueError) as exc:
        raise AddrMapCompileError(f"无法解析 {context}：{value!r}") from exc


def _register_name(cell) -> str:
    token = _text(cell)
    match = re.search(r"([A-Za-z_]\w*)\s*(?:\[\d+(?::\d+)?\])?", token)
    return match.group(1) if match else ""


def _contains_complement(cell) -> bool:
    text = _text(cell).lower()
    return "反码" in text or "complement" in text or "inverse" in text


def _cp_tokens(cell) -> frozenset[str]:
    text = _text(cell).upper().replace(" ", "")
    tokens = {f"CP{value}" for value in re.findall(r"CP(\d+)", text)}
    # Workbook shorthand ``CP1/2/3`` carries the CP prefix only once.
    shorthand = re.search(r"CP(\d+(?:/\d+)+)", text)
    if shorthand:
        tokens.update(f"CP{value}" for value in shorthand.group(1).split("/"))
    return frozenset(tokens)


@dataclass(frozen=True, slots=True)
class AddrMapSegment:
    name: str | None
    width: int
    lsb: int
    literal_value: int | None = None


@dataclass(slots=True)
class RegisterLayout:
    page: str
    register: str
    row_index: int
    page_row_index: int
    cp_tokens: frozenset[str]
    default_storage_word: int
    real_half: str
    complement_half: str | None
    description: str = ""
    map_expression: str = ""
    segments: tuple[AddrMapSegment, ...] = field(default_factory=tuple)
    fields: tuple["AddrMapField", ...] = field(default_factory=tuple)
    storage_segments: tuple[AddrMapSegment, ...] = field(default_factory=tuple)
    storage_fields: tuple["AddrMapField", ...] = field(default_factory=tuple)
    storage_layout_error: str | None = None

    @property
    def default_real_value(self) -> int:
        if self.real_half == "HIGH":
            return (self.default_storage_word >> 16) & 0xFFFF
        return self.default_storage_word & 0xFFFF

    def applies_to(self, cp: str | None) -> bool:
        if not cp or not self.cp_tokens:
            return True
        return _text(cp).upper() in self.cp_tokens

    def replace_field(self, real_value: int, field_layout: "AddrMapField", value: int) -> int:
        if field_layout.register_layout is not self:
            raise AddrMapCompileError(
                f"字段 {field_layout.name} 不属于寄存器 {self.register}"
            )
        try:
            parsed_value = int(value)
        except (TypeError, ValueError) as exc:
            raise AddrMapCompileError(
                f"字段 {field_layout.name} 的值不是整数：{value!r}"
            ) from exc
        if parsed_value < 0 or parsed_value >= 1 << field_layout.width:
            raise AddrMapCompileError(
                f"字段 {field_layout.name} 是 {field_layout.width} bit，"
                f"不能写入 {parsed_value}"
            )
        current = int(real_value)
        if current < 0 or current > 0xFFFF:
            raise AddrMapCompileError(
                f"寄存器 {self.register} 的真实值必须在 16 bit 范围内"
            )
        mask = ((1 << field_layout.width) - 1) << field_layout.lsb
        return (current & ~mask) | (parsed_value << field_layout.lsb)

    def storage_word(self, real_value: int) -> int:
        value = int(real_value)
        if value < 0 or value > 0xFFFF:
            raise AddrMapCompileError(
                f"寄存器 {self.register} 的真实值必须在 16 bit 范围内"
            )
        if self.real_half == "LOW":
            high = (~value & 0xFFFF) if self.complement_half == "HIGH" else (
                (self.default_storage_word >> 16) & 0xFFFF
            )
            return (high << 16) | value
        low = (~value & 0xFFFF) if self.complement_half == "LOW" else (
            self.default_storage_word & 0xFFFF
        )
        return (value << 16) | low


@dataclass(frozen=True, slots=True)
class AddrMapField:
    name: str
    width: int
    lsb: int
    register_layout: RegisterLayout
    source: str = "cp_addr_map"

    @property
    def page(self) -> str:
        return self.register_layout.page

    @property
    def register(self) -> str:
        return self.register_layout.register


@dataclass(frozen=True, slots=True)
class StorageFieldCatalogEntry:
    page: str
    register: str
    field: str
    lsb: int
    width: int
    row: int
    source: str
    fallback: bool
    cp_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaptureLayoutEntry:
    page: str
    register: str
    slot_width: int
    real_offset: int
    row_index: int


@dataclass(frozen=True, slots=True)
class AddrMapStorageWord:
    """One physical 32-bit word in an ADDR_MAP page image."""

    page_row_index: int
    row_index: int
    default_storage_word: int
    data_type: str
    high_text: str
    low_text: str


@dataclass(frozen=True, slots=True)
class AddrMapPageLayout:
    """Complete ordered SM page facts retained for Pattern generation."""

    name: str
    ra: int
    words: tuple[AddrMapStorageWord, ...]


@dataclass(slots=True)
class AddrMapCatalog:
    registers: tuple[RegisterLayout, ...]
    _register_by_name: dict[str, RegisterLayout]
    _fields_by_name: dict[str, tuple[AddrMapField, ...]]
    _storage_fields_by_name: dict[str, tuple[AddrMapField, ...]] = field(default_factory=dict)
    storage_pages: tuple[AddrMapPageLayout, ...] = ()
    incomplete_storage_pages: tuple[str, ...] = ()
    trim_storage_mappings: tuple[StorageMapping, ...] = ()
    verify_storage_mappings: tuple[StorageMapping, ...] = ()

    @property
    def pages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(register.page for register in self.registers))

    def resolve_page(self, name: str) -> AddrMapPageLayout:
        key = _text(name).casefold()
        for page in self.storage_pages:
            if page.name.casefold() == key:
                return page
        raise AddrMapCompileError(f"ADDR_MAP 中不存在完整页面 {name}")

    @property
    def fields(self) -> tuple[AddrMapField, ...]:
        return tuple(
            field_layout
            for matches in self._fields_by_name.values()
            for field_layout in matches
        )

    def resolve_register(self, name: str) -> RegisterLayout:
        key = _text(name).casefold()
        try:
            return self._register_by_name[key]
        except KeyError as exc:
            raise AddrMapCompileError(f"ADDR_MAP 中不存在寄存器 {name}") from exc

    def resolve_field(self, name: str) -> AddrMapField:
        key = _text(name).casefold()
        try:
            matches = self._fields_by_name[key]
        except KeyError as exc:
            raise AddrMapCompileError(f"ADDR_MAP 中不存在字段 {name}") from exc
        if len(matches) != 1:
            registers = "、".join(match.register for match in matches)
            raise AddrMapCompileError(
                f"字段 {name} 对应多个寄存器（{registers}），请使用批量字段绑定"
            )
        return matches[0]

    def resolve_fields(self, name: str) -> tuple[AddrMapField, ...]:
        """解析一个语义字段的全部落点；用于同值写入多个页面/寄存器。"""
        key = _text(name).casefold()
        if key in self._fields_by_name:
            return self._fields_by_name[key]
        for field in self.storage_fields:
            if self.storage_field_reference(field, exact=True).casefold() == key:
                return (field,)
        raise AddrMapCompileError(f"ADDR_MAP 中不存在字段 {name}")

    @property
    def storage_fields(self) -> tuple[AddrMapField, ...]:
        """Physical fields parsed from description, with blank-description fallback."""
        return tuple(field for register in self.registers for field in register.storage_fields)

    def resolve_storage_field(self, page: str, register: str, field: str) -> AddrMapField:
        register_layout = self.resolve_register(register)
        if register_layout.page.casefold() != _text(page).casefold():
            raise AddrMapCompileError(f"寄存器 {register} 不在页面 {page}")
        matches = tuple(candidate for candidate in register_layout.storage_fields
                        if candidate.name.casefold() == _text(field).casefold())
        if not matches:
            # Earlier GUI workbooks stored the CP addr map alias. Migrate only
            # an exact physical interval; never guess by a similar field name.
            legacy = tuple(candidate for candidate in register_layout.fields
                           if candidate.name.casefold() == _text(field).casefold())
            if len(legacy) == 1:
                matches = tuple(candidate for candidate in register_layout.storage_fields
                                if (candidate.lsb, candidate.width) == (legacy[0].lsb, legacy[0].width))
        if len(matches) != 1:
            raise AddrMapCompileError(f"页面 {page}/{register} 中字段 {field} 不唯一或不存在")
        return matches[0]

    def storage_field_reference(self, field: AddrMapField, *, exact: bool = False) -> str:
        """An exact internal COMMIT identifier for a physical description field."""
        if field.source == "description" or exact:
            return f"__STORAGE_R{field.register_layout.row_index}_B{field.lsb}_W{field.width}"
        return field.name

    def selected_storage_fields(self, kind: str, item: str) -> tuple[AddrMapField, ...] | None:
        mappings = self.trim_storage_mappings if kind.casefold() == "trim" else self.verify_storage_mappings
        mapping = next((entry for entry in mappings
                        if logical_item_key(entry.item) == logical_item_key(item)), None)
        if mapping is None:
            return None
        return tuple(sorted((self.resolve_storage_field(target.page, target.register, target.field)
                             for target in mapping.targets),
                            key=lambda field: (field.register_layout.row_index, field.lsb)))

    def matches_trim(self, cp: str, item: str, field: AddrMapField) -> bool:
        """Use the explicit workbook binding when present, otherwise legacy names."""
        selected = self.selected_storage_fields("trim", item)
        if selected is not None:
            return any(_same_physical_field(field, candidate) for candidate in selected)
        return trim_data_reference_matches(item, field.name)

    def matches_verify(self, cp: str, item: str, field: AddrMapField) -> bool:
        selected = self.selected_storage_fields("verify", item)
        if selected is not None:
            return any(_same_physical_field(field, candidate) for candidate in selected)
        return field.name.casefold() == (logical_item_key(item) + "_verify").casefold()

    def has_trim_storage_mapping(self, item: str) -> bool:
        """Whether explicit global storage targets replace legacy name matching."""
        key = logical_item_key(item)
        return any(logical_item_key(mapping.item) == key for mapping in self.trim_storage_mappings)

    def has_verify_storage_mapping(self, item: str) -> bool:
        key = logical_item_key(item)
        return any(logical_item_key(mapping.item) == key for mapping in self.verify_storage_mappings)

    def capture_layout(
        self, page: str, *, read_bit: int, cp: str | None = None,
        include_register: Callable[[RegisterLayout], bool] | None = None,
    ) -> tuple[CaptureLayoutEntry, ...]:
        if read_bit <= 0 or read_bit % 32:
            raise AddrMapCompileError("read_bit 必须是正的 32 bit 整数倍")
        group_size = read_bit // 32
        page_registers = [
            register for register in self.registers
            if register.page.casefold() == _text(page).casefold()
        ]
        if not page_registers:
            raise AddrMapCompileError(f"ADDR_MAP 中不存在页面 {page}")

        groups: dict[int, list[CaptureLayoutEntry]] = {}
        for register in page_registers:
            if not register.applies_to(cp):
                continue
            if include_register is not None and not include_register(register):
                continue
            slot_width = 4 if register.complement_half else 2
            # Capture 按 32-bit MSB 先出：真实值在 LOW half 时位于 4-byte
            # 槽的后两个字节；真实值在 HIGH half 时从槽首开始。
            real_offset = 2 if (
                register.real_half == "LOW" and slot_width == 4
            ) else 0
            entry = CaptureLayoutEntry(
                page=register.page,
                register=register.register,
                slot_width=slot_width,
                real_offset=real_offset,
                row_index=register.row_index,
            )
            group = register.page_row_index // group_size
            groups.setdefault(group, []).append(entry)

        result: list[CaptureLayoutEntry] = []
        for group in sorted(groups):
            result.extend(reversed(groups[group]))
        return tuple(result)


def _segment_specs(expression: str, *, context: str) -> list[AddrMapSegment]:
    text = _text(expression).strip("{}() ")
    if not text:
        return []
    parts = [part.strip() for part in text.split(",") if part.strip()]
    parsed: list[tuple[str, str, int | None, int | None]] = []
    known_width = 0
    bare_count = 0
    for part in parts:
        constant = _CONST_RE.fullmatch(part)
        if constant:
            width = int(constant.group("width"))
            parsed.append((
                "constant", part, width,
                _parse_verilog_int(part, context=f"{context} 常数字段"),
            ))
            known_width += width
            continue
        match = _RANGE_RE.fullmatch(part)
        if match:
            high = int(match.group("high"))
            low = int(match.group("low") or high)
            if high < low:
                raise AddrMapCompileError(f"{context} 中字段范围倒置：{part}")
            width = high - low + 1
            parsed.append(("field", match.group("name"), width, None))
            known_width += width
            continue
        if re.fullmatch(r"[A-Za-z_]\w*", part):
            parsed.append(("field", part, None, None))
            bare_count += 1
            continue
        raise AddrMapCompileError(f"{context} 中无法解析字段片段 {part!r}")
    if known_width > 16:
        raise AddrMapCompileError(f"{context} 的已知字段总宽度 {known_width} 超过 16 bit")
    # 真实母本约定：完整表达式只有一个裸字段时它占满剩余位；与其它片段
    # 混写的裸字段（如 PLL_CKGATE_OPTR）是单 bit 开关。
    implicit_width = (16 - known_width) if bare_count == 1 and len(parsed) == 1 else 1
    if bare_count and known_width + bare_count * implicit_width > 16:
        raise AddrMapCompileError(f"{context} 的未标位宽字段没有剩余 bit")

    lsb = 0
    result: list[AddrMapSegment] = []
    for kind, token, width, literal_value in reversed(parsed):
        actual_width = implicit_width if width is None else width
        result.append(AddrMapSegment(
            token if kind == "field" else None,
            actual_width,
            lsb,
            literal_value,
        ))
        lsb += actual_width
    if lsb > 16:
        raise AddrMapCompileError(f"{context} 的字段总宽度 {lsb} 超过 16 bit")
    return result


def _same_physical_field(left: AddrMapField, right: AddrMapField) -> bool:
    return (
        left.page.casefold(), left.register.casefold(), left.name.casefold(), left.lsb, left.width
    ) == (
        right.page.casefold(), right.register.casefold(), right.name.casefold(), right.lsb, right.width
    )


def storage_field_catalog(catalog: AddrMapCatalog) -> tuple[StorageFieldCatalogEntry, ...]:
    """Project physical description fields into an API-safe, stable catalog."""
    return tuple(StorageFieldCatalogEntry(
        page=field.page,
        register=field.register,
        field=field.name,
        lsb=field.lsb,
        width=field.width,
        row=field.register_layout.row_index + 2,
        source=field.source,
        fallback=field.source == "cp_addr_map_fallback",
        cp_tokens=tuple(sorted(field.register_layout.cp_tokens)),
    ) for field in catalog.storage_fields)


def _required_columns(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise AddrMapCompileError(f"ADDR_MAP 缺少列：{', '.join(missing)}")


def compile_addr_map_catalog(
    frame: pd.DataFrame,
    trim_storage_mappings=(),
    verify_storage_mappings=(),
) -> AddrMapCatalog:
    """把 ADDR_MAP DataFrame 编译成大小写不敏感、严格唯一的目录。"""
    _required_columns(
        frame,
        ("Word No.", "line", "bit[31:16]", "bit[15:0]", "data type", "CP Data[31:0]", "CP addr map"),
    )
    registers: list[RegisterLayout] = []
    register_by_name: dict[str, RegisterLayout] = {}
    fields_by_name: dict[str, list[AddrMapField]] = {}
    storage_fields_by_name: dict[str, list[AddrMapField]] = {}
    page_positions: dict[str, int] = {}
    page_names: dict[str, str] = {}
    page_ra: dict[str, int] = {}
    page_words: dict[str, list[AddrMapStorageWord]] = {}
    incomplete_storage_pages: set[str] = set()

    for ordinal, (_, row) in enumerate(frame.iterrows()):
        page = _text(row["Word No."])
        if not page:
            continue
        page_key = page.casefold()
        page_names.setdefault(page_key, page)
        page_position = page_positions.get(page_key, 0)
        page_positions[page_key] = page_position + 1
        if "SM Address" in frame.columns and (address := _text(row["SM Address"])):
            match = _SM_RA_RE.search(address)
            if not match:
                incomplete_storage_pages.add(page_key)
            else:
                ra = int(match.group(1), 0)
                previous_ra = page_ra.setdefault(page_key, ra)
                if previous_ra != ra:
                    incomplete_storage_pages.add(page_key)
                page_words.setdefault(page_key, []).append(AddrMapStorageWord(
                    page_row_index=page_position,
                    row_index=ordinal,
                    default_storage_word=_parse_verilog_int(
                        row["CP Data[31:0]"], context=f"页面 {page} 第 {page_position} 字"
                    ) & 0xFFFFFFFF,
                    data_type=_text(row["data type"]),
                    high_text=_text(row["bit[31:16]"]),
                    low_text=_text(row["bit[15:0]"]),
                ))
        if _text(row["data type"]).casefold() != "lable":
            continue

        high_cell = row["bit[31:16]"]
        low_cell = row["bit[15:0]"]
        high_is_complement = _contains_complement(high_cell)
        low_is_complement = _contains_complement(low_cell)
        if high_is_complement and low_is_complement:
            raise AddrMapCompileError(f"ADDR_MAP 第 {ordinal + 2} 行的高低半字都标为反码")
        if high_is_complement:
            real_half, complement_half = "LOW", "HIGH"
            register_name = _register_name(low_cell)
        elif low_is_complement:
            real_half, complement_half = "HIGH", "LOW"
            register_name = _register_name(high_cell)
        else:
            real_half, complement_half = "LOW", None
            register_name = _register_name(low_cell) or _register_name(high_cell)
        if not register_name:
            raise AddrMapCompileError(f"ADDR_MAP 第 {ordinal + 2} 行无法确定寄存器名称")
        register_key = register_name.casefold()
        if register_key in register_by_name:
            previous = register_by_name[register_key]
            raise AddrMapCompileError(
                f"寄存器 {register_name} 重复：第 {previous.row_index + 2} 行和第 {ordinal + 2} 行"
            )

        register = RegisterLayout(
            page=page,
            register=register_name,
            row_index=ordinal,
            page_row_index=page_position,
            cp_tokens=_cp_tokens(row["line"]),
            default_storage_word=_parse_verilog_int(
                row["CP Data[31:0]"], context=f"寄存器 {register_name} 的 CP Data[31:0]"
            ) & 0xFFFFFFFF,
            real_half=real_half,
            complement_half=complement_half,
            description=_without_cjk(row.get("description")),
            map_expression=_text(row["CP addr map"]),
        )
        register.segments = tuple(_segment_specs(
            row["CP addr map"], context=f"寄存器 {register_name} 的 CP addr map"
        ))
        description = register.description
        if description:
            try:
                register.storage_segments = tuple(_segment_specs(
                    description, context=f"寄存器 {register_name} 的 description"
                ))
            except AddrMapCompileError as exc:
                # A non-empty description is hardware layout authority. Never
                # silently reinterpret it as CP addr map when it is malformed.
                register.storage_layout_error = str(exc)
        else:
            register.storage_segments = register.segments
        fields: list[AddrMapField] = []
        for segment in register.segments:
            if segment.name is None:
                continue
            name, width, lsb = segment.name, segment.width, segment.lsb
            key = name.casefold()
            existing = fields_by_name.get(key, [])
            if existing and any(previous.width != width for previous in existing):
                widths = sorted({previous.width for previous in existing} | {width})
                raise AddrMapCompileError(
                    f"字段 {name} 的多处落点位宽不一致：{widths}"
                )
            field_layout = AddrMapField(
                name=name, width=width, lsb=lsb, register_layout=register
            )
            fields.append(field_layout)
            fields_by_name.setdefault(key, []).append(field_layout)
        register.fields = tuple(fields)
        storage_fields: list[AddrMapField] = []
        for segment in register.storage_segments:
            if segment.name is None:
                continue
            field_layout = AddrMapField(
                name=segment.name, width=segment.width, lsb=segment.lsb,
                register_layout=register,
                source="description" if description else "cp_addr_map_fallback",
            )
            storage_fields.append(field_layout)
            storage_fields_by_name.setdefault(field_layout.name.casefold(), []).append(field_layout)
        register.storage_fields = tuple(storage_fields)
        registers.append(register)
        register_by_name[register_key] = register

    if not registers:
        raise AddrMapCompileError("ADDR_MAP 中没有 data type=lable 的寄存器行")
    storage_pages = tuple(
        AddrMapPageLayout(page_names[key], page_ra[key], tuple(words))
        for key, words in page_words.items()
        if key not in incomplete_storage_pages
    )
    return AddrMapCatalog(
        tuple(registers), register_by_name,
        {key: tuple(value) for key, value in fields_by_name.items()},
        {key: tuple(value) for key, value in storage_fields_by_name.items()},
        storage_pages,
        tuple(page_names[key] for key, count in page_positions.items()
              if key in incomplete_storage_pages or len(page_words.get(key, ())) != count),
        normalize_storage_mappings(trim_storage_mappings),
        normalize_storage_mappings(verify_storage_mappings),
    )


def catalog_for_cp(catalog: AddrMapCatalog, cp: str) -> AddrMapCatalog:
    """Return a CP-filtered view while preserving legal cross-page field fanout."""
    registers = tuple(register for register in catalog.registers if register.applies_to(cp))
    register_by_name = {register.register.casefold(): register for register in registers}
    fields_by_name: dict[str, list[AddrMapField]] = {}
    storage_fields_by_name: dict[str, list[AddrMapField]] = {}
    for register in registers:
        for field_layout in register.fields:
            fields_by_name.setdefault(field_layout.name.casefold(), []).append(field_layout)
        for field_layout in register.storage_fields:
            storage_fields_by_name.setdefault(field_layout.name.casefold(), []).append(field_layout)
    if not registers:
        raise AddrMapCompileError(f"ADDR_MAP 中没有适用于 {cp} 的 label 寄存器")
    return AddrMapCatalog(
        registers,
        register_by_name,
        {key: tuple(value) for key, value in fields_by_name.items()},
        {key: tuple(value) for key, value in storage_fields_by_name.items()},
        catalog.storage_pages,
        catalog.incomplete_storage_pages,
        catalog.trim_storage_mappings,
        catalog.verify_storage_mappings,
    )


def catalog_from_state() -> AddrMapCatalog:
    """Compile the workbook currently loaded in ``program_gen.state``.

    The import stays local so the platform-neutral catalog has no state-module
    dependency at import time and remains easy to unit test.
    """
    from program_gen import state as G

    if G.ADDR_MAP is None:
        raise AddrMapCompileError("尚未载入 ADDR_MAP")
    return compile_addr_map_catalog(G.ADDR_MAP)
