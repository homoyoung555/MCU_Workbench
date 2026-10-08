"""Compile one-dimensional Shmoo rows into writer-facing plans."""

from dataclasses import dataclass
import math
import re
from typing import Dict, Tuple

import pandas as pd

from flow_recipe import FlowCompileError, RecipeDuration, compile_recipe_program
from program_gen.core.encoding import calc_limit
from program_gen.core.recipe_trim import recipe_pattern_name


class ShmooRecipeError(ValueError):
    """A Shmoo FLOW group cannot be represented by the first-version adapter."""


@dataclass(frozen=True)
class ShmooPoint:
    flow_row_index: int
    sub: str
    log_name: str
    dac: int
    target: object
    low_range: object
    high_range: object
    down_limit: float
    up_limit: float


@dataclass(frozen=True)
class ShmooPlan:
    flow_row_index: int
    cp: str
    item: str
    mode: str
    pattern_name: str
    default_value: str
    field_width: int
    vcc: str
    meas_pin: str
    force_value: str
    unit: str
    hbin: object
    force_wait: RecipeDuration | None
    pass_fail: bool
    points: Tuple[ShmooPoint, ...]

    @property
    def function_name(self) -> str:
        return self.item if self.item.lower().endswith("shmoo") else self.item + "_Shmoo"


def compile_shmoo_plans(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
) -> Dict[int, ShmooPlan]:
    """Return one plan per contiguous CP+item+type=shmoo group, keyed by its first row."""
    if "Recipe" not in flow_frame.columns:
        return {}
    recipe_text = flow_frame["Recipe"].fillna("").astype(str).str.strip()
    migrated = flow_frame.loc[recipe_text.ne("")]
    if migrated.empty:
        return {}

    try:
        program = compile_recipe_program(migrated, pattern_frame)
    except FlowCompileError as exc:
        raise ShmooRecipeError(str(exc)) from exc

    plans = {}
    for function in program.functions:
        if function.key.flow_type != "shmoo":
            continue
        rows = function.rows
        first = rows[0]
        # Persistent COMMIT Shmoo is compiled by core.commit_shmoo.  Keeping it
        # out here prevents the measurement compiler from treating it as an
        # invalid ENTER/JUDGE group before main can apply its priority rule.
        if first.operations and first.operations[0].name == "COMMIT":
            continue
        first_index = first.flow.excel_row - 2
        first_record = flow_frame.loc[first_index]
        _require_same_setup(flow_frame, rows)

        points = []
        seen_dacs = set()
        enter = None
        judge_wait = None
        pass_fail = None
        for executable in rows:
            names = [operation.name for operation in executable.operations]
            if names != ["ENTER", "JUDGE"]:
                raise ShmooRecipeError(
                    f"FLOW row {executable.flow.excel_row}: type=shmoo PF=YES 第一版必须使用 ENTER-JUDGE"
                )
            row_enter, judge = executable.operations
            pf = judge.named_parameter("PF") or "YES"
            row_pass_fail = pf == "YES"
            if pass_fail is None:
                pass_fail = row_pass_fail
            elif row_pass_fail != pass_fail:
                raise ShmooRecipeError(
                    f"FLOW row {executable.flow.excel_row}: 同一 Shmoo item 的 JUDGE.PF 必须一致"
                )
            if row_enter.dynamic_field is None:
                raise ShmooRecipeError(
                    f"FLOW row {executable.flow.excel_row}: Shmoo ENTER 必须绑定一个动态 Pattern 字段"
                )
            if row_pass_fail and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", executable.flow.sub):
                raise ShmooRecipeError(
                    f"FLOW row {executable.flow.excel_row}: PF=YES 的 sub 必须是可用作 LOG_ALIAS 的名称，"
                    f"实际 {executable.flow.sub!r}"
                )
            if enter is None:
                enter = row_enter
                judge_wait = judge.time_parameter("FWAIT")
            elif (
                row_enter.dynamic_field != enter.dynamic_field
                or row_enter.pattern_role != enter.pattern_role
                or judge.time_parameter("FWAIT") != judge_wait
            ):
                raise ShmooRecipeError(
                    f"FLOW row {executable.flow.excel_row}: 同一 Shmoo item 的 Pattern 字段或 JUDGE.FWAIT 不一致"
                )

            row_index = executable.flow.excel_row - 2
            record = flow_frame.loc[row_index]
            width = row_enter.dynamic_field.width
            low = record["low_range(%)"]
            high = record["high_range(%)"]
            target = record["target"]
            dacs = (_decimal_step(record["step"], executable.flow.excel_row),) if row_pass_fail else _decimal_range(
                record["step"], executable.flow.excel_row
            )
            for dac in dacs:
                if dac >= 1 << width:
                    raise ShmooRecipeError(
                        f"FLOW row {executable.flow.excel_row}: step={dac} 超出 Pattern 动态字段 {width} bit 范围 0-{(1 << width) - 1}"
                    )
                if dac in seen_dacs:
                    raise ShmooRecipeError(
                        f"FLOW row {executable.flow.excel_row}: 同一 Shmoo item 的 step={dac} 重复"
                    )
                seen_dacs.add(dac)
                down_limit, up_limit = _point_limits(target, low, high, row_pass_fail)
                sub = executable.flow.sub if row_pass_fail else f"dac{dac}"
                points.append(ShmooPoint(
                    flow_row_index=row_index,
                    sub=sub,
                    log_name=f"{executable.flow.item}_{sub}",
                    dac=dac,
                    target=target,
                    low_range=low,
                    high_range=high,
                    down_limit=down_limit,
                    up_limit=up_limit,
                ))

        if not pass_fail and len(rows) != 1:
            raise ShmooRecipeError(
                f"FLOW row {first.flow.excel_row}: PF=NO 只需一行，并在 step 填十进制范围（如 0-7）"
            )

        plans[first_index] = ShmooPlan(
            flow_row_index=first_index,
            cp=first.flow.cp,
            item=first.flow.item,
            mode=first.flow.mode,
            pattern_name=recipe_pattern_name(first.flow.item, enter.pattern_role),
            default_value=enter.dynamic_field.value,
            field_width=enter.dynamic_field.width,
            vcc=str(first_record["Vcc"]).strip(),
            meas_pin=str(first_record["meas pin"]).strip(),
            force_value=str(first_record["FV/FI"]).strip(),
            unit=str(first_record["UNIT"]).strip(),
            hbin=first_record["Hbin"],
            force_wait=judge_wait,
            pass_fail=pass_fail,
            points=tuple(points),
        )
        if plans[first_index].unit not in ("V", "uA", "mA", "A"):
            raise ShmooRecipeError(
                f"FLOW row {first.flow.excel_row}: PF=YES 第一版 UNIT 仅支持 V/uA/mA/A，"
                f"实际 {plans[first_index].unit!r}"
            )
    return plans


def _decimal_step(value: object, excel_row: int) -> int:
    if isinstance(value, bool):
        raise ShmooRecipeError(f"FLOW row {excel_row}: step 必须是非负十进制整数")
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if math.isfinite(number) and number >= 0 and number.is_integer():
        return int(number)
    raise ShmooRecipeError(f"FLOW row {excel_row}: step 必须是非负十进制整数，实际 {value!r}")


def _decimal_range(value: object, excel_row: int) -> Tuple[int, ...]:
    text = str(value).strip()
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if not match:
        raise ShmooRecipeError(
            f"FLOW row {excel_row}: PF=NO 的 step 必须是十进制范围（如 0-7），实际 {value!r}"
        )
    start, end = (int(part) for part in match.groups())
    direction = 1 if end >= start else -1
    return tuple(range(start, end + direction, direction))


def _point_limits(target: object, low: object, high: object, pass_fail: bool) -> Tuple[float, float]:
    if pass_fail or (not pd.isna(low) and not pd.isna(high)):
        return calc_limit(target, low, high, True), calc_limit(target, low, high, False)
    value = float(target)
    return value, value


def _require_same_setup(flow_frame: pd.DataFrame, rows) -> None:
    columns = ("mode", "Vcc", "meas pin", "FV/FI", "UNIT", "Hbin")
    first_index = rows[0].flow.excel_row - 2
    first = tuple(str(flow_frame.loc[first_index, column]).strip() for column in columns)
    for executable in rows[1:]:
        row_index = executable.flow.excel_row - 2
        actual = tuple(str(flow_frame.loc[row_index, column]).strip() for column in columns)
        if actual != first:
            raise ShmooRecipeError(
                f"FLOW row {executable.flow.excel_row}: 同一 Shmoo item 的 "
                + "/".join(columns) + " 必须一致；每个 sub 只改变 step/target/limit"
            )
