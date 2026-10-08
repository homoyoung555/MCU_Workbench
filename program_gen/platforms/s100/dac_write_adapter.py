"""S100 Adapter for the shared DAC_WRITE Recipe Module."""

from program_gen.core.dac_write import DacWriteModulePlan, DacWriteSourceKind
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_dac_write(plan: DacWriteModulePlan) -> RecipeModuleEmission:
    source = plan.source.symbol
    lines = []
    if plan.source.kind is DacWriteSourceKind.ARGUMENT:
        source = "dacWriteData"
        lines.append("\tint dacWriteData[MAX_SITE];")
    if plan.source.kind is not DacWriteSourceKind.DAC_FINAL:
        lines.extend((
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
        ))
        if plan.source.kind is DacWriteSourceKind.ADDR_MAP:
            mask = ((1 << plan.source.bit_width) - 1) << plan.source.bit_lsb
            lines.append(
                f"\t\t{source}[T_SOCKET]=({plan.source.register_symbol}[T_SOCKET]&"
                f"0x{mask:04X})>>{plan.source.bit_lsb};"
            )
        else:
            lines.append(f"\t\t{source}[T_SOCKET]={plan.source.literal};")
        lines.append("\t}")
    lines.extend((
        f"\tCALL_MACRO write_pat_temp_arry({source});",
        "\tLOGIC_WRITE_PATTERN_MEMORY("
        f"{plan.target.pattern.name}:{plan.target.s100_start_label},"
        f"{plan.target.pattern.name}:{plan.target.s100_end_label},"
        f"{plan.swd_pin},GB1,BIT_COUNT={plan.target.bit_width},"
        "SERIAL,MSB_LSB);",
    ))
    run = adapt_run_pattern(plan.run_pattern)
    return RecipeModuleEmission(
        statements=(*lines, *(run.statements if plan.execute_pattern else ())),
        resource_requires=run.resource_requires,
    )


__all__ = ["adapt_dac_write"]
