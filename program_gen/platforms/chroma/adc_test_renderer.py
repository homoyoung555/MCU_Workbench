"""Pure Chroma renderer for native SWD and KEIL ADC plans."""

from __future__ import annotations

from program_gen.core.adc_test import adc_pattern_names

from collections.abc import Mapping
import re

from program_gen.core.adc_execution import project_adc_phase
from program_gen.core.adc_test import AdcPhaseKind, AdcTestPlan
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.chroma.firmware_test_renderer import (
    action_pattern_span,
    compare_pattern_span,
    generate_digital_compare_resource,
    generate_level_sequence_resource,
    generate_send_code_resource,
)
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ChromaAdcRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_adc_test(
    plan: AdcTestPlan,
    render_name: str,
    hardware_bin,
    platform_facts,
    module_emissions: Mapping[int, RecipeModuleEmission] | None = None,
) -> FirmwareBodyRender:
    _validate(plan, render_name, platform_facts)
    _ = hardware_bin  # Chroma bin routing is owned by the canonical schedule.
    emissions = {} if module_emissions is None else dict(module_emissions)
    resources = []
    requirements = []
    lines = [f"{render_name}()", "{", "  int temp_cap_data[1024];"]
    for phase in plan.phases:
        lines.extend(sub_comment(phase.sub, '  '))
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
    lines.append("}")
    return FirmwareBodyRender(
        "\n".join(lines) + "\n",
        resources=tuple(resources),
        resource_requires=tuple(requirements),
    )


def _swd_phase(execution, config: str, capture: str) -> list[str]:
    phase = execution.source
    count = phase.capture.slot_count
    width = phase.capture.word_width_bits
    drive_pins = "+".join(drive.pin for drive in execution.drives)
    data = f"adc_data_{phase.adc_id.lower()}"
    lines = [
        f"  // {phase.adc_id} session",
        "  {",
        f"    int {data}[MAX_SITE][{count}]={{0}};",
    ]
    _adc_judge_declarations(lines, execution, indent="    ")
    lines.append(f"    POWER_ON({phase.power_profile});")
    _force_inputs(lines, execution, drive_pins)
    lines.extend((
        "",
        "    TEST_NUM++;",
        f'    TEST_NO(TEST_NUM); DATALOG_MSG="{config}";',
        f"    JUDGE_PAT({config},__{config});",
        "",
        "    SOCKET_INC(FRZ_OFF)",
        "    {",
        f"      SET_CAPTURE_MEM_MODE({phase.capture_pin}, PEL_K, ON, 32K);",
        "      TEST_NUM++;",
        f'      TEST_NO(TEST_NUM); DATALOG_MSG="{capture}";',
        f"      JUDGE_PAT({capture},__{capture});",
        f"      READ_CAPTURE_MEM_BLOCK(SOCKET, {phase.capture_pin}, 0, {count * width - 1}, temp_cap_data);",
        f"      for(K=0;K<{count};K++)",
        "      {",
        f"        {data}[SOCKET][K]=0;",
        f"        for(J=0;J<{width};J++)",
        f"          {data}[SOCKET][K] += temp_cap_data[{width}*K+J]<<(J);",
        "      }",
    ))
    _adc_judge(lines, execution, data, indent="      ")
    lines.extend((
        f"      SET_CAPTURE_MEM_MODE({phase.capture_pin}, PEL_K, OFF, 32K);",
        "    }",
    ))
    _cleanup(lines, execution, drive_pins)
    return lines


def _keil_phase(execution, emission, facts):
    phase = execution.source
    drive_pins = "+".join(drive.pin for drive in execution.drives)
    lines = [
        f"  // {phase.adc_id} session",
        "  {",
    ]
    if phase.kind is AdcPhaseKind.KEIL_SRAM_CAPTURE:
        _adc_judge_declarations(lines, execution, indent="    ")
    lines.append(f"    POWER_ON({phase.power_profile});")
    _force_inputs(lines, execution, drive_pins)
    resources = []
    for action in phase.run_actions:
        _require_action_pin(action, facts)
        if isinstance(action, LevelSequenceAction):
            resource = generate_level_sequence_resource(action)
            resources.append(resource)
            start, end = action_pattern_span(action)
            _pattern_run(lines, start, phase.sub, end)
        elif isinstance(action, SendCodeAction):
            resource = generate_send_code_resource(action)
            resources.append(resource)
            start, end = action_pattern_span(action)
            _pattern_run(lines, start, phase.sub, end)
        elif isinstance(action, WaitAction):
            lines.append(f"    WAIT({action.duration_ms}mS);")
        else:  # pragma: no cover - core compiler closes this union
            raise ChromaAdcRenderError(
                "ADC.CHROMA.ACTION.UNSUPPORTED", type(action).__name__
            )
    if phase.kind is AdcPhaseKind.KEIL_SRAM_CAPTURE:
        if phase.sram_capture is None or not isinstance(emission, RecipeModuleEmission):
            raise ChromaAdcRenderError(
                "ADC.CHROMA.SRAM_CAPTURE.EMISSION_MISSING", phase.adc_id
            )
        lines.extend(_indent(emission.statements, "  "))
        lines.extend(("    SOCKET_INC(FRZ_OFF)", "    {"))
        _adc_judge(
            lines, execution, phase.sram_capture.result_symbol, indent="      "
        )
        lines.append("    }")
    elif phase.kind is AdcPhaseKind.KEIL_DIGITAL_COMPARE:
        if emission is not None:
            raise ChromaAdcRenderError(
                "ADC.CHROMA.EMISSION.UNEXPECTED", phase.adc_id
            )
        if phase.digital_judge is None:
            raise ChromaAdcRenderError(
                "ADC.CHROMA.DIGITAL_JUDGE.MISSING", phase.adc_id
            )
        for pin in phase.digital_judge.pins:
            _require_io_pin(pin, facts)
        resource = generate_digital_compare_resource(phase.digital_judge)
        resources.append(resource)
        start, end = compare_pattern_span(phase.digital_judge.pins, phase.digital_judge.expected)
        _pattern_run(lines, start, phase.digital_judge.sub, end)
    else:  # pragma: no cover - validated before rendering
        raise ChromaAdcRenderError("ADC.CHROMA.PHASE.UNSUPPORTED", phase.adc_id)
    _cleanup(lines, execution, drive_pins)
    return lines, resources


def _force_inputs(lines, execution, drive_pins: str) -> None:
    if drive_pins:
        lines.append(f"    RELAY_ON({drive_pins},PPMU_PDCL,2mS);")
    for drive in execution.drives:
        lines.append(
            f"    FORCE_V_PPMU({drive.pin}, {_number(drive.voltage)}V,,@32mA,,2mS);"
        )


def _cleanup(lines, execution, drive_pins: str) -> None:
    if drive_pins:
        lines.append(f"    RELAY_OFF({drive_pins},PPMU_PDCL,2mS);")
    lines.extend(("    POWER_OFF();", "  }"))


def _adc_judge(lines, execution, data: str, *, indent: str) -> None:
    phase = execution.source
    slots = tuple(slot.source for slot in execution.slots if slot.judge_enabled)
    stem = phase.adc_id.lower()
    lines.extend((
        f"{indent}for(int item=0;item<{len(slots)};item++)",
        f"{indent}{{",
        f'{indent}  sprintf({stem}_log,"{phase.adc_id}_CH%d_%s_Verify",'
        f"{stem}_channel[item],{stem}_label[item]);",
        f"{indent}  JUDGE_VARIABLE(SOCKET,{data}[SOCKET][{stem}_channel[item]],"
        f"{stem}_down[item],{stem}_up[item],{stem}_log);",
        f"{indent}}}",
    ))


def _adc_judge_declarations(lines, execution, *, indent: str) -> None:
    slots = tuple(slot.source for slot in execution.slots if slot.judge_enabled)
    stem = execution.source.adc_id.lower()
    lines.extend((
        f"{indent}int {stem}_channel[{len(slots)}]={{"
        + ",".join(str(slot.channel) for slot in slots) + "};",
        f"{indent}int {stem}_down[{len(slots)}]={{"
        + ",".join(str(slot.low_limit) for slot in slots) + "};",
        f"{indent}int {stem}_up[{len(slots)}]={{"
        + ",".join(str(slot.high_limit) for slot in slots) + "};",
        f"{indent}char {stem}_label[{len(slots)}][32]={{"
        + ",".join(f'\"{_label(slot)}\"' for slot in slots) + "};",
        f"{indent}char {stem}_log[64]={{0}};",
    ))


def _pattern_run(lines: list[str], name: str, alias: str, end: str | None = None) -> None:
    lines.extend((
        "    TEST_NUM++;",
        f'    TEST_NO(TEST_NUM); DATALOG_MSG="{alias}";',
        f"    JUDGE_PAT({name},{end or '__' + name});",
    ))


def _indent(statements, prefix: str) -> list[str]:
    return [prefix + statement if statement else "" for statement in statements]


def _require_action_pin(action, facts) -> None:
    pin = getattr(action, "pin", None)
    if pin is not None:
        _require_io_pin(pin, facts)


def _require_io_pin(pin: str, facts) -> None:
    binding = next(
        (item for item in facts.pins if item.name.casefold() == pin.casefold()), None
    )
    if binding is None or binding.kind != "io":
        raise ChromaAdcRenderError("ADC.CHROMA.PIN.INVALID", repr(pin))


def _patterns(phase):
    names = dict(phase.pattern_names)
    default_config, default_capture = adc_pattern_names(phase.adc_id)
    return names.get('config', default_config), names.get('capture', default_capture)


def _requirement(adc_id: str, role: str, pattern: str) -> ResourceRequirement:
    return ResourceRequirement(
        f"adc-swd:chroma:{adc_id.casefold()}:{role}",
        f"pat/{pattern}.pat",
        f"v14.adc-swd/1:chroma:{role}",
        f"ADC SWD {role} Pattern ({adc_id})",
    )


def _label(slot) -> str:
    label = slot.logical_pin.removeprefix("INT_")
    return re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") or "VALUE"


def _number(value: float) -> str:
    return format(float(value), ".12g")


def _validate(plan, render_name, facts) -> None:
    if not isinstance(plan, AdcTestPlan):
        raise ChromaAdcRenderError("ADC.CHROMA.PLAN.INVALID", type(plan).__name__)
    if plan.typed_kind != "ADC_TEST":
        raise ChromaAdcRenderError("ADC.CHROMA.KIND.INVALID", plan.typed_kind)
    if not _IDENTIFIER.fullmatch(str(render_name)):
        raise ChromaAdcRenderError("ADC.CHROMA.NAME.INVALID", repr(render_name))
    if getattr(facts, "platform", "").casefold() != "chroma":
        raise ChromaAdcRenderError("ADC.CHROMA.PLATFORM.INVALID", repr(getattr(facts, "platform", None)))
    if getattr(facts, "cp", "").casefold() != plan.cp.casefold():
        raise ChromaAdcRenderError("ADC.CHROMA.CP.MISMATCH", f"{plan.cp}/{getattr(facts, 'cp', None)}")
    if not plan.phases:
        raise ChromaAdcRenderError("ADC.CHROMA.PHASES.EMPTY", plan.item)
    expected_recipes = {
        AdcPhaseKind.SWD_CAPTURE: ("SWD_CAPTURE", "ADC_JUDGE"),
        AdcPhaseKind.KEIL_SRAM_CAPTURE: (
            "RUN_SEQUENCE", "SRAM_CAPTURE", "ADC_JUDGE"
        ),
        AdcPhaseKind.KEIL_DIGITAL_COMPARE: ("RUN_SEQUENCE", "JUDGE"),
    }
    for phase in plan.phases:
        if not phase.independent_power_session:
            raise ChromaAdcRenderError("ADC.CHROMA.SESSION.REQUIRED", phase.adc_id)
        if expected_recipes.get(phase.kind) != phase.effective_recipe:
            raise ChromaAdcRenderError("ADC.CHROMA.RECIPE.INVALID", repr(phase.effective_recipe))


__all__ = ["ChromaAdcRenderError", "render_adc_test"]
