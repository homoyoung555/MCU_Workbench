"""Chroma READID/CHECKID translation of compiler-owned ID bindings."""

from program_gen.core.id_module import IdModulePlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolProvision


def adapt_read_id(plan: IdModulePlan) -> RecipeModuleEmission:
    plan.require_module("READID")
    return _adapt_id(plan, read=True)


def adapt_check_id(plan: IdModulePlan) -> RecipeModuleEmission:
    plan.require_module("CHECKID")
    return _adapt_id(plan, read=False)


def _adapt_id(plan: IdModulePlan, *, read: bool) -> RecipeModuleEmission:
    enter = adapt_run_pattern(plan.enter_fbist_mode)
    check = adapt_run_pattern(plan.check_pattern)
    lines = [f"  POWER_ON({plan.power_profile});", *enter.statements, *check.statements]
    provides = ()
    if read:
        lines.extend((
            "  SOCKET_INC(FRZ_OFF)",
            "  {",
            f"    {plan.gate_symbol}[SOCKET]=(PLAN_RESULT_MS[SOCKET]==FAIL)?1:0;",
            "    PLAN_RESULT_MS[SOCKET]=PASS;",
            "  }",
        ))
        provides = (SymbolProvision(
            RenderSymbolRef("ID_GATE", plan.gate_semantic_identity),
            plan.gate_symbol, "BOOL", 1, "SITE",
        ),)
    lines.append("  POWER_OFF();")
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=tuple(dict.fromkeys((*enter.resource_requires, *check.resource_requires))),
        provides=provides,
    )


__all__ = ["adapt_read_id", "adapt_check_id"]
