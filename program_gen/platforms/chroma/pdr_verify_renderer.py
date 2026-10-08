"""Render a typed ``PdrVerifyPlan`` into Chroma PLN tester source.

This is a platform adapter at the native-renderer seam: it maps the immutable
business plan onto Chroma's C-like PLN function block.  It never reads global
``G`` state, workbook cells, or the filesystem; ``power_rails`` and
``test_number`` are supplied by the caller so the platform can keep its own
pin/schedule concerns out of the business plan.
"""

from __future__ import annotations

from program_gen.core.pdr_verify import (
    PdrMismatchRule,
    PdrVerifyPlan,
)
from program_gen.platforms.chroma.pattern_emitter import emit_pattern_run


def render_pdr_verify_body(
    plan: PdrVerifyPlan, *, power_rails: tuple[str, ...], test_number: int
) -> str:
    """Return the Chroma PLN function block for one PDR_VERIFY definition."""
    if plan.typed_kind != "PDR_VERIFY":
        raise ValueError(f"plan {plan.item!r} is not a PDR_VERIFY plan")
    if plan.platform.value != "chroma":
        raise ValueError(f"plan {plan.item!r} is not the Chroma PDR_VERIFY profile")

    patterns = {resource.role: resource.name for resource in plan.pattern_resources}
    rails = "+".join(power_rails)
    lines: list[str] = []
    lines.append(f"{plan.item.title()}()")
    lines.append("{")
    lines.append(f"  TEST_NUM={test_number};")
    lines.append(f'  TEST_NO( TEST_NUM);DATALOG_MSG="{plan.item.lower()}";')
    lines.append("")
    lines.append("  int pdrVerifyflag[MAX_SITE];")
    lines.append("")
    if plan.relay not in ("", "/"):
        lines.append(f"  SET_CBIT({plan.relay}, ON, 5mS);")
    lines.append(f"  POWER_ON({plan.initial_power_profile});")
    lines.append("")

    lines.extend(emit_pattern_run(patterns["ENTER_FBIST"]))
    lines.extend(emit_pattern_run(patterns["ENTER_PDR_VERIFY"]))

    for index, check in enumerate(plan.status_checks):
        _force_pdr_voltage(lines, check, plan, rails)
        lines.extend(emit_pattern_run(patterns["STATUS_READ"]))
        _flag_check(lines, check.mismatch_rule, reset=index == 0)

    _summarize(lines)
    lines.extend(emit_pattern_run(patterns["EXIT_FBIST"]))
    lines.append("  POWER_OFF();")
    lines.append("  //POWER_DOWN_FAIL_SITE_X(MODE_B);")
    lines.append("")
    if plan.relay not in ("", "/"):
        lines.append(f"  SET_CBIT({plan.relay}, OFF, 5mS);")
    lines.append("}")
    return "\n".join(lines)


def _force_pdr_voltage(lines, check, plan, rails) -> None:
    level = _strip_profile(check.level_profile_identity or "")
    voltage = _strip_profile(check.voltage_profile_identity)
    limits = plan.power_limits
    lines.append(f"  LEVELS({level}, {_fmt(limits.level_settle_ms)}mS);")
    lines.append(
        f"  FORCE_V_MLDPS({rails}, {voltage},{_force_args(limits)});"
    )
    lines.append(f"  WAIT({_fmt(check.settle_ms)}mS);")
    lines.append("")


def _flag_check(lines, rule: PdrMismatchRule, *, reset: bool) -> None:
    cond = "FAIL" if rule is PdrMismatchRule.TESTER_FAIL else "PASS"
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    if reset:
        lines.append("    pdrVerifyflag[SOCKET]=0;")
    lines.append(f"    if(JUDGE_RESULT_MS[SOCKET]=={cond}) pdrVerifyflag[SOCKET]=1;")
    lines.append("  }")
    lines.append("")


def _summarize(lines) -> None:
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    lines.append("    if(pdrVerifyflag[SOCKET]==1)")
    lines.append("    {")
    lines.append("      PLAN_RESULT_MS[SOCKET]=FAIL;")
    lines.append("    }")
    lines.append("    else")
    lines.append("    {")
    lines.append("      PLAN_RESULT_MS[SOCKET]=PASS;")
    lines.append("    }")
    lines.append("  }")
    lines.append("")


def _force_args(limits) -> str:
    compliance = limits.compliance_profile or "NORM"
    return (
        f"@{_fmt(limits.voltage_range_v)}V,"
        f"@{_fmt(limits.current_range_ma)}mA,"
        f"{_fmt(limits.current_limit_ma)}mA,"
        f"{compliance},ON,{_fmt(limits.force_wait_ms)}mS"
    )


def _strip_profile(identity: str) -> str:
    return identity.rsplit(":", 1)[-1]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
