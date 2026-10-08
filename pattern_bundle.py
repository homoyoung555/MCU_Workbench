"""Compile the pattern sheet into explicit, linkable item bundles."""
from dataclasses import dataclass
import re
from typing import Dict, Optional, Tuple

import pandas as pd


class PatternCompileError(ValueError):
    """The pattern sheet or a Recipe-to-pattern link is invalid."""


@dataclass(frozen=True)
class PatternField:
    excel_row: int
    start_bit: int
    name: str
    value: str
    dynamic: bool

    @property
    def width(self) -> int:
        match = re.search(r"\[(\d+)\s*:\s*(\d+)\]", self.name)
        if match:
            return abs(int(match.group(1)) - int(match.group(2))) + 1
        return len(self.value)


@dataclass(frozen=True)
class PatternRow:
    excel_row: int
    addr: object
    description: str
    fields: Tuple[PatternField, ...]


@dataclass(frozen=True)
class PatternStep:
    role: str
    rows: Tuple[PatternRow, ...]

    @property
    def dynamic_fields(self) -> Tuple[PatternField, ...]:
        return tuple(field for row in self.rows for field in row.fields if field.dynamic)


@dataclass(frozen=True)
class PatternBundle:
    item: str
    steps: Tuple[PatternStep, ...]

    def step(self, role: str) -> PatternStep:
        normalized = role.strip().casefold()
        matches = [step for step in self.steps if step.role.casefold() == normalized]
        if len(matches) != 1:
            raise PatternCompileError(
                f"pattern item {self.item!r} 需要且只能有一个 role={role!r}，实际 {len(matches)} 个"
            )
        return matches[0]


@dataclass(frozen=True)
class PatternCatalog:
    bundles: Tuple[PatternBundle, ...]

    def bundle(self, item: str) -> PatternBundle:
        matches = [bundle for bundle in self.bundles if bundle.item == item]
        if len(matches) != 1:
            raise PatternCompileError(
                f"FLOW item {item!r} 需要且只能 link 一个 pattern bundle，实际 {len(matches)} 个"
            )
        return matches[0]


@dataclass(frozen=True)
class DynamicBinding:
    field: PatternField
    value: str


_FIELD_RE = re.compile(r"^\s*(\d+)\s*,\s*([^=]+?)\s*=\s*([01xX]+)(\*)?\s*$")


def parse_pattern_fields(description: object, excel_row: int) -> Tuple[PatternField, ...]:
    if _blank(description):
        return ()
    fields = []
    for line in str(description).splitlines():
        match = _FIELD_RE.fullmatch(line)
        if not match:
            continue
        value = match.group(3)
        dynamic = match.group(4) == "*"
        if dynamic and any(bit not in "01" for bit in value):
            raise PatternCompileError(
                f"pattern row {excel_row}: '*' 字段必须同时给出 0/1 默认值，不能使用 x"
            )
        field = PatternField(
            excel_row=excel_row,
            start_bit=int(match.group(1)),
            name=match.group(2).strip(),
            value=value,
            dynamic=dynamic,
        )
        if field.width != len(value):
            raise PatternCompileError(
                f"pattern row {excel_row}: 字段 {field.name} 位宽 {field.width} 与值 {value!r} 不一致"
            )
        fields.append(field)
    return tuple(fields)


def compile_pattern_bundles(frame: pd.DataFrame) -> PatternCatalog:
    required = ("item", "addr", "description", "pattern")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise PatternCompileError(f"pattern 缺少列: {', '.join(missing)}")

    item_order = []
    step_order: Dict[str, list] = {}
    rows_by_step: Dict[tuple, list] = {}
    closed_roles: Dict[str, set] = {}
    closed_items = set()
    current_item = None
    current_role = None

    for index, record in frame.iterrows():
        excel_row = int(index) + 2
        item_value = None if _blank(record["item"]) else str(record["item"]).strip()
        role_value = None if _blank(record["pattern"]) else str(record["pattern"]).strip()

        if item_value is not None and item_value != current_item:
            if current_item is not None:
                closed_items.add(current_item)
            if item_value in closed_items:
                raise PatternCompileError(
                    f"pattern row {excel_row}: item {item_value!r} 必须集中在一个连续块内"
                )
            current_item = item_value
            current_role = None
            if current_item not in step_order:
                item_order.append(current_item)
                step_order[current_item] = []
                closed_roles[current_item] = set()

        if role_value is not None and role_value != current_role:
            if current_item is None:
                raise PatternCompileError(f"pattern row {excel_row}: pattern role 缺少 item")
            if role_value in closed_roles[current_item]:
                raise PatternCompileError(
                    f"pattern row {excel_row}: item {current_item!r} 的 role {role_value!r} 必须连续"
                )
            if current_role is not None:
                closed_roles[current_item].add(current_role)
            current_role = role_value
            if role_value not in step_order[current_item]:
                step_order[current_item].append(role_value)
                rows_by_step[(current_item, role_value)] = []

        if _blank(record["description"]):
            continue
        if current_item is None or current_role is None:
            raise PatternCompileError(
                f"pattern row {excel_row}: description 必须位于明确的 item 和 pattern role 下"
            )
        rows_by_step[(current_item, current_role)].append(
            PatternRow(
                excel_row=excel_row,
                addr=record["addr"],
                description=str(record["description"]),
                fields=parse_pattern_fields(record["description"], excel_row),
            )
        )

    bundles = []
    for item in item_order:
        steps = tuple(
            PatternStep(role, tuple(rows_by_step[(item, role)]))
            for role in step_order[item]
        )
        bundles.append(PatternBundle(item, steps))
    return PatternCatalog(tuple(bundles))


def bind_dynamic_argument(
    catalog: PatternCatalog,
    item: str,
    role: str,
    argument: Optional[str],
) -> DynamicBinding:
    """Bind ENTER/DAC_WRITE's single binary argument to one starred field."""
    step = catalog.bundle(item).step(role)
    fields = step.dynamic_fields
    if len(fields) != 1:
        raise PatternCompileError(
            f"pattern item {item!r} role {role!r} 需要且只能有一个 '*' 字段，实际 {len(fields)} 个"
        )
    field = fields[0]
    value = field.value if argument is None else argument
    if not re.fullmatch(r"[01]+", value):
        raise PatternCompileError(f"动态参数必须是二进制，实际 {value!r}")
    if len(value) != field.width:
        raise PatternCompileError(
            f"动态参数 {value!r} 位宽 {len(value)} 与 {field.name} 的 {field.width} 位不一致"
        )
    return DynamicBinding(field=field, value=value)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or (
        isinstance(value, str) and not value.strip()
    )
