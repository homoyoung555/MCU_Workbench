"""Chroma emission for the ordinary VT_TEST Recipe Module."""

from __future__ import annotations

from program_gen.core.vt_test import VtTestPlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolRequirement


def adapt_vt_test(plan: VtTestPlan) -> RecipeModuleEmission:
    """Translate one compiler-owned ordinary VT plan to Chroma statements."""
    if not isinstance(plan, VtTestPlan):
        raise TypeError("VT_TEST adapter requires VtTestPlan")

    runs = (plan.enter, plan.enter_vt, plan.read)
    emissions = tuple(adapt_run_pattern(run) for run in runs)
    lines: list[str] = []
    if plan.gate is not None:
        lines.extend((f"  SOCKET_SET(B:{plan.gate.gate_symbol},FRZ_OFF)", "  {"))
    lines.extend((
        f"  POWER_ON({plan.power_profile});",
        "  RELAY_ON(TP,PPMU_PDCL,2mS);",
    ))
    lines.extend(_run_block(plan.enter, emissions[0]))
    lines.extend(_run_block(plan.enter_vt, emissions[1]))
    lines.append(f"  FORCE_V_PPMU(TP, {_voltage(plan.voltage)}V, ,@2uA, , 2mS);")
    if plan.retry_failed:
        lines.append("  BACKUP_PLAN_RESULT();")
    lines.extend(_run_block(plan.read, emissions[2]))
    if plan.retry_failed:
        lines.extend((
            "  FAIL_REJUDGE(1,FRZ_OFF)",
            "  {",
            *(_run_block(plan.read, emissions[2], indent="    ")),
            "  }",
        ))
    lines.extend((
        "  FORCE_V_PPMU(TP,0V, ,@200uA, , 2mS);",
        "  RELAY_OFF(TP,PPMU_PDCL,2mS);",
        "  POWER_OFF();",
    ))
    if plan.gate is not None:
        lines.append("  }")

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


def _run_block(plan, emission, *, indent="  "):
    return tuple(
        f"{indent}{statement.lstrip()}"
        for statement in emission.statements
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
