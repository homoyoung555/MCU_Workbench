"""S100 per-site bisection; scan comparisons and numeric logs never reject."""

from program_gen.core.margin_test import MarginTestPlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.platforms.s100.vt_test_adapter import _gate_open, _gate_close, _ignore_fail, _unique_resources
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolRequirement


def adapt_margin_test(plan: MarginTestPlan) -> RecipeModuleEmission:
    if not isinstance(plan, MarginTestPlan):
        raise TypeError("MARGIN_TEST adapter requires MarginTestPlan")
    emissions = tuple(adapt_run_pattern(run) for run in (plan.enter, plan.enter_vt, plan.read))
    start, end = f"{plan.start_voltage:.15g}", f"{plan.end_voltage:.15g}"
    lines = ["\tif(VTEN_FLAG)", "\t{"]
    if plan.gate is not None:
        lines.extend(_gate_open(plan.gate.gate_symbol))
    lines.extend((
        "\tint marginSites[MAX_SITE];",
        "\tdouble _C_marginVoltage;",
        "\tdouble marginStart[MAX_SITE],marginEnd[MAX_SITE],marginMid[MAX_SITE];",
        "\tint marginSite,marginOther,marginStep;",
        "\tfor(marginSite=0;marginSite<Sys_TEST_DIE;marginSite++)",
        "\t{",
        "\t\tmarginSites[marginSite]=Sys_ActiveSite[marginSite];",
        "\t\tif(!marginSites[marginSite])continue;",
        f"\t\tmarginStart[marginSite]={start};marginEnd[marginSite]={end};",
        "\t}",
        f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});",
        *_ignore_fail(emissions[0].statements),
        *_ignore_fail(emissions[1].statements),
        f"\tfor(marginStep=0;marginStep<{plan.iterations};marginStep++)",
        "\t{",
        "\t\tfor(marginSite=0;marginSite<Sys_TEST_DIE;marginSite++)",
        "\t\t{",
        "\t\t\tif(!marginSites[marginSite])continue;",
        "\t\t\tmarginMid[marginSite]=(marginStart[marginSite]+marginEnd[marginSite])/2;",
        "\t\t\tfor(marginOther=0;marginOther<Sys_TEST_DIE;marginOther++)",
        "\t\t\t\tSys_ActiveSite[marginOther]=(marginOther==marginSite);",
        # S100 FV accepts one scalar. I3=32uA is the smallest range covering 20uA.
        "\t\t\t_C_marginVoltage=marginMid[marginSite];",
        "\t\t\tLOGIC_PPMU_FV(TP, _C_marginVoltage, E2, I3);",
        "\t\t}",
        "\t\tfor(marginSite=0;marginSite<Sys_TEST_DIE;marginSite++)",
        "\t\t\tSys_ActiveSite[marginSite]=marginSites[marginSite];",
        "\t\tWAIT(5MS);",
        *_ignore_fail(emissions[2].statements),
        "\t\tfor(marginSite=0;marginSite<Sys_TEST_DIE;marginSite++)",
        "\t\t{",
        "\t\t\tif(!marginSites[marginSite])continue;",
        "\t\t\tif(Sys_DriverResult[marginSite]>=0.5)",
        "\t\t\t{marginStart[marginSite]=marginMid[marginSite];}",
        "\t\t\telse",
        "\t\t\t{marginEnd[marginSite]=marginMid[marginSite];}",
        "\t\t}",
        "\t}",
        "\tfor(marginSite=0;marginSite<Sys_TEST_DIE;marginSite++)",
        "\t{",
        "\t\tif(!marginSites[marginSite])continue;",
        "\t\t// An unchanged boundary means all FAIL or all PASS in the eight reads.",
        f"\t\tif(marginStart[marginSite]=={start})marginMid[marginSite]={start};",
        f"\t\telse if(marginEnd[marginSite]=={end})marginMid[marginSite]={end};",
        "\t\telse marginMid[marginSite]=(marginStart[marginSite]+marginEnd[marginSite])/2;",
        "\t\tGB[7+marginSite*64]=marginMid[marginSite];",
        "\t}",
        f"\tC_COMPARE(GB8, LOG_ALIAS={plan.result_label}, LOG_UNIT=V, IGNORE_FAIL);",
        "\tLOGIC_PPMU_FV(TP, 0V, E2, I3);",
        "\tWAIT(2MS);",
        "\tLOGIC_DISCONNECT_PPMU_PIN(TP);",
        "\tCALL_MACRO POWER_OFF();",
    ))
    if plan.gate is not None:
        lines.extend(_gate_close())
    lines.append("\t}")
    requires = () if plan.gate is None else (SymbolRequirement(
        RenderSymbolRef("ID_GATE", plan.gate.gate_semantic_identity), "BOOL", 1, "SITE"),)
    return RecipeModuleEmission(tuple(lines), _unique_resources(emissions), requires=requires)
