"""S100 emission for the ordinary VT_TEST Recipe Module."""

from __future__ import annotations

from program_gen.core.vt_test import VtTestPlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolRequirement


def adapt_vt_test(plan: VtTestPlan) -> RecipeModuleEmission:
    """Translate one compiler-owned ordinary VT plan to S100 statements."""
    if not isinstance(plan, VtTestPlan):
        raise TypeError("VT_TEST adapter requires VtTestPlan")

    runs = (plan.enter, plan.enter_vt, plan.read)
    emissions = tuple(adapt_run_pattern(run) for run in runs)
    lines: list[str] = []
    if plan.gate is not None:
        lines.extend(_gate_open(plan.gate.gate_symbol))
    lines.append(f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});")
    lines.extend(emissions[0].statements)
    lines.extend(emissions[1].statements)
    lines.extend((
        f"\tLOGIC_PPMU_FV(TP, {_voltage(plan.voltage)}V, E2, I1);",
        "\tWAIT(2MS);",
    ))
    if plan.retry_failed:
        lines.extend(_retry_read(emissions[2]))
    else:
        lines.extend(emissions[2].statements)
    lines.extend((
        # S100 I1=2uA; I5=512uA is its smallest range covering 200uA cleanup.
        "\tLOGIC_PPMU_FV(TP, 0V, E2, I5);",
        "\tWAIT(2MS);",
        "\tLOGIC_DISCONNECT_PPMU_PIN(TP);",
        "\tCALL_MACRO POWER_OFF();",
    ))
    if plan.gate is not None:
        lines.extend(_gate_close())

    requires = ()
    if plan.gate is not None:
        requires = (SymbolRequirement(
            RenderSymbolRef("ID_GATE", plan.gate.gate_semantic_identity),
            "BOOL", 1, "SITE",
        ),)
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=_unique_resources(emissions),
        requires=requires,
    )


def _retry_read(emission):
    read = _ignore_fail(emission.statements)
    run = tuple(emission.statements)
    return (
        "\t{",
        "\t\tint vtActiveSites[MAX_SITE],vtReadFailed[MAX_SITE],vtRetryPending=0;",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tvtActiveSites[T_SOCKET]=Sys_ActiveSite[T_SOCKET];",
        "\t\t}",
        *read,
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tvtReadFailed[T_SOCKET]=vtActiveSites[T_SOCKET] && Sys_DriverResult[T_SOCKET]<0.5;",
        "\t\t\tSys_ActiveSite[T_SOCKET]=vtReadFailed[T_SOCKET];",
        "\t\t\tvtRetryPending=vtRetryPending || vtReadFailed[T_SOCKET];",
        "\t\t}",
        "\t\tif(vtRetryPending==1)",
        "\t\t{",
        *(f"\t\t\t{line.lstrip()}" for line in run),
        "\t\t}",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tSys_ActiveSite[T_SOCKET]=vtActiveSites[T_SOCKET];",
        "\t\t}",
        "\t}",
    )


def _ignore_fail(statements):
    return tuple(
        statement.removesuffix(");") + ", IGNORE_FAIL);"
        for statement in statements
    )


def _gate_open(symbol):
    return (
        "\t{",
        "\t\tint vtPreviousSites[MAX_SITE],vtPending=0;",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tvtPreviousSites[T_SOCKET]=Sys_ActiveSite[T_SOCKET];",
        f"\t\t\tSys_ActiveSite[T_SOCKET]=vtPreviousSites[T_SOCKET] && {symbol}[T_SOCKET];",
        "\t\t\tvtPending=vtPending || Sys_ActiveSite[T_SOCKET];",
        "\t\t}",
        "\t\tif(vtPending==1)",
        "\t\t{",
    )


def _gate_close():
    return (
        "\t\t}",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t\tSys_ActiveSite[T_SOCKET]=vtPreviousSites[T_SOCKET];",
        "\t}",
    )


def _unique_resources(emissions):
    selected = {}
    for emission in emissions:
        for requirement in emission.resource_requires:
            selected.setdefault(requirement.logical_identity, requirement)
    return tuple(selected.values())


def _voltage(value: float) -> str:
    return f"{float(value):.15g}"


__all__ = ["adapt_vt_test"]
