"""Platform-neutral ID, UID construction, and BakeID gating plans."""

from dataclasses import dataclass
from datetime import date
import re
from typing import Dict, Iterable, Tuple

from flow_recipe import FlowCompileError, parse_recipe


class IdPlanError(ValueError):
    """An item does not satisfy the explicit ID/UID protocol."""


@dataclass(frozen=True)
class IdTargetDefinition:
    target: str
    kind: str


@dataclass(frozen=True)
class IdItemPlan:
    item: str
    target: IdTargetDefinition
    role: str
    failure_policy: str
    gate_symbol: str | None = None


@dataclass(frozen=True)
class IdPlanSet:
    rows: Dict[int, IdItemPlan]
    bake_gates: Dict[int, IdItemPlan]

    def for_row(self, flow_row_index: int) -> IdItemPlan | None:
        return self.rows.get(flow_row_index)

    def bake_gate_for_row(self, flow_row_index: int) -> IdItemPlan | None:
        return self.bake_gates.get(flow_row_index)


def parse_standard_id_item(item: str, flow_type: str) -> tuple[str, IdTargetDefinition]:
    """Resolve the formal FLOW protocol without substring target inference."""
    match = re.fullmatch(
        r"(Check|Read|Pgm)_CP(\d+)(ID|_?BakeID)(_Read)?",
        str(item).strip(), flags=re.IGNORECASE,
    )
    if match is None:
        raise IdPlanError(f"unknown ID item protocol: {item!r}")
    prefix, station, suffix, readback = match.groups()
    prefix = prefix.title()
    if ((prefix == "Pgm") != (str(flow_type).strip().casefold() == "uid")
            or (readback is not None and prefix != "Pgm")):
        raise IdPlanError(f"ID item {item!r} does not match FLOW type {flow_type!r}")
    bake = suffix.casefold() != "id"
    target = IdTargetDefinition(
        f"CP{station}" + ("_BakeID" if bake else "ID"), "BAKEID" if bake else "ID",
    )
    canonical = f"{prefix}_{target.target}" + ("_Read" if prefix == "Pgm" else "")
    return canonical, target


def compile_id_plan_set(flow) -> IdPlanSet:
    """Bind BakeID only to one preceding same-CP Read of the exact target."""
    rows = {}
    gates = {}
    preceding_reads = {}
    for row_index, record in flow.iterrows():
        flow_type = str(record.get("type", "")).strip().casefold()
        if flow_type not in ("id", "uid"):
            continue
        item = str(record.get("item", "")).strip()
        cp = str(record.get("CP NO", "")).strip().upper()
        if not re.fullmatch(r"CP\d+", cp):
            raise IdPlanError(f"invalid ID FLOW CP {cp!r}")
        canonical_item, target = parse_standard_id_item(item, flow_type)
        plan = compile_id_item_plan(canonical_item, (target,))
        rows[row_index] = plan
        key = (cp, target.target.casefold())
        if plan.role == "PRODUCE_GATE":
            preceding_reads.setdefault(key, []).append(plan)
        if plan.role != "COMMIT_CLOSURE" or plan.target.kind != "BAKEID":
            continue
        candidates = preceding_reads.get(key, ())
        if len(candidates) != 1:
            raise IdPlanError(
                f"BakeID {plan.item} requires exactly one preceding "
                f"Read_{plan.target.target} gate in {cp}"
            )
        gates[row_index] = candidates[0]
    return IdPlanSet(rows, gates)


@dataclass(frozen=True)
class BuildUidSchema:
    startup_cache_inputs: Tuple[str, ...]
    global_symbols: Tuple[str, ...]
    fields: Tuple[str, ...]
    crc_field: str
    crc_input_fields: Tuple[str, ...]
    field_bindings: Tuple["BuildUidField", ...] = ()


@dataclass(frozen=True)
class BuildUidField:
    field: str
    source: str
    index: int | None = None
    width: int = 8


@dataclass(frozen=True)
class BuildUidInputs:
    lot_id: str
    wafer_id: str
    wafer_slot: int
    x: int
    y: int
    build_date: date
    fab_id: int
    project_id: int
    project_version: int
    program_version: int


@dataclass(frozen=True)
class CrcPlan:
    field: str
    input_fields: Tuple[str, ...]


@dataclass(frozen=True)
class BuildUidPlan:
    cp: str
    startup_cache_inputs: Tuple[str, ...]
    global_symbols: Tuple[str, ...]
    fields: Tuple[str, ...]
    crc: CrcPlan
    full_replace: bool = True
    activation_condition: str = "RECIPE_CONTAINS_BUILDUID"


@dataclass(frozen=True)
class BuildUidStartupPlan:
    cache_inputs: Tuple[str, ...]
    global_symbols: Tuple[str, ...]
    validation_phase: str = "STARTUP_FAIL_FAST"
    read_once: bool = True


DEFAULT_BUILD_UID_STARTUP_PLAN = BuildUidStartupPlan(
    cache_inputs=("LOT_ID", "WAFER_ID", "WAFER_SLOT", "X", "Y"),
    global_symbols=(
        "WAFERID", "LOT_ID", "WAFER_SLOT", "X_CO", "Y_CO", "LOAD_ID_FLAG",
    ),
)


class UidPlanCompiler:
    def __init__(self, schema: BuildUidSchema) -> None:
        self._schema = schema

    def plan_for_cp(
        self,
        cp: str,
        *,
        recipe_modules: Iterable[str],
    ) -> BuildUidPlan | None:
        modules = tuple(str(module).strip().upper() for module in recipe_modules)
        count = modules.count("BUILDUID")
        if count == 0:
            return None
        if count > 1:
            raise IdPlanError("BUILDUID may appear at most once per CP")
        return BuildUidPlan(
            cp=str(cp),
            startup_cache_inputs=self._schema.startup_cache_inputs,
            global_symbols=self._schema.global_symbols,
            fields=self._schema.fields,
            crc=CrcPlan(
                field=self._schema.crc_field,
                input_fields=self._schema.crc_input_fields,
            ),
        )


def compile_build_uid_startup_plan(
    schema: BuildUidSchema,
    *,
    recipe_modules: Iterable[str],
) -> BuildUidStartupPlan | None:
    modules = tuple(str(module).strip().upper() for module in recipe_modules)
    count = modules.count("BUILDUID")
    if count == 0:
        return None
    if count > 1:
        raise IdPlanError("BUILDUID may appear at most once per CP")
    return BuildUidStartupPlan(
        cache_inputs=schema.startup_cache_inputs,
        global_symbols=schema.global_symbols,
    )


def compile_build_uid_startup_plan_from_flow(
    flow,
    cp: str,
) -> BuildUidStartupPlan | None:
    """Return startup dependencies iff the selected CP explicitly uses BUILDUID."""
    if "CP NO" not in flow.columns or "Recipe" not in flow.columns:
        raise IdPlanError("FLOW requires CP NO and Recipe columns for BUILDUID startup")
    modules = []
    selected = flow[flow["CP NO"].astype(str).str.strip().str.casefold()
                    == str(cp).strip().casefold()]
    for value in selected["Recipe"]:
        if value is None or (isinstance(value, float) and value != value):
            continue
        if not str(value).strip():
            continue
        try:
            modules.extend(call.name for call in parse_recipe(value))
        except FlowCompileError as exc:
            raise IdPlanError(f"invalid Recipe while resolving BUILDUID startup: {exc}") from exc
    count = modules.count("BUILDUID")
    if count == 0:
        return None
    if count > 1:
        raise IdPlanError("BUILDUID may appear at most once per CP")
    return DEFAULT_BUILD_UID_STARTUP_PLAN


def generate_build_uid_values(
    inputs: BuildUidInputs,
    schema: BuildUidSchema,
) -> Dict[str, int]:
    """Generate one complete BUILDUID field image from validated cached inputs."""
    _validate_build_uid_inputs(inputs)
    bindings = {binding.field: binding for binding in schema.field_bindings}
    if set(bindings) != set(schema.fields):
        raise IdPlanError("BUILDUID schema must bind every field exactly once")
    if schema.crc_field not in bindings:
        raise IdPlanError(f"BUILDUID CRC field {schema.crc_field!r} is not bound")
    values: Dict[str, int] = {}
    for field in schema.fields:
        binding = bindings[field]
        if binding.source.upper() == "CRC8":
            continue
        value = _build_uid_source_value(inputs, binding)
        if binding.width <= 0 or value < 0 or value >= (1 << binding.width):
            raise IdPlanError(
                f"BUILDUID field {field} value {value} exceeds {binding.width} bit"
            )
        values[field] = value
    missing_crc_inputs = tuple(
        field for field in schema.crc_input_fields if field not in values
    )
    if missing_crc_inputs:
        raise IdPlanError(
            "BUILDUID CRC input field(s) unavailable: " + ", ".join(missing_crc_inputs)
        )
    crc_bytes = tuple(values[field] for field in schema.crc_input_fields)
    if any(value > 0xFF for value in crc_bytes):
        raise IdPlanError("BUILDUID CRC inputs must be byte-wide values")
    values[schema.crc_field] = _crc8_complement(crc_bytes)
    return {field: values[field] for field in schema.fields}


def _validate_build_uid_inputs(inputs: BuildUidInputs) -> None:
    for name, text in (("lot_id", inputs.lot_id), ("wafer_id", inputs.wafer_id)):
        if not isinstance(text, str) or not text or not text.isascii():
            raise IdPlanError(f"BUILDUID {name} must be non-empty ASCII")
    if not 1 <= inputs.wafer_slot <= 25:
        raise IdPlanError("BUILDUID wafer_slot must be in 1..25")
    for name, coordinate in (("x", inputs.x), ("y", inputs.y)):
        if not isinstance(coordinate, int) or not -0xFFFF <= coordinate <= 0xFFFF:
            raise IdPlanError(f"BUILDUID {name} must be a signed 16-bit coordinate")
    if not isinstance(inputs.build_date, date):
        raise IdPlanError("BUILDUID build_date must be a date")
    for name, value in (
        ("fab_id", inputs.fab_id),
        ("project_id", inputs.project_id),
        ("project_version", inputs.project_version),
        ("program_version", inputs.program_version),
    ):
        if not isinstance(value, int) or not 0 <= value <= 0xFF:
            raise IdPlanError(f"BUILDUID {name} must be an unsigned byte")


def _build_uid_source_value(inputs: BuildUidInputs, binding: BuildUidField) -> int:
    source = binding.source.upper()
    if source in ("LOT_BYTE", "WAFER_BYTE"):
        if binding.index is None or binding.index < 0:
            raise IdPlanError(f"BUILDUID field {binding.field} requires a byte index")
        text = inputs.lot_id if source == "LOT_BYTE" else inputs.wafer_id
        if binding.index >= len(text):
            raise IdPlanError(
                f"BUILDUID {source} index {binding.index} exceeds input length"
            )
        return ord(text[binding.index])
    if source == "WAFER_SLOT":
        return inputs.wafer_slot
    if source == "XY_HIGH":
        return ((abs(inputs.y) >> 8) & 0xF) << 4 | ((abs(inputs.x) >> 8) & 0xF)
    if source == "X_LOW":
        return inputs.x & 0xFF
    if source == "Y_LOW":
        return inputs.y & 0xFF
    if source == "DATE_YM":
        return ((inputs.build_date.year % 10) << 4) | inputs.build_date.month
    if source == "FAB_ID":
        return inputs.fab_id
    if source == "PROJECT_WORD":
        return (inputs.project_id << 8) | inputs.project_version
    if source == "PROGRAM_VERSION":
        return inputs.program_version
    raise IdPlanError(f"unsupported BUILDUID source {binding.source!r}")


def _crc8_complement(values: Iterable[int]) -> int:
    crc = 0
    for value in values:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return (~crc) & 0xFF


@dataclass(frozen=True)
class BakeIdOperation:
    action: str
    site_scope: str


@dataclass(frozen=True)
class BakeIdPlan:
    item: str
    target: IdTargetDefinition
    gate_symbol: str
    operations: Tuple[BakeIdOperation, ...]


def compile_bakeid_plan(
    *,
    item: str,
    target_definitions: Iterable[IdTargetDefinition],
    gate_producer: IdItemPlan,
) -> BakeIdPlan:
    commit = compile_id_item_plan(item, target_definitions)
    if commit.role != "COMMIT_CLOSURE" or commit.target.kind.upper() != "BAKEID":
        raise IdPlanError(f"item {item!r} is not a BakeID commit closure")
    if gate_producer.role != "PRODUCE_GATE" or gate_producer.gate_symbol is None:
        raise IdPlanError("BakeID requires a Read_<target> gate producer")
    if gate_producer.target.target.casefold() != commit.target.target.casefold():
        raise IdPlanError("BakeID gate target does not match commit target")
    return BakeIdPlan(
        item=commit.item,
        target=commit.target,
        gate_symbol=gate_producer.gate_symbol,
        operations=(
            BakeIdOperation("READOTPMAP_UID", "ALL_ACTIVE_SITES"),
            BakeIdOperation("LOADMAP_UID", "ALL_ACTIVE_SITES"),
            BakeIdOperation("CHECKOTP_UID", "ALL_ACTIVE_SITES"),
            BakeIdOperation("COMMIT_BAKEID", "GATED_SITES"),
            BakeIdOperation("PGMOTP_UID", "GATED_SITES"),
        ),
    )


def compile_id_item_plan(
    item: str,
    target_definitions: Iterable[IdTargetDefinition],
) -> IdItemPlan:
    """Parse a full standard item name; never infer a role from a substring."""
    text = str(item).strip()
    parsed = None
    for expression, role, failure_policy in (
        (r"Check_(.+)", "HARD_CHECK", "FLOW_BIN"),
        (r"Read_(.+)", "PRODUCE_GATE", "DEFER"),
        (r"Pgm_(.+)_Read", "COMMIT_CLOSURE", "PGMOTP_RESULT"),
    ):
        match = re.fullmatch(expression, text, flags=re.IGNORECASE)
        if match:
            parsed = (match.group(1), role, failure_policy)
            break
    if parsed is None:
        raise IdPlanError(f"unknown ID item protocol: {item!r}")
    target_name, role, failure_policy = parsed
    targets = {definition.target.casefold(): definition for definition in target_definitions}
    target = targets.get(target_name.casefold())
    if target is None:
        raise IdPlanError(f"unknown ID target {target_name!r} in item {item!r}")
    gate_symbol = None
    if role == "PRODUCE_GATE":
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", target.target).strip("_").upper()
        gate_symbol = normalized + "_NEEDS_WRITE"
    return IdItemPlan(
        item=text,
        target=target,
        role=role,
        failure_policy=failure_policy,
        gate_symbol=gate_symbol,
    )
