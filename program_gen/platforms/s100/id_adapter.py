"""S100 READID/CHECKID translation of compiler-owned ID bindings."""

from program_gen.core.id_module import IdModulePlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
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
    check_lines = check.statements
    if read:
        check_lines = tuple(line.removesuffix(");") + ", IGNORE_FAIL);" for line in check_lines)
    lines = [f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});", *enter.statements, *check_lines]
    provides = ()
    if read:
        lines.extend((
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
            f"\t\t{plan.gate_symbol}[T_SOCKET]=(Sys_DriverResult[T_SOCKET]<0.5)?1:0;",
            "\t}",
        ))
        provides = (SymbolProvision(
            RenderSymbolRef("ID_GATE", plan.gate_semantic_identity),
            plan.gate_symbol, "BOOL", 1, "SITE",
        ),)
    lines.append("\tCALL_MACRO POWER_OFF();")
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=tuple(dict.fromkeys((*enter.resource_requires, *check.resource_requires))),
        provides=provides,
    )


__all__ = ["adapt_read_id", "adapt_check_id"]
