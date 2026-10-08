"""Platform-neutral FBIST Pattern generation plan.

The full, ordinary and PUMP entry points share one upstream compiler for the FBIST
pattern chain.  It freezes every workbook fact the legacy generators used to
read at render time into one immutable, workbook-free plan:

- the lowercase ``pattern`` sheet rows (item/pattern downward inheritance and
  the valid-row cell-format rule),
- VERSION CLK PIN / SWD PIN,
- the resolved 7-bit address of every row (sheet addr wins; FB MAP derivation
  remains only as the legacy compatibility rule for ordinary rows; ADDR_MAP is
  never consulted),
- the parsed description fields (``start,FIELD[hi:lo]=value``), their 16-bit
  register data, dynamic markers, and label identity,
- the PUMP aggregation targets (FLOW ``PUMP=yes`` items' ``trim dac`` and
  ``pump dac`` rows) merged into one ``set_all_final_vposp`` pattern.

Generators (Chroma/S100) consume only this plan; they never read a workbook,
a DataFrame, VERSION, FB MAP, the global ``G``, or the output directory.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping

import pandas as pd

import fb_map
from flow_recipe import FlowCompileError, dynamic_recipe_enter_operations
from program_gen.core.logical_item import logical_item_key
from program_gen.core.recipe_trim import pattern_output_name
from program_gen.core.trim_spec import TrimCompileError, dynamic_enter_operations
from program_gen.workbook import WorkbookModel


#: Every register written by a FBIST pattern is 16 bits wide today.
PATTERN_DATA_WIDTH = 16

#: The one fixed aggregate output name kept for existing consumers.  Only the
#: resource name survives; the master's same-named fixed block is not used.
AGGREGATE_PATTERN_NAME = "set_all_final_vposp"

#: Raw pattern-cell value of the legacy fixed aggregate block (rows 238-244 in
#: the formal master).  Future masters delete it; the plan never depends on it.
_LEGACY_AGGREGATE_ROLE = "set_all_final_vposp"

#: Legacy serial label bases for dynamic fields of ordinary patterns.
_SERIAL_BASES = ("a", "b", "c", "d", "e")

_FIELD_RE = re.compile(r"^\s*(\d+)\s*,\s*([^=]+?)\s*=\s*([01xX]+)(\*)?\s*$")
_BIT_RANGE_RE = re.compile(r"[\[<].*?[\]>]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ADDR_RE = re.compile(r"[01]{7}")

_ROLE_TRIM_MODE = "trim mode"
_ROLE_TRIM_DAC = "trim dac"
_ROLE_VERIFY_MODE = "verify mode"
_ROLE_PUMP_DAC = "pump dac"


class FbistPatternCompileError(ValueError):
    """The pattern sheet cannot be compiled into a valid generation plan."""


@dataclass(frozen=True)
class FbistPatternField:
    """One parsed description line of one pattern row."""

    excel_row: int
    line_index: int
    field_name: str
    label_base: str
    start_bit: int
    bit_width: int
    bit_hi: int
    bit_lo: int
    value: str
    dynamic: bool

    @property
    def description(self) -> str:
        """The ``FIELD=value`` text used in generated vector comments."""
        return f"{self.field_name}={self.value}"


@dataclass(frozen=True)
class FbistPatternWrite:
    """One register write: 7-bit addr plus merged 16-bit data fields."""

    source_rows: tuple[int, ...]
    raw_pattern: str
    addr_bits: str
    addr_int: int
    data_bits: str
    fields: tuple[FbistPatternField, ...]


@dataclass(frozen=True)
class FbistPatternRow:
    """One complete pattern-sheet data row frozen into the plan.

    ``excluded`` is empty for generated rows; otherwise it names the legacy
    reason the row produces no output (``invalid fill``, ``blank``,
    ``read_status_mode``, ``reuse dac``, ``legacy aggregate block``).
    """

    excel_row: int
    item: str
    role: str
    output_pattern: str | None
    addr_bits: str | None
    excluded: str
    description: str
    fields: tuple[FbistPatternField, ...]


@dataclass(frozen=True)
class FbistOutputPattern:
    """One ordinary output pattern with its writes in master order."""

    pattern_name: str
    writes: tuple[FbistPatternWrite, ...]


@dataclass(frozen=True)
class FbistPumpTarget:
    """One PUMP aggregate target field with its source identity."""

    item: str
    excel_row: int
    pattern_name: str
    role: str
    addr_bits: str
    field: FbistPatternField


@dataclass(frozen=True)
class FbistPumpAggregate:
    """The single PUMP aggregate pattern, targets and merged writes."""

    pattern_name: str
    writes: tuple[FbistPatternWrite, ...]
    targets: tuple[FbistPumpTarget, ...]


@dataclass(frozen=True)
class FbistPatternGenerationPlan:
    """The immutable upstream facts one platform generator executes."""

    workbook_identity: str
    clk_pin: str
    swd_pin: str
    patterns: tuple[FbistOutputPattern, ...]
    rows: tuple[FbistPatternRow, ...]
    pump_aggregate: FbistPumpAggregate
    pump_items: tuple[str, ...]
    dynamic_enter_patterns: tuple[str, ...]

    @property
    def identity(self) -> str:
        payload = json.dumps(
            _canonical(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest().upper()


@dataclass(frozen=True)
class FbistFieldLabel:
    """One label-catalog entry for a PUMP aggregate field (node 6 contract)."""

    logical_field_identity: str
    pattern_identity: str
    item: str
    field_label_base: str
    addr_bits: str
    bit_hi: int
    bit_lo: int
    bit_width: int
    dynamic: bool
    chroma_start_label: str
    chroma_end_label: str
    s100_start_label: str
    s100_end_label: str


@dataclass(frozen=True)
class FbistWritableFieldLabel:
    """One generated ordinary-pattern field writable at runtime."""

    logical_field_identity: str
    pattern_identity: str
    bit_width: int
    chroma_start_label: str
    s100_start_label: str
    s100_end_label: str


@dataclass(frozen=True)
class FbistPatternArtifact:
    """One immutable generated pattern file."""

    pattern_name: str
    relative_path: str
    content: bytes
    source_identity: str


@dataclass(frozen=True)
class FbistPatternGenerationResult:
    """What one platform generator returns: artifacts plus the label catalog."""

    platform: str
    workbook_identity: str
    artifacts: tuple[FbistPatternArtifact, ...]
    label_catalog: tuple[FbistFieldLabel, ...]


def compile_fbist_pattern_plan(
    workbook: WorkbookModel,
    flow_frame: pd.DataFrame,
    *,
    trim_specs: Mapping[int, object] | None = None,
    recipe_rows: Mapping[int, object] | None = None,
) -> FbistPatternGenerationPlan:
    """Compile one immutable FBIST pattern generation plan from the workbook."""
    return _compile_fbist_pattern_plan(workbook, flow_frame, trim_specs=trim_specs, recipe_rows=recipe_rows)


def compile_ordinary_fbist_pattern_plan(workbook: WorkbookModel) -> FbistPatternGenerationPlan:
    """Compile ordinary vectors without FLOW, runtime consumers or PUMP-only rows."""
    return _compile_fbist_pattern_plan(workbook, None, ordinary_only=True)


def compile_pump_fbist_pattern_plan(workbook: WorkbookModel) -> FbistPatternGenerationPlan:
    """Compile only the aggregate; every selected item must supply dynamic DAC fields."""
    try:
        flow = workbook.dataframe("FLOW")
    except KeyError as exc:
        raise FbistPatternCompileError("缺少 FLOW sheet") from exc
    missing = [name for name in ("item", "PUMP") if name not in flow.columns]
    if missing:
        raise FbistPatternCompileError(f"FLOW 缺少列: {', '.join(missing)}")
    for index, row in flow.iterrows():
        if _text(row["PUMP"]).casefold() == "yes" and not _text(row["item"]):
            raise FbistPatternCompileError(f"FLOW row {int(index) + 2}: PUMP=yes 必须填写 item")
    plan = _compile_fbist_pattern_plan(workbook, flow, pump_only=True)
    if not plan.pump_items:
        raise FbistPatternCompileError("FLOW 中没有 PUMP=yes 的 item，无法生成汇总资源")
    covered = {logical_item_key(target.item) for target in plan.pump_aggregate.targets}
    missing = [item for item in plan.pump_items if item not in covered]
    if missing:
        raise FbistPatternCompileError(
            "FLOW PUMP=yes 的 item 缺少有效的动态 trim dac/pump dac 配置: " + ", ".join(missing)
        )
    return plan


def _compile_fbist_pattern_plan(
    workbook, flow_frame, *, trim_specs=None, recipe_rows=None, ordinary_only=False, pump_only=False,
) -> FbistPatternGenerationPlan:
    if not isinstance(workbook, WorkbookModel):
        raise TypeError("compile_fbist_pattern_plan expects WorkbookModel")
    try:
        pattern_frame = workbook.dataframe("pattern")
    except KeyError as exc:
        raise FbistPatternCompileError("缺少 lowercase pattern sheet") from exc
    required = ("item", "addr", "description", "pattern")
    missing = [column for column in required if column not in pattern_frame.columns]
    if missing:
        raise FbistPatternCompileError(
            f"pattern 缺少列: {', '.join(missing)}"
        )
    pattern_sheet = workbook.sheet("pattern")

    clk_pin, swd_pin = _version_pins(workbook)
    pump_items = () if ordinary_only else _pump_items(flow_frame)
    dynamic_enters = _dynamic_enter_patterns(trim_specs, recipe_rows)
    fb_map_index = fb_map.build_index_from_workbook(workbook)

    rows: list[FbistPatternRow] = []
    pattern_writes: dict[str, list[FbistPatternWrite]] = {}
    pattern_order: list[str] = []
    current_item = ""
    current_role = ""

    for index, record in pattern_frame.iterrows():
        excel_row = int(index) + 2
        valid = _row_valid(pattern_sheet, excel_row)
        item_cell = record["item"]
        role_cell = record["pattern"]
        description = record["description"]

        if not valid:
            rows.append(FbistPatternRow(
                excel_row=excel_row,
                item="",
                role="",
                output_pattern=None,
                addr_bits=None,
                excluded="invalid fill",
                description="" if _blank(description) else str(description),
                fields=(),
            ))
            continue

        if isinstance(item_cell, str) and item_cell.strip():
            current_item = item_cell.strip()
        if isinstance(role_cell, str) and role_cell.strip():
            current_role = role_cell.strip()

        if pump_only and (logical_item_key(current_item) not in pump_items
                          or current_role not in (_ROLE_TRIM_DAC, _ROLE_PUMP_DAC)):
            rows.append(FbistPatternRow(
                excel_row, current_item, current_role, None, None,
                "outside PUMP aggregate", "" if _blank(description) else str(description), (),
            ))
            continue

        if _blank(description):
            rows.append(FbistPatternRow(
                excel_row=excel_row,
                item=current_item,
                role=current_role,
                output_pattern=None,
                addr_bits=None,
                excluded="blank",
                description="",
                fields=(),
            ))
            continue

        if (not current_item or not current_role) and not (ordinary_only and current_role == _ROLE_PUMP_DAC):
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: description 必须位于明确的 item 和 "
                "pattern role 下"
            )

        output_pattern, excluded = _resolve_output(current_item, current_role, description, excel_row)
        if ordinary_only and current_role == _ROLE_PUMP_DAC:
            excluded = "PUMP aggregate only"
        if excluded:
            rows.append(FbistPatternRow(
                excel_row=excel_row,
                item=current_item,
                role=current_role,
                output_pattern=None,
                addr_bits=None,
                excluded=excluded,
                description=str(description),
                fields=(),
            ))
            continue

        addr_bits = _resolve_addr(excel_row, record["addr"], description, fb_map_index)
        fields = _parse_fields(excel_row, description, addr_bits, fb_map_index)
        rows.append(FbistPatternRow(
            excel_row=excel_row,
            item=current_item,
            role=current_role,
            output_pattern=output_pattern,
            addr_bits=addr_bits,
            excluded="",
            description=str(description),
            fields=fields,
        ))
        if output_pattern is None or pump_only:
            continue  # pump dac rows produce no ordinary output pattern
        write = FbistPatternWrite(
            source_rows=(excel_row,),
            raw_pattern=_raw_role(role_cell),
            addr_bits=addr_bits,
            addr_int=int(addr_bits, 2),
            data_bits=_encode_data(fields),
            fields=fields,
        )
        if output_pattern not in pattern_writes:
            pattern_writes[output_pattern] = []
            pattern_order.append(output_pattern)
        pattern_writes[output_pattern].append(write)

    patterns = tuple(
        FbistOutputPattern(name, tuple(pattern_writes[name]))
        for name in pattern_order
    )
    aggregate = _compile_aggregate(rows, pump_items)
    return FbistPatternGenerationPlan(
        workbook_identity=workbook.identity,
        clk_pin=clk_pin,
        swd_pin=swd_pin,
        patterns=patterns,
        rows=tuple(rows),
        pump_aggregate=aggregate,
        pump_items=pump_items,
        dynamic_enter_patterns=dynamic_enters,
    )


def compile_fbist_label_catalog(plan: FbistPatternGenerationPlan) -> tuple[FbistFieldLabel, ...]:
    """Return the platform-neutral label catalog of the PUMP aggregate.

    Node 6 (SETVPOSP) consumes only this catalog; it never re-parses field
    names.  Chroma writes through ``<base>`` (start label only), S100 through
    ``<base>_st``/``<base>_sp``.
    """
    entries = []
    for target in plan.pump_aggregate.targets:
        base = target.field.label_base
        entries.append(FbistFieldLabel(
            logical_field_identity=f"{target.item}:{base}",
            pattern_identity=plan.pump_aggregate.pattern_name,
            item=target.item,
            field_label_base=base,
            addr_bits=target.addr_bits,
            bit_hi=target.field.bit_hi,
            bit_lo=target.field.bit_lo,
            bit_width=target.field.bit_width,
            dynamic=target.field.dynamic,
            chroma_start_label=base,
            chroma_end_label="",
            s100_start_label=f"{base}_st",
            s100_end_label=f"{base}_sp",
        ))
    return tuple(entries)


def compile_fbist_writable_field_catalog(
    plan: FbistPatternGenerationPlan,
) -> tuple[FbistWritableFieldLabel, ...]:
    """Return generated labels for dynamic fields in ordinary patterns."""
    entries = []
    for pattern in plan.patterns:
        for write in pattern.writes:
            for field in write.fields:
                if not field.dynamic:
                    continue
                try:
                    base = _SERIAL_BASES[field.line_index] + "_data"
                except IndexError as error:
                    raise FbistPatternCompileError(
                        f"pattern row {field.excel_row}: dynamic field label exceeds catalog"
                    ) from error
                entries.append(FbistWritableFieldLabel(
                    logical_field_identity=(
                        f"{pattern.pattern_name}:{field.label_base}:{field.excel_row}"
                    ),
                    pattern_identity=pattern.pattern_name,
                    bit_width=field.bit_width,
                    chroma_start_label=base,
                    s100_start_label=f"{base}_st",
                    s100_end_label=f"{base}_sp",
                ))
    return tuple(entries)


# --------------------------------------------------------------------------
# compilation helpers
# --------------------------------------------------------------------------


def _row_valid(sheet, excel_row: int) -> bool:
    """Legacy valid-row rule: the F-column fill must be the default black."""
    fill = sheet.cell(excel_row, 6).fill
    return (fill.fgColor.rgb or "") == "00000000"


def _raw_role(role_cell) -> str:
    return role_cell.strip() if isinstance(role_cell, str) else ""


def _resolve_output(item: str, role: str, description, excel_row: int):
    if role in (_ROLE_TRIM_MODE, _ROLE_TRIM_DAC, _ROLE_VERIFY_MODE):
        try:
            return pattern_output_name(item, role, description), ""
        except ValueError as exc:
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: {exc}"
            ) from exc
    if role == _ROLE_PUMP_DAC:
        return None, ""
    if role == "read_status_mode":
        return None, "read_status_mode"
    if role == "reuse dac":
        return None, "reuse dac"
    if role == _LEGACY_AGGREGATE_ROLE:
        return None, "legacy aggregate block"
    return role, ""


def _resolve_addr(excel_row: int, addr, description, fb_map_index) -> str:
    field_names = _pattern_field_names(description)
    try:
        resolved, _derived = fb_map.resolve_addr(addr, field_names, fb_map_index)
    except ValueError as exc:
        raise FbistPatternCompileError(
            f"pattern row {excel_row}: {exc}"
        ) from exc
    resolved = str(resolved).strip()
    if not _ADDR_RE.fullmatch(resolved):
        raise FbistPatternCompileError(
            f"pattern row {excel_row}: addr {resolved!r} 非法（应为 7 位 0/1）"
        )
    return resolved


def _parse_fields(
    excel_row: int, description, addr_bits: str, fb_map_index
) -> tuple[FbistPatternField, ...]:
    addr_int = int(addr_bits, 2)
    fields: list[FbistPatternField] = []
    occupied: set[int] = set()
    for line_index, line in enumerate(_description_lines(description)):
        if not _line_has_start_bit(line):
            if "=" not in line:
                raise FbistPatternCompileError(
                    f"pattern row {excel_row}: 无法解析字段行 {line!r}"
                )
            name, value = line.split("=", 1)
            try:
                start_bit = fb_map.resolve_field_start_bit(
                    name.strip(), addr_int, fb_map_index
                )
            except ValueError as exc:
                raise FbistPatternCompileError(
                    f"pattern row {excel_row}: {exc}"
                ) from exc
            line = f"{start_bit},{name.strip()}={value}"
        match = _FIELD_RE.fullmatch(line)
        if not match:
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: 无法解析字段行 {line!r}"
            )
        start_bit = int(match.group(1))
        field_name = match.group(2).strip()
        value = match.group(3)
        star = match.group(4) == "*"
        width = _field_width(field_name, len(value))
        if width != len(value):
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: 字段 {field_name} 位宽 {width} "
                f"与值 {value!r} 不一致"
            )
        bit_lo = start_bit - width + 1
        if bit_lo < 0 or start_bit >= PATTERN_DATA_WIDTH:
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: 字段行 {line!r} 超出 "
                f"{PATTERN_DATA_WIDTH}bit 寄存器范围"
            )
        overlap = [bit for bit in range(bit_lo, start_bit + 1) if bit in occupied]
        if overlap:
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: 字段位段重叠: {field_name} 与已有字段 "
                f"在 bit {overlap[0]} 冲突"
            )
        occupied.update(range(bit_lo, start_bit + 1))
        if line_index >= len(_SERIAL_BASES):
            raise FbistPatternCompileError(
                f"pattern row {excel_row}: 一行超过 {len(_SERIAL_BASES)} 个字段，"
                "无法分配串行 label"
            )
        label_base = _label_base(field_name, excel_row)
        fields.append(FbistPatternField(
            excel_row=excel_row,
            line_index=line_index,
            field_name=field_name,
            label_base=label_base,
            start_bit=start_bit,
            bit_width=width,
            bit_hi=start_bit,
            bit_lo=bit_lo,
            value=value + ("*" if star else ""),
            dynamic=star or "x" in value.lower(),
        ))
    return tuple(fields)


def _encode_data(fields: tuple[FbistPatternField, ...]) -> str:
    data = 0
    for field in fields:
        bits = field.value.rstrip("*").lower().replace("x", "0")
        if not bits:
            continue
        data |= int(bits, 2) << field.bit_lo
    return format(data & ((1 << PATTERN_DATA_WIDTH) - 1), f"0{PATTERN_DATA_WIDTH}b")


def _compile_aggregate(rows: tuple[FbistPatternRow, ...], pump_items) -> FbistPumpAggregate:
    targets: list[FbistPumpTarget] = []
    for row in rows:
        if row.excluded or row.role not in (_ROLE_TRIM_DAC, _ROLE_PUMP_DAC):
            continue
        if logical_item_key(row.item) not in pump_items:
            continue
        if not any(field.dynamic for field in row.fields):
            continue
        for field in row.fields:
            if not field.dynamic:
                continue
            targets.append(FbistPumpTarget(
                item=row.item,
                excel_row=row.excel_row,
                pattern_name=row.output_pattern or "",
                role=row.role,
                addr_bits=row.addr_bits or "",
                field=field,
            ))

    writes: list[FbistPatternWrite] = []
    by_addr: dict[str, list[FbistPumpTarget]] = {}
    for target in targets:
        by_addr.setdefault(target.addr_bits, []).append(target)

    label_bases: set[str] = set()
    for addr_bits, grouped in by_addr.items():
        fields = tuple(target.field for target in grouped)
        for field in fields:
            if field.label_base in label_bases:
                raise FbistPatternCompileError(
                    f"PUMP 聚合 Pattern {AGGREGATE_PATTERN_NAME} 内 label base 重复: "
                    f"{field.label_base!r}"
                )
            label_bases.add(field.label_base)
        _check_overlap(addr_bits, fields)
        source_rows = tuple(dict.fromkeys(field.excel_row for field in fields))
        writes.append(FbistPatternWrite(
            source_rows=source_rows,
            raw_pattern="",
            addr_bits=addr_bits,
            addr_int=int(addr_bits, 2),
            data_bits=_encode_data(fields),
            fields=fields,
        ))
    return FbistPumpAggregate(
        pattern_name=AGGREGATE_PATTERN_NAME,
        writes=tuple(writes),
        targets=tuple(targets),
    )


def _check_overlap(addr_bits: str, fields: tuple[FbistPatternField, ...]) -> None:
    occupied: set[int] = set()
    for field in fields:
        overlap = [bit for bit in range(field.bit_lo, field.bit_hi + 1) if bit in occupied]
        if overlap:
            raise FbistPatternCompileError(
                f"PUMP 聚合 addr {addr_bits}: 字段位段重叠: {field.field_name} "
                f"与已有字段在 bit {overlap[0]} 冲突"
            )
        occupied.update(range(field.bit_lo, field.bit_hi + 1))


def _field_width(field_name: str, value_width: int) -> int:
    match = re.search(r"[\[<](\d+)\s*:\s*(\d+)[\]>]", field_name)
    if not match:
        return value_width
    return abs(int(match.group(1)) - int(match.group(2))) + 1


def _label_base(field_name: str, excel_row: int) -> str:
    base = _BIT_RANGE_RE.sub("", field_name).strip().lower()
    if not base or not _IDENTIFIER_RE.fullmatch(base):
        raise FbistPatternCompileError(
            f"pattern row {excel_row}: 字段名 {field_name!r} 无法生成合法 label base"
        )
    return base


def _version_pins(workbook: WorkbookModel) -> tuple[str, str]:
    try:
        version = workbook.dataframe("VERSION")
    except KeyError as exc:
        raise FbistPatternCompileError("缺少 VERSION sheet") from exc
    if "CLK PIN" not in version.columns or "SWD PIN" not in version.columns:
        raise FbistPatternCompileError("VERSION 缺少 CLK PIN/SWD PIN 列")
    if version.empty:
        raise FbistPatternCompileError("VERSION 缺少首行 CLK PIN/SWD PIN 配置")
    clk = _text(version.iloc[0]["CLK PIN"])
    swd = _text(version.iloc[0]["SWD PIN"])
    if not clk or not swd:
        raise FbistPatternCompileError("VERSION CLK PIN/SWD PIN 不能为空")
    return clk, swd


def _pump_items(flow_frame: pd.DataFrame) -> tuple[str, ...]:
    if "PUMP" not in flow_frame.columns:
        return ()
    items: list[str] = []
    for _index, record in flow_frame.iterrows():
        pump = record.get("PUMP")
        if _blank(pump):
            continue
        if str(pump).strip().casefold() != "yes":
            continue
        item = record.get("item")
        if _blank(item):
            continue
        key = logical_item_key(str(item))
        if key and key not in items:
            items.append(key)
    return tuple(items)


def _dynamic_enter_patterns(trim_specs, recipe_rows) -> tuple[str, ...]:
    references: set[str] = set()
    try:
        if trim_specs:
            references.update(
                operation.reference
                for operation in dynamic_enter_operations(trim_specs, None)
            )
        if recipe_rows:
            references.update(
                operation.reference
                for operation in dynamic_recipe_enter_operations(recipe_rows, None)
            )
    except (TrimCompileError, FlowCompileError) as exc:
        raise FbistPatternCompileError(str(exc)) from exc
    return tuple(sorted(references))


def _pattern_field_names(description) -> list[str]:
    names = []
    for line in _description_lines(description):
        if "=" not in line:
            continue
        left = line.split("=", 1)[0]
        if _line_has_start_bit(line):
            names.append(left.split(",", 1)[1].strip())
        else:
            names.append(left.strip())
    return names


def _description_lines(description) -> list[str]:
    return [line.strip() for line in str(description).splitlines() if line.strip()]


def _line_has_start_bit(line: str) -> bool:
    if "," not in line:
        return False
    return line.split(",", 1)[0].strip().lstrip("-").isdigit()


def _blank(value) -> bool:
    return value is None or (
        isinstance(value, float) and pd.isna(value)
    ) or (
        isinstance(value, str) and not value.strip()
    )


def _text(value) -> str:
    if _blank(value):
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------
# canonicalization for the deterministic plan identity
# --------------------------------------------------------------------------


def _canonical(value, _seen: set[int] | None = None):
    from dataclasses import fields as dataclass_fields, is_dataclass

    seen = set() if _seen is None else _seen
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return "NaN" if value != value else value
    identity = id(value)
    if identity in seen:
        return type(value).__qualname__
    if is_dataclass(value):
        seen.add(identity)
        try:
            return {
                field.name: _canonical(getattr(value, field.name), seen)
                for field in dataclass_fields(value)
                if not field.name.startswith("_")
            }
        finally:
            seen.remove(identity)
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            return [
                [_canonical(key, seen), _canonical(item, seen)]
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ]
        finally:
            seen.remove(identity)
    if isinstance(value, (tuple, list, set, frozenset)):
        seen.add(identity)
        try:
            return [_canonical(item, seen) for item in value]
        finally:
            seen.remove(identity)
    return str(value)


__all__ = [
    "AGGREGATE_PATTERN_NAME",
    "FbistFieldLabel",
    "FbistOutputPattern",
    "FbistPatternArtifact",
    "FbistPatternCompileError",
    "FbistPatternField",
    "FbistPatternGenerationPlan",
    "FbistPatternGenerationResult",
    "FbistPatternRow",
    "FbistPatternWrite",
    "FbistPumpAggregate",
    "FbistPumpTarget",
    "FbistWritableFieldLabel",
    "PATTERN_DATA_WIDTH",
    "compile_fbist_label_catalog",
    "compile_fbist_writable_field_catalog",
    "compile_fbist_pattern_plan",
    "compile_ordinary_fbist_pattern_plan",
    "compile_pump_fbist_pattern_plan",
]
