"""Chroma translation for the shared, position-based DAC_ADJ Module."""

from program_gen.core.dac_adjust import (
    DacAdjustModulePlan,
    DacAdjustTargetSourceKind,
)
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_dac_adjust(plan: DacAdjustModulePlan) -> RecipeModuleEmission:
    codes = ",".join(str(code) for code in plan.codes)
    lines = [f"  int dacAdjCodes[{len(plan.codes)}]={{{codes}}};"]
    lines.extend(("  SOCKET_INC(FRZ_OFF)", "  {"))
    source = plan.target_source
    if source is not None and source.kind is DacAdjustTargetSourceKind.ADDR_MAP:
        mask = (1 << source.bit_width) - 1
        lines.append(
            f"    {plan.target_symbol}[SOCKET]="
            f"({source.register_symbol}[SOCKET]>>{source.bit_lsb})&0x{mask:X};"
        )
    lines.extend([
        f"    if({plan.condition.source_symbol}[SOCKET]{plan.condition.operator}{plan.condition.threshold:g})",
        "    {", "      int dacAdjIndex=0;",
        f"      while(dacAdjCodes[dacAdjIndex]!={plan.target_symbol}[SOCKET]) dacAdjIndex++;",
        f"      dacAdjIndex+={plan.delta};",
        "      if(dacAdjIndex<0) dacAdjIndex=0;",
        f"      if(dacAdjIndex>{len(plan.codes) - 1}) dacAdjIndex={len(plan.codes) - 1};",
        f"      {plan.target_symbol}[SOCKET]=dacAdjCodes[dacAdjIndex];",
        "    }", "  }",
    ])
    return RecipeModuleEmission(statements=tuple(lines))


__all__ = ["adapt_dac_adjust"]
