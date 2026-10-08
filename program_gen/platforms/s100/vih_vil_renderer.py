"""Pure S100 renderer for DC_VIH_VIL."""

from __future__ import annotations

import hashlib
import re

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.core.vih_vil import KeilVihVilPlan, SwdVihVilPlan, build_vih_vil_vectors
from program_gen.platforms.s100.firmware_test_renderer import (
    action_pattern_span, generate_level_sequence_resource, generate_send_code_resource,
)
from program_gen.render_plan import ResourceRequest, ResourceRequirement


def render_vih_vil(plan, render_name, hardware_bin, facts):
    _validate(plan, render_name, facts)
    if isinstance(plan, SwdVihVilPlan):
        body = _swd_lines(plan)
        resources, requirements = (), tuple(_external(pattern) for pattern in plan.patterns)
    else:
        body, resources = _keil_lines(plan, facts)
        requirements = ()
    lines = [
        f"@@PLAN {render_name}", "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;", "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;", f"\tREMARK             = {render_name};", "",
        *body, "\tCONDITION", "\t\tIF_FAIL", f"\t\tREJECT_BIN = {_hardware_bin(hardware_bin)};", "@@END_PLAN",
    ]
    return FirmwareBodyRender("\n".join(lines) + "\n", resources=resources, resource_requires=requirements)


def _swd_lines(plan):
    lines = [f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});", "", *_run(plan.config_pattern)]
    modes = ((False, False), (True, True), (True, False), (False, True))
    for (odd_high, even_high), pattern in zip(modes, plan.capture_patterns):
        lines.extend((
            f"\tLOGIC_SET_DRV_LEVEL(VILVIH_ODD,{_drive(odd_high, plan.power_profile)},0.0V,0.0V,VR1);",
            f"\tLOGIC_SET_DRV_LEVEL(VILVIH_EVEN,{_drive(even_high, plan.power_profile)},0.0V,0.0V,VR1);", "",
            *_run(pattern),
        ))
    lines.extend((
        "\tLOGIC_SET_DRV_LEVEL(VILVIH_ODD,0.0V,0.0V,0.0V,VR1);",
        "\tLOGIC_SET_DRV_LEVEL(VILVIH_EVEN,0.0V,0.0V,0.0V,VR1);",
        "\tCALL_MACRO POWER_OFF();", "",
    ))
    return lines


def _keil_lines(plan, facts):
    lines, resources = [], []
    for variant in plan.variants:
        voltage = _power(plan.power_profile)
        lines.extend((
            f"\tCALL_MACRO POWER_ON({voltage});",
            f"\tLOGIC_SET_DRV_LEVEL(IO_ALLPINS,{voltage}*0.55,{voltage}*0.45,0.0V,VR1);",
            f"\tLOGIC_SET_CMP_LEVEL(IO_ALLPINS,{voltage}*0.67,{voltage}*0.33,VR1);", "",
        ))
        for action in variant.entry_actions:
            if isinstance(action, WaitAction):
                lines.append(f"\tWAIT({action.duration_ms}MS);")
                continue
            resource = (
                generate_level_sequence_resource(action)
                if isinstance(action, LevelSequenceAction)
                else generate_send_code_resource(action)
                if isinstance(action, SendCodeAction)
                else None
            )
            if resource is None:
                raise ValueError(f"VIHVIL.S100.ENTRY_ACTION_INVALID: {type(action).__name__}")
            resources.append(resource)
            start, end = action_pattern_span(action)
            lines.extend((f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);", ""))
        resource = _keil_pattern(variant.pattern, facts.io_pins, variant.variant)
        resources.append(resource)
        lines.extend(_run(variant.pattern))
        lines.extend(("\tCALL_MACRO POWER_OFF();", ""))
    return lines, tuple(resources)


def _run(pattern):
    return [f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,VIH_5MHZ);", ""]


def _external(pattern):
    return ResourceRequirement(
        f"vih-vil-swd:s100:{pattern.casefold()}", f"{pattern}.sd",
        "v14.vih-vil-swd/1:s100:external", f"VIH/VIL SWD Pattern ({pattern})",
    )


def _keil_pattern(name, pins, variant):
    vectors = build_vih_vil_vectors(tuple(pins), variant)
    idle = "X" * len(vectors.pins)
    rows = [f"START:{idle};", f"      {vectors.case_a_input};RPT 1000;", f"      {vectors.case_a_input};RPT 10000;"]
    rows.extend(f"      {vectors.case_a_full};" for _ in range(10))
    rows.extend((f"      {idle};", f"      {vectors.case_b_input};RPT 1000;", f"      {vectors.case_b_input};RPT 10000;"))
    rows.extend(f"      {vectors.case_b_full};" for _ in range(10))
    rows.append(f"  END:{idle};")
    content = ("HEAD[PIN_NAME]:\n\n" + ",".join(vectors.pins) + ";\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n" + "\n".join(rows) + "\n\n@@END_PATTERN_DEFINE\n").encode("ascii")
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(f"vih-vil:s100:{name.casefold()}", f"{name}.sd", content, "v14.vih-vil/1:s100:generated", f"generated:s100:vih-vil:sha256:{digest}", "S100 generated VIH/VIL judge Pattern")


def _power(value):
    return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I) else f"_C_{value}"


def _drive(high, profile):
    return _power(profile) if high else "0.0V"


def _hardware_bin(value):
    if isinstance(value, bool) or not str(value).strip().isdigit():
        raise ValueError("VIHVIL.S100.BIN.INVALID")
    return int(str(value).strip())


def _validate(plan, name, facts):
    if not isinstance(plan, (SwdVihVilPlan, KeilVihVilPlan)):
        raise TypeError("VIHVIL.S100.PLAN.INVALID")
    if plan.typed_kind != "DC_VIH_VIL" or plan.effective_recipe != ("VIH_VIL_TEST",):
        raise ValueError("VIHVIL.S100.CONTRACT.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
        raise ValueError("VIHVIL.S100.NAME.INVALID")
    if facts.platform.casefold() != "s100" or facts.cp.casefold() != plan.cp.casefold():
        raise ValueError("VIHVIL.S100.FACTS.INVALID")
    if not facts.pin_groups.vih_vil_odd or not facts.pin_groups.vih_vil_even:
        raise ValueError("VIHVIL.S100.GROUPS.EMPTY")


__all__ = ["render_vih_vil"]
