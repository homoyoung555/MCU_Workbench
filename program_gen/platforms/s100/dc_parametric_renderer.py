"""Pure S100 renderer for DC_PARAMETRIC_TEST."""

from __future__ import annotations

import re

from program_gen.core.dc_parametric import LeakagePlan, RpdRpuPlan, VolVohPlan
from program_gen.core.firmware_render import FirmwareBodyRender, sub_comment
from program_gen.render_plan import ResourceRequirement


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class S100DcRenderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def render_dc_parametric(plan, render_name, hardware_bin, platform_facts):
    _validate(plan, render_name, platform_facts)
    requirements = tuple(_requirement(pattern) for pattern in plan.config_patterns)
    lines = [
        f"@@PLAN {render_name}", "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;", "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;", f"\tREMARK             = {render_name};", "",
        f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});", "",
    ]
    if isinstance(plan, LeakagePlan):
        lines.extend(_run_pattern(plan.config_patterns[0]))
        for phase in plan.phases:
            lines.extend(sub_comment(phase.sub, '\t'))
            sibling = plan.phases[1] if phase is plan.phases[0] else plan.phases[0]
            lines.extend(_leakage_phase(phase, sibling))
    else:
        for phase in plan.phases:
            lines.extend(sub_comment(phase.sub, '\t'))
            lines.extend(_run_pattern(phase.config_pattern))
            lines.extend(_group_phase(phase, plan, platform_facts))
    lines.extend((
        "\tCALL_MACRO POWER_OFF();", "", "\tCONDITION", "\t\tIF_FAIL",
        f"\t\tREJECT_BIN = {_hardware_bin(hardware_bin)};", "@@END_PLAN",
    ))
    return FirmwareBodyRender(
        "\n".join(lines) + "\n", resource_requires=requirements
    )


def _leakage_phase(phase, sibling):
    low = _limit(phase.measurement.low_limit, phase.measurement.unit)
    high = _limit(phase.measurement.high_limit, phase.measurement.unit)
    alias = _alias(phase.sub)
    return [
        f"\tLOGIC_PPMU_FV(Leakage_ODD_pins,{_force_v(phase.force.value)},E2,I1);",
        f"\tLOGIC_PPMU_FV(Leakage_EVEN_pins,{_force_v(sibling.force.value)},E2,I1);",
        "\tWAIT(2MS);",
        f"\tLOGIC_PPMU_MI(Leakage_ODD_pins,DOWN_LIMIT={low},UP_LIMIT={high},LOG_ALIAS={alias}_odd_[PINGROUP],LOG_UNIT=NA);",
        f"\tLOGIC_PPMU_MI(Leakage_EVEN_pins,DOWN_LIMIT={low},UP_LIMIT={high},LOG_ALIAS={alias}_even_[PINGROUP],LOG_UNIT=NA);",
        "\tLOGIC_PPMU_FV(Leakage_ODD_pins,0V,E2,I1);",
        "\tLOGIC_PPMU_FV(Leakage_EVEN_pins,0V,E2,I1);", "",
    ]


def _group_phase(phase, plan, facts):
    lines = []
    low = _limit(phase.measurement.low_limit, phase.measurement.unit)
    high = _limit(phase.measurement.high_limit, phase.measurement.unit)
    unit = phase.measurement.unit.upper()
    for index, _members in enumerate(facts.pin_groups.dc_groups, start=1):
        group = f"DC{index}_pins"
        alias = f"{_alias(phase.sub)}_dc{index}_[PINGROUP]"
        if isinstance(plan, VolVohPlan):
            lines.extend((
                f"\tLOGIC_PPMU_FI({group},{phase.force.value},E2,I7);",
                "\tWAIT(1MS);",
                f"\tLOGIC_PPMU_MV({group},DOWN_LIMIT={low},UP_LIMIT={high},LOG_ALIAS={alias},LOG_UNIT={unit});",
                f"\tLOGIC_PPMU_FV({group},0V,E2,I2);",
            ))
        elif isinstance(plan, RpdRpuPlan):
            lines.extend((
                f"\tLOGIC_PPMU_FV({group},{_force_v(phase.force.value)},E2,I5);",
                "\tWAIT(5MS);",
                f"\tLOGIC_PPMU_MI({group},DOWN_LIMIT={low},UP_LIMIT={high},LOG_ALIAS={alias},LOG_UNIT={unit});",
                f"\tLOGIC_PPMU_FV({group},0V,E2,I5);",
            ))
        lines.extend((f"\tLOGIC_DISCONNECT_PPMU_PIN({group});", ""))
    return lines


def _run_pattern(pattern):
    return [f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,VIH_5MHZ);", ""]


def _requirement(pattern):
    return ResourceRequirement(
        f"dc-swd:s100:{pattern.casefold()}", f"{pattern}.sd",
        "v14.dc-swd/1:s100:config", f"DC SWD config Pattern ({pattern})",
    )


def _power(value):
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V", value, re.I):
        return value[:-1]
    return f"_C_{value}"


def _force_v(value):
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:mV|V)", value, re.I):
        return value
    return f"_C_{value}"


def _limit(value, unit):
    return f"{format(float(value), '.12g')}{unit.upper()}"


def _alias(value):
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()


def _hardware_bin(value):
    if isinstance(value, bool) or not str(value).strip().isdigit():
        raise S100DcRenderError("DC.S100.BIN.INVALID", repr(value))
    return int(str(value).strip())


def _validate(plan, name, facts):
    if not isinstance(plan, (LeakagePlan, VolVohPlan, RpdRpuPlan)):
        raise S100DcRenderError("DC.S100.PLAN.INVALID", type(plan).__name__)
    if plan.typed_kind != "DC_PARAMETRIC_TEST" or plan.effective_recipe != ("DC_TEST",):
        raise S100DcRenderError("DC.S100.CONTRACT.INVALID", plan.typed_kind)
    if not plan.shared_power_session or len(plan.phases) != 2:
        raise S100DcRenderError("DC.S100.SESSION.INVALID", plan.item)
    if not _IDENTIFIER.fullmatch(str(name)):
        raise S100DcRenderError("DC.S100.NAME.INVALID", repr(name))
    if facts.platform.casefold() != "s100" or facts.cp.casefold() != plan.cp.casefold():
        raise S100DcRenderError("DC.S100.FACTS.INVALID", f"{facts.platform}/{facts.cp}")
    if not facts.pin_groups.dc_groups or not facts.pin_groups.leakage_odd or not facts.pin_groups.leakage_even:
        raise S100DcRenderError("DC.S100.PIN_GROUPS.EMPTY", plan.item)


__all__ = ["S100DcRenderError", "render_dc_parametric"]
