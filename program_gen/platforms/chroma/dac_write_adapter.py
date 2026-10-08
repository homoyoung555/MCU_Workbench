"""Chroma Adapter for the shared DAC_WRITE Recipe Module."""

from program_gen.core.dac_write import DacWriteModulePlan, DacWriteSourceKind
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_dac_write(plan: DacWriteModulePlan) -> RecipeModuleEmission:
    source = plan.source.symbol
    lines = []
    if plan.source.kind is DacWriteSourceKind.ARGUMENT:
        source = "dacWriteData"
        lines.append("  int dacWriteData[MAX_SITE];")
    lines.extend(("  SOCKET_INC(FRZ_OFF)", "  {"))
    if plan.source.kind is DacWriteSourceKind.ADDR_MAP:
        mask = ((1 << plan.source.bit_width) - 1) << plan.source.bit_lsb
        lines.append(
            f"    {source}[SOCKET]=({plan.source.register_symbol}[SOCKET]&"
            f"0x{mask:04X})>>{plan.source.bit_lsb};"
        )
    elif plan.source.kind is DacWriteSourceKind.ARGUMENT:
        lines.append(f"    {source}[SOCKET]={plan.source.literal};")
    lines.extend((
        f"    convert_to_string({source}[SOCKET],{plan.target.bit_width},"
        "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
        f"    for(I=0;I<{plan.target.bit_width};I++)",
        "    {",
        f"      WRITE_PAT_MEM(SOCKET,{plan.swd_pin},"
        f"{plan.target.pattern.name}:{plan.target.chroma_start_label}+I,,"
        "BUFF_W_P[I]);",
        "    }",
        "  }",
    ))
    run = adapt_run_pattern(plan.run_pattern)
    return RecipeModuleEmission(
        statements=(*lines, *(run.statements if plan.execute_pattern else ())),
        resource_requires=run.resource_requires,
    )


__all__ = ["adapt_dac_write"]
