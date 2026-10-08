"""Compile FLOW Recipe cells into platform-neutral function plans.

This neutral module is the seam shared by preflight and both tester adapters. It
owns Recipe parsing, FLOW row identity, duplicate detection, and function
grouping so platform writers never need to reinterpret spreadsheet strings.
"""
from dataclasses import dataclass
import re
from typing import Iterable, Optional, Tuple, Union

import pandas as pd

from pattern_bundle import (
    PatternCatalog,
    PatternCompileError,
    PatternField,
    bind_dynamic_argument,
    compile_pattern_bundles,
)
from program_gen.core.trim_mode import TrimModeError, trim_mode_adapter
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_key
from program_gen.core.sram_capture import (
    SramCaptureArgument,
    SramCaptureCompileError,
    parse_sram_capture_argument,
)


class FlowCompileError(ValueError):
    """The FLOW/Recipe workbook contract is invalid."""


def _validate_sram_capture_call(
    name: str,
    argument: Optional[str],
    sram_capture: Optional[SramCaptureArgument],
) -> None:
    if name == "SRAM_CAPTURE":
        if (
            not isinstance(sram_capture, SramCaptureArgument)
            or argument != sram_capture.canonical_spec
        ):
            raise FlowCompileError(
                "SRAM_CAPTURE raw argument 必须与 typed argument 完全一致"
            )
    elif sram_capture is not None:
        raise FlowCompileError(f"{name} 不能携带 SRAM_CAPTURE typed argument")


@dataclass(frozen=True)
class RecipeDuration:
    amount: int
    unit: str

    @property
    def canonical(self) -> str:
        return f"{self.amount}{self.unit}"


@dataclass(frozen=True)
class RecipeParameter:
    name: str
    value: Union[RecipeDuration, str]


@dataclass(frozen=True)
class RecipeValueToken:
    kind: str
    token: str


@dataclass(frozen=True)
class RecipeAssignment:
    field: str
    value: RecipeValueToken


@dataclass(frozen=True)
class RecipeCall:
    name: str
    argument: Optional[str] = None
    parameters: Tuple[RecipeParameter, ...] = ()
    assignments: Tuple[RecipeAssignment, ...] = ()
    sram_capture: Optional[SramCaptureArgument] = None

    def __post_init__(self) -> None:
        _validate_sram_capture_call(self.name, self.argument, self.sram_capture)

    def time_parameter(self, name: str) -> Optional[RecipeDuration]:
        canonical_name = str(name).strip().upper()
        return next(
            (parameter.value for parameter in self.parameters
             if parameter.name == canonical_name),
            None,
        )

    def named_parameter(self, name: str) -> Optional[str]:
        canonical_name = str(name).strip().upper()
        value = next(
            (parameter.value for parameter in self.parameters
             if parameter.name == canonical_name),
            None,
        )
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class FlowFunctionKey:
    cp: str
    item: str
    flow_type: str


@dataclass(frozen=True)
class FlowRow:
    excel_row: int
    cp: str
    item: str
    flow_type: str
    sub: str
    mode: str
    recipe: Tuple[RecipeCall, ...]


@dataclass(frozen=True)
class FlowFunctionPlan:
    key: FlowFunctionKey
    rows: Tuple[FlowRow, ...]


@dataclass(frozen=True)
class FlowProgram:
    functions: Tuple[FlowFunctionPlan, ...]


@dataclass(frozen=True)
class ResolvedRecipeCall:
    name: str
    argument: Optional[str]
    pattern_role: Optional[str] = None
    pattern_name: Optional[str] = None
    pattern_explicit: bool = False
    dynamic_field: Optional[PatternField] = None
    value_source: Optional[str] = None
    value: Optional[str] = None
    requires_set_helper: bool = False
    parameters: Tuple[RecipeParameter, ...] = ()
    assignments: Tuple[RecipeAssignment, ...] = ()
    sram_capture: Optional[SramCaptureArgument] = None

    def __post_init__(self) -> None:
        _validate_sram_capture_call(self.name, self.argument, self.sram_capture)

    def time_parameter(self, name: str) -> Optional[RecipeDuration]:
        canonical_name = str(name).strip().upper()
        return next(
            (parameter.value for parameter in self.parameters
             if parameter.name == canonical_name),
            None,
        )

    def named_parameter(self, name: str) -> Optional[str]:
        canonical_name = str(name).strip().upper()
        value = next(
            (parameter.value for parameter in self.parameters
             if parameter.name == canonical_name),
            None,
        )
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class ExecutableFlowRow:
    flow: FlowRow
    operations: Tuple[ResolvedRecipeCall, ...]


@dataclass(frozen=True)
class ExecutableFunctionPlan:
    key: FlowFunctionKey
    rows: Tuple[ExecutableFlowRow, ...]


@dataclass(frozen=True)
class RecipeProgram:
    functions: Tuple[ExecutableFunctionPlan, ...]


@dataclass(frozen=True)
class DynamicRecipeEnter:
    reference: str
    default_value: str
    field_width: int


@dataclass(frozen=True)
class DacWritePlan:
    flow_row_index: int
    item: str
    dac_symbol: str
    pattern_name: str
    helper_name: str
    default_value: str
    field_width: int
    value_source: str
    value: Optional[str]
    needs_global_variable: bool
    needs_set_helper: bool


@dataclass(frozen=True)
class DacWritePlanSet:
    plans: Tuple[DacWritePlan, ...]

    def for_row(self, flow_row_index: int) -> Optional[DacWritePlan]:
        return next(
            (plan for plan in self.plans if plan.flow_row_index == flow_row_index),
            None,
        )

    @property
    def global_symbols(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(
            plan.dac_symbol for plan in self.plans if plan.needs_global_variable
        ))

    @property
    def helper_plans(self) -> Tuple[DacWritePlan, ...]:
        selected = {}
        for plan in self.plans:
            if plan.needs_set_helper:
                selected.setdefault(plan.pattern_name, plan)
        return tuple(selected.values())


@dataclass(frozen=True)
class ResultExportPlan:
    flow_row_index: int
    item: str
    sub: str
    flow_type: str
    source_kind: str
    format: str
    symbol: str
    c_type: str
    explicit: bool
    implied_by_uid: bool
    persist_to_uid: bool = False
    persist_to_otp: bool = False
    unit: str = ""


@dataclass(frozen=True)
class ResultExportPlanSet:
    plans: Tuple[ResultExportPlan, ...]

    def for_row(self, flow_row_index: int) -> Optional[ResultExportPlan]:
        return next(
            (plan for plan in self.plans if plan.flow_row_index == flow_row_index),
            None,
        )

    @property
    def global_declarations(self) -> Tuple[Tuple[str, str], ...]:
        return tuple(dict.fromkeys(
            (plan.c_type, plan.symbol)
            for plan in self.plans
            if plan.source_kind != "DAC_FINAL"
        ))


_MODULE_ARGUMENTS = {
    "FREQ_TEST": False,
    "OPA_TEST": False,
    "DAC_TEST": False,
    "BUILD": False,
    "BUILDMAP": False,
    "BUILDUID": False,
    "CAL": False,
    "CAPTURE": False,
    "ADC_JUDGE": False,
    "CHECK": False,
    "CHECKID": False,
    "CHECKOTP": True,
    "COMMIT": True,
    "CONCAT": False,
    "DAC_ADJ": True,
    "DAC_WRITE": True,
    "DC_TEST": False,
    "DEPEND": True,
    "ENTER": True,
    "EXPORT": False,
    "JUDGE": False,
    "LOADMAP": True,
    "LOOPNM": False,
    "NMLOOP": False,
    "NM_TEST": True,
    "VT_TEST": True,
    "VIH_VIL_TEST": False,
    "MARGIN_TEST": True,
    "PVD_TEST": False,
    "PGMOTP": True,
    "READID": False,
    "READOTPMAP": True,
    "REBUILD": True,
    "RUN": True,
    "RUN_SEQUENCE": False,
    "SRAM_CAPTURE": True,
    "SWD_CAPTURE": False,
    "SETVPOSP": False,
    "TRIM": False,
}
_MODULE_TIME_PARAMETERS = {
    "ENTER": frozenset(("WAIT",)),
    "TRIM": frozenset(("FWAIT", "SWAIT")),
    "DAC_ADJ": frozenset(("FWAIT", "SWAIT")),
    "JUDGE": frozenset(("FWAIT", "SWAIT")),
}
_MODULE_TEXT_PARAMETERS = {
    "ENTER": {
        "ROLE": frozenset(("TRIM", "VERIFY")),
        "SHMOO": frozenset(("STEP",)),
    },
    "DAC_WRITE": {"SHMOO": frozenset(("STEP",))},
    "EXPORT": {"FORMAT": frozenset(("RAW", "BCD16_MV", "ADC12_3V3"))},
    "JUDGE": {"PF": frozenset(("YES", "NO"))},
}
_MODULE_PATTERN_PARAMETERS = frozenset(("ENTER", "TRIM"))
_CALL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(?:\((.*)\))?$")
_DURATION_RE = re.compile(r"^(\d+)\s*(US|MS)$", re.IGNORECASE)
_DAC_ADJ_RE = re.compile(
    r"^(?:(?:<=|>=|<|>|==)\s*-?(?:\d+(?:\.\d*)?|\.\d+)\s*:\s*[+-]\d+|"
    r"[+-]\d+|[A-Za-z_][A-Za-z0-9_]*\s*(?:<=|>=|<|>)\s*"
    r"-?(?:\d+(?:\.\d*)?|\.\d+)\s*:\s*[A-Za-z_][A-Za-z0-9_]*\s*[+-]\d+)$"
)
_COMMIT_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_COMMIT_DECIMAL_RE = re.compile(r"^\d+$")
_COMMIT_HEX_RE = re.compile(r"^0[xX][0-9A-Fa-f]+$")
_COMMIT_BINARY_RE = re.compile(r"^0[bB][01]+$")


def parse_recipe(value: object) -> Tuple[RecipeCall, ...]:
    """Parse one Recipe cell using ``-`` or a newline as the separator.

    Arguments follow each module's grammar. Binary strings retain leading zeroes.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise FlowCompileError("Recipe 不能为空")
    raw = str(value).strip()
    if not raw:
        raise FlowCompileError("Recipe 不能为空")

    tokens = []
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        if not line.strip():
            continue
        line_tokens = _split_recipe_line(line)
        if any(not token.strip() for token in line_tokens):
            raise FlowCompileError(f"Recipe 语法非法: {line!r}")
        tokens.extend(line_tokens)

    calls = []
    for token in tokens:
        token = token.strip()
        match = _CALL_RE.fullmatch(token)
        if not match:
            raise FlowCompileError(f"Recipe 语法非法: {token!r}")
        name = match.group(1).upper()
        name = {"VT": "VT_TEST", "MARGIN": "MARGIN_TEST"}.get(name, name)
        raw_arguments = match.group(2)
        if name not in _MODULE_ARGUMENTS:
            raise FlowCompileError(f"未知 Recipe 模块: {name}")
        assignments = ()
        sram_capture = None
        if name == "COMMIT":
            argument, parameters, assignments = _parse_commit_arguments(raw_arguments)
        elif name == "SRAM_CAPTURE":
            try:
                sram_capture = parse_sram_capture_argument(raw_arguments)
            except SramCaptureCompileError as exc:
                raise FlowCompileError(str(exc)) from exc
            argument = sram_capture.canonical_spec
            parameters = ()
        else:
            argument, parameters = _parse_call_arguments(name, raw_arguments)
        if name == "RUN" and argument is None:
            raise FlowCompileError("RUN 必须填写 Pattern 名")
        calls.append(RecipeCall(
            name=name,
            argument=argument,
            parameters=parameters,
            assignments=assignments,
            sram_capture=sram_capture,
        ))
    return tuple(calls)


def _split_recipe_line(line: str) -> list[str]:
    """Split module separators without treating signed arguments as separators."""
    tokens = []
    start = 0
    depth = 0
    for index, character in enumerate(line):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise FlowCompileError(f"Recipe 语法非法: {line!r}")
        elif character == "-" and depth == 0:
            tokens.append(line[start:index])
            start = index + 1
    if depth != 0:
        raise FlowCompileError(f"Recipe 语法非法: {line!r}")
    tokens.append(line[start:])
    return tokens


def _parse_commit_arguments(
    raw_arguments: Optional[str],
) -> Tuple[Optional[str], Tuple[RecipeParameter, ...], Tuple[RecipeAssignment, ...]]:
    if raw_arguments is None:
        return None, (), ()
    if not raw_arguments.strip():
        raise FlowCompileError("Recipe 语法非法: COMMIT()")

    parts = [part.strip() for part in raw_arguments.split(",")]
    if any(not part or "=" not in part for part in parts):
        raise FlowCompileError(f"Recipe 语法非法: COMMIT({raw_arguments})")

    assignments = []
    assigned_fields = set()
    for part in parts:
        field, raw_value = (piece.strip() for piece in part.split("=", 1))
        if not _COMMIT_FIELD_RE.fullmatch(field) or not raw_value:
            raise FlowCompileError(f"Recipe 语法非法: COMMIT({part})")
        canonical_field = field.casefold()
        if canonical_field in assigned_fields:
            raise FlowCompileError(f"COMMIT 字段 {field} 重复赋值")
        assigned_fields.add(canonical_field)
        if _COMMIT_DECIMAL_RE.fullmatch(raw_value):
            value = RecipeValueToken(kind="DECIMAL", token=raw_value)
        elif _COMMIT_HEX_RE.fullmatch(raw_value):
            value = RecipeValueToken(kind="HEX", token=raw_value)
        elif _COMMIT_BINARY_RE.fullmatch(raw_value):
            value = RecipeValueToken(kind="BINARY", token=raw_value)
        elif raw_value.casefold() == "step":
            value = RecipeValueToken(kind="STEP", token="STEP")
        elif _COMMIT_FIELD_RE.fullmatch(raw_value):
            value = RecipeValueToken(kind="VARIABLE", token=raw_value)
        else:
            raise FlowCompileError(
                "COMMIT 右值只接受十进制、0x、0b、STEP 或变量标识符，"
                f"实际 {raw_value!r}"
            )
        assignments.append(RecipeAssignment(field=field, value=value))
    return None, (), tuple(assignments)


def _parse_call_arguments(
    module_name: str,
    raw_arguments: Optional[str],
) -> Tuple[Optional[str], Tuple[RecipeParameter, ...]]:
    if raw_arguments is None:
        return None, ()
    if not raw_arguments.strip():
        raise FlowCompileError(f"Recipe 语法非法: {module_name}()")

    parts = [part.strip() for part in raw_arguments.split(",")]
    if any(not part for part in parts):
        raise FlowCompileError(f"Recipe 语法非法: {module_name}({raw_arguments})")

    argument = None
    parameters = []
    parameter_names = set()
    allowed_parameters = _MODULE_TIME_PARAMETERS.get(module_name, frozenset())
    for part in parts:
        is_dac_adj_argument = (
            module_name == "DAC_ADJ" and _DAC_ADJ_RE.fullmatch(part) is not None
        )
        if "=" not in part or is_dac_adj_argument:
            if module_name == "NM_TEST":
                part = part.casefold()
                if part not in ("normal", "repair"):
                    raise FlowCompileError("NM_TEST 位置参数只能是 normal/repair")
            elif module_name in ("VT_TEST", "MARGIN_TEST"):
                if not re.fullmatch(r"NM|OTP-[A-Za-z][A-Za-z0-9_]*", part, re.I):
                    raise FlowCompileError(f"{module_name} 位置参数只能是 NM 或 OTP-页面名")
                part = "NM" if part.upper() == "NM" else "OTP-" + part[4:].casefold()
            elif module_name == "DAC_ADJ":
                if not _DAC_ADJ_RE.fullmatch(part):
                    raise FlowCompileError(f"Recipe 语法非法: {module_name}({part})")
            elif module_name in (
                "DEPEND", "RUN", "READOTPMAP", "LOADMAP", "CHECKOTP", "PGMOTP"
            ):
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", part):
                    raise FlowCompileError(f"Recipe 语法非法: {module_name}({part})")
                if module_name in ("READOTPMAP", "LOADMAP", "CHECKOTP", "PGMOTP"):
                    if part.casefold() != "uid":
                        raise FlowCompileError(
                            f"{module_name} 第一版位置参数只支持 UID，实际 {part!r}"
                        )
                    part = "UID"
            elif not re.fullmatch(r"[01]+", part):
                raise FlowCompileError(f"Recipe 语法非法: {module_name}({part})")
            if not _MODULE_ARGUMENTS[module_name]:
                raise FlowCompileError(f"{module_name} 不接受参数")
            if argument is not None:
                raise FlowCompileError(f"{module_name} 只能有一个位置参数")
            argument = part
            continue

        key, raw_value = (piece.strip() for piece in part.split("=", 1))
        key = key.upper()
        if key == "PATTERN" and module_name in _MODULE_PATTERN_PARAMETERS:
            if key in parameter_names:
                raise FlowCompileError(f"{module_name} 参数 {key} 重复")
            value = raw_value.strip()
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
                raise FlowCompileError(
                    f"{module_name} 参数 PATTERN 必须是完整 Pattern 名，实际 {raw_value!r}"
                )
            parameter_names.add(key)
            parameters.append(RecipeParameter(name=key, value=value))
            continue
        text_parameters = _MODULE_TEXT_PARAMETERS.get(module_name, {})
        if key in text_parameters:
            if key in parameter_names:
                raise FlowCompileError(f"{module_name} 参数 {key} 重复")
            canonical_value = raw_value.strip().upper()
            if canonical_value not in text_parameters[key]:
                allowed = "/".join(sorted(text_parameters[key]))
                raise FlowCompileError(
                    f"{module_name} 参数 {key} 只能是 {allowed}，实际 {raw_value!r}"
                )
            parameter_names.add(key)
            parameters.append(RecipeParameter(name=key, value=canonical_value))
            continue
        if key not in allowed_parameters:
            raise FlowCompileError(f"{module_name} 不接受参数 {key}")
        if key in parameter_names:
            raise FlowCompileError(f"{module_name} 参数 {key} 重复")
        duration_match = _DURATION_RE.fullmatch(raw_value)
        if not duration_match:
            raise FlowCompileError(
                f"{module_name} 参数 {key} 必须是非负整数加 US/MS，实际 {raw_value!r}"
            )
        parameter_names.add(key)
        parameters.append(
            RecipeParameter(
                name=key,
                value=RecipeDuration(
                    amount=int(duration_match.group(1)),
                    unit=duration_match.group(2).upper(),
                ),
            )
        )
    return argument, tuple(parameters)


def default_id_recipe(item: str, flow_type: str) -> str | None:
    """Only formal ID and ordinary UID have implicit Recipe presets."""
    flow_type = str(flow_type).strip().casefold()
    if flow_type not in ("id", "uid"):
        return None
    # uid_plan also consumes parsed Recipes; defer this import until compilation.
    from program_gen.core.uid_plan import IdPlanError, parse_standard_id_item

    try:
        canonical, target = parse_standard_id_item(item, flow_type)
    except IdPlanError as exc:
        raise FlowCompileError(str(exc)) from exc
    if flow_type == "id":
        return "READID" if canonical.startswith("Read_") else "CHECKID"
    return "COMMIT-PGMOTP(UID)" if target.kind == "ID" else None


def default_recipe(item: str, flow_type: str, mode: str | None = None) -> str | None:
    if (
        str(flow_type).strip().casefold() == "trim"
        and str(mode).strip().casefold() == "fbist"
        and logical_item_key(item) not in {
            logical_item_key("Pdr_Trim"),
            logical_item_key("Bor_Trim"),
        }
    ):
        return "ENTER-TRIM-JUDGE"
    if (
        str(flow_type).strip().casefold() == "verify"
        and logical_item_key(item) == logical_item_key("DC_VIHVIL_Test")
        and str(mode).strip().casefold() in ("swd", "keil")
    ):
        return "VIH_VIL_TEST"
    if (
        str(flow_type).strip().casefold() == "verify"
        and logical_item_key(item) == logical_item_key("Adc_Test")
        and str(mode).strip().casefold() == "swd"
    ):
        # Formal-master migration default. Native ADC phases still retain this
        # explicit module chain; ADC_TEST itself is not a same-name deep Recipe.
        return "SWD_CAPTURE-ADC_JUDGE"
    if str(flow_type).strip().casefold() == "main":
        return "NM_TEST"
    if str(flow_type).strip().casefold() == "vt":
        return "VT_TEST"
    if str(flow_type).strip().casefold() == "margin":
        return "MARGIN_TEST"
    return default_id_recipe(item, flow_type)


def compile_flow(frame: pd.DataFrame) -> FlowProgram:
    """Compile all FLOW rows into ordered ``item + type`` function plans.

    A concrete row is identified by ``CP + item + type + sub``.  Recipe is
    behaviour, not identity.  Within one CP, rows sharing ``item + type`` must
    be contiguous and their subs remain in workbook order.
    """
    required = ("CP NO", "item", "type", "sub", "Recipe")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise FlowCompileError(f"FLOW 缺少列: {', '.join(missing)}")

    plans = []
    current_key = None
    current_rows = []
    closed_keys = set()
    identities = set()

    def flush_current():
        if current_key is not None:
            plans.append(FlowFunctionPlan(current_key, tuple(current_rows)))

    for index, record in frame.iterrows():
        excel_row = int(index) + 2
        cp = _required_text(record["CP NO"], "CP NO", excel_row)
        item = _required_text(record["item"], "item", excel_row)
        flow_type = _required_text(record["type"], "type", excel_row).lower()
        sub = _required_text(record["sub"], "sub", excel_row)
        mode = (
            _required_text(record["mode"], "mode", excel_row).casefold()
            if "mode" in frame.columns
            else "fbist"
        )
        key = FlowFunctionKey(cp=cp, item=item, flow_type=flow_type)
        identity = (cp, item, flow_type, sub)

        if identity in identities:
            raise FlowCompileError(
                f"FLOW row {excel_row}: 重复 FLOW 行身份 CP+item+type+sub={identity!r}"
            )
        identities.add(identity)

        if current_key != key:
            if key in closed_keys:
                raise FlowCompileError(
                    f"FLOW row {excel_row}: 同一 CP 下 item+type 行必须连续: "
                    f"{cp}/{item}/{flow_type}"
                )
            if current_key is not None:
                closed_keys.add(current_key)
                flush_current()
            current_key = key
            current_rows = []

        try:
            raw_recipe = record["Recipe"]
            if pd.isna(raw_recipe) or not str(raw_recipe).strip():
                raw_recipe = default_recipe(item, flow_type, mode)
            recipe = parse_recipe(raw_recipe)
        except FlowCompileError as exc:
            raise FlowCompileError(f"FLOW row {excel_row}: {exc}") from exc
        row = FlowRow(
            excel_row=excel_row,
            cp=cp,
            item=item,
            flow_type=flow_type,
            sub=sub,
            mode=mode,
            recipe=recipe,
        )
        _validate_export_recipe(row)
        current_rows.append(row)

    flush_current()
    return FlowProgram(functions=tuple(plans))


def compile_recipe_program(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
    trim_keys: Optional[set[tuple[str, str]]] = None,
) -> RecipeProgram:
    """Compile workbook rows into operations with all pattern links resolved."""
    flow = compile_flow(flow_frame)
    catalog = compile_pattern_bundles(pattern_frame)
    trim_keys = _flow_trim_keys(flow_frame) if trim_keys is None else trim_keys
    functions = []
    for function in flow.functions:
        rows = []
        for row in function.rows:
            operations = tuple(
                _resolve_call(row, call, catalog, trim_keys) for call in row.recipe
            )
            _validate_dac_write_order(row, operations)
            _validate_export_order(row, operations)
            rows.append(ExecutableFlowRow(flow=row, operations=operations))
        functions.append(ExecutableFunctionPlan(key=function.key, rows=tuple(rows)))
    return RecipeProgram(functions=tuple(functions))


def compile_recipe_rows(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
) -> dict[int, ExecutableFlowRow]:
    """Compile only migrated Recipe rows and key them by FLOW dataframe index."""
    if "Recipe" not in flow_frame.columns:
        return {}
    recipe_text = flow_frame["Recipe"].fillna("").astype(str).str.strip()
    selected = recipe_text.ne("")
    for index, record in flow_frame.loc[~selected].iterrows():
        if default_recipe(
            record.get("item", ""),
            record.get("type", ""),
            record.get("mode", ""),
        ) is not None:
            selected.loc[index] = True
    migrated = flow_frame.loc[selected]
    if migrated.empty:
        return {}
    program = compile_recipe_program(
        migrated, pattern_frame, trim_keys=_flow_trim_keys(flow_frame)
    )
    return {
        executable_row.flow.excel_row - 2: executable_row
        for function in program.functions
        for executable_row in function.rows
    }


def _flow_trim_keys(flow_frame: pd.DataFrame) -> set[tuple[str, str]]:
    return {
        (str(record["CP NO"]).strip().casefold(), logical_item_key(record["item"]))
        for _, record in flow_frame.iterrows()
        if str(record.get("type", "")).strip().casefold() == "trim"
    }


def recipe_setup_operations(row: ExecutableFlowRow) -> Tuple[ResolvedRecipeCall, ...]:
    """Return the ordered ENTER/RUN prefix without silently reordering Recipe."""
    operations = row.operations
    prefix_length = 0
    while (prefix_length < len(operations)
           and operations[prefix_length].name in ("ENTER", "RUN")):
        prefix_length += 1
    if any(operation.name in ("ENTER", "RUN")
           for operation in operations[prefix_length:]):
        raise FlowCompileError(
            f"FLOW row {row.flow.excel_row}: ENTER/RUN 必须连续位于流程前部"
        )
    return operations[:prefix_length]


def dynamic_recipe_enter_operations(
    rows: dict[int, ExecutableFlowRow],
    current_cp: Optional[str],
) -> Tuple[DynamicRecipeEnter, ...]:
    """Return each runtime-written ENTER helper once across all migrated rows."""
    selected = {}
    for row in rows.values():
        if current_cp is not None and row.flow.cp != str(current_cp).strip():
            continue
        for operation in row.operations:
            runtime_enter = (
                operation.value_source == "ARGUMENT"
                or (row.flow.flow_type == "shmoo" and operation.value_source == "DEFAULT")
                or operation.named_parameter("SHMOO") == "STEP"
            )
            if (operation.name != "ENTER"
                    or not runtime_enter
                    or operation.dynamic_field is None):
                continue
            reference = operation.pattern_name or _recipe_pattern_name(
                row.flow.item, operation.pattern_role
            )
            helper = DynamicRecipeEnter(
                reference=reference,
                default_value=operation.dynamic_field.value,
                field_width=operation.dynamic_field.width,
            )
            previous = selected.get(reference)
            if previous is not None and previous != helper:
                raise FlowCompileError(
                    f"pattern {reference!r} 的动态 ENTER 字段定义不一致"
                )
            selected.setdefault(reference, helper)
    return tuple(selected.values())


def compile_dac_write_plan_set(
    rows: dict[int, ExecutableFlowRow],
    current_cp: Optional[str],
) -> DacWritePlanSet:
    """Compile every DAC_WRITE decision for one CP into one shared plan set."""
    plans = []
    for flow_row_index, row in rows.items():
        if current_cp is not None and row.flow.cp != str(current_cp).strip():
            continue
        for operation in row.operations:
            if (operation.name != "DAC_WRITE"
                    or operation.dynamic_field is None):
                continue
            pattern_name = _recipe_dac_pattern_name(row.flow.item)
            item_slug = re.sub(
                r"[^A-Za-z0-9]+", "_", str(row.flow.item).strip()
            ).strip("_").lower()
            item_slug = re.sub(
                r"_(?:trim|verify)$", "", item_slug, flags=re.IGNORECASE
            )
            plans.append(DacWritePlan(
                flow_row_index=flow_row_index,
                item=row.flow.item,
                dac_symbol=logical_dac_final_symbol(row.flow.item),
                pattern_name=pattern_name,
                helper_name=f"set_{item_slug}_trim_data",
                default_value=operation.dynamic_field.value,
                field_width=operation.dynamic_field.width,
                value_source=operation.value_source,
                value=operation.value,
                needs_global_variable=operation.value_source == "ADDR_MAP",
                needs_set_helper=operation.requires_set_helper,
            ))
    return DacWritePlanSet(tuple(plans))


def compile_result_export_plan_set(
    flow_frame: pd.DataFrame,
    rows: dict[int, ExecutableFlowRow],
    current_cp: Optional[str],
) -> ResultExportPlanSet:
    """Compile explicit EXPORT and UID-implied exports into one shared plan set."""
    plans = []
    for flow_row_index, record in flow_frame.iterrows():
        cp = str(record.get("CP NO", "")).strip()
        if current_cp is not None and cp != str(current_cp).strip():
            continue
        row = rows.get(flow_row_index)
        export_ops = (
            [operation for operation in row.operations if operation.name == "EXPORT"]
            if row is not None else []
        )
        explicit = bool(export_ops)
        implied_by_uid = str(record.get("UID", "")).strip().casefold() == "yes"
        if not explicit and not implied_by_uid:
            continue

        flow_type = str(record.get("type", "")).strip().casefold()
        if flow_type not in ("verify", "trim"):
            raise FlowCompileError(
                f"FLOW row {flow_row_index + 2}: EXPORT 暂只支持 type=verify/trim，实际 {flow_type}"
            )
        item = str(record.get("item", "")).strip()
        sub = str(record.get("sub", "/")).strip()
        source_kind = "DAC_FINAL" if flow_type == "trim" else "MEASUREMENT"
        requested_format = export_ops[0].named_parameter("FORMAT") if explicit else None
        export_format = (
            "RAW" if source_kind == "DAC_FINAL"
            else requested_format or _default_export_format(item, implied_by_uid)
        )
        symbol = _result_export_symbol(item, sub, flow_type)
        plans.append(ResultExportPlan(
            flow_row_index=flow_row_index,
            item=item,
            sub=sub,
            flow_type=flow_type,
            source_kind=source_kind,
            format=export_format,
            symbol=symbol,
            c_type=(
                "int" if source_kind == "DAC_FINAL"
                else "double" if export_format == "RAW"
                else "int"
            ),
            explicit=explicit,
            implied_by_uid=implied_by_uid,
            persist_to_uid=implied_by_uid,
            persist_to_otp=(
                str(record.get("OTP", "")).strip().casefold() == "yes"
            ),
            unit=str(record.get("UNIT", "")).strip(),
        ))
    return ResultExportPlanSet(tuple(plans))


def _default_export_format(item: str, implied_by_uid: bool) -> str:
    if not implied_by_uid:
        return "RAW"
    return "ADC12_3V3" if "ts" in logical_item_key(item) else "BCD16_MV"


def _result_export_symbol(
    item: str,
    sub: str,
    flow_type: str,
) -> str:
    parts = [str(item).strip()]
    if str(sub).strip() not in ("", "/"):
        parts.append(str(sub).strip())
    stem = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(parts)).strip("_").upper()
    if flow_type == "trim":
        return f"{stem}_DAC_EXPORT"
    return f"{stem}_EXPORT"


def _recipe_pattern_name(item: str, role: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(item).strip()).strip("_").lower()
    slug = re.sub(r"_(?:trim|verify)$", "", slug, flags=re.IGNORECASE)
    if role == "trim mode":
        return f"enter_{slug}"
    if role == "verify mode":
        return f"enter_{slug}_verify"
    raise FlowCompileError(f"item {item!r} 不支持 ENTER pattern role {role!r}")


def _recipe_dac_pattern_name(item: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(item).strip()).strip("_").lower()
    slug = re.sub(r"_(?:trim|verify)$", "", slug, flags=re.IGNORECASE)
    return f"set_{slug}_dac"


def resolve_recipe_pattern_reference(
    catalog: PatternCatalog,
    pattern_name: str,
    role: str,
):
    """Resolve one explicit ordinary-TRIM output name to its source bundle."""
    requested = str(pattern_name).strip()
    expected_role = str(role).strip()
    matches = []
    known_roles = []
    for bundle in catalog.bundles:
        for step in bundle.steps:
            if step.role.casefold() not in ("trim mode", "trim dac", "verify mode"):
                continue
            output_name = (
                _recipe_dac_pattern_name(bundle.item)
                if step.role.casefold() == "trim dac"
                else _recipe_pattern_name(bundle.item, step.role)
            )
            if output_name.casefold() == requested.casefold():
                known_roles.append((bundle, step.role, output_name))
                if step.role.casefold() == expected_role.casefold():
                    matches.append((bundle, output_name))
    if len(matches) == 1:
        return matches[0]
    if known_roles:
        actual_roles = ", ".join(sorted({str(value[1]) for value in known_roles}))
        raise PatternCompileError(
            f"PATTERN {requested!r} 的 role 为 {actual_roles!r}，"
            f"不能用于 {expected_role!r}"
        )
    raise PatternCompileError(
        f"PATTERN {requested!r} 不存在于已编译的普通 TRIM Pattern 中"
    )


def _trim_pattern_reference(row: FlowRow, catalog: PatternCatalog):
    references = [
        call.named_parameter("PATTERN")
        for call in row.recipe
        if call.name == "TRIM" and call.named_parameter("PATTERN") is not None
    ]
    if len(references) > 1:
        raise FlowCompileError(f"FLOW row {row.excel_row}: TRIM 只能指定一个 PATTERN")
    if not references:
        return None
    return resolve_recipe_pattern_reference(catalog, references[0], "trim dac")


def validate_explicit_recipe_patterns(recipe_rows, available_patterns) -> None:
    """Require every explicit Recipe reference to survive Pattern compilation."""
    available = {str(name).strip().casefold() for name in available_patterns}
    for row in recipe_rows.values():
        for operation in row.operations:
            if not operation.pattern_explicit:
                continue
            name = str(operation.pattern_name).strip()
            if name.casefold() not in available:
                raise FlowCompileError(
                    f"FLOW row {row.flow.excel_row} {operation.name}: "
                    f"PATTERN {name!r} 未产生可用的 Pattern 编译资源"
                )


def _resolve_call(
    row: FlowRow,
    call: RecipeCall,
    catalog: PatternCatalog,
    trim_keys: set[tuple[str, str]],
) -> ResolvedRecipeCall:
    try:
        if call.name == "ENTER":
            role = _enter_role(row.flow_type, call.named_parameter("ROLE"))
            explicit = call.named_parameter("PATTERN")
            if explicit is not None and not (
                row.flow_type == "trim"
                or (row.flow_type == "verify" and row.mode == "fbist")
            ):
                raise FlowCompileError(
                    "PATTERN 只支持 type=trim 或 type=verify、mode=fbist 的 ENTER 用途"
                )
            selected = (
                resolve_recipe_pattern_reference(catalog, explicit, role)
                if explicit is not None else None
            )
            pattern_item = row.item if selected is None else selected[0].item
            pattern_name = None if selected is None else selected[1]
            if row.flow_type == "trim":
                binding = trim_mode_adapter(row.mode).enter(
                    catalog, pattern_item, role, call.argument
                )
                return ResolvedRecipeCall(
                    name=call.name,
                    argument=call.argument,
                    pattern_role=binding.role,
                    pattern_name=pattern_name,
                    pattern_explicit=explicit is not None,
                    dynamic_field=binding.dynamic_field,
                    value_source=binding.value_source,
                    value=binding.value,
                    parameters=call.parameters,
                )
            if call.argument is None:
                step = catalog.bundle(pattern_item).step(role)
                if not step.dynamic_fields:
                    return ResolvedRecipeCall(
                        name=call.name,
                        argument=None,
                        pattern_role=role,
                        pattern_name=pattern_name,
                        pattern_explicit=explicit is not None,
                        value_source="STATIC",
                        parameters=call.parameters,
                    )
            binding = bind_dynamic_argument(catalog, pattern_item, role, call.argument)
            return ResolvedRecipeCall(
                name=call.name,
                argument=call.argument,
                pattern_role=role,
                pattern_name=pattern_name,
                pattern_explicit=explicit is not None,
                dynamic_field=binding.field,
                value_source="ARGUMENT" if call.argument is not None else "DEFAULT",
                value=binding.value,
                parameters=call.parameters,
            )
        if call.name == "RUN":
            return ResolvedRecipeCall(
                name=call.name,
                argument=call.argument,
                value_source="PATTERN_REF",
                value=call.argument,
                parameters=call.parameters,
            )
        if call.name == "TRIM":
            if row.flow_type != "trim":
                raise FlowCompileError(f"TRIM 只能用于 type=trim，实际 {row.flow_type}")
            selected = _trim_pattern_reference(row, catalog)
            pattern_item = row.item if selected is None else selected[0].item
            pattern_name = None if selected is None else selected[1]
            binding = trim_mode_adapter(row.mode).set_data(catalog, pattern_item)
            return ResolvedRecipeCall(
                name=call.name,
                argument=None,
                pattern_role=binding.role,
                pattern_name=pattern_name,
                pattern_explicit=selected is not None,
                dynamic_field=binding.dynamic_field,
                value_source="TRIM_LOOP",
                parameters=call.parameters,
            )
        if call.name == "DEPEND":
            if row.flow_type != "trim":
                raise FlowCompileError(
                    f"DEPEND 只能用于 type=trim，实际 {row.flow_type}"
                )
            binding = trim_mode_adapter(row.mode).set_data(
                catalog, call.argument
            )
            return ResolvedRecipeCall(
                name=call.name,
                argument=call.argument,
                pattern_role=binding.role,
                dynamic_field=binding.dynamic_field,
                value_source="DAC_FINAL",
                value=call.argument,
                parameters=call.parameters,
            )
        if call.name == "DAC_ADJ":
            if row.flow_type == "adjust":
                return ResolvedRecipeCall(
                    name=call.name,
                    argument=call.argument,
                    value_source="RAW_EXPORT",
                    value=call.argument,
                    parameters=call.parameters,
                )
            if row.flow_type != "trim":
                raise FlowCompileError(
                    f"DAC_ADJ 只能用于 type=trim，实际 {row.flow_type}"
                )
            selected = _trim_pattern_reference(row, catalog)
            pattern_item = row.item if selected is None else selected[0].item
            pattern_name = None if selected is None else selected[1]
            binding = trim_mode_adapter(row.mode).set_data(catalog, pattern_item)
            return ResolvedRecipeCall(
                name=call.name,
                argument=call.argument,
                pattern_role=binding.role,
                pattern_name=pattern_name,
                pattern_explicit=selected is not None,
                dynamic_field=binding.dynamic_field,
                value_source="RAW_DAC",
                value=call.argument,
                parameters=call.parameters,
            )
        if call.name == "DAC_WRITE":
            if row.flow_type != "verify":
                raise FlowCompileError(
                    f"DAC_WRITE 只能用于 type=verify，实际 {row.flow_type}"
                )
            binding = bind_dynamic_argument(catalog, row.item, "trim dac", call.argument)
            has_current_cp_trim = (
                row.cp.casefold(), logical_item_key(row.item)
            ) in trim_keys
            return ResolvedRecipeCall(
                name=call.name,
                argument=call.argument,
                pattern_role="trim dac",
                dynamic_field=binding.field,
                value_source=(
                    "ARGUMENT" if call.argument is not None
                    else "DAC_FINAL" if has_current_cp_trim
                    else "ADDR_MAP"
                ),
                value=binding.value if call.argument is not None else None,
                requires_set_helper=not has_current_cp_trim,
                parameters=call.parameters,
            )
        if call.name == "JUDGE" and row.flow_type == "trim":
            selected = _trim_pattern_reference(row, catalog)
            pattern_item = row.item if selected is None else selected[0].item
            pattern_name = None if selected is None else selected[1]
            binding = trim_mode_adapter(row.mode).set_data(catalog, pattern_item)
            return ResolvedRecipeCall(
                name=call.name,
                argument=None,
                pattern_role=binding.role,
                pattern_name=pattern_name,
                pattern_explicit=selected is not None,
                dynamic_field=binding.dynamic_field,
                value_source="EFFECTIVE_DAC",
                parameters=call.parameters,
            )
        return ResolvedRecipeCall(
            name=call.name,
            argument=call.argument,
            parameters=call.parameters,
            assignments=call.assignments,
            sram_capture=call.sram_capture,
        )
    except (PatternCompileError, TrimModeError) as exc:
        raise FlowCompileError(f"FLOW row {row.excel_row} {call.name}: {exc}") from exc


def _validate_dac_write_order(
    row: FlowRow,
    operations: Tuple[ResolvedRecipeCall, ...],
) -> None:
    indices = [index for index, operation in enumerate(operations)
               if operation.name == "DAC_WRITE"]
    if not indices:
        return
    judge_indices = [index for index, operation in enumerate(operations)
                     if operation.name == "JUDGE"]
    if len(indices) != 1 or len(judge_indices) != 1 or indices[0] >= judge_indices[0]:
        raise FlowCompileError(
            f"FLOW row {row.excel_row}: DAC_WRITE 必须且只能出现一次，并位于 JUDGE 前"
        )


def _validate_export_order(
    row: FlowRow,
    operations: Tuple[ResolvedRecipeCall, ...],
) -> None:
    if row.flow_type == "verify" and row.mode.casefold() == "fbist":
        _validate_standard_verify_exports(row, operations)
        return
    indices = [index for index, operation in enumerate(operations)
               if operation.name == "EXPORT"]
    if not indices:
        return
    judge_indices = [index for index, operation in enumerate(operations)
                     if operation.name == "JUDGE"]
    if len(indices) != 1 or len(judge_indices) != 1 or indices[0] <= judge_indices[0]:
        raise FlowCompileError(
            f"FLOW row {row.excel_row}: EXPORT 必须且只能出现一次，并位于 JUDGE 后"
        )


def _validate_export_recipe(row: FlowRow) -> None:
    if row.flow_type == "verify" and row.mode.casefold() == "fbist":
        _validate_standard_verify_exports(row, row.recipe)
        return
    indices = [index for index, call in enumerate(row.recipe)
               if call.name == "EXPORT"]
    if not indices:
        return
    if row.flow_type not in ("verify", "trim"):
        raise FlowCompileError(
            f"FLOW row {row.excel_row}: EXPORT 暂只支持 verify/trim，"
            f"当前 type={row.flow_type}"
        )
    judge_indices = [index for index, call in enumerate(row.recipe)
                     if call.name == "JUDGE"]
    if len(indices) != 1 or len(judge_indices) != 1 or indices[0] <= judge_indices[0]:
        raise FlowCompileError(
            f"FLOW row {row.excel_row}: EXPORT 必须且只能出现一次，并位于 JUDGE 后"
        )


def _validate_standard_verify_exports(row: FlowRow, operations: tuple) -> None:
    judge_ordinal = 0
    exported_judges = set()
    for operation in operations:
        if operation.name == "JUDGE":
            judge_ordinal += 1
        elif operation.name == "EXPORT":
            if judge_ordinal == 0:
                raise FlowCompileError(
                    f"FLOW row {row.excel_row}: EXPORT 前没有已完成的 JUDGE"
                )
            if judge_ordinal in exported_judges:
                raise FlowCompileError(
                    f"FLOW row {row.excel_row}: 同一次 JUDGE 只能 EXPORT 一次"
                )
            exported_judges.add(judge_ordinal)


def _enter_role(flow_type: str, override: Optional[str] = None) -> str:
    if override is not None:
        return override.strip().casefold() + " mode"
    if flow_type == "trim":
        return "trim mode"
    if flow_type in ("verify", "shmoo"):
        return "verify mode"
    raise FlowCompileError(f"ENTER 暂不支持 type={flow_type}")


def _required_text(value: object, column: str, excel_row: int) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise FlowCompileError(f"FLOW row {excel_row}: {column} 不能为空")
    text = str(value).strip()
    if not text:
        raise FlowCompileError(f"FLOW row {excel_row}: {column} 不能为空")
    return text
