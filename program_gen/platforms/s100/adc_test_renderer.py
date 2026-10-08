"""Pure S100 renderer for native SWD and KEIL ADC plans."""

from __future__ import annotations

from program_gen.core.adc_test import adc_pattern_names as _patterns_for_adc

from collections.abc import Mapping
import re

from program_gen.core.adc_execution import project_adc_phase
from program_gen.core.adc_test import AdcPhaseKind, AdcTestPlan
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platform_program.facts import PlatformProgramFacts
from program_gen.platforms.s100.firmware_test_renderer import (
    action_pattern_span, compare_pattern_span,
    generate_digital_compare_resource,
    generate_level_sequence_resource,
    generate_send_code_resource,
)
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class S100AdcRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_adc_test(
    plan: AdcTestPlan,
    render_name: str,
    hardware_bin: int | str,
    platform_facts: PlatformProgramFacts,
    module_emissions: Mapping[int, RecipeModuleEmission] | None = None,
) -> FirmwareBodyRender:
    """Render one plan whose ADC phases each own an independent power session."""
    _validate(plan, render_name, platform_facts)
    reject_bin = _hardware_bin(hardware_bin)
    emissions = {} if module_emissions is None else dict(module_emissions)
    resources = []
    requirements = []
    lines = [
        f"@@PLAN {render_name}",
        "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;",
        "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;",
        f"\tREMARK             = {render_name};",
        "",
    ]
    for phase in plan.phases:
        lines.extend(sub_comment(phase.sub, '\t'))
        execution = project_adc_phase(phase, platform_facts.io_pins)
        if phase.kind is AdcPhaseKind.SWD_CAPTURE:
            config, capture = _patterns(phase)
            requirements.extend((
                _requirement(phase.adc_id, "config", config),
                _requirement(phase.adc_id, "capture", capture),
            ))
            lines.extend(_swd_phase(execution, config, capture))
        else:
            phase_lines, phase_resources = _keil_phase(
                execution, emissions.get(phase.row), platform_facts
            )
            lines.extend(phase_lines)
            resources.extend(phase_resources)
    lines.extend((
        "\tCONDITION",
        "\tIF_FAIL",
        f"\tREJECT_BIN = {reject_bin};",
        "@@END_PLAN",
    ))
    return FirmwareBodyRender(
        "\n".join(lines) + "\n",
        resources=tuple(resources),
        resource_requires=tuple(requirements),
    )


def _swd_phase(execution, config: str, capture: str) -> list[str]:
    phase = execution.source
    count = phase.capture.slot_count
    width = phase.capture.word_width_bits
    data = f"{phase.adc_id}_DATA"
    lines = [
        f"\t// {phase.adc_id} session",
        f"\tint {data}[MAX_SITE][{count}]={{0}};",
        f"\tCALL_MACRO POWER_ON(_C_{phase.power_profile});",
        "",
    ]
    _force_inputs(lines, execution)
    lines.extend((
        "\tWAIT(5MS);",
        "",
        f"\tRUN_PATTERN({config}:START,{config}:END,1,TS_500K);",
        "",
        f"\tLOGIC_SET_AC_DATALOG({capture}:START,{capture}:END,"
        "LOG_ENABLE_ALL,AC_IGNORE_FAIL);",
        f'\tLOGIC_DAQ_TRANSFER_SETTING({phase.capture_pin}, "1", '
        "TRIG=PTN_TRIG,ACLOG_FILTER_BY_PTN_TRIG_MODE);",
        f"\tRUN_PATTERN({capture}:START,{capture}:END,1,TS_500K);",
        f"\tLOGIC_DAQ_DATA_READ(DATA_COUNT={count * width});",
        "",
        f"\tfor(int K=0;K<{count};K++)",
        "\t{",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
        f"\t\t\t{data}[T_SOCKET][K]=0;",
        f"\t\t\tfor(int J=0;J<{width};J++)",
        f"\t\t\t\t{data}[T_SOCKET][K] += "
        "(int)Sys_SW_BUFFER_DATA[T_SOCKET][J+(K*16)]<<J;",
        "\t\t}",
        "\t}",
        "",
    ))
    _adc_judge(lines, execution, data)
    _cleanup(lines, execution)
    return lines


def _keil_phase(execution, emission, facts):
    phase = execution.source
    lines = [
        f"\t// {phase.adc_id} session",
        f"\tCALL_MACRO POWER_ON(_C_{phase.power_profile});",
        "",
    ]
    _force_inputs(lines, execution)
    lines.append("\tWAIT(5MS);")
    resources = []
    for action in phase.run_actions:
        _require_action_pin(action, facts)
        if isinstance(action, LevelSequenceAction):
            resource = generate_level_sequence_resource(action)
            resources.append(resource)
            start, end = action_pattern_span(action)
            lines.append(
                f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);"
            )
        elif isinstance(action, SendCodeAction):
            resource = generate_send_code_resource(action)
            resources.append(resource)
            start, end = action_pattern_span(action)
            lines.append(
                f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);"
            )
        elif isinstance(action, WaitAction):
            lines.append(f"\tWAIT({action.duration_ms}MS);")
        else:  # pragma: no cover - core compiler closes this union
            raise S100AdcRenderError(
                "ADC.S100.ACTION.UNSUPPORTED", type(action).__name__
            )
    if phase.kind is AdcPhaseKind.KEIL_SRAM_CAPTURE:
        if phase.sram_capture is None or not isinstance(emission, RecipeModuleEmission):
            raise S100AdcRenderError(
                "ADC.S100.SRAM_CAPTURE.EMISSION_MISSING", phase.adc_id
            )
        lines.extend(emission.statements)
        _adc_judge(lines, execution, phase.sram_capture.result_symbol)
    elif phase.kind is AdcPhaseKind.KEIL_DIGITAL_COMPARE:
        if emission is not None:
            raise S100AdcRenderError("ADC.S100.EMISSION.UNEXPECTED", phase.adc_id)
        if phase.digital_judge is None:
            raise S100AdcRenderError(
                "ADC.S100.DIGITAL_JUDGE.MISSING", phase.adc_id
            )
        for pin in phase.digital_judge.pins:
            _require_io_pin(pin, facts)
        resource = generate_digital_compare_resource(phase.digital_judge)
        resources.append(resource)
        start, end = compare_pattern_span(phase.digital_judge)
        lines.extend((
            f"\tRUN_PATTERN({start},{end},1,VIH_5MHZ);",
            "",
        ))
    else:  # pragma: no cover - validated before rendering
        raise S100AdcRenderError("ADC.S100.PHASE.UNSUPPORTED", phase.adc_id)
    _cleanup(lines, execution)
    return lines, resources


def _force_inputs(lines, execution) -> None:
    for drive in execution.drives:
        lines.extend((
            f"\tLOGIC_SET_DRV_LEVEL({drive.pin}, {_number(drive.voltage)}V, "
            "0.0V, 0.0V, VR1);",
            f"\tLOGIC_DRIVE_PIN({drive.pin}, DRIVE_ENABLE, HIGH);",
        ))


def _cleanup(lines, execution) -> None:
    lines.append("")
    for drive in execution.drives:
        lines.append(f"\tLOGIC_DRIVE_PIN({drive.pin}, DRIVE_DISABLE);")
    lines.extend(("\tCALL_MACRO POWER_OFF();", ""))


def _adc_judge(lines, execution, data: str) -> None:
    phase = execution.source
    slots = tuple(slot.source for slot in execution.slots if slot.judge_enabled)
    stem = phase.adc_id.lower()
    lines.extend((
        f"\tint {stem}_channel[{len(slots)}]={{"
        + ",".join(str(slot.channel) for slot in slots) + "};",
        f"\tfor(int item=0;item<{len(slots)};item++)",
        "\t{",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
        f"\t\t\tGBX[1+1024*T_SOCKET]={data}[T_SOCKET][{stem}_channel[item]];",
        "\t\t}",
        "\t\tswitch(item)",
        "\t\t{",
    ))
    for index, slot in enumerate(slots):
        lines.append(
            f"\t\tcase {index}: C_COMPARE(GBX2, DOWN_LIMIT={slot.low_limit}, "
            f"UP_LIMIT={slot.high_limit}, LOG_ALIAS={_alias(phase.adc_id, slot)}); break;"
        )
    lines.extend((
        "\t\t}",
        "\t}",
    ))


def render_adc_alias_startup(plan: AdcTestPlan, platform_facts: PlatformProgramFacts) -> str:
    lines = []
    for phase in plan.phases:
        if phase.kind is AdcPhaseKind.KEIL_DIGITAL_COMPARE:
            continue
        execution = project_adc_phase(phase, platform_facts.io_pins)
        for slot in execution.slots:
            if not slot.judge_enabled:
                continue
            source = slot.source
            lines.append(
                f"\tSET_CSV_LOG_ALIAS(LOG_ALIAS={_alias(phase.adc_id, source)}, "
                f"DOWN_LIMIT={source.low_limit}, UP_LIMIT={source.high_limit}, "
                "LOG_UNIT=NA);"
            )
    return "\r\n".join(lines) + ("\r\n" if lines else "")


def _require_action_pin(action, facts) -> None:
    pin = getattr(action, "pin", None)
    if pin is not None:
        _require_io_pin(pin, facts)


def _require_io_pin(pin: str, facts) -> None:
    present = {str(value).casefold() for value in facts.io_pins}
    if pin.casefold() not in present:
        raise S100AdcRenderError("ADC.S100.PIN.INVALID", repr(pin))


def _patterns(phase):
    names = dict(phase.pattern_names)
    default_config, default_capture = _patterns_for_adc(phase.adc_id)
    return names.get('config', default_config), names.get('capture', default_capture)


def _requirement(adc_id: str, role: str, pattern: str) -> ResourceRequirement:
    return ResourceRequirement(
        f"adc-swd:s100:{adc_id.casefold()}:{role}",
        f"{pattern}.sd",
        f"v14.adc-swd/1:s100:{role}",
        f"ADC SWD {role} pattern ({adc_id})",
    )


def _alias(adc_id, slot) -> str:
    return f"{adc_id}_CH{slot.channel}_{_label(slot)}_VERIFY".upper()


def _label(slot) -> str:
    label = re.sub(r"^INT_", "", slot.logical_pin, flags=re.IGNORECASE)
    return (re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") or "VALUE").upper()


def _number(value: float) -> str:
    return format(float(value), ".12g")


def _hardware_bin(value: int | str) -> int:
    if isinstance(value, bool) or not str(value).strip().isdigit():
        raise S100AdcRenderError("ADC.S100.BIN.INVALID", repr(value))
    return int(str(value).strip())


def _validate(plan: AdcTestPlan, render_name: str, facts: PlatformProgramFacts) -> None:
    if not isinstance(plan, AdcTestPlan):
        raise S100AdcRenderError("ADC.S100.PLAN.INVALID", type(plan).__name__)
    if plan.typed_kind != "ADC_TEST":
        raise S100AdcRenderError("ADC.S100.KIND.INVALID", plan.typed_kind)
    if not _IDENTIFIER.fullmatch(str(render_name)):
        raise S100AdcRenderError("ADC.S100.NAME.INVALID", repr(render_name))
    if not isinstance(facts, PlatformProgramFacts) or facts.platform.casefold() != "s100":
        raise S100AdcRenderError(
            "ADC.S100.PLATFORM.INVALID", repr(getattr(facts, "platform", None))
        )
    if facts.cp.casefold() != plan.cp.casefold():
        raise S100AdcRenderError("ADC.S100.CP.MISMATCH", f"{plan.cp}/{facts.cp}")
    if not plan.phases:
        raise S100AdcRenderError("ADC.S100.PHASES.EMPTY", plan.item)
    expected_recipes = {
        AdcPhaseKind.SWD_CAPTURE: ("SWD_CAPTURE", "ADC_JUDGE"),
        AdcPhaseKind.KEIL_SRAM_CAPTURE: (
            "RUN_SEQUENCE", "SRAM_CAPTURE", "ADC_JUDGE"
        ),
        AdcPhaseKind.KEIL_DIGITAL_COMPARE: ("RUN_SEQUENCE", "JUDGE"),
    }
    for phase in plan.phases:
        if not phase.independent_power_session:
            raise S100AdcRenderError("ADC.S100.SESSION.REQUIRED", phase.adc_id)
        if expected_recipes.get(phase.kind) != phase.effective_recipe:
            raise S100AdcRenderError("ADC.S100.RECIPE.INVALID", repr(phase.effective_recipe))
        if (
            phase.capture.slot_count != 22
            or phase.capture.word_width_bits != 16
            or len(phase.slots) != 22
            or tuple(slot.channel for slot in phase.slots) != tuple(range(22))
            or phase.capture.masks_upper_bits
        ):
            raise S100AdcRenderError("ADC.S100.CAPTURE.INVALID", phase.adc_id)


__all__ = ["S100AdcRenderError", "render_adc_alias_startup", "render_adc_test"]
