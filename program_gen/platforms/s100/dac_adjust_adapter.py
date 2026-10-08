"""S100 translation for the shared, position-based DAC_ADJ Module."""

from program_gen.core.dac_adjust import (
    DacAdjustModulePlan,
    DacAdjustTargetSourceKind,
)
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_dac_adjust(plan: DacAdjustModulePlan) -> RecipeModuleEmission:
    codes = ",".join(str(code) for code in plan.codes)
    lines = [
        f"\tint dacAdjCodes[{len(plan.codes)}]={{{codes}}};",
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
    ]
    source = plan.target_source
    if source is not None and source.kind is DacAdjustTargetSourceKind.ADDR_MAP:
        mask = (1 << source.bit_width) - 1
        lines.append(
            f"\t\t{plan.target_symbol}[T_SOCKET]="
            f"({source.register_symbol}[T_SOCKET]>>{source.bit_lsb})&0x{mask:X};"
        )
    lines.extend([
        f"\t\tif({plan.condition.source_symbol}[T_SOCKET]{plan.condition.operator}{plan.condition.threshold:g})",
        "\t\t{", "\t\t\tint dacAdjIndex=0;",
        f"\t\t\twhile(dacAdjCodes[dacAdjIndex]!={plan.target_symbol}[T_SOCKET]) dacAdjIndex++;",
        f"\t\t\tdacAdjIndex+={plan.delta};",
        "\t\t\tif(dacAdjIndex<0) dacAdjIndex=0;",
        f"\t\t\tif(dacAdjIndex>{len(plan.codes) - 1}) dacAdjIndex={len(plan.codes) - 1};",
        f"\t\t\t{plan.target_symbol}[T_SOCKET]=dacAdjCodes[dacAdjIndex];",
        "\t\t}", "\t}",
    ])
    return RecipeModuleEmission(statements=tuple(lines))


__all__ = ["adapt_dac_adjust"]
