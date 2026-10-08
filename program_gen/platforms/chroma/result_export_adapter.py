"""Chroma Adapter for the shared EXPORT Recipe Module."""

from program_gen.core.result_export import ResultExportFormat, ResultExportModulePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolProvision


def adapt_result_export(plan: ResultExportModulePlan) -> RecipeModuleEmission:
    symbol = plan.symbol
    source = f"RESULT_PIN(SOCKET, {plan.source_pin})"
    lines = ["  SOCKET_INC(FRZ_OFF)", "  {"]
    if plan.format is ResultExportFormat.RAW:
        lines.append(f"    {symbol}[SOCKET]={source};")
    elif plan.format is ResultExportFormat.BCD16_MV:
        lines.extend((
            f"    {symbol}[SOCKET]=(int)({source}*1000+0.5);",
            f"    {symbol}[SOCKET]=(({symbol}[SOCKET]/1000)%10)*4096+"
            f"(({symbol}[SOCKET]/100)%10)*256+"
            f"(({symbol}[SOCKET]/10)%10)*16+({symbol}[SOCKET]%10);",
        ))
    else:
        lines.append(f"    {symbol}[SOCKET]=(int)({source}/3.3*4096);")
    lines.append("  }")
    return RecipeModuleEmission(
        statements=tuple(lines),
        provides=(_provision(plan),),
    )


def _provision(plan: ResultExportModulePlan) -> SymbolProvision:
    return SymbolProvision(
        RenderSymbolRef("RESULT", plan.semantic_identity),
        plan.semantic_identity,
        plan.value_type,
        plan.bit_width,
        "SITE",
    )


__all__ = ["adapt_result_export"]
