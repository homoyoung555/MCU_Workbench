"""Compile upper-layer STANDARD_VERIFY Recipe facts into immutable plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from types import MappingProxyType
from typing import Mapping

from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation
from program_gen.core.encoding import calc_limit
from program_gen.core.recipe_trim import recipe_pattern_name
from program_gen.core.run_pattern import (
    PatternResourceRef,
    PatternSpan,
    RunPatternPlan,
)
from program_gen.core.verify_modules import (
    EnterPlan,
    JudgeMeasurementKind,
    JudgeMeasurementPlan,
    JudgePeWindowPlan,
    JudgePlan,
    PeWindowKind,
)
from program_gen.core.result_export import (
    ResultExportFormat,
    ResultExportModulePlan,
)


STANDARD_VERIFY_MODULES = frozenset((
    "ENTER",
    "JUDGE",
    "RUN",
    "EXPORT",
    "DAC_WRITE",
    "COMMIT",
    "DAC_ADJ",
    "SETVPOSP",
))


class StandardVerifyPlanError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class StandardVerifyStep:
    module: str
    source_operation_index: int
    argument: str | None = None
    pattern_role: str | None = None
    dynamic_field: object | None = None
    value_source: str | None = None
    value: str | None = None
    requires_set_helper: bool = False
    parameters: tuple[object, ...] = ()
    assignments: tuple[object, ...] = ()
    judge_ordinal: int | None = None
    export_judge_ordinal: int | None = None
    module_plan: object | None = None


@dataclass(frozen=True, slots=True)
class ShmooExecutionPoint:
    row: int
    excel_row: int
    step: int
    sub: str
    log_name: str
    steps: tuple[StandardVerifyStep, ...]


@dataclass(frozen=True, slots=True)
class ShmooExecutionPlan:
    consumer_module: str
    consumer_index: int
    field_width: int
    default_value: int
    pass_fail: bool
    points: tuple[ShmooExecutionPoint, ...]


@dataclass(frozen=True, slots=True)
class StandardVerifyPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    effective_recipe: tuple[str, ...]
    steps: tuple[StandardVerifyStep, ...]
    initial_power_profile: str | None = None
    relay: str | None = None
    test_number: int | None = None
    protocol_enter: RunPatternPlan | None = None
    protocol_exit: RunPatternPlan | None = None
    shmoo: ShmooExecutionPlan | None = None


def compile_standard_verify_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, object],
    flow_frame: object | None = None,
    export_rows: Mapping[int, object] = MappingProxyType({}),
    dac_write_rows: Mapping[int, object] = MappingProxyType({}),
    nm_pattern_frame: object | None = None,
    version_frame: object | None = None,
    commit_rows: Mapping[int, tuple[object, ...]] = MappingProxyType({}),
) -> Mapping[int, StandardVerifyPlan]:
    plans = {}
    for operation in operations:
        if operation.typed_kind != "STANDARD_VERIFY":
            continue
        recipe_row = recipe_rows.get(operation.row)
        recipe_operations = tuple(getattr(recipe_row, "operations", ()))
        module_names = tuple(item.name for item in recipe_operations) or (
            ("ENTER", "JUDGE", "EXPORT")
            if operation.row in export_rows
            else ("ENTER", "JUDGE")
        )
        unsupported = tuple(
            module for module in module_names
            if module not in STANDARD_VERIFY_MODULES
        )
        if unsupported:
            raise StandardVerifyPlanError(
                "SV.RECIPE.MODULE_UNSUPPORTED",
                f"FLOW row {operation.row + 2} does not allow {unsupported[0]}",
            )
        if "ENTER" not in module_names:
            raise StandardVerifyPlanError(
                "SV.RECIPE.ENTER_REQUIRED",
                f"FLOW row {operation.row + 2} STANDARD_VERIFY requires ENTER",
            )
        if "JUDGE" not in module_names:
            raise StandardVerifyPlanError(
                "SV.RECIPE.JUDGE_REQUIRED",
                f"FLOW row {operation.row + 2} STANDARD_VERIFY requires JUDGE",
            )
        judge_ordinal = 0
        commit_ordinal = 0
        steps = []
        record = flow_frame.iloc[operation.row] if flow_frame is not None else None
        enter_source = next(
            (item for item in recipe_operations if item.name == "ENTER"), None
        )
        enter_plan, judge_plan = _module_plans(
            operation,
            record,
            nm_pattern_frame,
            getattr(enter_source, "pattern_name", None)
            or recipe_pattern_name(
                operation.item,
                getattr(enter_source, "pattern_role", None) or "verify mode",
            ),
            version_frame,
        )
        for index, module in enumerate(module_names):
            source = recipe_operations[index] if recipe_operations else None
            if module == "JUDGE":
                judge_ordinal += 1
            if module == "EXPORT" and judge_ordinal == 0:
                raise StandardVerifyPlanError(
                    "SV.RECIPE.EXPORT_BEFORE_JUDGE",
                    f"FLOW row {operation.row + 2} EXPORT has no completed JUDGE",
                )
            module_plan = (
                enter_plan if module == "ENTER" else
                judge_plan if module == "JUDGE" else
                _export_plan(operation, export_rows.get(operation.row),
                             judge_plan, judge_ordinal)
                if module == "EXPORT" else
                dac_write_rows.get(operation.row)
                if module == "DAC_WRITE" else
                _run_plan(
                    getattr(source, "value", None)
                    or getattr(source, "argument", None)
                )
                if module == "RUN" else None
            )
            if module == "COMMIT":
                row_commits = commit_rows.get(operation.row, ())
                if commit_ordinal >= len(row_commits):
                    raise StandardVerifyPlanError(
                        "SV.COMMIT.PLAN_MISSING",
                        f"FLOW row {operation.row + 2} COMMIT lacks compiled plan",
                    )
                module_plan = row_commits[commit_ordinal]
                commit_ordinal += 1
            steps.append(StandardVerifyStep(
                module=module,
                source_operation_index=index,
                argument=getattr(source, "argument", None),
                pattern_role=getattr(source, "pattern_role", None),
                dynamic_field=getattr(source, "dynamic_field", None),
                value_source=getattr(source, "value_source", None),
                value=getattr(source, "value", None),
                requires_set_helper=bool(
                    getattr(source, "requires_set_helper", False)
                ),
                parameters=tuple(getattr(source, "parameters", ())),
                assignments=tuple(getattr(source, "assignments", ())),
                judge_ordinal=judge_ordinal if module == "JUDGE" else None,
                export_judge_ordinal=(
                    judge_ordinal if module == "EXPORT" and judge_ordinal else None
                ),
                module_plan=module_plan,
            ))
        plans[operation.row] = StandardVerifyPlan(
            row=operation.row,
            excel_row=operation.row + 2,
            cp=operation.cp,
            item=operation.item,
            provenance=operation.provenance,
            effective_recipe=module_names,
            steps=tuple(steps),
            initial_power_profile=_cell(record, "Vcc") if record is not None else None,
            relay=_cell(record, "relay") if record is not None else None,
            test_number=(operation.row + 1) * 100 if record is not None else None,
            protocol_enter=_run_plan("enter_fbist_mode") if record is not None else None,
            protocol_exit=_run_plan("exit_fbist_mode") if record is not None else None,
        )
    return MappingProxyType(
        _compile_shmoo_execution(plans, operations, recipe_rows, flow_frame)
    )


def _compile_shmoo_execution(plans, operations, recipe_rows, flow_frame):
    """Fold contiguous SHMOO=STEP verify rows into their base typed plan."""
    if flow_frame is None:
        return plans
    ordered = [operation for operation in operations if operation.row in plans]
    groups = []
    current = []
    current_key = None
    for operation in ordered:
        recipe = recipe_rows.get(operation.row)
        markers = tuple(
            (index, call)
            for index, call in enumerate(getattr(recipe, "operations", ()))
            if call.named_parameter("SHMOO") == "STEP"
        )
        if not markers:
            if current:
                groups.append(current)
                current, current_key = [], None
            continue
        if len(markers) != 1:
            raise StandardVerifyPlanError(
                "SV.SHMOO.CONSUMER_COUNT",
                f"FLOW row {operation.row + 2} requires exactly one SHMOO=STEP consumer",
            )
        index, call = markers[0]
        if call.name not in ("ENTER", "DAC_WRITE"):
            raise StandardVerifyPlanError(
                "SV.SHMOO.CONSUMER_UNSUPPORTED",
                f"FLOW row {operation.row + 2} does not allow SHMOO on {call.name}",
            )
        key = (operation.cp.casefold(), operation.item.casefold(), index, call.name)
        if current and key != current_key:
            groups.append(current)
            current = []
        current_key = key
        current.append((operation, index, call))
    if current:
        groups.append(current)

    for group in groups:
        first_operation, consumer_index, consumer = group[0]
        base = plans[first_operation.row]
        module_sequences = {
            tuple(step.module for step in plans[operation.row].steps)
            for operation, _, _ in group
        }
        if len(module_sequences) != 1:
            raise StandardVerifyPlanError(
                "SV.SHMOO.RECIPE_MISMATCH",
                f"FLOW row {first_operation.row + 2} grouped scan Recipes differ",
            )
        fields = tuple(call.dynamic_field for _, _, call in group)
        if any(field is None for field in fields) or len(set(fields)) != 1:
            raise StandardVerifyPlanError(
                "SV.SHMOO.FIELD_AMBIGUOUS",
                f"FLOW row {first_operation.row + 2} SHMOO consumer must bind one shared field",
            )
        field = fields[0]
        pass_fail_values = []
        for operation, _, _ in group:
            recipe = recipe_rows[operation.row]
            judges = tuple(call for call in recipe.operations if call.name == "JUDGE")
            values = {call.named_parameter("PF") or "YES" for call in judges}
            if len(values) != 1:
                raise StandardVerifyPlanError(
                    "SV.SHMOO.JUDGE_MISMATCH",
                    f"FLOW row {operation.row + 2} JUDGE.PF values differ",
                )
            pass_fail_values.append(values.pop() == "YES")
        if len(set(pass_fail_values)) != 1:
            raise StandardVerifyPlanError(
                "SV.SHMOO.JUDGE_MISMATCH",
                f"FLOW row {first_operation.row + 2} grouped JUDGE.PF values differ",
            )
        pass_fail = pass_fail_values[0]
        if not pass_fail and len(group) != 1:
            raise StandardVerifyPlanError(
                "SV.SHMOO.RANGE_ROWS",
                f"FLOW row {first_operation.row + 2} PF=NO scan requires one range row",
            )

        points = []
        seen = set()
        for operation, _, _ in group:
            record = flow_frame.iloc[operation.row]
            values = (
                (_decimal_step(record.get("step"), operation.row + 2),)
                if pass_fail else
                _decimal_range(record.get("step"), operation.row + 2)
            )
            for value in values:
                if value >= 1 << field.width:
                    raise StandardVerifyPlanError(
                        "SV.SHMOO.STEP_RANGE",
                        f"FLOW row {operation.row + 2} step={value} exceeds {field.width} bits",
                    )
                if value in seen:
                    raise StandardVerifyPlanError(
                        "SV.SHMOO.STEP_DUPLICATE",
                        f"FLOW row {operation.row + 2} duplicates step={value}",
                    )
                seen.add(value)
                sub = str(record.get("sub", "/")).strip()
                if not pass_fail:
                    sub = f"dac{value}"
                point_steps = tuple(
                    _with_shmoo_alias(
                        step,
                        f"{operation.item}_{sub}",
                        None if pass_fail else float(record.get("target")),
                    )
                    for step in plans[operation.row].steps
                )
                points.append(ShmooExecutionPoint(
                    operation.row,
                    operation.row + 2,
                    value,
                    sub,
                    f"{operation.item}_{sub}",
                    point_steps,
                ))
        plans[first_operation.row] = replace(
            base,
            shmoo=ShmooExecutionPlan(
                consumer.name,
                consumer_index,
                field.width,
                int(field.value, 2),
                pass_fail,
                tuple(points),
            ),
        )
        for operation, _, _ in group[1:]:
            del plans[operation.row]
    return plans


def _with_shmoo_alias(
    step: StandardVerifyStep, alias: str, fixed_limit: float | None,
) -> StandardVerifyStep:
    if step.module != "JUDGE" or step.module_plan is None:
        return step
    judge = step.module_plan
    measurement = replace(judge.measurement, alias=alias)
    if fixed_limit is not None:
        measurement = replace(
            measurement, low_limit=fixed_limit, high_limit=fixed_limit
        )
    return replace(step, module_plan=replace(judge, measurement=measurement))


def _decimal_step(value: object, excel_row: int) -> int:
    if isinstance(value, bool):
        raise StandardVerifyPlanError("SV.SHMOO.STEP", f"FLOW row {excel_row} step must be decimal")
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if math.isfinite(number) and number >= 0 and number.is_integer():
        return int(number)
    raise StandardVerifyPlanError(
        "SV.SHMOO.STEP", f"FLOW row {excel_row} step must be a non-negative decimal integer"
    )


def _decimal_range(value: object, excel_row: int) -> tuple[int, ...]:
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", str(value).strip())
    if not match:
        raise StandardVerifyPlanError(
            "SV.SHMOO.STEP", f"FLOW row {excel_row} PF=NO step must be a decimal range"
        )
    start, end = (int(part) for part in match.groups())
    direction = 1 if end >= start else -1
    return tuple(range(start, end + direction, direction))


def _module_plans(
    operation: FlowOperation,
    record: object | None,
    nm_pattern_frame: object | None,
    enter_pattern_name: str,
    version_frame: object | None,
):
    if record is None:
        return None, None
    enter = EnterPlan(_pattern(enter_pattern_name))
    unit = _cell(record, "UNIT")
    unit_key = unit.casefold()
    if unit_key.endswith("hz"):
        kind = JudgeMeasurementKind.FREQUENCY
    elif unit_key.endswith("v"):
        kind = JudgeMeasurementKind.VOLTAGE
    elif unit_key.endswith("a"):
        kind = JudgeMeasurementKind.CURRENT
    else:
        raise StandardVerifyPlanError(
            "SV.JUDGE.UNIT_UNSUPPORTED",
            f"FLOW row {operation.row + 2} has unsupported UNIT {unit!r}",
        )
    version_target = _version_target(version_frame, operation.cp, operation.item)
    if version_target is None:
        low_limit = calc_limit(
            record.get("target"), record.get("low_range(%)"),
            record.get("high_range(%)"), True,
        )
        high_limit = calc_limit(
            record.get("target"), record.get("low_range(%)"),
            record.get("high_range(%)"), False,
        )
        limit_source = "FLOW"
    else:
        version_column, target = version_target
        low_limit = round(target - 0.05, 12)
        high_limit = round(target + 0.05, 12)
        limit_source = f"VERSION:{version_column}"
    measurement = JudgeMeasurementPlan(
        kind=kind,
        pin=_cell(record, "meas pin"),
        force=_cell(record, "FV/FI"),
        low_limit=low_limit,
        high_limit=high_limit,
        unit=unit,
        gate=_frequency_gate(unit, record.get("target"))
        if kind is JudgeMeasurementKind.FREQUENCY else "2mS",
        settle="50mS",
        alias=f"{operation.item.lower()}_Final",
        limit_source=limit_source,
    )
    return enter, JudgePlan(
        operation.item,
        measurement,
        pe_window=_pe_window_plan(
            record, operation.row, nm_pattern_frame
        ),
    )


def _frequency_gate(unit: str, target) -> str:
    scale = {"hz": 1, "khz": 1_000, "mhz": 1_000_000}[unit.casefold()]
    frequency_hz = abs(float(target)) * scale
    for ceiling, gate in (
        (1_000, "@1KHZ"),
        (10_000, "@10KHZ"),
        (100_000, "@100KHZ"),
        (1_000_000, "@1MHZ"),
        (5_000_000, "@5MHZ"),
        (10_000_000, "@10MHZ"),
    ):
        if frequency_hz < ceiling:
            return gate
    return "@100MHZ"


def _pe_window_plan(record, row: int, nm_pattern_frame):
    pe = _cell(record, "PE").upper()
    if pe in ("", "/", "NO"):
        return None
    try:
        kind = PeWindowKind(pe)
    except ValueError as exc:
        raise StandardVerifyPlanError(
            "SV.JUDGE.PE_UNSUPPORTED",
            f"FLOW row {row + 2} has unsupported PE {pe!r}",
        ) from exc
    used = {
        PeWindowKind.ERASE: "page erase 1st",
        PeWindowKind.PROGRAM: "page program PCKB 1st",
    }[kind]
    pattern_name = None
    if nm_pattern_frame is not None:
        for _, pattern_record in nm_pattern_frame.iterrows():
            if _cell(pattern_record, "used") == used:
                pattern_name = _cell(pattern_record, "Pattern name").split(".")[0]
                break
    if not pattern_name:
        raise StandardVerifyPlanError(
            "SV.JUDGE.PE_PATTERN_MISSING",
            f"FLOW row {row + 2} NM_pattern lacks used={used!r}",
        )
    pattern = PatternResourceRef(
        pattern_name, f"pattern:{pattern_name}", ("START", "pe_1", "END")
    )
    return JudgePeWindowPlan(
        kind,
        RunPatternPlan(
            pattern, PatternSpan.segment("START", "pe_1"), "TS_5MHZ"
        ),
        RunPatternPlan(
            pattern, PatternSpan.segment("pe_1", "END"), "TS_5MHZ"
        ),
    )


def _export_plan(operation, source, judge_plan, judge_ordinal):
    if source is None or judge_plan is None:
        return None
    return ResultExportModulePlan(
        semantic_identity=f"{operation.cp.upper()}:{source.symbol}",
        symbol=source.symbol,
        source_judge_ordinal=judge_ordinal,
        source_pin=judge_plan.measurement.pin,
        format=ResultExportFormat(source.format),
        c_type=source.c_type,
    )


def _pattern(name: str) -> PatternResourceRef:
    return PatternResourceRef(name, f"pattern:{name}", ("START", "END"))


def _run_plan(name: str) -> RunPatternPlan:
    if not name:
        raise StandardVerifyPlanError(
            "SV.RUN.PATTERN_MISSING",
            "STANDARD_VERIFY RUN requires a Pattern reference",
        )
    return RunPatternPlan(_pattern(name), PatternSpan.full(), "TS_5MHZ")


def _cell(record: object, name: str) -> str:
    value = record.get(name)
    return "" if value is None else str(value).strip()


def _version_target(version_frame, cp: str, item: str):
    if version_frame is None:
        return None
    columns = {
        str(column).strip().casefold(): column for column in version_frame.columns
    }
    column = columns.get(str(item).split("_", 1)[0].strip().casefold())
    cp_column = columns.get("cp num")
    if column is None or cp_column is None:
        return None
    row = next((
        record for _, record in version_frame.iterrows()
        if _cell(record, cp_column).casefold() == str(cp).strip().casefold()
    ), None)
    if row is None:
        return None
    raw = _cell(row, column)
    if raw in ("", "/"):
        return None
    try:
        return str(column), float(raw)
    except ValueError as exc:
        raise StandardVerifyPlanError(
            "SV.JUDGE.VERSION_TARGET_INVALID",
            f"VERSION {column} for {cp} has invalid target {raw!r}",
        ) from exc


__all__ = [
    "StandardVerifyPlan",
    "StandardVerifyPlanError",
    "StandardVerifyStep",
    "STANDARD_VERIFY_MODULES",
    "compile_standard_verify_plans",
]
