"""Pure S100 renderer for native FREQ_TEST plans."""

from __future__ import annotations

import re

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.freq_test import FreqTestPlan
from program_gen.render_plan import ResourceRequirement
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.s100.firmware_test_renderer import (
    action_pattern_span, generate_level_sequence_resource, generate_send_code_resource,
)


def render_freq_test(plan, render_name, hardware_bin, facts):
    _validate(plan, render_name, facts)
    body = [f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});", ""]
    resources = []
    body.extend(_actions(plan.entry_actions, resources))
    for index, case in enumerate(plan.cases):
        body.append(
            f"\t// ==================== FREQ: {case.source} * {_num(case.multiplier)} / {_num(case.divider)} -> {_num(case.target)} {case.unit} ===================="
        )
        if index and case.repower_before:
            body.extend(("\tCALL_MACRO POWER_OFF();", f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});", ""))
            body.extend(_actions(plan.entry_actions, resources))
        if case.external_clock is not None:
            body.extend((
                f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN({case.external_clock.pin},{_num(case.external_clock.frequency_hz)});",
                "",
            ))
        if case.config_pattern:
            body.extend((f"\tRUN_PATTERN({case.config_pattern}:START,{case.config_pattern}:END,1,TS_5MHZ);", ""))
        else:
            body.extend(_actions(case.actions, resources))
        body.extend((
            f"\tLOGIC_SET_CMP_LEVEL({plan.measurement_pin},2V,2V,VR1);",
            "\tWAIT(3MS);",
            f"\tLOGIC_TMU_STARTPIN({plan.measurement_pin},VOH,POS);",
            f"\tLOGIC_TMU_STOPPIN({plan.measurement_pin},VOL,POS);",
            "\tLOGIC_TMU_SET_AND_START(CMD_TRIG,NULL,AVG=128,HYS_ON);",
            "\tWAIT(3MS);",
            f"\tLOGIC_TMU_MEAS_FREQ(DOWN_LIMIT={_num(case.low_limit)}{case.unit},UP_LIMIT={_num(case.high_limit)}{case.unit},TIME_OUT=50mS);",
        ))
        if case.external_clock is not None:
            body.extend((f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN(NULL,{_num(case.external_clock.frequency_hz)});", ""))
        else:
            body.append("")
    body.extend(_actions(plan.exit_actions, resources))
    body.extend(("\tCALL_MACRO POWER_OFF();", ""))
    lines = [
        f"@@PLAN {render_name}", "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;", "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;", f"\tREMARK             = {render_name};", "",
        *body, "\tCONDITION", "\t\tIF_FAIL", f"\t\tREJECT_BIN = {_hardware_bin(hardware_bin)};", "@@END_PLAN",
    ]
    return FirmwareBodyRender(
        "\n".join(lines) + "\n",
        resources=tuple(resources),
        resource_requires=tuple(_external(pattern) for pattern in plan.config_patterns),
    )


def _actions(actions, resources):
    lines = []
    for action in actions:
        if isinstance(action, WaitAction):
            lines.append(f"\tWAIT({action.duration_ms}MS);")
        else:
            if isinstance(action, LevelSequenceAction):
                resource = generate_level_sequence_resource(action)
            elif isinstance(action, SendCodeAction):
                resource = generate_send_code_resource(action)
            else:
                raise ValueError(f"FREQ.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource)
            start, end = action_pattern_span(action)
            lines.extend((f"\tRUN_PATTERN({start},{end},1,TS_5MHZ);", ""))
    return tuple(lines)


def _external(pattern):
    return ResourceRequirement(
        f"freq-swd:s100:{pattern.casefold()}", f"{pattern}.sd",
        "v14.freq-swd/1:s100:external", f"FREQ SWD Pattern ({pattern})",
    )


def _power(value):
    return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I) else f"_C_{value}"


def _num(value):
    return format(float(value), ".12g")


def _hardware_bin(value):
    if isinstance(value, bool) or not str(value).strip().isdigit():
        raise ValueError("FREQ.S100.BIN.INVALID")
    return int(str(value).strip())


def _validate(plan, name, facts):
    if not isinstance(plan, FreqTestPlan):
        raise TypeError("FREQ.S100.PLAN.INVALID")
    if plan.typed_kind != "FREQ_TEST" or plan.effective_recipe != ("FREQ_TEST",):
        raise ValueError("FREQ.S100.CONTRACT.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
        raise ValueError("FREQ.S100.NAME.INVALID")
    if facts.platform.casefold() != "s100" or facts.cp.casefold() != plan.cp.casefold():
        raise ValueError("FREQ.S100.FACTS.INVALID")


__all__ = ["render_freq_test"]
