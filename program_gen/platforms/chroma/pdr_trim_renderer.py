"""Render a typed ``DedicatedTrimPlan`` (PDR_TRIM) into Chroma PLN source.

PDR_Trim is a status-transition search, not a target-driven trim: it walks a
fixed 16-entry DAC array at PDR_TAR voltage, records the first passing DAC into
``PDR_DAC_FINAL``, then verifies the reset at PDR_MIN.  This renderer mirrors
the legacy ``trim_item_write`` PDR branch byte-for-byte.
"""

from __future__ import annotations

from program_gen.core.dedicated_trim import DedicatedTrimPlan


def render_pdr_trim_body(
    plan: DedicatedTrimPlan,
    *,
    power_rails: str,
) -> str:
    """Return the Chroma PLN function block for one PDR_TRIM definition."""
    if plan.typed_kind != "PDR_TRIM":
        raise ValueError(f"plan {plan.item!r} is not a PDR_TRIM plan")

    lines: list[str] = []
    lines.append(f"{plan.item.title()}()")
    lines.append("{")
    lines.append(f"  TEST_NUM={plan.test_number};")
    lines.append(f'  TEST_NO(TEST_NUM);DATALOG_MSG="{plan.item.lower()}";')
    lines.append("")
    lines.append("  int trimDac[MAX_SITE],pdrPassflag[MAX_SITE];")
    lines.append("")
    codes = ",".join(str(code) for code in plan.search_codes)
    lines.append(f"  int dacArray[16]={{{codes}}};")
    lines.append("")
    lines.append("  int cyc=0;")
    lines.append(f"  int endCyc={plan.dac_bits};")
    lines.append("  char cycMsg[48];")
    lines.append("")
    lines.append("  //initial")
    lines.append("  for(I=0;I<MAX_SITE;I++)")
    lines.append("  {")
    lines.append("    trimDac[I]=8;")
    lines.append("    pdrPassflag[I]=0;")
    lines.append("  }")
    lines.append("")
    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, ON, 5mS);")
    lines.append(f"  POWER_ON({plan.initial_vcc});")
    lines.append("")
    _pattern_step(lines, "enter_fbist_mode")
    _pattern_step(lines, "set_all_final_vposp")
    lines.append("  set_pdr_trim_data(trimDac);")
    lines.append("")
    lines.append("  LEVELS(PDR_TAR_LVL, 3mS);")
    lines.append(
        f"  FORCE_V_MLDPS({power_rails}, VCC_PDR_TAR,@6V,@500mA,200mA,NORM,ON,2mS);"
    )
    lines.append("  WAIT(10mS);")
    lines.append("")
    # status-transition search loop
    lines.append("  for(cyc=0;cyc<16;cyc++)")
    lines.append("  {")
    lines.append('    sprintf(cycMsg,"pdr_trim_index_%d",cyc);')
    lines.append("    SOCKET_INC(FRZ_OFF)")
    lines.append("    {")
    lines.append("      trimDac[SOCKET]=dacArray[cyc];")
    lines.append("    }")
    lines.append("")
    lines.append("    set_pdr_trim_data(trimDac);")
    lines.append("")
    lines.append("    TEST_NUM++;")
    lines.append("    TEST_NO(TEST_NUM); DATALOG_MSG=cycMsg;")
    lines.append("    JUDGE_PAT(read_status_mode,__read_status_mode);")
    lines.append("")
    lines.append("    SOCKET_INC(FRZ_OFF)")
    lines.append("    {")
    lines.append("      if(PLAN_RESULT_MS[SOCKET]==PASS)")
    lines.append("      {")
    lines.append("        PDR_DAC_FINAL[SOCKET]=trimDac[SOCKET];")
    lines.append("      }")
    lines.append("      else")
    lines.append("      {")
    lines.append("        if(trimDac[SOCKET]==8)")
    lines.append("        {")
    lines.append("          PDR_DAC_FINAL[SOCKET]=8;")
    lines.append("          pdrPassflag[SOCKET]=1;")
    lines.append("        }")
    lines.append("      }")
    lines.append("      PLAN_RESULT_MS[SOCKET]=PASS;")
    lines.append("    }")
    lines.append("  }")
    lines.append("")
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    lines.append(
        '    JUDGE_VARIABLE ( SOCKET, PDR_DAC_FINAL[SOCKET],    0,   15, "Pdr_DAC_Final");'
    )
    lines.append("  }")
    lines.append("")
    _pattern_step(lines, "exit_fbist_mode")
    lines.append("  POWER_OFF();")
    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, OFF, 5mS);")
    # second phase: verify reset at PDR_MIN
    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, ON, 5mS);")
    lines.append(f"  POWER_ON({plan.initial_vcc});")
    lines.append("")
    _pattern_step(lines, "enter_fbist_mode")
    _pattern_step(lines, "set_all_final_vposp")
    lines.append("  set_pdr_trim_data(PDR_DAC_FINAL);")
    lines.append("")
    lines.append("  LEVELS(PDR_MIN_LVL, 3mS);")
    lines.append(
        f"  FORCE_V_MLDPS({power_rails}, VCC_PDR_MIN,@6V,@500mA,200mA,NORM,ON,2mS);"
    )
    lines.append("  WAIT(10mS);")
    lines.append("")
    lines.append("  TEST_NUM++;")
    lines.append("  TEST_NO(TEST_NUM); DATALOG_MSG=cycMsg;")
    lines.append("  JUDGE_PAT(read_status_mode,__read_status_mode);")
    lines.append("")
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    lines.append("    if(JUDGE_RESULT_MS[SOCKET]==FAIL)")
    lines.append("    {")
    lines.append("      PLAN_RESULT_MS[SOCKET]=PASS;")
    lines.append("    }")
    lines.append("    else")
    lines.append("    {")
    lines.append("      PLAN_RESULT_MS[SOCKET]=FAIL;")
    lines.append("    }")
    lines.append("")
    lines.append("    if(pdrPassflag[SOCKET]==1)PLAN_RESULT_MS[SOCKET]=FAIL;")
    lines.append("")
    lines.append("  }")
    lines.append("")
    _pattern_step(lines, "exit_fbist_mode")
    lines.append("  POWER_OFF();")
    lines.append("  //POWER_DOWN_FAIL_SITE_X(MODE_B);")
    lines.append("")
    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, OFF, 5mS);")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _pattern_step(lines: list[str], name: str) -> None:
    lines.append("  TEST_NUM++;")
    lines.append(f'  TEST_NO(TEST_NUM); DATALOG_MSG="{name}";')
    lines.append(f"  JUDGE_PAT({name},__{name});")
    lines.append("")
