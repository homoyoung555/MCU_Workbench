"""Pure Chroma renderer for DC_VIH_VIL."""

from __future__ import annotations

import hashlib
import re

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.core.vih_vil import KeilVihVilPlan, SwdVihVilPlan, build_vih_vil_vectors
from program_gen.platforms.chroma.firmware_test_renderer import (
    action_pattern_span, generate_level_sequence_resource, generate_send_code_resource,
)
from program_gen.render_plan import ResourceRequest, ResourceRequirement


def render_vih_vil(plan, render_name, hardware_bin, facts):
    _validate(plan, render_name, facts)
    _ = hardware_bin
    if isinstance(plan, SwdVihVilPlan):
        return _render_swd(plan, render_name)
    return _render_keil(plan, render_name, facts)


def _render_swd(plan, name):
    requirements = tuple(_external(pattern) for pattern in plan.patterns)
    lines = [f"{name}()", "{", f"  POWER_ON({_power(plan.power_profile)});", ""]
    lines.extend(_judge(plan.config_pattern))
    modes = (("LL", "F0", "F0"), ("HH", "F1", "F1"), ("HL", "F1", "F0"), ("LH", "F0", "F1"))
    for (case, odd, even), pattern in zip(modes, plan.capture_patterns):
        lines.extend((
            f"  PIN_MODE(VILVIH_ODD,{odd},EDGE,MASK,IO_ON,OFF);",
            f"  PIN_MODE(VILVIH_EVEN,{even},EDGE,MASK,IO_ON,OFF);", "",
        ))
        lines.extend(_judge(pattern))
    lines.extend((
        "  PIN_MODE(VILVIH_ODD,NRZ,EDGE,ENABLE,IO_NRZ,OFF);",
        "  PIN_MODE(VILVIH_EVEN,NRZ,EDGE,ENABLE,IO_NRZ,OFF);",
        "  POWER_OFF();", "}",
    ))
    return FirmwareBodyRender("\n".join(lines) + "\n", resource_requires=requirements)


def _render_keil(plan, name, facts):
    lines = [f"{name}()", "{"]
    resources = []
    for variant in plan.variants:
        voltage = _power(plan.power_profile)
        lines.extend((
            f"  POWER_ON({voltage});",
            f"  SET_LEVELN(TYP_LVL,IO_ALLPINS,{voltage}*0.45,{voltage}*0.55,{voltage}*0.33,{voltage}*0.67,0uA,0uA,{voltage}*0.5,,);",
            "  LEVELS(TYP_LVL,3mS);",
            f"  PIN_MODE({facts.clk_pin},NRZ,EDGE,ENABLE,IO_NRZ,OFF);", "",
        ))
        for action in variant.entry_actions:
            if isinstance(action, WaitAction):
                lines.append(f"  WAIT({action.duration_ms}mS);")
                continue
            resource = (
                generate_level_sequence_resource(action)
                if isinstance(action, LevelSequenceAction)
                else generate_send_code_resource(action)
                if isinstance(action, SendCodeAction)
                else None
            )
            if resource is None:
                raise ValueError(f"VIHVIL.CHROMA.ENTRY_ACTION_INVALID: {type(action).__name__}")
            resources.append(resource)
            lines.extend(_judge(*action_pattern_span(action)))
        resource = _keil_pattern(variant.pattern, facts.io_pins, variant.variant)
        resources.append(resource)
        lines.extend(_judge(variant.pattern))
        lines.extend((
            "  SET_LEVELN(TYP_LVL,IO_ALLPINS,0V,VCC_TYP,VCC_TYP*0.45,VCC_TYP*0.55,0uA,0uA,VCC_TYP*0.5,,);",
            "  POWER_OFF();", "",
        ))
    lines.append("}")
    return FirmwareBodyRender("\n".join(lines) + "\n", resources=tuple(resources))


def _judge(pattern, end=None):
    return ["  TEST_NUM++;", f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";', f"  JUDGE_PAT({pattern},{end or '__' + pattern});", ""]


def _external(pattern):
    return ResourceRequirement(
        f"vih-vil-swd:chroma:{pattern.casefold()}", f"pat/{pattern}.pat",
        "v14.vih-vil-swd/1:chroma:external", f"VIH/VIL SWD Pattern ({pattern})",
    )


def _keil_pattern(name, pins, variant):
    vectors = build_vih_vil_vectors(tuple(pins), variant)
    idle = "X" * len(vectors.pins)
    rows = [f"*{idle}*TS1;", f"*{vectors.case_a_input}*RPT 1000;", f"*{vectors.case_a_input}*RPT 10000;"]
    rows.extend(f"*{vectors.case_a_full}*;" for _ in range(10))
    rows.extend((f"*{idle}*;", f"*{vectors.case_b_input}*RPT 1000;", f"*{vectors.case_b_input}*RPT 10000;"))
    rows.extend(f"*{vectors.case_b_full}*;" for _ in range(10))
    rows.append(f"*{idle}*STOP;")
    content = ('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + ",".join(vectors.pins) + ";\n\n" + f"SPM_PATTERN({name}) {{\n\n  " + "\n  ".join(rows) + "\n}\n").encode("ascii")
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(f"vih-vil:chroma:{name.casefold()}", f"pat/{name}.pat", content, "v14.vih-vil/1:chroma:generated", f"generated:chroma:vih-vil:sha256:{digest}", "Chroma generated VIH/VIL judge Pattern")


def _power(value):
    return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I) else value


def _validate(plan, name, facts):
    if not isinstance(plan, (SwdVihVilPlan, KeilVihVilPlan)):
        raise TypeError("VIHVIL.CHROMA.PLAN.INVALID")
    if plan.typed_kind != "DC_VIH_VIL" or plan.effective_recipe != ("VIH_VIL_TEST",):
        raise ValueError("VIHVIL.CHROMA.CONTRACT.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
        raise ValueError("VIHVIL.CHROMA.NAME.INVALID")
    if facts.platform.casefold() != "chroma" or facts.cp.casefold() != plan.cp.casefold():
        raise ValueError("VIHVIL.CHROMA.FACTS.INVALID")
    if not facts.pin_groups.vih_vil_odd or not facts.pin_groups.vih_vil_even:
        raise ValueError("VIHVIL.CHROMA.GROUPS.EMPTY")


__all__ = ["render_vih_vil"]
