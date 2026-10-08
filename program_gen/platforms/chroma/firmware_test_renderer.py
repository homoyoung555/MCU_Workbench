"""Pure Chroma renderer for platform-neutral firmware test plans."""

from __future__ import annotations

import hashlib
import math
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
    SramValueJudgePlan,
)
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.core.firmware_test import (
    DownloadPhase,
    DutResetAction,
    FirmwareTestPlan,
    KeilPhase,
    _execution_steps_for,
)
from program_gen.core.run_sequence import (
    LevelSequenceAction,
    SendCodeAction,
    WaitAction,
)
from program_gen.core.trigger_pattern import trigger_pattern_name, send_label, compare_pattern_name, compare_label
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.platforms.chroma.dut_reset_pattern import (
    generate_dut_reset_pattern,
)
from program_gen.render_plan import ResourceRequest, ResourceRequirement
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY


_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TS1_NS = 200


class ChromaFirmwareRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class _Renderer:
    def __init__(self, plan: FirmwareTestPlan, facts):
        self.plan = plan
        self.facts = facts
        self.lines: list[str] = []
        self.resources: dict[str, ResourceRequest] = {}
        self.requirements: dict[str, ResourceRequirement] = {}
        self.supplies: dict[str, SupplyForceAction] = {}
        self.voltage_forces: dict[str, str] = {}
        self.clocks: dict[str, tuple[ClockSignal, str]] = {}

    def render(self, name: str) -> FirmwareBodyRender:
        self.lines.extend((f"{name}()", "{"))
        if self.plan.typed_kind == "FIRMWARE_FUNCTION_TEST":
            index = 0
            while index < len(self.plan.phases):
                phase = self.plan.phases[index]
                count = (phase.judge.capture.layout.count
                         if isinstance(phase, KeilPhase) and isinstance(phase.judge, SramValueJudgePlan)
                         else 1)
                self._session(self.plan.phases[index:index + count])
                index += count
        elif self.plan.typed_kind in ("CODE_DOWNLOAD", "FIRMWARE_RUN_TEST"):
            self._session(self.plan.execution_steps)
        else:
            self._fail(
                "FW.CHROMA.PLAN.TYPED_KIND_UNSUPPORTED",
                f"unsupported typed kind {self.plan.typed_kind!r}",
            )
        self.lines.append("}")
        return FirmwareBodyRender(
            "\n".join(self.lines) + "\n",
            tuple(self.resources.values()),
            tuple(self.requirements.values()),
        )

    def _session(self, steps) -> None:
        if not steps:
            self._fail("FW.CHROMA.SESSION.EMPTY", "firmware session is empty")
        profiles = {
            step.power_profile
            for step in steps
            if isinstance(step, (DownloadPhase, KeilPhase))
        }
        if len(profiles) != 1:
            self._fail(
                "FW.CHROMA.SESSION.POWER_CONFLICT",
                f"one power session requires one profile, got {sorted(profiles)!r}",
            )
        self.lines.extend(sub_comment(steps[0].sub))
        self.lines.append(f"  POWER_ON({next(iter(profiles))});")
        for step in steps:
            if step is not steps[0] and isinstance(step, (DownloadPhase, KeilPhase)):
                self.lines.extend(sub_comment(step.sub, '  '))
            if isinstance(step, DownloadPhase):
                self._download(step)
            elif isinstance(step, KeilPhase):
                self._keil(step)
            elif isinstance(step, DutResetAction):
                self._reset(step)
            else:
                self._unsupported(step)
        if self.clocks:
            self._fail(
                "FW.CHROMA.CLOCK.CLEANUP_MISSING",
                f"live clocks remain at POWER_OFF: {tuple(self.clocks)!r}",
            )
        self._cleanup_voltage_forces()
        self.lines.append("  POWER_OFF();")
        self.supplies.clear()

    def _download(self, phase: DownloadPhase) -> None:
        pattern = phase.pattern
        requirement = ResourceRequirement(
            pattern.logical_identity,
            f"pat/{pattern.name}.pat",
            f"v13.pattern/1:chroma:{pattern.name}",
            "Firmware download pattern",
        )
        self._require(requirement)
        self._pattern_run(pattern.name, pattern.name)

    def _keil(self, phase: KeilPhase) -> None:
        for action in phase.actions:
            if isinstance(action, LevelSequenceAction):
                self._level_sequence(action)
            elif isinstance(action, SendCodeAction):
                self._send_code(action)
            elif isinstance(action, WaitAction):
                if action.duration_ms <= 0:
                    self._fail(
                        "FW.CHROMA.WAIT.DURATION_INVALID",
                        f"wait must be positive, got {action.duration_ms!r}ms",
                    )
                self.lines.append(f"  WAIT({action.duration_ms}mS);")
            elif isinstance(action, SupplyForceAction):
                self._supply_force(action)
            elif isinstance(action, ForceVoltageAction):
                self._voltage_force(action)
            elif isinstance(action, ClockForceAction):
                self._clock_force(action)
            else:
                self._unsupported(action)
        self._judge(phase.judge, phase.power_profile)
        for action in phase.cleanup_actions:
            if not isinstance(action, ClockStopAction):
                self._unsupported(action)
            self._clock_stop(action)
        if self.clocks:
            self._fail(
                "FW.CHROMA.CLOCK.CLEANUP_INCOMPLETE",
                f"phase {phase.sub!r} left clocks active",
            )
        self._cleanup_voltage_forces()

    def _reset(self, action: DutResetAction) -> None:
        reset_pin = next(
            (pin.name for pin in self.facts.pins if pin.name.casefold() == "nrst"),
            None,
        )
        if reset_pin is None:
            self._fail(
                "FW.CHROMA.RESET.PIN_MISSING",
                "platform facts do not declare the NRST tester symbol",
            )
        resource = generate_dut_reset_pattern(reset_pin, action)
        self._resource(resource)
        self._pattern_run("firmware_dut_reset", "firmware_dut_reset")

    def _level_sequence(self, action: LevelSequenceAction) -> None:
        self._pin(action.pin)
        resource = generate_level_sequence_resource(action)
        name, end = action_pattern_span(action)
        self._resource(resource)
        self._pattern_run(name, name, end)

    def _send_code(self, action: SendCodeAction) -> None:
        self._pin(action.pin)
        resource = generate_send_code_resource(action)
        name, end = action_pattern_span(action)
        self._resource(resource)
        self._pattern_run(name, name, end)

    def _supply_force(self, action: SupplyForceAction) -> None:
        self._pin(action.rail, power=True)
        current_range = _mldps_current_range(
            action.current_compliance, action.current_unit
        )
        voltage = _voltage(action.voltage)
        self.lines.append(
            f"  FORCE_V_MLDPS({action.rail},{voltage},@6V,{current_range},"
            "NORM,ON,2mS);"
        )
        self.supplies[action.rail.casefold()] = action

    def _voltage_force(self, action: ForceVoltageAction) -> None:
        if not action.points:
            self._fail(
                "FW.CHROMA.VOLTAGE_FORCE.EMPTY",
                "ForceVoltageAction requires at least one point",
            )
        for point in action.points:
            self._pin(point.pin)
            key = point.pin.casefold()
            if key not in self.voltage_forces:
                self.lines.append(f"  RELAY_ON({point.pin},PPMU_PDCL,2mS);")
            self.lines.append(
                f"  FORCE_V_PPMU({point.pin},{_voltage(point.voltage)},,@32mA,,2mS);"
            )
            self.voltage_forces[key] = point.pin

    def _clock_force(self, action: ClockForceAction) -> None:
        if self.clocks:
            self._fail(
                "FW.CHROMA.CLOCK.ALREADY_ACTIVE",
                "a second ClockForceAction requires an explicit typed stop",
            )
        if not action.signals:
            self._fail(
                "FW.CHROMA.CLOCK.EMPTY",
                "ClockForceAction requires at least one signal",
            )
        pins = tuple(signal.pin.casefold() for signal in action.signals)
        if len(set(pins)) != len(pins) or any(
            not math.isfinite(signal.frequency_hz) or signal.frequency_hz <= 0
            for signal in action.signals
        ):
            self._fail(
                "FW.CHROMA.CLOCK.FACTS_INVALID",
                "clock pins must be unique and frequencies must be positive",
            )
        modes = self._clock_modes(action.signals)
        downgraded = tuple(
            signal for signal in action.signals if modes[signal.pin.casefold()] == "pattern"
        )
        if len(downgraded) > 1:
            self._fail(
                "FW.CHROMA.CLOCK.PATTERN_MULTI_UNSUPPORTED",
                "one Chroma Pattern Engine cannot host multiple clock loops",
            )
        for signal in action.signals:
            self.lines.append(
                f"  PIN_MODE({signal.pin},FCLK,EDGE,MASK,IO_ON,OFF);"
            )
            mode = modes[signal.pin.casefold()]
            self.clocks[signal.pin.casefold()] = (signal, mode)
            if mode == "tmu":
                half_ns = 1e9 / (2.0 * signal.frequency_hz)
                self.lines.append(
                    f"  FRUN_CLK({signal.pin},{_time(2 * half_ns)},0nS,{_time(half_ns)});"
                )
        for signal, mode in self.clocks.values():
            if mode == "tmu":
                self.lines.append(f"  FRUN_CLK_MODE({signal.pin},1,0,ON);")
        for signal in downgraded:
            resource = self._clock_loop(signal)
            self._resource(resource)
            self._pattern_run(
                f"firmware_{signal.pin.lower()}_clkloop",
                f"firmware_{signal.pin.lower()}_clkloop",
            )

    def _clock_stop(self, action: ClockStopAction) -> None:
        expected = {signal.pin.casefold(): signal for signal in action.signals}
        live = {key: signal for key, (signal, _mode) in self.clocks.items()}
        if expected != live:
            self._fail(
                "FW.CHROMA.CLOCK.STOP_MISMATCH",
                f"stop signals {sorted(expected)!r} do not match live clocks",
            )
        for signal, mode in self.clocks.values():
            if mode == "pattern":
                self.lines.append("  PAT_CONTINUE();")
        for signal, mode in self.clocks.values():
            if mode == "tmu":
                self.lines.append(f"  FRUN_CLK_MODE({signal.pin},1,0,OFF);")
        self.clocks.clear()

    def _judge(self, judge, power_profile: str) -> None:
        if isinstance(judge, SramValueJudgePlan):
            self._sram_judge(judge)
        elif isinstance(judge, ScalarMeasurementJudgePlan):
            self._scalar_judge(judge)
        elif isinstance(judge, DigitalCompareJudgePlan):
            self._digital_judge(judge, power_profile)
        else:
            self._fail(
                "FW.CHROMA.JUDGE.UNSUPPORTED",
                f"unsupported judge {type(judge).__name__}",
            )

    def _sram_judge(self, judge: SramValueJudgePlan) -> None:
        capture = judge.capture
        self._pin(capture.capture_pin)
        if capture.capture_pin.casefold() != self.facts.swd_pin.casefold():
            self._fail("FW.CHROMA.SRAM.PIN_MISMATCH", "capture pin must match platform SWD pin")
        if judge.index == 0:
            emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("SRAM_CAPTURE", capture, "chroma")
            self.lines.extend(emission.statements)
            for requirement in emission.resource_requires:
                self._require(requirement)
        self._datalog(judge.sub)
        alias = judge.sub.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
        self.lines.extend((
            "  SOCKET_INC(FRZ_OFF)", "  {",
            f"    JUDGE_VARIABLE(SOCKET,{capture.result_symbol}[SOCKET][{judge.index}],"
            f'{_number(judge.low_limit)},{_number(judge.high_limit)},"{alias}");',
            "  }",
        ))

    def _scalar_judge(self, judge: ScalarMeasurementJudgePlan) -> None:
        self._pin(judge.pin, power=judge.kind is JudgeMeasurementKind.CURRENT)
        self._datalog(judge.sub)
        low = f"{_number(judge.low_limit)}{judge.unit}"
        high = f"{_number(judge.high_limit)}{judge.unit}"
        if judge.kind is JudgeMeasurementKind.CURRENT:
            if judge.pin.casefold() not in self.supplies:
                self._fail(
                    "FW.CHROMA.JUDGE.SUPPLY_LEASE_MISSING",
                    f"current judge {judge.pin!r} has no SupplyForce lease",
                )
            self.lines.append(
                f"  JUDGE_I_MLDPS({judge.pin},{low},{high},2mS,32,AVE,50uS,,);"
            )
        elif judge.kind is JudgeMeasurementKind.VOLTAGE:
            self.lines.extend((
                f"  RELAY_ON({judge.pin},PPMU_PDCL,2mS);",
                f"  FORCE_I_PPMU({judge.pin},0uA,@200uA,,6V,-2V,3mS);",
                f"  JUDGE_V_PPMU({judge.pin},{low},{high},2mS);",
                f"  FORCE_I_PPMU({judge.pin},0uA,@200uA,,6V,-2V,3mS);",
                f"  RELAY_OFF({judge.pin},PPMU_PDCL,2mS);",
            ))
        else:
            self._fail(
                "FW.CHROMA.JUDGE.SCALAR_KIND_UNSUPPORTED",
                f"unsupported scalar kind {judge.kind!r}",
            )

    def _digital_judge(self, judge: DigitalCompareJudgePlan, profile: str) -> None:
        if not judge.pins or len(judge.pins) != len(judge.expected) or any(
            state not in ("H", "L") for state in judge.expected
        ):
            self._fail(
                "FW.CHROMA.JUDGE.DIGITAL_FACTS_INVALID",
                "digital judge pins and H/L states must align",
            )
        for pin in judge.pins:
            self._pin(pin)
        if any(mode == "pattern" for _signal, mode in self.clocks.values()):
            for pin, expected in zip(judge.pins, judge.expected):
                low, high = (
                    (f"{profile}-0.6", f"{profile}+0.1")
                    if expected == "H"
                    else ("0.1V", "0.5V")
                )
                self._datalog(f"{judge.sub}:{pin}")
                self.lines.extend((
                    f"  RELAY_ON({pin},PPMU_PDCL,2mS);",
                    f"  FORCE_I_PPMU({pin},0uA,@200uA,,6V,-2V,3mS);",
                    f"  JUDGE_V_PPMU({pin},{low},{high},2mS);",
                    f"  RELAY_OFF({pin},PPMU_PDCL,2mS);",
                ))
            return
        resource = generate_digital_compare_resource(judge)
        self._resource(resource)
        name, end = compare_pattern_span(judge.pins, judge.expected)
        self._pattern_run(name, judge.sub, end)

    def _cleanup_voltage_forces(self) -> None:
        for pin in self.voltage_forces.values():
            self.lines.extend((
                f"  FORCE_V_PPMU({pin},0V,,@32mA,,2mS);",
                f"  RELAY_OFF({pin},PPMU_PDCL,2mS);",
            ))
        self.voltage_forces.clear()

    def _clock_modes(self, signals: tuple[ClockSignal, ...]) -> dict[str, str]:
        occupied: set[tuple[int, int]] = set()
        modes = {}
        for signal in sorted(signals, key=lambda item: item.frequency_hz, reverse=True):
            self._pin(signal.pin)
            binding = self._binding(signal.pin)
            groups = set()
            for site, channel in enumerate(binding.channels):
                try:
                    groups.add((site, int(channel) // 8))
                except (TypeError, ValueError) as exc:
                    raise ChromaFirmwareRenderError(
                        "FW.CHROMA.CLOCK.CHANNEL_INVALID",
                        f"{signal.pin!r} has non-numeric Chroma channel {channel!r}",
                    ) from exc
            mode = "pattern" if occupied.intersection(groups) else "tmu"
            modes[signal.pin.casefold()] = mode
            if mode == "tmu":
                occupied.update(groups)
        return modes

    def _clock_loop(self, signal: ClockSignal) -> ResourceRequest:
        name = f"firmware_{signal.pin.lower()}_clkloop"
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{signal.pin};\n\nSPM_PATTERN({name}) {{\n\n"
            "  *X*TS3;\n  *X*;\n  *X*;\n"
            "LOOP:  *0*;\n  *1*JCONT LOOP;\n"
            "  *X*;\n  *X*;\n  *X*;\n  *X*STOP;\n}\n"
        ).encode("ascii")
        return self._generated(
            name,
            signal.pin,
            content,
            f"clock-loop:{_number(signal.frequency_hz)}Hz",
        )

    def _pattern_run(self, name: str, alias: str, end: str | None = None) -> None:
        self._datalog(alias)
        self.lines.append(f"  JUDGE_PAT({name},{end or '__' + name});")

    def _datalog(self, alias: str) -> None:
        escaped = str(alias).replace("\\", "\\\\").replace('"', '\\"')
        self.lines.extend((
            "  TEST_NUM++;",
            f'  TEST_NO(TEST_NUM); DATALOG_MSG="{escaped}";',
        ))

    def _pin(self, name: str, *, power: bool = False) -> None:
        binding = self._binding(name)
        expected = "pwr" if power else "io"
        if binding.kind != expected:
            self._fail(
                "FW.CHROMA.PIN.KIND_INVALID",
                f"pin {name!r} is {binding.kind!r}, expected {expected!r}",
            )

    def _binding(self, name: str):
        binding = next(
            (pin for pin in self.facts.pins if pin.name.casefold() == name.casefold()),
            None,
        )
        if binding is None:
            self._fail(
                "FW.CHROMA.PIN.UNDECLARED",
                f"pin {name!r} is absent from platform facts",
            )
        return binding

    def _resource(self, resource: ResourceRequest) -> None:
        path_owner = next(
            (
                item
                for item in self.resources.values()
                if item.relative_path.casefold() == resource.relative_path.casefold()
                and item.logical_identity != resource.logical_identity
            ),
            None,
        )
        if path_owner is not None:
            self._fail(
                "FW.CHROMA.RESOURCE.PATH_CONFLICT",
                f"path {resource.relative_path!r} has multiple logical identities",
            )
        previous = self.resources.get(resource.logical_identity)
        if previous is not None and previous != resource:
            self._fail(
                "FW.CHROMA.RESOURCE.CONFLICT",
                f"resource {resource.logical_identity!r} has conflicting content",
            )
        self.resources.setdefault(resource.logical_identity, resource)

    def _require(self, requirement: ResourceRequirement) -> None:
        path_owner = next(
            (
                item
                for item in self.requirements.values()
                if item.relative_path.casefold() == requirement.relative_path.casefold()
                and item.logical_identity != requirement.logical_identity
            ),
            None,
        )
        if path_owner is not None:
            self._fail(
                "FW.CHROMA.REQUIREMENT.PATH_CONFLICT",
                f"path {requirement.relative_path!r} has multiple logical identities",
            )
        previous = self.requirements.get(requirement.logical_identity)
        if previous is not None and previous != requirement:
            self._fail(
                "FW.CHROMA.REQUIREMENT.CONFLICT",
                f"requirement {requirement.logical_identity!r} conflicts",
            )
        self.requirements.setdefault(requirement.logical_identity, requirement)

    @staticmethod
    def _generated(
        name: str, pin: str, content: bytes, purpose: str
    ) -> ResourceRequest:
        digest = hashlib.sha256(content).hexdigest().upper()
        return ResourceRequest(
            f"firmware-chroma:{name}:{purpose}",
            f"pat/{name}.pat",
            content,
            f"v14.firmware-action/1:chroma:{purpose}",
            f"generated:chroma:{pin}:sha256:{digest}",
            f"Chroma firmware {purpose} Pattern",
        )

    def _unsupported(self, action) -> None:
        self._fail(
            "FW.CHROMA.ACTION.UNSUPPORTED",
            f"unsupported typed action {type(action).__name__}",
        )

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise ChromaFirmwareRenderError(code, message)


def render_firmware_test(
    plan: FirmwareTestPlan,
    render_name: str,
    hardware_bin,
    platform_facts,
) -> FirmwareBodyRender:
    """Render one complete Chroma firmware test body from detached typed facts."""
    if not isinstance(plan, FirmwareTestPlan):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.PLAN.INVALID", "expected FirmwareTestPlan"
        )
    name = str(render_name).strip()
    if not _SYMBOL_RE.fullmatch(name):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.NAME.INVALID", f"unsafe render name {render_name!r}"
        )
    if getattr(platform_facts, "platform", "").casefold() != "chroma":
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.FACTS.PLATFORM_MISMATCH",
            "renderer requires Chroma platform facts",
        )
    if getattr(platform_facts, "cp", "").casefold() != plan.cp.casefold():
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.FACTS.CP_MISMATCH",
            f"facts CP {getattr(platform_facts, 'cp', None)!r} != {plan.cp!r}",
        )
    _validate_plan_shape(plan)
    _ = hardware_bin  # Chroma reject bins are owned by the flow, not body syntax.
    return _Renderer(plan, platform_facts).render(name)


def generate_level_sequence_resource(action: LevelSequenceAction) -> ResourceRequest:
    """Generate the shared Chroma LevelSequenceAction pattern resource."""
    if not re.fullmatch(r"[HL]+", action.levels):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.LEVEL.STATES_INVALID",
            f"invalid level sequence {action.levels!r}",
        )
    if action.segment_duration_ns <= 0 or action.segment_duration_ns % _TS1_NS:
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.LEVEL.TIMING_UNREPRESENTABLE",
            f"{action.segment_duration_ns}ns is not a positive TS1 multiple",
        )
    name = trigger_pattern_name(action)
    repeat = action.segment_duration_ns // _TS1_NS
    vectors = "\n".join(
        f"  *{'1' if level == 'H' else '0'}*RPT {repeat};"
        for level in action.levels
    )
    content = (
        'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
        f"{action.pin};\n\nSPM_PATTERN({name}) {{\n\n"
        f"  *X*TS1;\n{vectors}\n  *X*STOP;\n}}\n"
    ).encode("ascii")
    return _Renderer._generated(name, action.pin, content, "level-sequence")


def generate_send_code_resource(action: SendCodeAction) -> ResourceRequest:
    """Generate the shared Chroma SendCodeAction pattern resource."""
    if (
        not isinstance(action.value, int)
        or isinstance(action.value, bool)
        or not 0 <= action.value <= 255
    ):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.SEND_CODE.OUT_OF_RANGE",
            f"send code must be an integer from 0 to 255, got {action.value!r}",
        )
    name = trigger_pattern_name(action)
    frames = []
    for value in range(256):
        label = send_label(value)
        vectors = "\n".join(f"  *{bit}*RPT 422;" for bit in f"{value:08b}")
        frames.append(
            f"{label}_ST:\n  *X*TS1;\n  *1*RPT 632;\n  *0*RPT 422;\n"
            "  *1*RPT 422;\n  *0*RPT 422;\n"
            f"{vectors}\n  *0*RPT 502;\n{label}_SP:\n  *X*;\n"
        )
    content = (
        'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
        f"{action.pin};\n\nSPM_PATTERN({name}) {{\n\n"
        + "\n".join(frames) + "  *X*STOP;\n}\n"
    ).encode("ascii")
    return _Renderer._generated(name, action.pin, content, "send-code")


def action_pattern_span(action: LevelSequenceAction | SendCodeAction) -> tuple[str, str]:
    name = trigger_pattern_name(action)
    if isinstance(action, SendCodeAction):
        label = send_label(action.value)
        return f"{name}:{label}_ST", f"{name}:{label}_SP"
    return name, f"__{name}"


def compare_pattern_span(pins, expected) -> tuple[str, str]:
    name = compare_pattern_name(pins)
    label = compare_label(expected)
    return f"{name}:{label}_ST", f"{name}:{label}_SP"


def generate_digital_compare_resource(judge: DigitalCompareJudgePlan) -> ResourceRequest:
    """Share all H/L states using the full PVD compare waveform."""
    if not judge.pins or len(judge.pins) != len(judge.expected) or any(
        state not in ("H", "L") for state in judge.expected
    ):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.JUDGE.DIGITAL_FACTS_INVALID",
            "digital judge pins and H/L states must align",
        )
    name = compare_pattern_name(judge.pins)
    idle = "X" * len(judge.pins)
    frames = []
    for states in product("HL", repeat=len(judge.pins)):
        vector = compare_label(states)
        label = vector
        frames.append(
            f"{label}_ST:\n  *{idle}*TS1;\n"
            f"  *{idle}*RPT 100;\n  *{idle}*RPT 100;\n"
            f"  *{vector}*;\n  *{vector}*;\n"
            f"  *{vector}*RPT 100;\n  *{vector}*;\n"
            f"  *{idle}*;\n  *{idle}*;\n{label}_SP:\n  *{idle}*;\n"
        )
    content = (
        'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
        f"{','.join(judge.pins)};\n\nSPM_PATTERN({name}) {{\n\n"
        + "\n".join(frames) + f"  *{idle}*STOP;\n}}\n"
    ).encode("ascii")
    return _Renderer._generated(name, "+".join(judge.pins), content, "digital-compare")


def _validate_plan_shape(plan: FirmwareTestPlan) -> None:
    if not plan.phases or any(
        not isinstance(phase, (DownloadPhase, KeilPhase)) for phase in plan.phases
    ):
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.PLAN.PHASES_INVALID",
            "firmware plan requires DownloadPhase/KeilPhase facts",
        )
    has_download = any(isinstance(phase, DownloadPhase) for phase in plan.phases)
    has_keil = any(isinstance(phase, KeilPhase) for phase in plan.phases)
    expected_kind = (
        "FIRMWARE_FUNCTION_TEST"
        if has_download and has_keil
        else "CODE_DOWNLOAD"
        if has_download
        else "FIRMWARE_RUN_TEST"
    )
    if plan.typed_kind != expected_kind:
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.PLAN.TYPED_KIND_MISMATCH",
            f"phase composition requires {expected_kind!r}",
        )
    expected_steps = _execution_steps_for(expected_kind, plan.phases)
    if tuple(expected_steps) != plan.execution_steps:
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.PLAN.EXECUTION_STEPS_MISMATCH",
            "execution_steps do not match the compiled phase/sub contract",
        )


def _mldps_current_range(value: float, unit: str) -> str:
    scales = {"ua": 1e-6, "ma": 1e-3, "a": 1.0}
    normalized = str(unit).strip().casefold()
    if normalized not in scales or not math.isfinite(float(value)) or float(value) <= 0:
        raise ChromaFirmwareRenderError(
            "FW.CHROMA.SUPPLY.COMPLIANCE_INVALID",
            f"invalid current compliance {value!r}{unit}",
        )
    amps = abs(float(value)) * scales[normalized]
    ranges = (
        (5e-6, "@5uA,5uA", False),
        (25e-6, "@25uA,25uA", False),
        (250e-6, "@250uA,250uA", False),
        (2.5e-3, "@2.5mA,2.5mA", True),
        (25e-3, "@25mA,25mA", False),
        (500e-3, "@500mA,500mA", True),
        (1.0, "@1A,1A", True),
    )
    for limit, rendered, inclusive in ranges:
        matches = amps <= limit if inclusive else amps < limit
        if matches:
            return rendered
    raise ChromaFirmwareRenderError(
        "FW.CHROMA.SUPPLY.COMPLIANCE_OUT_OF_RANGE",
        f"current compliance {value!r}{unit} exceeds 1A",
    )


def _voltage(value: object) -> str:
    text = str(value).strip()
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return f"{text}V"
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)[vV]", text):
        return text.upper()
    if _SYMBOL_RE.fullmatch(text):
        return text.upper()
    raise ChromaFirmwareRenderError(
        "FW.CHROMA.VOLTAGE.INVALID", f"unsafe voltage expression {value!r}"
    )


def _number(value: float) -> str:
    return format(float(value), ".12g")


def _time(value_ns: float) -> str:
    if value_ns >= 1e6:
        return f"{value_ns / 1e6:.2f}mS"
    if value_ns >= 1e3:
        return f"{value_ns / 1e3:.2f}uS"
    return f"{value_ns:.2f}nS"


__all__ = [
    "ChromaFirmwareRenderError",
    "action_pattern_span",
    "compare_pattern_span",
    "generate_level_sequence_resource",
    "generate_send_code_resource",
    "generate_digital_compare_resource",
    "render_firmware_test",
]
