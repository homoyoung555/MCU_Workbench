"""Pure S100 renderer for compiler-owned generic firmware test plans."""

from __future__ import annotations

import hashlib
from itertools import product
import re

from program_gen.core.firmware_force import (
    ClockForceAction,
    ClockSignal,
    ClockStopAction,
    ForceVoltageAction,
    SupplyForceAction,
)
from program_gen.core.firmware_judge import (
    DigitalCompareJudgePlan,
    ScalarMeasurementJudgePlan,
)
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.core.firmware_test import (
    DownloadPhase,
    DutResetAction,
    FirmwareTestPlan,
    KeilPhase,
)
from program_gen.core.run_sequence import (
    LevelSequenceAction,
    SendCodeAction,
    WaitAction,
)
from program_gen.core.trigger_pattern import (
    trigger_pattern_name, send_label, compare_pattern_name, compare_label,
)
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.platform_program.facts import PlatformProgramFacts
from program_gen.platforms.s100.dut_reset_resource import (
    generate_dut_reset_resource,
)
from program_gen.render_plan import ResourceRequest, ResourceRequirement


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DPS_RANGES_UA = ((5, "I1"), (25, "I2"), (250, "I3"), (2500, "I4"),
                  (25000, "I5"), (250000, "I6"))
_S100_PERIOD_NS = 200
_LOW_CLOCK_LIMIT_HZ = 600_000


class S100FirmwareRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_firmware_test(
    plan: FirmwareTestPlan,
    render_name: str,
    hardware_bin: int | str,
    platform_facts: PlatformProgramFacts,
) -> FirmwareBodyRender:
    """Render one immutable firmware plan without workbook or filesystem access."""
    hardware_bin = _hardware_bin(hardware_bin)
    _validate_entry(plan, render_name, platform_facts)
    renderer = _Renderer(platform_facts)
    renderer.lines.extend((
        f"@@PLAN {render_name}",
        "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;",
        "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;",
        f"\tREMARK             = {render_name};",
        "",
    ))

    if plan.typed_kind == "CODE_DOWNLOAD":
        _require_phase_shape(plan, DownloadPhase)
        renderer.render_session(plan.phases)
    elif plan.typed_kind == "FIRMWARE_FUNCTION_TEST":
        if not any(isinstance(phase, DownloadPhase) for phase in plan.phases) or not any(
            isinstance(phase, KeilPhase) for phase in plan.phases
        ):
            raise S100FirmwareRenderError(
                "S100.FW.PLAN.SHAPE_INVALID",
                "FIRMWARE_FUNCTION_TEST requires download and KEIL phases",
            )
        for phase in plan.phases:
            if not isinstance(phase, (DownloadPhase, KeilPhase)):
                raise S100FirmwareRenderError(
                    "S100.FW.PHASE.UNSUPPORTED", type(phase).__name__
                )
            renderer.render_session((phase,))
    elif plan.typed_kind == "FIRMWARE_RUN_TEST":
        _require_phase_shape(plan, KeilPhase)
        renderer.render_session(plan.execution_steps)
    else:
        raise S100FirmwareRenderError(
            "S100.FW.PLAN.KIND_UNSUPPORTED", plan.typed_kind
        )

    renderer.lines.extend((
        "",
        "\tCONDITION",
        "\tIF_FAIL",
        f"\tREJECT_BIN = {hardware_bin};",
        "@@END_PLAN",
    ))
    return FirmwareBodyRender(
        "\n".join(renderer.lines) + "\n",
        tuple(renderer.resources.values()),
        tuple(renderer.requirements.values()),
    )


class _Renderer:
    def __init__(self, facts: PlatformProgramFacts):
        self.facts = facts
        self.lines: list[str] = []
        self.resources: dict[str, ResourceRequest] = {}
        self.requirements: dict[str, ResourceRequirement] = {}
        self.supply_leases: set[str] = set()
        self.live_clocks: tuple[ClockSignal, ...] = ()

    def render_session(self, steps) -> None:
        steps = tuple(steps)
        if not steps:
            raise S100FirmwareRenderError(
                "S100.FW.SESSION.EMPTY", "firmware session has no phase"
            )
        profiles = {
            step.power_profile
            for step in steps
            if isinstance(step, (DownloadPhase, KeilPhase))
        }
        if len(profiles) != 1:
            raise S100FirmwareRenderError(
                "S100.FW.SESSION.POWER_CONFLICT",
                "one session requires one power profile",
            )
        self.lines.extend(sub_comment(steps[0].sub, "\t"))
        profile = next(iter(profiles))
        self.lines.append(f"\tCALL_MACRO POWER_ON({_constant(profile)});")
        self.lines.append("")
        for step in steps:
            if step is not steps[0] and isinstance(step, (DownloadPhase, KeilPhase)):
                self.lines.extend(sub_comment(step.sub, '\t'))
            if isinstance(step, DownloadPhase):
                self._render_download(step)
            elif isinstance(step, KeilPhase):
                self._render_keil(step)
            elif isinstance(step, DutResetAction):
                self._render_reset(step)
            else:
                raise S100FirmwareRenderError(
                    "S100.FW.STEP.UNSUPPORTED", type(step).__name__
                )
        if self.live_clocks:
            raise S100FirmwareRenderError(
                "S100.FW.CLOCK.CLEANUP_REQUIRED",
                "ClockForceAction must be closed by typed ClockStopAction",
            )
        self.lines.append("\tCALL_MACRO POWER_OFF();")
        self.lines.append("")
        self.supply_leases.clear()

    def _render_download(self, phase: DownloadPhase) -> None:
        pattern = phase.pattern
        requirement = ResourceRequirement(
            pattern.logical_identity,
            f"{pattern.name}.sd",
            f"v13.pattern/1:s100:{pattern.name}",
            "Firmware download pattern",
        )
        self._add_requirement(requirement)
        self.lines.extend((
            f"\tRUN_PATTERN({pattern.name}:START,{pattern.name}:END,1,TS_5MHZ);",
            "",
        ))

    def _render_keil(self, phase: KeilPhase) -> None:
        if phase.effective_recipe != ("RUN_SEQUENCE", "JUDGE"):
            raise S100FirmwareRenderError(
                "S100.FW.RECIPE.UNSUPPORTED", "-".join(phase.effective_recipe)
            )
        for action in phase.actions:
            self._render_action(action)
        self._render_judge(phase.judge)
        for action in phase.cleanup_actions:
            if not isinstance(action, ClockStopAction):
                raise S100FirmwareRenderError(
                    "S100.FW.CLEANUP.UNSUPPORTED", type(action).__name__
                )
            self._render_clock_stop(action)
        if self.live_clocks:
            raise S100FirmwareRenderError(
                "S100.FW.CLOCK.CLEANUP_REQUIRED", phase.sub
            )

    def _render_action(self, action) -> None:
        if isinstance(action, (LevelSequenceAction, SendCodeAction)):
            resource = (generate_level_sequence_resource(action)
                        if isinstance(action, LevelSequenceAction)
                        else generate_send_code_resource(action))
            self._add_resource(resource)
            start, end = action_pattern_span(action)
            self.lines.append(f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);")
        elif isinstance(action, WaitAction):
            self.lines.append(f"\tWAIT({action.duration_ms}MS);")
        elif isinstance(action, SupplyForceAction):
            compliance, current_range = _dps_compliance(action)
            self.lines.append(
                f"\tLOGIC_FORCE_DPS({action.rail}, {_voltage(action.voltage)}, "
                f"{compliance}, {current_range}, WAIT=3MS);"
            )
            self.supply_leases.add(action.rail.casefold())
        elif isinstance(action, ForceVoltageAction):
            for point in action.points:
                _safe_identifier(point.pin, "S100.FW.PIN.INVALID")
                self.lines.append(
                    f"\tLOGIC_PPMU_FV({point.pin}, {_voltage(point.voltage)}, E2, I7);"
                )
        elif isinstance(action, ClockForceAction):
            self._render_clock_force(action)
        else:
            raise S100FirmwareRenderError(
                "S100.FW.ACTION.UNSUPPORTED", type(action).__name__
            )

    def _render_judge(self, judge) -> None:
        if isinstance(judge, DigitalCompareJudgePlan):
            resource = generate_digital_compare_resource(judge)
            self._add_resource(resource)
            start, end = compare_pattern_span(judge)
            self.lines.extend((
                f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);",
                "",
            ))
            return
        if not isinstance(judge, ScalarMeasurementJudgePlan):
            raise S100FirmwareRenderError(
                "S100.FW.JUDGE.UNSUPPORTED", type(judge).__name__
            )
        alias = _alias(judge.sub)
        low, high = _number(judge.low_limit), _number(judge.high_limit)
        if judge.kind is JudgeMeasurementKind.CURRENT:
            if judge.pin.casefold() not in self.supply_leases:
                raise S100FirmwareRenderError(
                    "S100.FW.JUDGE.SUPPLY_LEASE_MISSING", judge.pin
                )
            unit = judge.unit.upper()
            self.lines.extend((
                f"\tLOGIC_DPS_MI({judge.pin}, UP_LIMIT={high}{unit}, "
                f"DOWN_LIMIT={low}{unit},MEAS_LOOP=100,AVG);",
                f"\tC_ASSIGN(GB30, {judge.pin});",
                "\tC_MUL(GB30, 1000000);",
                f"\tC_COMPARE(GB30, UP_LIMIT={high}, DOWN_LIMIT={low}, "
                f"UNIT={unit}, LOG_ALIAS={alias}, LOG_UNIT={judge.unit});",
                "\tC_ASSIGN(GB31, GB30);",
                "",
            ))
        elif judge.kind is JudgeMeasurementKind.VOLTAGE:
            self.lines.extend((
                f"\tLOGIC_PPMU_MV({judge.pin}, DOWN_LIMIT={low}{judge.unit}, "
                f"UP_LIMIT={high}{judge.unit}, MEAS_LOOP=8, AVG, "
                f"LOG_ALIAS={alias}, LOG_UNIT={judge.unit});",
                "",
            ))
        else:
            raise S100FirmwareRenderError(
                "S100.FW.JUDGE.UNSUPPORTED", str(judge.kind)
            )

    def _render_reset(self, action: DutResetAction) -> None:
        nrst = "NRST" if any(pin.name == "NRST" for pin in self.facts.pins) else self.facts.nrst_pin
        resource = generate_dut_reset_resource(nrst, action)
        self._add_resource(resource)
        self.lines.extend((
            "\tRUN_PATTERN(dut_reset:START,dut_reset:END,1,VIH_5MHZ);",
            "",
        ))

    def _render_clock_force(self, action: ClockForceAction) -> None:
        if self.live_clocks:
            raise S100FirmwareRenderError(
                "S100.FW.CLOCK.ALREADY_ACTIVE", "clock lease is already active"
            )
        low = tuple(signal for signal in action.signals if signal.frequency_hz < _LOW_CLOCK_LIMIT_HZ)
        if len(low) > 1:
            raise S100FirmwareRenderError(
                "S100.FW.CLOCK.MULTIPLE_LOW_UNSUPPORTED",
                "S100 continuous Pattern Engine supports one low clock lease",
            )
        for signal in action.signals:
            _safe_identifier(signal.pin, "S100.FW.PIN.INVALID")
            if signal.frequency_hz <= 0:
                raise S100FirmwareRenderError(
                    "S100.FW.CLOCK.FREQUENCY_INVALID", signal.pin
                )
            if signal.frequency_hz >= _LOW_CLOCK_LIMIT_HZ:
                self.lines.append(
                    f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN({signal.pin},"
                    f"{int(round(signal.frequency_hz))});"
                )
            else:
                sd, sr = _clock_resources(signal)
                self._add_resource(sd)
                self._add_resource(sr)
                name = sd.relative_path[:-3]
                self.lines.append(
                    f"\tRUN_PATTERN({name}:START,{name}:END,3,TS_FORCE_CLK);"
                )
        self.live_clocks = action.signals

    def _render_clock_stop(self, action: ClockStopAction) -> None:
        if action.signals != self.live_clocks:
            raise S100FirmwareRenderError(
                "S100.FW.CLOCK.CLEANUP_MISMATCH",
                "ClockStopAction must close the active ClockForceAction",
            )
        for signal in action.signals:
            if signal.frequency_hz >= _LOW_CLOCK_LIMIT_HZ:
                self.lines.append(
                    f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN(NULL,"
                    f"{int(round(signal.frequency_hz))});"
                )
            else:
                self.lines.append("\tLOGIC_CLEAR_CONT();")
        self.lines.append("")
        self.live_clocks = ()

    def _add_resource(self, resource: ResourceRequest) -> None:
        previous = self.resources.get(resource.logical_identity)
        if previous is not None and previous != resource:
            raise S100FirmwareRenderError(
                "S100.FW.RESOURCE.CONFLICT", resource.logical_identity
            )
        self.resources[resource.logical_identity] = resource

    def _add_requirement(self, requirement: ResourceRequirement) -> None:
        previous = self.requirements.get(requirement.logical_identity)
        if previous is not None and previous != requirement:
            raise S100FirmwareRenderError(
                "S100.FW.RESOURCE.CONFLICT", requirement.logical_identity
            )
        self.requirements[requirement.logical_identity] = requirement


def _validate_entry(plan, render_name, facts) -> None:
    if not isinstance(plan, FirmwareTestPlan):
        raise S100FirmwareRenderError("S100.FW.PLAN.INVALID", type(plan).__name__)
    _safe_identifier(render_name, "S100.FW.RENDER_NAME.INVALID")
    if facts.platform.casefold() != "s100":
        raise S100FirmwareRenderError("S100.FW.PLATFORM.INVALID", facts.platform)
    if facts.cp.casefold() != plan.cp.casefold():
        raise S100FirmwareRenderError("S100.FW.CP.MISMATCH", f"{plan.cp}/{facts.cp}")


def _hardware_bin(value: int | str) -> int:
    if isinstance(value, bool):
        raise S100FirmwareRenderError("S100.FW.BIN.INVALID", repr(value))
    text = str(value).strip()
    if not text.isdigit():
        raise S100FirmwareRenderError("S100.FW.BIN.INVALID", repr(value))
    return int(text)


def _require_phase_shape(plan: FirmwareTestPlan, phase_type: type) -> None:
    if not plan.phases or any(not isinstance(phase, phase_type) for phase in plan.phases):
        raise S100FirmwareRenderError(
            "S100.FW.PLAN.SHAPE_INVALID", plan.typed_kind
        )


def generate_level_sequence_resource(action: LevelSequenceAction) -> ResourceRequest:
    _safe_identifier(action.pin, "S100.FW.PIN.INVALID")
    if not action.levels or any(level not in "HL" for level in action.levels):
        raise S100FirmwareRenderError("S100.FW.LEVEL.INVALID", action.levels)
    if action.segment_duration_ns <= 0 or action.segment_duration_ns % _S100_PERIOD_NS:
        raise S100FirmwareRenderError(
            "S100.FW.LEVEL.DURATION_UNSUPPORTED", str(action.segment_duration_ns)
        )
    name = trigger_pattern_name(action)
    rpt = action.segment_duration_ns // _S100_PERIOD_NS
    vectors = "".join(
        f"      {'1' if level == 'H' else '0'};RPT {rpt};\n"
        for level in action.levels
    )
    content = (
        f"HEAD[PIN_NAME]:\n\n{action.pin};\n\nEND_HEAD;\n\n"
        "@@PATTERN_DEFINE\n\nSTART:X;\n      X;RPT 100;\n"
        f"{vectors}  END:X;\n\n@@END_PATTERN_DEFINE\n"
    )
    return _generated_resource(
        f"pattern:firmware-level:{name}", f"{name}.sd", content,
        f"v14.firmware-level/1:s100:{action.pin}:{action.levels}:{action.segment_duration_ns}",
        "FIRMWARE LevelSequenceAction",
    )


def generate_send_code_resource(action: SendCodeAction) -> ResourceRequest:
    _safe_identifier(action.pin, "S100.FW.PIN.INVALID")
    if not 0 <= action.value <= 255:
        raise S100FirmwareRenderError("S100.FW.CODE.OUT_OF_RANGE", str(action.value))
    name = trigger_pattern_name(action)
    sections = []
    for value in range(256):
        label = send_label(value)
        encoded = "".join(f"      {bit};RPT 422;\n" for bit in format(value, "08b"))
        sections.append(
            f"{label}_ST:X;\n      X;RPT 100;\n"
            "      1;RPT 632;\n      0;RPT 422;\n      1;RPT 422;\n"
            f"      0;RPT 422;// 0x{value:02X}\n{encoded}"
            f"      0;RPT 502;\n{label}_SP:X;\n\n"
        )
    content = (
        f"HEAD[PIN_NAME]:\n\n{action.pin};\n\nEND_HEAD;\n\n"
        "@@PATTERN_DEFINE\n\n" + "".join(sections) + "@@END_PATTERN_DEFINE\n"
    )
    return _generated_resource(
        f"pattern:firmware-send:{name}", f"{name}.sd", content,
        f"v14.firmware-send/2:s100:{action.pin}:all-u8",
        "Shared SendCodeAction Pattern",
    )


def generate_digital_compare_resource(judge: DigitalCompareJudgePlan) -> ResourceRequest:
    """One pin-group Pattern with independently executable H/L labels."""
    for pin in judge.pins:
        _safe_identifier(pin, "S100.FW.PIN.INVALID")
    state = "".join(judge.expected)
    if not judge.pins or len(judge.pins) != len(state) or any(value not in "HL" for value in state):
        raise S100FirmwareRenderError("S100.FW.JUDGE.DIGITAL_INVALID", state)
    name = compare_pattern_name(judge.pins)
    idle = "X" * len(judge.pins)
    sections = []
    for values in product("HL", repeat=len(judge.pins)):
        state = compare_label(values)
        sections.append(
            f"{state}_ST:{idle};\n      {idle};RPT 100;\n\n"
            f"      {state};\n      {state};RPT 500;// wait 100uS\n"
            f"      {state};\n\n      {idle};\n{state}_SP:{idle};\n\n"
        )
    content = (
        f"HEAD[PIN_NAME]:\n\n{','.join(judge.pins)};\n\nEND_HEAD;\n\n"
        "@@PATTERN_DEFINE\n\n" + "".join(sections) + "@@END_PATTERN_DEFINE\n"
    )
    return _generated_resource(
        f"pattern:firmware-compare:{name}", f"{name}.sd", content,
        f"v14.firmware-compare/2:s100:{','.join(judge.pins)}:all-HL",
        "Shared DigitalCompareJudgePlan Pattern",
    )


def action_pattern_span(action) -> tuple[str, str]:
    name = trigger_pattern_name(action)
    if isinstance(action, SendCodeAction):
        label = send_label(action.value)
        return f"{name}:{label}_ST", f"{name}:{label}_SP"
    return f"{name}:START", f"{name}:END"


def compare_pattern_span(judge) -> tuple[str, str]:
    name, label = compare_pattern_name(judge.pins), compare_label(judge.expected)
    return f"{name}:{label}_ST", f"{name}:{label}_SP"


def _clock_resources(signal: ClockSignal) -> tuple[ResourceRequest, ResourceRequest]:
    name = f"{signal.pin.lower()}_clkloop"
    sd_content = (
        f"HEAD[PIN_NAME]:\n\n{signal.pin},TRIGPIN,\n\nEND_HEAD;\n\n"
        "@@PATTERN_DEFINE\n\nSTART:0X;\n"
        f"      XX;SUB_CONT_ON R{name}:{name};\n"
        "      0X;\n      0X;\n  END:0X;\n\n@@END_PATTERN_DEFINE\n"
    )
    sr_content = (
        f"HEAD[PIN_NAME]:\n\n{signal.pin},TRIGPIN\n\nEND_HEAD;\n\n"
        f"@@PATTERN_DEFINE\n\n      {name}:0X;\n      1X;RTN;\n"
        "      XX;\n\n@@END_PATTERN_DEFINE\n"
    )
    spec = f"v14.firmware-clock/1:s100:{signal.pin}:{_number(signal.frequency_hz)}"
    return (
        _generated_resource(
            f"pattern:firmware-clock:{name}", f"{name}.sd", sd_content, spec,
            "FIRMWARE low-frequency ClockForceAction Group3 TS_FORCE_CLK",
        ),
        _generated_resource(
            f"pattern-subroutine:firmware-clock:R{name}", f"R{name}.sr", sr_content,
            spec + ":subroutine", "FIRMWARE low-frequency clock .sr closure",
        ),
    )


def _generated_resource(identity, path, content, spec, purpose) -> ResourceRequest:
    encoded = content.encode("ascii")
    digest = hashlib.sha256(encoded).hexdigest().upper()
    return ResourceRequest(
        identity, path, encoded, spec,
        f"generated:s100:firmware:sha256:{digest}", purpose,
    )


def _dps_compliance(action: SupplyForceAction) -> tuple[str, str]:
    unit_scale = {"a": 1_000_000, "ma": 1_000, "ua": 1}
    unit = action.current_unit.strip().casefold().replace("μ", "u").replace("µ", "u")
    if unit not in unit_scale or action.current_compliance <= 0:
        raise S100FirmwareRenderError(
            "S100.FW.SUPPLY.COMPLIANCE_INVALID", action.current_unit
        )
    microamps = action.current_compliance * unit_scale[unit]
    selected = next((name for upper, name in _DPS_RANGES_UA if microamps <= upper), None)
    if selected is None:
        raise S100FirmwareRenderError(
            "S100.FW.SUPPLY.RANGE_UNSUPPORTED", _number(microamps)
        )
    compliance = (
        f"{_number(microamps / 1000)}MA" if microamps >= 1000
        else f"{_number(microamps)}UA"
    )
    return compliance, selected


def _constant(value: str) -> str:
    value = str(value).strip()
    if _IDENTIFIER.fullmatch(value):
        return f"_C_{value.upper()}"
    return _voltage(value)


def _voltage(value: str) -> str:
    value = str(value).strip()
    if _IDENTIFIER.fullmatch(value):
        return f"_C_{value.upper()}"
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:V)?", value, re.I):
        return value if value.upper().endswith("V") else value + "V"
    raise S100FirmwareRenderError("S100.FW.VOLTAGE.INVALID", value)


def _safe_identifier(value: str, code: str) -> str:
    value = str(value).strip()
    if not _IDENTIFIER.fullmatch(value):
        raise S100FirmwareRenderError(code, value)
    return value


def _alias(value: str) -> str:
    alias = re.sub(r"[^A-Za-z0-9_]", "_", str(value).strip()).upper()
    if not alias or not re.match(r"[A-Z_]", alias):
        alias = "FW_" + alias
    return alias


def _number(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else format(number, ".12g")


__all__ = [
    "S100FirmwareRenderError",
    "action_pattern_span",
    "compare_pattern_span",
    "generate_level_sequence_resource",
    "generate_send_code_resource",
    "generate_digital_compare_resource",
    "render_firmware_test",
]
