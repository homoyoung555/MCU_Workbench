"""Chroma per-site bisection with non-rejecting numeric Datalog."""

from program_gen.core.margin_test import MarginTestPlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.platforms.chroma.vt_test_adapter import _run_block, _unique_resources
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolRequirement


def adapt_margin_test(plan: MarginTestPlan) -> RecipeModuleEmission:
    if not isinstance(plan, MarginTestPlan):
        raise TypeError("MARGIN_TEST adapter requires MarginTestPlan")
    emissions = tuple(adapt_run_pattern(run) for run in (plan.enter, plan.enter_vt, plan.read))
    start, end = f"{plan.start_voltage:.15g}", f"{plan.end_voltage:.15g}"
    lines = ["  if(VTEN_FLAG)", "  {"]
    if plan.gate is not None:
        lines.extend((f"  SOCKET_SET(B:{plan.gate.gate_symbol},FRZ_OFF)", "  {"))
    lines.extend((
        "  VOLTAGE marginStart[MAX_SITE],marginEnd[MAX_SITE],marginMid[MAX_SITE];",
        "  int marginStep;",
        f"  POWER_ON({plan.power_profile});",
        "  RELAY_ON(TP,PPMU_PDCL,2mS);",
        *_run_block(plan.enter, emissions[0]),
        *_run_block(plan.enter_vt, emissions[1]),
        "  SOCKET_INC(FRZ_OFF)",
        "  {",
        f"    marginStart[SOCKET]={start}V;marginEnd[SOCKET]={end}V;",
        "  }",
        f"  for(marginStep=0;marginStep<{plan.iterations};marginStep++)",
        "  {",
        "    SOCKET_INC(FRZ_OFF)",
        "    {",
        "      marginMid[SOCKET]=(marginStart[SOCKET]+marginEnd[SOCKET])/2;",
        "      FORCE_V_PPMU(TP,marginMid[SOCKET], ,@20uA, ,0mS);",
        "    }",
        "    WAIT(5mS);",
        *_run_block(plan.read, emissions[2], indent="    "),
        "    SOCKET_INC(FRZ_OFF)",
        "    {",
        "      if(JUDGE_RESULT_MS[SOCKET]==PASS)",
        "      {marginStart[SOCKET]=marginMid[SOCKET];}",
        "      else",
        "      {marginEnd[SOCKET]=marginMid[SOCKET];}",
        "    }",
        "  }",
        "  TEST_NUM++;",
        "  SOCKET_INC(FRZ_OFF)",
        "  {",
        "    // An unchanged boundary means all FAIL or all PASS in the eight reads.",
        f"    if(marginStart[SOCKET]=={start}V)marginMid[SOCKET]={start}V;",
        f"    else if(marginEnd[SOCKET]=={end}V)marginMid[SOCKET]={end}V;",
        "    else marginMid[SOCKET]=(marginStart[SOCKET]+marginEnd[SOCKET])/2;",
        f'    TEST_NO(TEST_NUM);DATALOG_MSG="{plan.result_label}";',
        f'    JUDGE_VARIABLE(SOCKET,marginMid[SOCKET], , ,"{plan.result_label}");',
        "    // Data collection only: do not reject on enter/read results.",
        "    PLAN_RESULT_MS[SOCKET]=PASS;",
        "  }",
        "  FORCE_V_PPMU(TP,0V, ,@20uA, ,2mS);",
        "  RELAY_OFF(TP,PPMU_PDCL,2mS);",
        "  POWER_OFF();",
    ))
    if plan.gate is not None:
        lines.append("  }")
    lines.append("  }")
    requires = () if plan.gate is None else (SymbolRequirement(
        RenderSymbolRef("ID_GATE", plan.gate.gate_semantic_identity), "BOOL", 1, "SITE"),)
    return RecipeModuleEmission(tuple(lines), _unique_resources(emissions), requires=requires)
