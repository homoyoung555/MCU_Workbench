"""Render a typed ``PdrVerifyPlan`` into S100 PRG tester source.

Mirror of ``chroma/pdr_verify_renderer.py`` for the S100/YT5100 platform.  The
business plan is identical; only the emitted ``@@PLAN`` syntax, driver-result
judgment, and power-rail macros differ.  No global ``G`` state or filesystem
access is used.
"""

from __future__ import annotations

from program_gen.core.pdr_verify import (
    PdrMismatchRule,
    PdrVerifyPlan,
)


def render_pdr_verify_body(
    plan: PdrVerifyPlan, *, power_rails: tuple[str, ...], reject_bin: int
) -> str:
    """Return the S100 PRG ``@@PLAN`` block for one PDR_VERIFY definition."""
    if plan.typed_kind != "PDR_VERIFY":
        raise ValueError(f"plan {plan.item!r} is not a PDR_VERIFY plan")
    if plan.platform.value != "s100":
        raise ValueError(f"plan {plan.item!r} is not the S100 PDR_VERIFY profile")

    patterns = {resource.role: resource.name for resource in plan.pattern_resources}
    enter_pattern = patterns["ENTER_PDR_VERIFY"]
    status_pattern = patterns["STATUS_READ"]

    lines: list[str] = []
    lines.append(f"@@PLAN {plan.item.title()}")
    lines.append("	SITE_SEQUENCE      = OFF;")
    lines.append("	GO_THROUGH         = ON;")
    lines.append("	DISABLE_BY_MARK_NO = NULL;")
    lines.append("	S_SETUP_FILE       = c:\\set.dat;")
    lines.append(f"	REMARK             = {plan.item.title()};")
    lines.append("")
    lines.append("	int pdrVerifyflag[MAX_SITE];")
    lines.append("")
    if plan.relay not in ("", "/"):
        lines.append(
            f"	IO_CLOSE_USER_RELAY({plan.relay},CONNECT_MODE,"
            "ALL_SITE_ON,WAIT=1MS);"
        )
    lines.append(f"	CALL_MACRO POWER_ON(_C_{plan.initial_power_profile});")
    lines.append("")
    lines.append("	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);")
    lines.append("")
    lines.append(
        f"	RUN_PATTERN({enter_pattern}:START,{enter_pattern}:END,1,TS_5MHZ);"
    )
    lines.append("")

    for check in plan.status_checks:
        _force_pdr_voltage(lines, check, plan, power_rails)
        lines.append(
            f"	RUN_PATTERN({status_pattern}:START,{status_pattern}:END,1,TS_5MHZ);"
        )
        lines.append("")
        _driver_result_check(lines, check.mismatch_rule, check.driver_result_threshold)

    _summarize(lines)
    lines.append("")
    lines.append("	CALL_MACRO POWER_OFF();")
    lines.append("")
    if plan.relay not in ("", "/"):
        lines.append(
            f"	IO_CLOSE_USER_RELAY({plan.relay},DISCONNECT_MODE,"
            "ALL_SITE_ON,WAIT=1MS);"
        )
    lines.append("	CONDITION")
    lines.append("	IF_FAIL")
    lines.append(f"	REJECT_BIN = {reject_bin};")
    lines.append("@@END_PLAN")
    return "\n".join(lines) + "\n"


def _force_pdr_voltage(lines, check, plan, rails) -> None:
    voltage = _strip_profile(check.voltage_profile_identity)
    limits = plan.power_limits
    for rail in rails:
        lines.append(
            f"	LOGIC_FORCE_DPS({rail}, _C_{voltage}, "
            f"{_fmt(limits.current_range_ma)}MA, {limits.compliance_profile}, "
            f"WAIT={_fmt(limits.force_wait_ms)}MS);"
        )
    lines.append(
        f"	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_{voltage}, "
        f"{_fmt(limits.drive_low_v)}V, {_fmt(limits.drive_low_v)}V, VR1);"
    )
    lines.append(
        f"	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_{voltage}*"
        f"{_fmt(limits.compare_high_ratio)},_C_{voltage}*"
        f"{_fmt(limits.compare_low_ratio)},VR2);"
    )
    # Only the PDR_MAX stage settles with a WAIT; PDR_MIN flows straight into
    # the next status RUN_PATTERN (matching the historical writer's blank-line
    # asymmetry).
    if check.settle_ms:
        lines.append(f"	WAIT({_fmt(check.settle_ms)}MS);")
        lines.append("")


def _driver_result_check(lines, rule: PdrMismatchRule, threshold) -> None:
    op = ">" if rule is PdrMismatchRule.DRIVER_RESULT_GT_HALF else "<"
    lines.append("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)")
    lines.append("	{")
    lines.append("		pdrVerifyflag[T_SOCKET]=0;")
    lines.append(
        f"		if(Sys_DriverResult[T_SOCKET] {op} {_fmt(threshold)}) "
        f"pdrVerifyflag[T_SOCKET]=1;"
    )
    lines.append("	}")
    lines.append("")


def _summarize(lines) -> None:
    lines.append("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)")
    lines.append("	{")
    lines.append("		if(pdrVerifyflag[T_SOCKET]==1)")
    lines.append("		{")
    lines.append("			SYS_SetTestResult(FAIL,T_SOCKET);")
    lines.append("		}")
    lines.append("		else")
    lines.append("		{")
    lines.append("			SYS_SetTestResult(PASS,T_SOCKET);")
    lines.append("		}")
    lines.append("	}")


def _strip_profile(identity: str) -> str:
    return identity.rsplit(":", 1)[-1]


def _fmt(value) -> str:
    if value is None:
        return ""
    if float(value) == 0:
        return "0.0"
    if float(value) == int(value):
        return str(int(value))
    return str(value)
