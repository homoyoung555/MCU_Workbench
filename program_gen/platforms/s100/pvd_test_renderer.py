"""Pure S100 renderer for the compiler-owned PVD hysteresis plan."""

from __future__ import annotations

import math
import re

from program_gen.core.firmware_judge import DigitalCompareJudgePlan
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.pvd_test import PvdTestPlan
from program_gen.core.trigger_pattern import trigger_pattern_name
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction
from program_gen.platform_program.facts import PlatformProgramFacts
from program_gen.platforms.s100.firmware_test_renderer import (
    action_pattern_span, compare_pattern_span,
    generate_digital_compare_resource,
    generate_level_sequence_resource,
    generate_send_code_resource,
)
from program_gen.render_plan import ResourceRequest


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class S100PvdRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_pvd_test(
    plan: PvdTestPlan,
    render_name: str,
    hardware_bin: int | str,
    platform_facts: PlatformProgramFacts,
) -> FirmwareBodyRender:
    """Render one runtime loop; every iteration owns one hysteresis session."""
    _validate(plan, render_name, platform_facts)
    dynamic = _loop_shape(plan)
    reject_bin = _hardware_bin(hardware_bin)
    resources: dict[str, ResourceRequest] = {}
    count = len(plan.cases)
    lines = [
        f"@@PLAN {render_name}",
        "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;",
        "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;",
        f"\tREMARK             = {render_name};",
        "",
    ]
    send_arrays = {}
    for number, (action_index, actions) in enumerate(dynamic, start=1):
        variable = "pvd_snd" if number == 1 else f"pvd_snd_{number}"
        send_arrays[action_index] = variable
        values = ",".join(str(action.value) for action in actions)
        lines.append(f"\tint {variable}[{count}]={{{values}}};")
    lines.extend((
        "\tchar _C_snd_st[100],_C_snd_sp[100];",
        "",
        f"\tfor(int item=0;item<{count};item++)",
        "\t{",
        f"\t\tCALL_MACRO POWER_ON(_C_{plan.power_profile});",
        "",
    ))
    for action_index in range(len(plan.cases[0].entry_actions)):
        actions = tuple(case.entry_actions[action_index] for case in plan.cases)
        if action_index in send_arrays:
            for action in actions:
                _add_resource(resources, generate_send_code_resource(action))
            stem = trigger_pattern_name(actions[0])
            variable = send_arrays[action_index]
            lines.extend((
                f'\t\tsprintf(_C_snd_st,"{stem}:S%02X_ST",{variable}[item]);',
                f'\t\tsprintf(_C_snd_sp,"{stem}:S%02X_SP",{variable}[item]);',
                "\t\tRUN_PATTERN(_C_snd_st,_C_snd_sp,1,VIH_5MHZ);",
            ))
        else:
            action = actions[0]
            resource = (
                generate_level_sequence_resource(action)
                if isinstance(action, LevelSequenceAction)
                else generate_send_code_resource(action)
            )
            _add_resource(resources, resource)
            start, end = action_pattern_span(action)
            lines.append(
                f"\t\tRUN_PATTERN({start},{end},1,VIH_5MHZ);"
            )
    lines.append("")

    for point_index, point in enumerate(plan.cases[0].points):
        # Direct DPS updates preserve the PVD hysteresis state inside the session.
        lines.extend(("\t\tswitch(item)", "\t\t{"))
        for case_index, case in enumerate(plan.cases):
            voltage = float(case.points[point_index].voltage)
            lines.append(f"\t\t\tcase {case_index}:")
            for rail in platform_facts.force_rails:
                lines.append(
                    f"\t\t\t\tLOGIC_FORCE_DPS({rail}, {_voltage(voltage)}, "
                    "500MA, I7, WAIT=0.5MS);"
                )
            lines.extend((
                f"\t\t\t\tLOGIC_SET_DRV_LEVEL(IO_ALLPINS, {_voltage(voltage)}, "
                "0.0V, 0.0V, VR1);",
                f"\t\t\t\tLOGIC_SET_CMP_LEVEL(IO_ALLPINS, "
                f"{_voltage(voltage * 0.55)}, {_voltage(voltage * 0.45)}, VR2);",
                "\t\t\t\tbreak;",
            ))
        lines.append("\t\t}")
        judge = DigitalCompareJudgePlan(
            plan.compare_pins,
            point.expected,
            "/",
            f"runtime_{point_index + 1}",
            plan.provenance,
        )
        resource = generate_digital_compare_resource(judge)
        _add_resource(resources, resource)
        start, end = compare_pattern_span(judge)
        lines.extend((
            f"\t\tRUN_PATTERN({start},{end},1,VIH_5MHZ);",
            "",
        ))
    lines.extend(("\t\tCALL_MACRO POWER_OFF();", "\t}", ""))

    lines.extend((
        "\tCONDITION",
        "\tIF_FAIL",
        f"\tREJECT_BIN = {reject_bin};",
        "@@END_PLAN",
    ))
    return FirmwareBodyRender("\n".join(lines) + "\n", tuple(resources.values()))


def _validate(plan, render_name, facts) -> None:
    if not isinstance(plan, PvdTestPlan):
        raise S100PvdRenderError("S100.PVD.PLAN.INVALID", type(plan).__name__)
    if plan.typed_kind != "PVD_TEST" or plan.effective_recipe != ("PVD_TEST",):
        raise S100PvdRenderError("S100.PVD.RECIPE.INVALID", plan.typed_kind)
    if not _IDENTIFIER.fullmatch(str(render_name)):
        raise S100PvdRenderError("S100.PVD.RENDER_NAME.INVALID", str(render_name))
    if facts.platform.casefold() != "s100":
        raise S100PvdRenderError("S100.PVD.PLATFORM.INVALID", facts.platform)
    if facts.cp.casefold() != plan.cp.casefold():
        raise S100PvdRenderError(
            "S100.PVD.CP.MISMATCH", f"{plan.cp}/{facts.cp}"
        )
    if not plan.cases or not facts.force_rails:
        raise S100PvdRenderError(
            "S100.PVD.SESSION.INVALID", "cases and force rails are required"
        )
    if not _IDENTIFIER.fullmatch(plan.power_profile):
        raise S100PvdRenderError(
            "S100.PVD.POWER_PROFILE.INVALID", plan.power_profile
        )
    for rail in facts.force_rails:
        if not _IDENTIFIER.fullmatch(rail):
            raise S100PvdRenderError("S100.PVD.RAIL.INVALID", rail)


def _loop_shape(plan):
    first = plan.cases[0]
    expected = tuple(point.expected for point in first.points)
    action_count = len(first.entry_actions)
    dynamic = []
    for case in plan.cases:
        if not case.entry_actions or len(case.points) != 4:
            raise S100PvdRenderError("S100.PVD.CASE.SHAPE_INVALID", case.case_id)
        for point in case.points:
            _scalar(point.voltage)
            if (
                len(point.expected) != len(plan.compare_pins)
                or any(state not in ("H", "L") for state in point.expected)
            ):
                raise S100PvdRenderError(
                    "S100.PVD.CASE.EXPECT_INVALID", case.case_id
                )
        if tuple(point.expected for point in case.points) != expected:
            raise S100PvdRenderError(
                "S100.PVD.CASE.COMPARE_SHAPE_MISMATCH", case.case_id
            )
        if len(case.entry_actions) != action_count:
            raise S100PvdRenderError(
                "S100.PVD.CASE.ACTION_SHAPE_MISMATCH", case.case_id
            )
        if any(
            not isinstance(action, (LevelSequenceAction, SendCodeAction))
            for action in case.entry_actions
        ):
            raise S100PvdRenderError(
                "S100.PVD.ACTION.UNSUPPORTED", case.case_id
            )
    for index in range(action_count):
        actions = tuple(case.entry_actions[index] for case in plan.cases)
        if all(action == actions[0] for action in actions[1:]):
            continue
        if not all(
            isinstance(action, SendCodeAction)
            and action.pin.casefold() == actions[0].pin.casefold()
            and action.explicit_pin == actions[0].explicit_pin
            for action in actions
        ):
            raise S100PvdRenderError(
                "S100.PVD.CASE.ACTION_SHAPE_MISMATCH", str(index + 1)
            )
        dynamic.append((index, actions))
    return tuple(dynamic)


def _add_resource(
    resources: dict[str, ResourceRequest], resource: ResourceRequest
) -> None:
    previous = resources.get(resource.logical_identity)
    if previous is not None and previous != resource:
        raise S100PvdRenderError(
            "S100.PVD.RESOURCE.CONFLICT", resource.logical_identity
        )
    resources[resource.logical_identity] = resource


def _hardware_bin(value: int | str) -> int:
    if isinstance(value, bool) or not str(value).strip().isdigit():
        raise S100PvdRenderError("S100.PVD.BIN.INVALID", repr(value))
    return int(str(value).strip())


def _voltage(value: float) -> str:
    return _scalar(value) + "V"


def _scalar(value: float) -> str:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise S100PvdRenderError("S100.PVD.VOLTAGE.INVALID", repr(value))
    return str(int(number)) if number.is_integer() else format(number, ".12g")


__all__ = ["S100PvdRenderError", "render_pvd_test"]
