"""Compile ordinary FBIST trim rows into platform-neutral execution plans.

The public interface is deliberately small: callers compile workbook rows into
``TrimSpec`` objects and tester adapters render those objects.  Search
algorithms, per-point flash actions, measurement selection, dependencies, and
final DAC adjustment remain implementation details of this module.
"""

from dataclasses import dataclass, replace
import re
from typing import Dict, Iterable, Optional, Tuple, Union

import pandas as pd

from flow_recipe import resolve_recipe_pattern_reference
from pattern_bundle import PatternCatalog, PatternCompileError, PatternField, compile_pattern_bundles
from program_gen.core.logical_item import (
    LogicalItemCatalog,
    LogicalItemError,
    logical_dac_final_symbol,
)
from program_gen.core.recipe_trim import (
    TrimRecipeError,
    TrimRecipePlan,
    compile_trim_recipe_plans,
    recipe_pattern_name,
    trim_data_helper_name,
)


class TrimCompileError(ValueError):
    """A FLOW trim row cannot be represented by the generic trim module."""


@dataclass(frozen=True)
class TrimOperation:
    kind: str
    reference: Optional[str] = None
    scope: str = "ONCE"
    wait: object = None
    value_source: Optional[str] = None
    value: Optional[str] = None
    default_value: Optional[str] = None
    field_width: Optional[int] = None
    mode: Optional[str] = None
    force_wait: object = None
    set_wait: object = None
    source_symbol: Optional[str] = None
    helper_name: Optional[str] = None


@dataclass(frozen=True)
class SearchVariant:
    kind: str
    scheduled: bool


@dataclass(frozen=True)
class LinearRange:
    """An inclusive, ascending DAC range with a constant positive step."""

    start: int
    stop: int
    step: int = 1

    def __post_init__(self) -> None:
        if self.step <= 0 or self.stop < self.start:
            raise ValueError("LinearRange must ascend with a positive step")
        if (self.stop - self.start) % self.step:
            raise ValueError("LinearRange stop must lie on its step")

    @property
    def count(self) -> int:
        return ((self.stop - self.start) // self.step) + 1

    @property
    def codes(self) -> Tuple[int, ...]:
        """Compatibility projection for callers that still consume codes."""
        return tuple(range(self.start, self.stop + 1, self.step))


@dataclass(frozen=True)
class ExplicitCodes:
    """A DAC sequence whose order is itself part of the trim semantics."""

    values: Tuple[int, ...]

    @property
    def codes(self) -> Tuple[int, ...]:
        return self.values


SearchDomain = Union[LinearRange, ExplicitCodes]


@dataclass(frozen=True, init=False)
class SearchPlan:
    search_bits: int
    domain: SearchDomain
    domain_source: str
    variants: Tuple[SearchVariant, ...]
    per_point_actions: Tuple[TrimOperation, ...]

    def __init__(
        self,
        search_bits: int,
        codes: Optional[Tuple[int, ...]] = None,
        domain_source: str = "",
        variants: Tuple[SearchVariant, ...] = (),
        per_point_actions: Tuple[TrimOperation, ...] = (),
        *,
        domain: Optional[SearchDomain] = None,
    ) -> None:
        """Create a plan, accepting legacy ``codes`` callers during migration."""
        if domain is None:
            if codes is None:
                raise TypeError("SearchPlan requires domain or legacy codes")
            domain = ExplicitCodes(tuple(codes))
        elif codes is not None and tuple(codes) != domain.codes:
            raise ValueError("SearchPlan codes and domain disagree")
        object.__setattr__(self, "search_bits", search_bits)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "domain_source", domain_source)
        object.__setattr__(self, "variants", variants)
        object.__setattr__(self, "per_point_actions", per_point_actions)

    @property
    def codes(self) -> Tuple[int, ...]:
        """Read-only compatibility projection; renderers should consume domain."""
        return self.domain.codes

    def insert_operations(
        self,
        *,
        before: str,
        operations: Iterable[TrimOperation],
    ) -> "SearchPlan":
        """Return a special-search variant with typed per-point actions inserted."""
        updated = _insert_before(self.per_point_actions, before, tuple(operations))
        for operation in updated:
            if operation.scope != "EACH_SEARCH_POINT":
                raise TrimCompileError(
                    f"SEARCH 内动作 {operation.kind} 的 scope 必须是 EACH_SEARCH_POINT"
                )
        return replace(self, per_point_actions=updated)


@dataclass(frozen=True)
class DacBinding:
    pattern_name: str
    helper_name: str
    field: PatternField
    field_width: int
    default_value: str
    write_pin: Optional[str] = None


@dataclass(frozen=True)
class MeasurementPlan:
    family: str
    unit: str
    pin: str
    force: str
    target: float
    low_limit: object
    high_limit: object
    search_low_limit: Optional[float]
    search_high_limit: Optional[float]
    sample_timeout_value: Optional[int]
    sample_timeout_unit: Optional[str]


@dataclass(frozen=True)
class DacAdjustment:
    operator: str
    threshold: float
    delta: int


@dataclass(frozen=True)
class TrimProtocolPlan:
    """Mode-entry and safe-exit resources required by a standard trim body."""

    enter_pattern: str
    exit_pattern: str


@dataclass(frozen=True)
class TrimSpec:
    flow_row_index: int
    cp: str
    item: str
    mode: str
    protocol: TrimProtocolPlan
    vcc: str
    trim_tar_reference: Optional[str]
    operations: Tuple[TrimOperation, ...]
    search: SearchPlan
    dac: DacBinding
    measurement: MeasurementPlan
    dependencies: Tuple[str, ...]
    adjust: Optional[DacAdjustment]
    dac_final_symbol: str
    relay: Optional[str]
    test_number: int
    dac_export_symbol: Optional[str] = None

    @staticmethod
    def operation(
        kind: str,
        *,
        reference: Optional[str] = None,
        scope: str = "ONCE",
        wait: object = None,
        value_source: Optional[str] = None,
        value: Optional[str] = None,
        default_value: Optional[str] = None,
        field_width: Optional[int] = None,
        mode: Optional[str] = None,
        force_wait: object = None,
        set_wait: object = None,
        source_symbol: Optional[str] = None,
        helper_name: Optional[str] = None,
    ) -> TrimOperation:
        return TrimOperation(
            kind=str(kind).strip().upper(),
            reference=reference,
            scope=str(scope).strip().upper(),
            wait=wait,
            value_source=value_source,
            value=value,
            default_value=default_value,
            field_width=field_width,
            mode=mode,
            force_wait=force_wait,
            set_wait=set_wait,
            source_symbol=source_symbol,
            helper_name=helper_name,
        )

    def insert_operations(
        self,
        *,
        before: str,
        operations: Iterable[TrimOperation],
    ) -> "TrimSpec":
        """Return a special trim plan without changing the workbook interface."""
        updated = _insert_before(self.operations, before, tuple(operations))
        for operation in updated:
            if operation.scope != "ONCE":
                raise TrimCompileError(
                    f"顶层动作 {operation.kind} 的 scope 必须是 ONCE"
                )
        return replace(self, operations=updated)


_REQUIRED_FLOW_COLUMNS = (
    "CP NO",
    "item",
    "type",
    "Recipe",
    "mode",
    "DAC bit",
    "step",
    "Bisection",
    "PE",
    "FV/FI",
    "meas pin",
    "low_range(%)",
    "target",
    "high_range(%)",
    "UNIT",
    "Vcc",
)
_ADJUST_RE = re.compile(
    r"^\s*(<=|>=|<|>|==)\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*:\s*([+-]?\d+)\s*$"
)


def compile_trim_specs(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
    version_columns: Optional[Iterable[str]] = None,
    nm_pattern_frame: Optional[pd.DataFrame] = None,
    *,
    version_frame: Optional[pd.DataFrame] = None,
    result_export_plans=None,
) -> Dict[int, TrimSpec]:
    """Compile migrated ordinary FBIST trim rows, keyed by FLOW row index.

    PDR/BOR are deliberately rejected because their search result is a digital
    status transition across supply levels, not an analogue/frequency target.
    Blank Recipe rows remain outside this seam until the new mother is filled.

    ``version_columns`` carries the VERSION sheet column names so a trim item
    whose target is declared there (e.g. ``vpose`` -> ``VPOSE_TAR``) can be
    compiled as a symbol reference instead of a literal target.  ``nm_pattern_frame``
    carries the NM_pattern sheet so an ERASE/PROGRAM per-point action resolves to
    its physical flash pattern name (``fbist_erase_main_1st_page`` etc.).
    """
    missing = [column for column in _REQUIRED_FLOW_COLUMNS if column not in flow_frame.columns]
    if missing:
        raise TrimCompileError(f"FLOW 缺少列: {', '.join(missing)}")

    migrated_trim_rows = []
    for index, record in flow_frame.iterrows():
        recipe = _text(record.get("Recipe"))
        if not recipe or _text(record.get("type")).casefold() != "trim":
            continue
        item = _text(record.get("item"))
        if _is_dedicated_trim(item):
            raise TrimCompileError(
                f"FLOW row {int(index) + 2}: {item} 必须使用专用流程，不能进入通用 TRIM"
            )
        if _text(record.get("mode")).casefold() != "fbist":
            raise TrimCompileError(
                f"FLOW row {int(index) + 2}: 通用 TRIM 当前只支持 mode=fbist"
            )
        migrated_trim_rows.append(index)

    if not migrated_trim_rows:
        return {}

    try:
        recipe_plans = compile_trim_recipe_plans(flow_frame, pattern_frame)
        catalog = compile_pattern_bundles(pattern_frame)
        item_catalog = LogicalItemCatalog.compile(flow_frame, pattern_frame)
    except (TrimRecipeError, PatternCompileError, LogicalItemError) as exc:
        raise TrimCompileError(str(exc)) from exc

    version_columns = (
        frozenset(_text(column).casefold() for column in version_columns)
        if version_columns is not None
        else frozenset()
    )
    nm_patterns = _nm_pattern_names(nm_pattern_frame)
    pattern_write_pins = _compile_pattern_write_pins(version_frame)
    specs = {}
    result_export_plans = dict(result_export_plans or {})
    test_numbers = _compile_trim_test_numbers(flow_frame, pattern_frame)
    for row_index in migrated_trim_rows:
        recipe_plan = recipe_plans.get(row_index)
        if recipe_plan is None:
            raise TrimCompileError(
                f"FLOW row {int(row_index) + 2}: Recipe 没有编译成 TrimRecipePlan"
            )
        record = flow_frame.loc[row_index]
        specs[row_index] = _compile_spec(
            record,
            row_index,
            recipe_plan,
            catalog,
            item_catalog,
            tuple(flow_frame.attrs.get("common_dac_dependencies", ())),
            version_columns,
            nm_patterns,
            test_numbers,
            pattern_write_pins,
            result_export_plans.get(row_index),
        )
    return specs


def dynamic_enter_operations(
    specs: Dict[int, TrimSpec],
    current_cp: Optional[str],
) -> Tuple[TrimOperation, ...]:
    """Return each parameterized ENTER helper once for the selected CP."""
    selected = {}
    for spec in specs.values():
        if current_cp is not None and spec.cp != str(current_cp).strip():
            continue
        for operation in spec.operations:
            if operation.kind != "ENTER" or operation.value_source != "ARGUMENT":
                continue
            previous = selected.get(operation.reference)
            if previous is not None and (
                previous.default_value != operation.default_value
                or previous.field_width != operation.field_width
            ):
                raise TrimCompileError(
                    f"pattern {operation.reference!r} 的动态 ENTER 字段定义不一致"
                )
            selected.setdefault(operation.reference, operation)
    return tuple(selected.values())


def _compile_spec(
    record: pd.Series,
    row_index: int,
    recipe_plan: TrimRecipePlan,
    catalog: PatternCatalog,
    item_catalog: LogicalItemCatalog,
    common_dependencies: Tuple[str, ...],
    version_columns: frozenset,
    nm_patterns: Dict[str, str],
    test_numbers: Dict[Tuple[str, str], int],
    pattern_write_pins: Dict[str, str],
    result_export_plan,
) -> TrimSpec:
    item = _text(record["item"])
    vcc = _text(record["Vcc"]).upper()
    trim_tar_reference = _trim_tar_reference(item, version_columns)
    trim_operation = next(operation for operation in recipe_plan.operations
                          if operation.name == "TRIM")
    default_pattern_name = recipe_pattern_name(item, "trim dac")
    if trim_operation.pattern_name.casefold() == default_pattern_name.casefold():
        dac_bundle = catalog.bundle(item)
    else:
        dac_bundle, _pattern_name = resolve_recipe_pattern_reference(
            catalog, trim_operation.pattern_name, "trim dac"
        )
    trim_step = dac_bundle.step("trim dac")
    dynamic_fields = trim_step.dynamic_fields
    if len(dynamic_fields) != 1:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: {item} 的 trim dac 必须有且只有一个 '*' 字段"
        )
    field = dynamic_fields[0]

    search = _compile_search(record, field.width, row_index)
    measurement = _compile_measurement(record, row_index)
    explicit_dependencies = tuple(
        operation.value
        for operation in recipe_plan.operations
        if operation.name == "DEPEND"
    )
    # Explicit DAC mappings may belong to a differently named Pattern item.
    # Keep same-item legacy dependencies when present; otherwise use the DAC owner.
    original_bundle = next((bundle for bundle in catalog.bundles if bundle.item == item), dac_bundle)
    legacy_dependencies = _compile_dependencies(original_bundle)
    dependencies = _ordered_unique(
        dependency
        for dependency in (
            *common_dependencies,
            *legacy_dependencies,
            *explicit_dependencies,
        )
        if item_catalog.resolve(dependency).name.casefold() != item.casefold()
    )
    adjust_operation = next(
        (operation for operation in recipe_plan.operations
         if operation.name == "DAC_ADJ"),
        None,
    )
    adjust = _compile_adjustment(
        None if adjust_operation is None else adjust_operation.value,
        row_index,
    )
    pe_action = _compile_pe(record["PE"], row_index, nm_patterns)
    per_point = [
        TrimOperation("SET_DAC", reference=trim_operation.pattern_name,
                      scope="EACH_SEARCH_POINT"),
    ]
    if pe_action is not None:
        kind, pe_pattern = pe_action
        per_point.append(
            TrimOperation(kind, reference=pe_pattern, scope="EACH_SEARCH_POINT")
        )
    per_point.append(TrimOperation("MEASURE", scope="EACH_SEARCH_POINT"))
    search = replace(search, per_point_actions=tuple(per_point))

    operations = []
    for operation in recipe_plan.operations:
        if operation.name == "ENTER":
            operations.append(
                TrimOperation(
                    "ENTER",
                    reference=operation.pattern_name,
                    wait=operation.wait,
                    value_source=operation.value_source,
                    value=operation.value,
                    default_value=operation.default_value,
                    field_width=operation.field_width,
                    mode=recipe_plan.mode,
                )
            )
        elif operation.name == "RUN":
            operations.append(
                TrimOperation(
                    "RUN",
                    reference=operation.pattern_name,
                    value_source=operation.value_source,
                    value=operation.value,
                    mode=recipe_plan.mode,
                )
            )
        elif operation.name == "DEPEND":
            continue
        elif operation.name == "TRIM":
            operations.append(
                TrimOperation(
                    "TRIM",
                    reference=operation.pattern_name,
                    value_source=operation.value_source,
                    default_value=operation.default_value,
                    field_width=operation.field_width,
                    mode=recipe_plan.mode,
                    force_wait=operation.force_wait,
                    set_wait=operation.set_wait,
                )
            )
        elif operation.name == "DAC_ADJ":
            operations.append(
                TrimOperation(
                    "DAC_ADJ",
                    reference=operation.pattern_name,
                    value_source=operation.value_source,
                    value=operation.value,
                    default_value=operation.default_value,
                    field_width=operation.field_width,
                    mode=recipe_plan.mode,
                    force_wait=operation.force_wait,
                    set_wait=operation.set_wait,
                )
            )
        elif operation.name == "JUDGE":
            operations.append(
                TrimOperation(
                    "JUDGE",
                    reference=operation.pattern_name,
                    value_source=operation.value_source,
                    default_value=operation.default_value,
                    field_width=operation.field_width,
                    mode=recipe_plan.mode,
                    force_wait=operation.force_wait,
                    set_wait=operation.set_wait,
                )
            )

    if dependencies:
        trim_index = next(
            index for index, operation in enumerate(operations)
            if operation.kind == "TRIM"
        )
        dependency_operations = tuple(
            _compile_dependency_operation(dependency, item_catalog, catalog, recipe_plan.mode)
            for dependency in dependencies
        )
        operations[trim_index:trim_index] = dependency_operations

    if result_export_plan is not None:
        operations.append(TrimOperation(
            "EXPORT", source_symbol=result_export_plan.symbol
        ))

    return TrimSpec(
        flow_row_index=int(row_index),
        cp=_text(record["CP NO"]),
        item=item,
        mode=recipe_plan.mode,
        protocol=TrimProtocolPlan(
            enter_pattern="enter_fbist_mode",
            exit_pattern="exit_fbist_mode",
        ),
        vcc=vcc,
        trim_tar_reference=trim_tar_reference,
        operations=tuple(operations),
        search=search,
        dac=DacBinding(
            pattern_name=trim_operation.pattern_name,
            helper_name=trim_data_helper_from_pattern(trim_operation.pattern_name),
            field=field,
            field_width=field.width,
            default_value=field.value,
            write_pin=pattern_write_pins.get(_text(record["CP NO"]).casefold()),
        ),
        measurement=measurement,
        dependencies=dependencies,
        adjust=adjust,
        dac_final_symbol=recipe_plan.dac_final_symbol,
        relay=_compile_relay(record.get("relay")),
        test_number=test_numbers[(_text(record["CP NO"]), item)],
        dac_export_symbol=(
            None if result_export_plan is None else result_export_plan.symbol
        ),
    )


def _compile_search(record: pd.Series, field_width: int, row_index: int) -> SearchPlan:
    try:
        search_bits = int(record["DAC bit"])
    except (TypeError, ValueError) as exc:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: DAC bit 必须是整数"
        ) from exc
    if search_bits <= 0:
        raise TrimCompileError(f"FLOW row {int(row_index) + 2}: DAC bit 必须大于 0")
    if search_bits > field_width:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: 搜索宽度 {search_bits} 超过 Pattern 字段宽度 {field_width}"
        )

    explicit = _parse_step(record["step"], row_index)
    if explicit:
        domain: SearchDomain = ExplicitCodes(explicit)
        source = "EXPLICIT_STEP"
        if len(set(explicit)) != len(explicit):
            raise TrimCompileError(f"FLOW row {int(row_index) + 2}: step 不能包含重复 DAC code")
    else:
        domain = LinearRange(0, (1 << search_bits) - 1)
        source = "FULL_RANGE"
    maximum = (1 << field_width) - 1
    if isinstance(domain, ExplicitCodes):
        invalid = [code for code in domain.codes if code < 0 or code > maximum]
    else:
        invalid = [domain.start] if domain.start < 0 else (
            [domain.stop] if domain.stop > maximum else []
        )
    if invalid:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: DAC code {invalid[0]} 超过字段范围 0..{maximum}"
        )

    variants = _compile_variants(record["Bisection"], row_index)
    return SearchPlan(
        search_bits=search_bits,
        domain=domain,
        domain_source=source,
        variants=variants,
        per_point_actions=(),
    )


def _compile_variants(value: object, row_index: int) -> Tuple[SearchVariant, ...]:
    mode = _text(value).casefold()
    if mode == "yes":
        return (SearchVariant("BISECTION", True),)
    if mode == "no":
        return (SearchVariant("FULL_SCAN", True),)
    if mode == "both_m":
        return (
            SearchVariant("BISECTION", True),
            SearchVariant("FULL_SCAN", False),
        )
    if mode == "both":
        return (
            SearchVariant("BISECTION", True),
            SearchVariant("FULL_SCAN", True),
        )
    raise TrimCompileError(
        f"FLOW row {int(row_index) + 2}: Bisection 不支持 {value!r}"
    )


def _compile_measurement(record: pd.Series, row_index: int) -> MeasurementPlan:
    unit = _text(record["UNIT"])
    normalized = unit.casefold()
    if "hz" in normalized:
        family = "FREQUENCY"
    elif normalized.endswith("a"):
        family = "CURRENT"
    elif normalized == "v":
        family = "VOLTAGE"
    else:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: TRIM UNIT 不支持 {unit!r}"
        )
    raw_target = record["target"]
    try:
        float(raw_target)
    except (TypeError, ValueError) as exc:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: target 必须是数值"
        ) from exc
    # Keep the raw numeric type: golden renders ``str(round(target ...))``, so an
    # int cell must stay int ("-3") while a float cell keeps its ".0" ("15.0").
    target = raw_target if isinstance(raw_target, (int, float)) else float(raw_target)
    # Confirmed ordinary-Trim search observation window.  All three measurement
    # families use the same target-relative window; platform renderers consume
    # the compiled values and never re-derive it.
    search_low_limit = target - 2 * abs(target)
    search_high_limit = target + 5 * abs(target)
    return MeasurementPlan(
        family=family,
        unit=unit,
        pin=_text(record["meas pin"]),
        force=_text(record["FV/FI"]),
        target=target,
        low_limit=record["low_range(%)"],
        high_limit=record["high_range(%)"],
        search_low_limit=search_low_limit,
        search_high_limit=search_high_limit,
        sample_timeout_value=50,
        sample_timeout_unit="mS" if family == "FREQUENCY" else "uS",
    )


def trim_data_helper_from_pattern(pattern_name: object) -> str:
    """Compile the confirmed ordinary-Trim DAC-pattern naming protocol."""
    pattern = _text(pattern_name)
    if not pattern.casefold().endswith("_dac"):
        raise TrimCompileError(
            f"普通 TRIM DAC Pattern {pattern!r} 必须以 '_dac' 结尾，"
            "才能编译对应 trim-data helper"
        )
    return pattern[:-4] + "_trim_data"


def _compile_relay(value: object) -> Optional[str]:
    relay = _text(value)
    return None if not relay or relay == "/" else relay


def _compile_pattern_write_pins(
    version_frame: Optional[pd.DataFrame],
) -> Dict[str, str]:
    """Compile the explicit VERSION CP→SWD PIN helper-write binding."""
    if version_frame is None:
        return {}
    required = {"CP num", "SWD PIN"}
    if not required.issubset(version_frame.columns):
        raise TrimCompileError(
            "VERSION 缺少普通 TRIM helper 所需列: "
            + ", ".join(sorted(required - set(version_frame.columns)))
        )
    result: Dict[str, str] = {}
    for _, record in version_frame.iterrows():
        cp = _text(record.get("CP num"))
        pin = _text(record.get("SWD PIN"))
        if not cp or not pin or pin == "/":
            continue
        key = cp.casefold()
        previous = result.get(key)
        if previous is not None and previous.casefold() != pin.casefold():
            raise TrimCompileError(
                f"VERSION {cp} 声明了冲突的 SWD PIN: {previous!r} / {pin!r}"
            )
        result[key] = pin
    return result


def _compile_trim_test_numbers(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
) -> Dict[Tuple[str, str], int]:
    """Compile ``TEST_NUM = Pattern execution ordinal * 50`` once upstream.

    The ordinal is the item's first executable Pattern role within its CP, not
    the Pattern-bundle ordinal and not the FLOW row.  Renderers therefore only
    consume the resulting integer and never need to re-read either worksheet.
    """
    executions_by_cp: Dict[str, Dict[str, int]] = {}
    for _, record in flow_frame.iterrows():
        if _text(record.get("type")).casefold() in ("os", "shmoo"):
            continue
        cp = _text(record.get("CP NO"))
        item = _text(record.get("item"))
        if cp and item:
            counts = executions_by_cp.setdefault(cp, {})
            counts[item] = counts.get(item, 0) + 1

    role_items = []
    current_item = ""
    for _, record in pattern_frame.iterrows():
        declared_item = _text(record.get("item"))
        if declared_item:
            current_item = declared_item
        role = _text(record.get("pattern"))
        if role and role.casefold() != "reuse dac" and current_item:
            role_items.append(current_item)

    result: Dict[Tuple[str, str], int] = {}
    for cp, execution_counts in executions_by_cp.items():
        ordinal = 0
        for item in role_items:
            count = execution_counts.get(item, 0)
            if not count:
                continue
            result.setdefault((cp, item), (ordinal + 1) * 50)
            ordinal += count
        # Newly named TRIM items can explicitly reuse existing Pattern resources.
        # Allocate after legacy ordinals so existing test numbers remain stable.
        for _, record in flow_frame.iterrows():
            item = _text(record.get('item'))
            if (_text(record.get('CP NO')) == cp and _text(record.get('type')).casefold() == 'trim'
                    and (cp, item) not in result):
                result[(cp, item)] = (ordinal + 1) * 50
                ordinal += execution_counts.get(item, 1)
    return result


def _compile_dependency_operation(
    dependency: str,
    item_catalog: LogicalItemCatalog,
    pattern_catalog: PatternCatalog,
    mode: str,
) -> TrimOperation:
    item = item_catalog.resolve(dependency)
    step = pattern_catalog.bundle(item.name).step("trim dac")
    fields = step.dynamic_fields
    if len(fields) != 1:
        raise TrimCompileError(
            f"dependency {item.name!r} trim dac must contain exactly one '*' field"
        )
    field = fields[0]
    return TrimOperation(
        "DEPEND",
        reference=item.pattern("trim dac"),
        value_source="DAC_FINAL",
        value=item.name,
        default_value=field.value,
        field_width=field.width,
        mode=mode,
        source_symbol=logical_dac_final_symbol(item.name),
        helper_name=trim_data_helper_name(item.name),
    )


def _ordered_unique(values: Iterable[str]) -> Tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        key = str(value).strip().casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(str(value).strip())
    return tuple(result)


def _compile_dependencies(bundle) -> Tuple[str, ...]:
    dependencies = []
    for step in bundle.steps:
        if step.role.casefold() != "reuse dac":
            continue
        for row in step.rows:
            dependency = _text(row.description)
            if dependency and dependency not in dependencies:
                dependencies.append(dependency)
    return tuple(dependencies)


def _compile_pe(
    value: object,
    row_index: int,
    nm_patterns: Dict[str, str],
) -> Optional[Tuple[str, str]]:
    """Resolve a FLOW PE cell to ``(kind, physical_pattern_name)``.

    ``ERASE`` -> ``page erase 1st`` pattern, ``PROGRAM`` -> ``page program PCKB
    1st`` pattern, both resolved against the NM_pattern sheet.
    """
    pe = _text(value).upper()
    if pe in ("", "/", "NO"):
        return None
    if pe == "ERASE":
        used_key = "page erase 1st"
    elif pe == "PROGRAM":
        used_key = "page program PCKB 1st"
    else:
        raise TrimCompileError(f"FLOW row {int(row_index) + 2}: PE 不支持 {value!r}")
    pattern_name = nm_patterns.get(used_key)
    if pattern_name is None:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: NM_pattern 缺少 used={used_key!r} 的 pattern"
        )
    return pe, pattern_name


def _nm_pattern_names(frame: Optional[pd.DataFrame]) -> Dict[str, str]:
    """Map NM_pattern ``used`` keys to physical pattern names (no extension)."""
    if frame is None:
        return {}
    names = {}
    for _, record in frame.iterrows():
        used = _text(record.get("used"))
        name = _text(record.get("Pattern name"))
        if used and name:
            names[used] = name.split(".")[0]
    return names


def _compile_adjustment(value: object, row_index: int) -> Optional[DacAdjustment]:
    text = _text(value)
    if text in ("", "/"):
        return None
    match = _ADJUST_RE.fullmatch(text)
    if not match:
        raise TrimCompileError(
            f"FLOW row {int(row_index) + 2}: DAC ADJ 格式应为 <1.16:+1，实际 {value!r}"
        )
    return DacAdjustment(
        operator=match.group(1),
        threshold=float(match.group(2)),
        delta=int(match.group(3)),
    )


def _parse_step(value: object, row_index: int) -> Tuple[int, ...]:
    text = _text(value)
    if text in ("", "/"):
        return ()
    codes = []
    for token in re.split(r"[,\n]+", text):
        token = token.strip()
        if not token:
            raise TrimCompileError(f"FLOW row {int(row_index) + 2}: step 包含空 token")
        range_match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", token)
        try:
            if range_match:
                start, end = (int(part) for part in range_match.groups())
                direction = 1 if end >= start else -1
                codes.extend(range(start, end + direction, direction))
            else:
                codes.append(int(token))
        except ValueError as exc:
            raise TrimCompileError(
                f"FLOW row {int(row_index) + 2}: step token 非法 {token!r}"
            ) from exc
    return tuple(codes)


def _insert_before(
    current: Tuple[TrimOperation, ...],
    before: str,
    additions: Tuple[TrimOperation, ...],
) -> Tuple[TrimOperation, ...]:
    target = str(before).strip().upper()
    indexes = [index for index, operation in enumerate(current) if operation.kind == target]
    if len(indexes) != 1:
        raise TrimCompileError(
            f"插入点 {target} 必须在计划中出现一次，实际 {len(indexes)} 次"
        )
    index = indexes[0]
    return current[:index] + additions + current[index:]


def _is_dedicated_trim(item: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", item.casefold()).strip("_")
    return normalized.startswith("pdr_") or normalized.startswith("bor_")


def _trim_tar_reference(item: str, version_columns: frozenset) -> Optional[str]:
    """Map a trim item to a VERSION-declared target symbol when one exists.

    ``vpose`` etc. appear both as a FLOW item and as a VERSION column, so the
    rendered body must compare against the ``VPOSE_TAR`` symbol rather than a
    literal target.  The item prefix before the first underscore identifies the
    VERSION column; absent that column the target stays a literal.
    """
    prefix = item.split("_")[0].casefold()
    if prefix in version_columns:
        return f"{item.split('_')[0].upper()}_TAR"
    return None


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()
