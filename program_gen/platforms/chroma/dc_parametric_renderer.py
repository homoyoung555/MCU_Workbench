"""Pure Chroma renderer for DC_PARAMETRIC_TEST."""

from __future__ import annotations

import re

from program_gen.core.dc_parametric import LeakagePlan, RpdRpuPlan, VolVohPlan
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.render_plan import ResourceRequirement


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ChromaDcRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_dc_parametric(plan, render_name, hardware_bin, platform_facts):
    _validate(plan, render_name, platform_facts)
    _ = hardware_bin
    requirements = tuple(
        _requirement(pattern) for pattern in plan.config_patterns
    )
    lines = [f"{render_name}()", "{", f"  POWER_ON({_power(plan.power_profile)});", ""]
    if isinstance(plan, LeakagePlan):
        lines.extend(_run_pattern(plan.config_patterns[0]))
        lines.append("  RELAY_OFF(IO_ALLPINS,PDCL,2mS);")
        for phase in plan.phases:
            lines.extend(sub_comment(phase.sub, '  '))
            sibling = plan.phases[1] if phase is plan.phases[0] else plan.phases[0]
            lines.extend(_leakage_phase(phase, sibling))
    else:
        lines.extend(("  char temp_group[48],log_msg[48];", ""))
        for phase in plan.phases:
            lines.extend(sub_comment(phase.sub, '  '))
            lines.extend(_run_pattern(phase.config_pattern))
            lines.append("  RELAY_OFF(IO_ALLPINS,PDCL,2mS);")
            lines.extend(_group_phase(phase, plan, platform_facts))
    lines.extend(("  POWER_OFF();", "}"))
    return FirmwareBodyRender(
        "\n".join(lines) + "\n", resource_requires=requirements
    )


def _leakage_phase(phase, sibling):
    low = _limit(phase.measurement.low_limit, phase.measurement.unit)
    high = _limit(phase.measurement.high_limit, phase.measurement.unit)
    alias = _alias(phase.sub)
    return [
        "  RELAY_ON(Leakage_ODD_pins,PPMU_PDCL,2mS);",
        "  RELAY_ON(Leakage_EVEN_pins,PPMU_PDCL,2mS);",
        f"  FORCE_V_PPMU(Leakage_ODD_pins,{_force_v(phase.force.value)},,@2uA,,2mS);",
        f"  FORCE_V_PPMU(Leakage_EVEN_pins,{_force_v(sibling.force.value)},,@2uA,,2mS);",
        "  WAIT(2mS);",
        "  TEST_NUM++;", f'  TEST_NO(TEST_NUM); DATALOG_MSG="{alias}_odd";',
        f"  JUDGE_I_PPMU(Leakage_ODD_pins,{low},{high},2mS);",
        "  TEST_NUM++;", f'  TEST_NO(TEST_NUM); DATALOG_MSG="{alias}_even";',
        f"  JUDGE_I_PPMU(Leakage_EVEN_pins,{low},{high},2mS);",
        "  FORCE_V_PPMU(Leakage_ODD_pins,0V,,@2uA,,2mS);",
        "  FORCE_V_PPMU(Leakage_EVEN_pins,0V,,@2uA,,2mS);",
        "  RELAY_OFF(Leakage_ODD_pins,PPMU_PDCL,2mS);",
        "  RELAY_OFF(Leakage_EVEN_pins,PPMU_PDCL,2mS);", "",
    ]


def _group_phase(phase, plan, facts):
    group = "MT_GROUP_PINS"
    lines = [
        f"  for(I=1;I<={len(facts.pin_groups.dc_groups)};I++)", "  {",
        '    sprintf(temp_group,"DC%d_pins",I);',
        "    GetPinbyName(temp_group);",
        f"    RELAY_ON({group},PPMU_PDCL,2mS);",
        "    TEST_NUM++;",
        f'    sprintf(log_msg,"{_alias(phase.sub)}_dc%d",I);',
        '    TEST_NO(TEST_NUM); DATALOG_MSG=log_msg;',
    ]
    low = _limit(phase.measurement.low_limit, phase.measurement.unit)
    high = _limit(phase.measurement.high_limit, phase.measurement.unit)
    if isinstance(plan, VolVohPlan):
        lines.extend((
            f"    FORCE_I_PPMU({group},{phase.force.value},@32mA,,6V,-2V,3mS);",
            f"    JUDGE_V_PPMU({group},{low},{high},2mS);",
            f"    FORCE_V_PPMU({group},0V,,@2uA,,2mS);",
        ))
    elif isinstance(plan, RpdRpuPlan):
        lines.extend((
            f"    FORCE_V_PPMU({group},{_force_v(phase.force.value)},,@200uA,,2mS);",
            f"    JUDGE_I_PPMU({group},{low},{high},2mS);",
            f"    FORCE_V_PPMU({group},0V,,@200uA,,2mS);",
        ))
    lines.extend((f"    RELAY_OFF({group},PPMU_PDCL,2mS);", "  }", ""))
    return lines


def dc_group_helper():
    """Keep the vendor pin-group lookup convention used by the legacy writer."""
    return (
        "int *MT_Group_Pins,MT_Group_PinsCnt=0;\n"
        "int GetPinbyName(char *name)\n{\n"
        "  MT_Group_PinsCnt = GetPinChannel(name,MT_Group_Pins);\n"
        "  if(MT_Group_PinsCnt == -1) MT_Group_PinsCnt = GetPGChannel(name,MT_Group_Pins);\n"
        "  return MT_Group_PinsCnt;\n}\n\n"
    )


def _run_pattern(pattern):
    return [
        "  TEST_NUM++;", f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";',
        f"  JUDGE_PAT({pattern},__{pattern});", "",
    ]


def _requirement(pattern):
    return ResourceRequirement(
        f"dc-swd:chroma:{pattern.casefold()}", f"pat/{pattern}.pat",
        "v14.dc-swd/1:chroma:config", f"DC SWD config Pattern ({pattern})",
    )


def _power(value):
    return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I) else value


def _force_v(value):
    return value


def _limit(value, unit):
    return f"{format(float(value), '.12g')}{unit}"


def _alias(value):
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()


def _validate(plan, name, facts):
    if not isinstance(plan, (LeakagePlan, VolVohPlan, RpdRpuPlan)):
        raise ChromaDcRenderError("DC.CHROMA.PLAN.INVALID", type(plan).__name__)
    if plan.typed_kind != "DC_PARAMETRIC_TEST" or plan.effective_recipe != ("DC_TEST",):
        raise ChromaDcRenderError("DC.CHROMA.CONTRACT.INVALID", plan.typed_kind)
    if not plan.shared_power_session or len(plan.phases) != 2:
        raise ChromaDcRenderError("DC.CHROMA.SESSION.INVALID", plan.item)
    if not _IDENTIFIER.fullmatch(str(name)):
        raise ChromaDcRenderError("DC.CHROMA.NAME.INVALID", repr(name))
    if facts.platform.casefold() != "chroma" or facts.cp.casefold() != plan.cp.casefold():
        raise ChromaDcRenderError("DC.CHROMA.FACTS.INVALID", f"{facts.platform}/{facts.cp}")
    if not facts.pin_groups.dc_groups or not facts.pin_groups.leakage_odd or not facts.pin_groups.leakage_even:
        raise ChromaDcRenderError("DC.CHROMA.PIN_GROUPS.EMPTY", plan.item)


__all__ = ["ChromaDcRenderError", "render_dc_parametric"]
