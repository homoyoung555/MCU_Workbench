"""Pure Chroma renderer for platform-neutral PVD hysteresis plans."""

from __future__ import annotations

import math
import re

from program_gen.core.firmware_judge import DigitalCompareJudgePlan
from program_gen.core.trigger_pattern import trigger_pattern_name
from program_gen.platforms.chroma.firmware_test_renderer import (
    action_pattern_span, compare_pattern_span, generate_level_sequence_resource,
    generate_send_code_resource, generate_digital_compare_resource,
)
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.pvd_test import PvdCase, PvdPoint, PvdTestPlan
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction
from program_gen.render_plan import ResourceRequest


_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CASE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
_PVD_LEVEL_NS = 5_000_000


class ChromaPvdRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class _Renderer:
    def __init__(self, plan: PvdTestPlan, facts):
        self.plan = plan
        self.facts = facts
        self.lines: list[str] = []
        self.resources: dict[str, ResourceRequest] = {}

    def render(self, name: str) -> FirmwareBodyRender:
        dynamic = self._validate_loop_shape()
        count = len(self.plan.cases)
        voltage_rows = ",".join(
            "{" + ",".join(_number(point.voltage) for point in case.points) + "}"
            for case in self.plan.cases
        )
        case_width = max(len(case.case_id) for case in self.plan.cases) + 1
        case_ids = ",".join(f'"{case.case_id}"' for case in self.plan.cases)
        self.lines.extend((
            f"{name}()",
            "{",
            f"  double pvd_v[{count}][4]={{{voltage_rows}}};",
            f"  char pvd_case[{count}][{case_width}]={{{case_ids}}};",
        ))
        send_arrays = {}
        for number, (action_index, actions) in enumerate(dynamic, start=1):
            variable = "pvd_snd" if number == 1 else f"pvd_snd_{number}"
            send_arrays[action_index] = variable
            values = ",".join(str(action.value) for action in actions)
            self.lines.append(f"  int {variable}[{count}]={{{values}}};")
        self.lines.extend((
            "  char snd_st[64],snd_sp[64],pvd_log[64];",
            "",
            f"  for(int item=0;item<{count};item++)",
            "  {",
            f"    POWER_ON({self.plan.power_profile});",
        ))
        for action_index in range(len(self.plan.cases[0].entry_actions)):
            actions = tuple(case.entry_actions[action_index] for case in self.plan.cases)
            if action_index in send_arrays:
                self._dynamic_send_code(actions, send_arrays[action_index])
            else:
                self._entry_action(actions[0])
        for point_index, point in enumerate(self.plan.cases[0].points):
            self.lines.append(f"    POWER_Shmoo_ON(pvd_v[item][{point_index}]);")
            pattern, end = self._compare_pattern(point.expected)
            state = "".join(point.expected)
            self.lines.extend((
                "    TEST_NUM++;",
                f'    sprintf(pvd_log,"PVD:%s:{point_index + 1}:{state}",pvd_case[item]);',
                "    TEST_NO(TEST_NUM); DATALOG_MSG=pvd_log;",
                f"    JUDGE_PAT({pattern},{end});",
            ))
        self.lines.extend(("    POWER_OFF();", "  }", "}"))
        return FirmwareBodyRender(
            "\n".join(self.lines) + "\n",
            tuple(self.resources.values()),
        )

    def _validate_loop_shape(self):
        first = self.plan.cases[0]
        dynamic = []
        expected = tuple(point.expected for point in first.points)
        action_count = len(first.entry_actions)
        for case in self.plan.cases:
            self._validate_case(case)
            if tuple(point.expected for point in case.points) != expected:
                self._fail(
                    "PVD.CHROMA.CASE.COMPARE_SHAPE_MISMATCH",
                    f"case {case.case_id!r} has a different compare sequence",
                )
            if len(case.entry_actions) != action_count:
                self._fail(
                    "PVD.CHROMA.CASE.ACTION_SHAPE_MISMATCH",
                    f"case {case.case_id!r} has a different entry action count",
                )
        for index in range(action_count):
            actions = tuple(case.entry_actions[index] for case in self.plan.cases)
            if all(action == actions[0] for action in actions[1:]):
                continue
            if not all(
                isinstance(action, SendCodeAction)
                and action.pin.casefold() == actions[0].pin.casefold()
                and action.explicit_pin == actions[0].explicit_pin
                for action in actions
            ):
                self._fail(
                    "PVD.CHROMA.CASE.ACTION_SHAPE_MISMATCH",
                    f"entry action {index + 1} cannot share one runtime loop",
                )
            dynamic.append((index, actions))
        return tuple(dynamic)

    def _validate_case(self, case: PvdCase) -> None:
        if not _CASE_ID_RE.fullmatch(case.case_id):
            self._fail(
                "PVD.CHROMA.CASE.ID_INVALID",
                f"unsafe case id {case.case_id!r}",
            )
        if not case.entry_actions:
            self._fail(
                "PVD.CHROMA.CASE.ENTRY_EMPTY",
                f"case {case.case_id!r} has no entry actions",
            )
        if len(case.points) != 4 or any(
            not isinstance(point, PvdPoint) for point in case.points
        ):
            self._fail(
                "PVD.CHROMA.CASE.POINTS_INVALID",
                f"case {case.case_id!r} requires exactly four PvdPoint facts",
            )

        for action in case.entry_actions:
            if not isinstance(action, (LevelSequenceAction, SendCodeAction)):
                self._fail(
                    "PVD.CHROMA.ACTION.UNSUPPORTED",
                    f"unsupported typed action {type(action).__name__}",
                )
            self._io_pin(action.pin)
            if isinstance(action, LevelSequenceAction):
                if not re.fullmatch(r"[HL]+", action.levels):
                    self._fail(
                        "PVD.CHROMA.LEVEL.STATES_INVALID",
                        f"invalid level sequence {action.levels!r}",
                    )
                if action.segment_duration_ns != _PVD_LEVEL_NS:
                    self._fail(
                        "PVD.CHROMA.LEVEL.PROFILE_UNSUPPORTED",
                        "PVD level sequence requires 5ms per H/L segment",
                    )
            elif (
                not isinstance(action.value, int)
                or isinstance(action.value, bool)
                or not 0 <= action.value <= 255
            ):
                self._fail(
                    "PVD.CHROMA.SEND_CODE.OUT_OF_RANGE",
                    "send code must be an integer from 0 to 255, "
                    f"got {action.value!r}",
                )
        for ordinal, point in enumerate(case.points, start=1):
            self._validate_point(case.case_id, ordinal, point)

    def _entry_action(self, action) -> None:
        if isinstance(action, LevelSequenceAction):
            self._level_sequence(action)
        else:
            self._send_code(action)

    def _level_sequence(self, action: LevelSequenceAction) -> None:
        self._resource(generate_level_sequence_resource(action))
        name, end = action_pattern_span(action)
        self._pattern_run(name, name, "    ", end)

    def _send_code(self, action: SendCodeAction) -> None:
        self._resource(generate_send_code_resource(action))
        name, end = action_pattern_span(action)
        self._pattern_run(name, name, "    ", end)

    def _dynamic_send_code(self, actions, variable: str) -> None:
        for action in actions:
            self._resource(generate_send_code_resource(action))
        name = trigger_pattern_name(actions[0])
        stem = f"{name}:S%02X_ST"
        end = f"{name}:S%02X_SP"
        self.lines.extend((
            f'    sprintf(snd_st,"{stem}",{variable}[item]);',
            f'    sprintf(snd_sp,"{end}",{variable}[item]);',
            "    TEST_NUM++;",
            "    TEST_NO(TEST_NUM); DATALOG_MSG=snd_st;",
            "    JUDGE_PAT(S:snd_st,S:snd_sp);",
        ))

    def _validate_point(self, case_id: str, ordinal: int, point: PvdPoint) -> None:
        voltage = float(point.voltage)
        if not math.isfinite(voltage) or voltage < 0:
            self._fail(
                "PVD.CHROMA.POINT.VOLTAGE_INVALID",
                f"case {case_id!r} point {ordinal} has invalid voltage",
            )
        if (
            len(point.expected) != len(self.plan.compare_pins)
            or any(state not in ("H", "L") for state in point.expected)
        ):
            self._fail(
                "PVD.CHROMA.POINT.EXPECT_INVALID",
                f"case {case_id!r} point {ordinal} has invalid H/L expectation",
            )

    def _compare_pattern(self, expected: tuple[str, ...]) -> tuple[str, str]:
        pins = self.plan.compare_pins
        for pin in pins:
            self._io_pin(pin)
        judge = DigitalCompareJudgePlan(pins, expected, "pat", self.plan.item, self.plan.provenance)
        self._resource(generate_digital_compare_resource(judge))
        return compare_pattern_span(pins, expected)

    def _pattern_run(self, name: str, alias: str, indent: str, end: str | None = None) -> None:
        escaped = alias.replace("\\", "\\\\").replace('"', '\\"')
        self.lines.extend((
            f"{indent}TEST_NUM++;",
            f'{indent}TEST_NO(TEST_NUM); DATALOG_MSG="{escaped}";',
            f"{indent}JUDGE_PAT({name},{end or '__' + name});",
        ))

    def _io_pin(self, name: str) -> None:
        binding = next(
            (
                pin for pin in self.facts.pins
                if pin.name.casefold() == str(name).casefold()
            ),
            None,
        )
        if binding is None:
            self._fail(
                "PVD.CHROMA.PIN.UNDECLARED",
                f"pin {name!r} is absent from platform facts",
            )
        if binding.kind != "io":
            self._fail(
                "PVD.CHROMA.PIN.KIND_INVALID",
                f"pin {name!r} is {binding.kind!r}, expected 'io'",
            )

    def _resource(self, resource: ResourceRequest) -> None:
        path_owner = next(
            (
                item for item in self.resources.values()
                if item.relative_path.casefold() == resource.relative_path.casefold()
                and item.logical_identity != resource.logical_identity
            ),
            None,
        )
        if path_owner is not None:
            self._fail(
                "PVD.CHROMA.RESOURCE.PATH_CONFLICT",
                f"path {resource.relative_path!r} has multiple identities",
            )
        previous = self.resources.get(resource.logical_identity)
        if previous is not None and previous != resource:
            self._fail(
                "PVD.CHROMA.RESOURCE.CONFLICT",
                f"resource {resource.logical_identity!r} has conflicting content",
            )
        self.resources.setdefault(resource.logical_identity, resource)

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise ChromaPvdRenderError(code, message)


def render_pvd_test(
    plan: PvdTestPlan,
    render_name: str,
    hardware_bin,
    platform_facts,
) -> FirmwareBodyRender:
    """Render one complete Chroma PVD body from detached typed facts."""
    if not isinstance(plan, PvdTestPlan):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.PLAN.INVALID",
            "expected PvdTestPlan",
        )
    name = str(render_name).strip()
    if not _SYMBOL_RE.fullmatch(name):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.NAME.INVALID",
            f"unsafe render name {render_name!r}",
        )
    if plan.typed_kind != "PVD_TEST" or plan.effective_recipe != ("PVD_TEST",):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.PLAN.CONTRACT_INVALID",
            "plan must declare typed_kind/Recipe PVD_TEST",
        )
    if not plan.cases or len({case.case_id.casefold() for case in plan.cases}) != len(plan.cases):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.PLAN.CASES_INVALID",
            "plan requires non-empty cases with unique case ids",
        )
    if (
        len(plan.compare_pins) != 2
        or len({pin.casefold() for pin in plan.compare_pins}) != 2
    ):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.PLAN.COMPARE_PINS_INVALID",
            "PVD requires two distinct compare pins",
        )
    if not _SYMBOL_RE.fullmatch(plan.power_profile):
        raise ChromaPvdRenderError(
            "PVD.CHROMA.PLAN.POWER_PROFILE_INVALID",
            f"unsafe power profile {plan.power_profile!r}",
        )
    if getattr(platform_facts, "platform", "").casefold() != "chroma":
        raise ChromaPvdRenderError(
            "PVD.CHROMA.FACTS.PLATFORM_MISMATCH",
            "renderer requires Chroma platform facts",
        )
    if getattr(platform_facts, "cp", "").casefold() != plan.cp.casefold():
        raise ChromaPvdRenderError(
            "PVD.CHROMA.FACTS.CP_MISMATCH",
            f"facts CP {getattr(platform_facts, 'cp', None)!r} != {plan.cp!r}",
        )
    _ = hardware_bin  # Chroma reject bins are owned by the canonical flow.
    return _Renderer(plan, platform_facts).render(name)


def _number(value: float) -> str:
    return format(float(value), ".12g")


__all__ = ["ChromaPvdRenderError", "render_pvd_test"]
