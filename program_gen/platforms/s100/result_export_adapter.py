"""S100 Adapter for the shared EXPORT Recipe Module."""

from program_gen.core.result_export import ResultExportFormat, ResultExportModulePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import RenderSymbolRef, SymbolProvision


def adapt_result_export(plan: ResultExportModulePlan) -> RecipeModuleEmission:
    symbol = plan.symbol
    source = "GB[5+T_SOCKET*64]"
    lines = [
        f"\tC_ASSIGN(GB6,{plan.source_pin});",
        "",
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
    ]
    if plan.format is ResultExportFormat.RAW:
        lines.append(f"\t\t{symbol}[T_SOCKET]={source};")
    elif plan.format is ResultExportFormat.BCD16_MV:
        lines.extend((
            f"\t\t{symbol}[T_SOCKET]=(int)({source}*1000+0.5);",
            f"\t\t{symbol}[T_SOCKET]=(({symbol}[T_SOCKET]/1000)%10)*4096+"
            f"(({symbol}[T_SOCKET]/100)%10)*256+"
            f"(({symbol}[T_SOCKET]/10)%10)*16+({symbol}[T_SOCKET]%10);",
        ))
    else:
        lines.append(f"\t\t{symbol}[T_SOCKET]=(int)({source}/3.3*4096);")
    lines.append("\t}")
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
