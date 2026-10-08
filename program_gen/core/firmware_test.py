"""Platform-neutral phase plans for firmware-backed FLOW items."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow, ResolvedRecipeCall
from program_gen.core.firmware_force import (
    ClockForceAction,
    ClockStopAction,
    FirmwareForceAction,
    FirmwareForceCompileError,
    compile_firmware_force_action,
)
from program_gen.core.firmware_judge import (
    FirmwareJudgeCompileError,
    FirmwareJudgePlan,
    SramValueJudgePlan,
    compile_firmware_judge_plans,
)
from program_gen.core.run_pattern import PatternResourceRef, RunPatternCompileError
from program_gen.core.run_sequence import (
    ForceStopAction,
    NativeRunSequenceAction,
    RepowerAction,
    RunSequenceCompileError,
    parse_run_sequence_step,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation
from program_gen.core.result_binding import ResultIdentity
from program_gen.core.sram_capture import compile_sram_capture_plan, SramCaptureCompileError


class FirmwareTestCompileError(ValueError):
    """A HEX/KEIL row violates the firmware phase Recipe contract."""

    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


@dataclass(frozen=True, slots=True)
class DownloadPhase:
    row: int
    sub: str
    provenance: WorkbookProvenance
    power_profile: str
    pattern: PatternResourceRef
    effective_recipe: tuple[str, ...] = ("DOWNLOAD_CODE",)


@dataclass(frozen=True, slots=True)
class KeilPhase:
    row: int
    sub: str
    provenance: WorkbookProvenance
    power_profile: str
    operations: tuple[ResolvedRecipeCall, ...]
    actions: tuple[NativeRunSequenceAction | FirmwareForceAction, ...]
    judge: FirmwareJudgePlan
    cleanup_actions: tuple[ClockStopAction, ...] = ()

    @property
    def effective_recipe(self) -> tuple[str, ...]:
        return tuple(operation.name for operation in self.operations)


FirmwarePhase = DownloadPhase | KeilPhase


@dataclass(frozen=True, slots=True)
class DutResetAction:
    low_duration_ms: int = 5
    high_duration_ms: int = 5
    final_state: str = "RELEASED_HIGH"


FirmwareExecutionStep = FirmwarePhase | DutResetAction


@dataclass(frozen=True, slots=True)
class FirmwareTestPlan:
    cp: str
    item: str
    typed_kind: str
    phases: tuple[FirmwarePhase, ...]
    execution_steps: tuple[FirmwareExecutionStep, ...]

    @property
    def row_indices(self) -> tuple[int, ...]:
        return tuple(phase.row for phase in self.phases)

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return tuple(phase.row + 2 for phase in self.phases)


def compile_firmware_test_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    version: pd.DataFrame,
) -> Mapping[int, FirmwareTestPlan]:
    """Compile generic VERIFY_HEX/VERIFY_KEIL candidates in workbook order.

    Protocol-specific KEIL kinds such as PVD, ADC, and FREQ remain owned by
    their dedicated compilers even though they use the same transport mode.
    """
    validate_firmware_recipe_contract(operations, flow)
    sram_judges = _compile_sram_judges(operations, recipe_rows, flow, version)
    try:
        judge_plans = dict(compile_firmware_judge_plans(
            tuple(op for op in operations if op.row not in sram_judges), flow
        ))
        judge_plans.update(sram_judges)
    except FirmwareJudgeCompileError as exc:
        raise FirmwareTestCompileError(exc.code, exc.row, str(exc)) from exc
    default_pins = _default_pins(version)
    grouped: list[tuple[tuple[str, str], list[FirmwarePhase]]] = []
    identities: dict[tuple[str, str], tuple[str, str]] = {}
    seen: set[tuple[str, str]] = set()
    active_key: tuple[str, str] | None = None
    for operation in operations:
        if operation.typed_kind not in ("VERIFY_HEX", "VERIFY_KEIL"):
            active_key = None
            continue
        key = (operation.cp.casefold(), operation.item.casefold())
        if key != active_key:
            if key in seen:
                raise FirmwareTestCompileError(
                    "FW.GROUP.NONCONTIGUOUS",
                    operation.row,
                    "同一 CP/item 的固件阶段必须在 FLOW 中连续出现",
                )
            seen.add(key)
            grouped.append((key, []))
            active_key = key
        identities.setdefault(key, (operation.cp, operation.item))
        if operation.mode == "hex":
            resource_name = _required_text(
                flow.iloc[operation.row].get("step"), operation.row, "step"
            )
            try:
                pattern = PatternResourceRef(
                    name=resource_name,
                    logical_identity=f"firmware-download:{resource_name}",
                    ordered_labels=("START", "END"),
                )
            except RunPatternCompileError as exc:
                raise FirmwareTestCompileError(
                    exc.code, operation.row, str(exc)
                ) from exc
            phase: FirmwarePhase = DownloadPhase(
                operation.row,
                _text(flow.iloc[operation.row].get("sub")),
                operation.provenance,
                _required_text(
                    flow.iloc[operation.row].get("Vcc"), operation.row, "Vcc"
                ).upper(),
                pattern,
            )
        else:
            executable = recipe_rows.get(operation.row)
            if executable is None:
                raise FirmwareTestCompileError(
                    "FW.RECIPE.KEIL_UNCOMPILED",
                    operation.row,
                    "mode=keil 的显式 Recipe 未生成公共编译输出",
                )
            phase = KeilPhase(
                operation.row,
                _text(flow.iloc[operation.row].get("sub")),
                operation.provenance,
                _required_text(
                    flow.iloc[operation.row].get("Vcc"), operation.row, "Vcc"
                ).upper(),
                executable.operations,
                (),
                judge_plans[operation.row],
            )
            if operation.row not in sram_judges and phase.effective_recipe != ("RUN_SEQUENCE", "JUDGE"):
                raise FirmwareTestCompileError(
                    "FW.RECIPE.KEIL_UNSUPPORTED",
                    operation.row,
                    "通用固件 KEIL phase 当前只支持 RUN_SEQUENCE-JUDGE",
                )
            try:
                marker = object()
                parsed_actions = parse_run_sequence_step(
                    flow.iloc[operation.row].get("step"),
                    default_pins.get(operation.cp.upper(), ""),
                    force_action=marker,
                ) if phase.effective_recipe != ("JUDGE",) else ()
                force = (
                    compile_firmware_force_action(
                        flow.iloc[operation.row], row=operation.row
                    )
                    if any(action is marker for action in parsed_actions)
                    else None
                )
                compiled_actions = tuple(
                    force if action is marker else action
                    for action in parsed_actions
                )
                phase = KeilPhase(
                    phase.row,
                    phase.sub,
                    phase.provenance,
                    phase.power_profile,
                    phase.operations,
                    compiled_actions,
                    phase.judge,
                    _clock_cleanup_for(compiled_actions),
                )
            except (RunSequenceCompileError, FirmwareForceCompileError) as exc:
                raise FirmwareTestCompileError(
                    exc.code, operation.row, str(exc)
                ) from exc
        grouped[-1][1].append(phase)

    plans = {}
    for key, phases in grouped:
        cp, item = identities[key]
        for column in ("Hbin", "Sbin"):
            values = {
                _text(flow.iloc[phase.row].get(column))
                for phase in phases
                if _text(flow.iloc[phase.row].get(column))
            }
            if len(values) > 1:
                raise FirmwareTestCompileError(
                    "FW.GROUP.BIN_CONFLICT",
                    phases[0].row,
                    f"同一固件测试项的 {column} 必须在所有 phase 一致",
                )
        has_download = any(isinstance(phase, DownloadPhase) for phase in phases)
        has_keil = any(isinstance(phase, KeilPhase) for phase in phases)
        typed_kind = (
            "FIRMWARE_FUNCTION_TEST"
            if has_download and has_keil
            else "CODE_DOWNLOAD"
            if has_download
            else "FIRMWARE_RUN_TEST"
        )
        compiled_phases = tuple(phases)
        if typed_kind == "FIRMWARE_RUN_TEST" and len({
            phase.power_profile for phase in compiled_phases
        }) != 1:
            raise FirmwareTestCompileError(
                "FW.GROUP.POWER_CONFLICT",
                compiled_phases[0].row,
                "共享供电会话的所有 KEIL phase 必须使用同一 Vcc profile",
            )
        plan = FirmwareTestPlan(
            cp,
            item,
            typed_kind,
            compiled_phases,
            _execution_steps_for(typed_kind, compiled_phases),
        )
        plans[plan.phases[0].row] = plan
    return MappingProxyType(plans)


def _execution_steps_for(
    typed_kind: str, phases: tuple[FirmwarePhase, ...]
) -> tuple[FirmwareExecutionStep, ...]:
    steps: list[FirmwareExecutionStep] = []
    for phase in phases:
        if (
            typed_kind == "FIRMWARE_RUN_TEST"
            and steps
            and isinstance(steps[-1], KeilPhase)
            and steps[-1].sub != phase.sub
            and not (isinstance(phase, KeilPhase)
                     and isinstance(phase.judge, SramValueJudgePlan)
                     and phase.judge.index > 0)
        ):
            steps.append(DutResetAction())
        steps.append(phase)
    return tuple(steps)


def _compile_sram_judges(operations, recipe_rows, flow, version):
    """Bind an explicit capture to consecutive JUDGE rows in the same item.

    The capture row consumes value zero. Each following JUDGE consumes the
    next value; no implicit Recipe, retrigger, reset, or cross-item dependency.
    """
    plans = {}
    for position, operation in enumerate(operations):
        executable = recipe_rows.get(operation.row)
        if operation.typed_kind != "VERIFY_KEIL" or executable is None:
            continue
        calls = executable.operations
        if not any(call.name == "SRAM_CAPTURE" for call in calls):
            continue
        def fail(message, row=operation.row):
            raise FirmwareTestCompileError("FW.SRAM.GROUP_INVALID", row, message)
        if tuple(call.name for call in calls) != ("RUN_SEQUENCE", "SRAM_CAPTURE", "JUDGE"):
            fail("SRAM 首行必须为 RUN_SEQUENCE-SRAM_CAPTURE(...)-JUDGE")
        argument = calls[1].sram_capture
        count = argument.count
        members = operations[position:position + count]
        if len(members) != count:
            fail(f"SRAM_CAPTURE 采集 {count} 个值，需要同一 item 连续 {count} 行判定")
        version_rows = version.loc[version["CP num"].astype(str).str.strip().str.casefold() == operation.cp.casefold()]
        pins = {_text(record.get("SWD PIN")) for _, record in version_rows.iterrows()}
        if len(pins) != 1 or not next(iter(pins), "") or "/" in pins:
            fail("SRAM_CAPTURE 需要当前 CP 唯一的 VERSION SWD PIN")
        try:
            capture = compile_sram_capture_plan(
                argument, capture_pin=next(iter(pins)), provenance=operation.provenance,
                result_identity=ResultIdentity(operation.cp, operation.item, str(operation.row + 2), "SRAM_CAPTURE"),
            )
        except SramCaptureCompileError as exc:
            fail(str(exc))
        subs = set()
        profile = _text(flow.iloc[operation.row].get("Vcc")).upper()
        for index, member in enumerate(members):
            if (member.cp.casefold(), member.item.casefold(), member.typed_kind) != (operation.cp.casefold(), operation.item.casefold(), "VERIFY_KEIL"):
                fail("SRAM 判定行必须连续位于同一 CP/item 且 mode=keil", member.row)
            if member.row != operation.row + index or member.row in plans:
                fail("SRAM 判定行不能跳行或重叠", member.row)
            member_calls = recipe_rows[member.row].operations
            if index and tuple(call.name for call in member_calls) != ("JUDGE",):
                fail("后续 SRAM 判定行 Recipe 必须显式填写 JUDGE", member.row)
            if any(call.parameters for call in member_calls):
                fail("SRAM 结果判定不接受 PF/等待等 Recipe 参数", member.row)
            record = flow.iloc[member.row]
            if index and _text(record.get("step")) not in ("", "/"):
                fail("后续 SRAM 判定行 step 必须留空或 /，避免重复触发", member.row)
            if _text(record.get("Vcc")).upper() != profile:
                fail("同一次 SRAM 采集的所有判定行必须使用同一 Vcc", member.row)
            if _text(record.get("UNIT")) != "/" or _text(record.get("target")) not in ("", "/"):
                fail("SRAM 无符号原始值使用 UNIT=/、target=/，上下限填写绝对数值", member.row)
            sub = _required_text(record.get("sub"), member.row, "sub")
            if sub.casefold() in subs:
                fail("同一次 SRAM 采集的 sub 必须唯一", member.row)
            subs.add(sub.casefold())
            try:
                low, high = (float(record.get(column)) for column in ("low_range(%)", "high_range(%)"))
                if not (math.isfinite(low) and math.isfinite(high) and 0 <= low <= high <= capture.layout.value_mask):
                    raise ValueError()
            except (TypeError, ValueError):
                fail("SRAM 上下限必须为位宽范围内的有限绝对数值，且下限不大于上限", member.row)
            plans[member.row] = SramValueJudgePlan(capture, index, low, high, sub, member.provenance)
    return plans


def _clock_cleanup_for(
    actions: tuple[NativeRunSequenceAction | FirmwareForceAction, ...]
) -> tuple[ClockStopAction, ...]:
    live_signals = ()
    for action in actions:
        if isinstance(action, ClockForceAction):
            live_signals = action.signals
        elif isinstance(action, (ForceStopAction, RepowerAction)):
            live_signals = ()
    return (ClockStopAction(live_signals),) if live_signals else ()


def validate_firmware_recipe_contract(
    operations: tuple[FlowOperation, ...], flow: pd.DataFrame
) -> None:
    """Reject intrinsic HEX Recipes and blank generic KEIL Recipes early."""
    for operation in operations:
        if operation.typed_kind not in ("VERIFY_HEX", "VERIFY_KEIL"):
            continue
        recipe = _text(flow.iloc[operation.row].get("Recipe"))
        if operation.mode == "hex" and recipe:
            raise FirmwareTestCompileError(
                "FW.RECIPE.HEX_INTRINSIC_ONLY",
                operation.row,
                "mode=hex 的 Recipe 必须为空；编译器固定使用 DOWNLOAD_CODE",
            )
        if operation.mode == "keil" and not recipe:
            raise FirmwareTestCompileError(
                "FW.RECIPE.KEIL_REQUIRED",
                operation.row,
                "mode=keil 必须显式填写 Recipe",
            )


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _required_text(value: object, row: int, field: str) -> str:
    value = _text(value)
    if not value or value == "/":
        raise FirmwareTestCompileError(
            "FW.PHASE.FACT_MISSING", row, f"{field} is required"
        )
    return value


def _default_pins(version: pd.DataFrame) -> Mapping[str, str]:
    if "CP num" not in version.columns or "GET PIN" not in version.columns:
        raise FirmwareTestCompileError(
            "FW.VERSION.GET_PIN_MISSING", 0, "VERSION requires CP num and GET PIN"
        )
    result = {}
    for row, record in version.iterrows():
        cp = _text(record.get("CP num")).upper()
        pin = _text(record.get("GET PIN"))
        if not cp:
            continue
        if not pin or pin == "/":
            raise FirmwareTestCompileError(
                "FW.VERSION.GET_PIN_MISSING", int(row), f"{cp} GET PIN is missing"
            )
        if cp in result and result[cp] != pin:
            raise FirmwareTestCompileError(
                "FW.VERSION.GET_PIN_CONFLICT", int(row), f"{cp} GET PIN conflicts"
            )
        result[cp] = pin
    return MappingProxyType(result)
