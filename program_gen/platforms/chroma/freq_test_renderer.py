"""Pure Chroma renderer for native FREQ_TEST plans."""

from __future__ import annotations

import re

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.freq_test import FreqTestPlan
from program_gen.render_plan import ResourceRequirement
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.chroma.firmware_test_renderer import (
    action_pattern_span, generate_level_sequence_resource, generate_send_code_resource,
)


def render_freq_test(plan, render_name, hardware_bin, facts):
    _validate(plan, render_name, facts)
    _ = hardware_bin
    schmitt_on = f"  SET_TFTM_MODE({plan.measurement_pin},SCHMITT_ON);"
    schmitt_off = f"  SET_TFTM_MODE({plan.measurement_pin},SCHMITT_OFF);"
    lines = [f"{render_name}()", "{", f"  POWER_ON({_power(plan.power_profile)});", schmitt_on, ""]
    resources = []
    lines.extend(_actions(plan.entry_actions, resources))
    for index, case in enumerate(plan.cases):
        lines.append(
            f"  // ==================== FREQ: {case.source} * {_num(case.multiplier)} / {_num(case.divider)} -> {_num(case.target)} {case.unit} ===================="
        )
        if index and case.repower_before:
            lines.extend((schmitt_off, "  POWER_OFF();", f"  POWER_ON({_power(plan.power_profile)});", schmitt_on, ""))
            lines.extend(_actions(plan.entry_actions, resources))
        if case.external_clock is not None:
            lines.extend(_external_start(case.external_clock.pin, case.external_clock.frequency_hz))
        lines.extend(_run(case.config_pattern) if case.config_pattern else _actions(case.actions, resources))
        lines.extend((
            "  WAIT(3mS);",
            f"  JUDGE_FREQ({plan.measurement_pin},,,,{_num(case.low_limit)}{case.unit},{_num(case.high_limit)}{case.unit},{_gate(case.target, case.unit)},,50mS,);",
        ))
        if case.external_clock is not None:
            lines.extend(_external_stop(case.external_clock.pin))
        lines.append("")
    lines.extend(_actions(plan.exit_actions, resources))
    lines.extend((schmitt_off, "  POWER_OFF();", "}"))
    return FirmwareBodyRender(
        "\n".join(lines) + "\n",
        resources=tuple(resources),
        resource_requires=tuple(_external(pattern) for pattern in plan.config_patterns),
    )


def _run(pattern, end=None):
    return (
        "  TEST_NUM++;",
        f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";',
        f"  JUDGE_PAT({pattern},{end or '__' + pattern});",
        "",
    )


def _external_start(pin, frequency_hz):
    period = 1e9 / frequency_hz
    return (
        f"  PIN_MODE({pin},FCLK,EDGE,MASK,IO_ON,OFF);",
        f"  FRUN_CLK({pin},{_num(period)}nS,0nS,{_num(period / 2)}nS);",
        f"  FRUN_CLK_MODE({pin},1,0,ON);",
        "",
    )


def _external_stop(pin):
    return (f"  FRUN_CLK_MODE({pin},1,0,OFF);", "")


def _actions(actions, resources):
    lines = []
    for action in actions:
        if isinstance(action, WaitAction):
            lines.append(f"  WAIT({action.duration_ms}mS);")
        else:
            if isinstance(action, LevelSequenceAction):
                resource = generate_level_sequence_resource(action)
            elif isinstance(action, SendCodeAction):
                resource = generate_send_code_resource(action)
            else:
                raise ValueError(f"FREQ.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource)
            lines.extend(_run(*action_pattern_span(action)))
    return tuple(lines)


def _external(pattern):
    return ResourceRequirement(
        f"freq-swd:chroma:{pattern.casefold()}", f"pat/{pattern}.pat",
        "v14.freq-swd/1:chroma:external", f"FREQ SWD Pattern ({pattern})",
    )


def _gate(target, unit):
    if unit == "Hz":
        return "@1KHZ"
    if unit == "KHz":
        return "@1KHZ" if target < 1 else "@10KHZ" if target < 10 else "@100KHZ" if target < 100 else "@1MHZ"
    return "@1MHZ" if target < 1 else "@5MHZ" if target < 5 else "@10MHZ" if target < 10 else "@100MHZ"


def _power(value):
    return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I) else value


def _num(value):
    return format(float(value), ".12g")


def _validate(plan, name, facts):
    if not isinstance(plan, FreqTestPlan):
        raise TypeError("FREQ.CHROMA.PLAN.INVALID")
    if plan.typed_kind != "FREQ_TEST" or plan.effective_recipe != ("FREQ_TEST",):
        raise ValueError("FREQ.CHROMA.CONTRACT.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
        raise ValueError("FREQ.CHROMA.NAME.INVALID")
    if facts.platform.casefold() != "chroma" or facts.cp.casefold() != plan.cp.casefold():
        raise ValueError("FREQ.CHROMA.FACTS.INVALID")


__all__ = ["render_freq_test"]
