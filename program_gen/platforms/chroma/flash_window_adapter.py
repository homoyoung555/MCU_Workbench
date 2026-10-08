"""Chroma Adapters for FLASH_WINDOW shared Recipe Modules."""

from program_gen.core.flash_window import (
    BuildMapPlan,
    NmLoopPlan,
    NmLoopPowerOff,
    NmLoopPowerOn,
    NmLoopRepeat,
    NmLoopRun,
)
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_build_map(plan: BuildMapPlan) -> RecipeModuleEmission:
    lines = ["  SOCKET_INC(FRZ_OFF)", "  {"]
    current_page = None
    for register in plan.registers:
        if register.page != current_page:
            lines.extend((
                "",
                f"    ////////////////////////{register.page} page address map///////////////////////////",
                "",
            ))
            current_page = register.page
        target = f"REG_{register.register.upper()}[SOCKET]"
        if register.description:
            lines.append(f"    //{register.description}")
        lines.append(f"    //Default = 0x{register.default_storage_word:08X}")
        terms = (
            f"({term.symbol}[SOCKET]<<{term.lsb})"
            if term.symbol is not None else f"({term.value}<<{term.lsb})"
            for term in register.terms
        )
        lines.extend((f"    {target}={'+'.join(terms)};", ""))
    lines.append("  }")
    return RecipeModuleEmission(statements=tuple(lines))


def adapt_nm_loop(plan: NmLoopPlan) -> RecipeModuleEmission:
    lines = []
    requirements = []
    for instruction in plan.instructions:
        if isinstance(instruction, NmLoopPowerOn):
            lines.append(f"  POWER_ON({instruction.profile.upper()});")
        elif isinstance(instruction, NmLoopPowerOff):
            lines.append("  POWER_OFF();")
        elif isinstance(instruction, NmLoopRun):
            emission = adapt_run_pattern(instruction.pattern)
            lines.extend(emission.statements)
            requirements.extend(emission.resource_requires)
        elif isinstance(instruction, NmLoopRepeat):
            lines.extend((f"  for(I=0;I<{instruction.count};I++)", "  {"))
            for run in instruction.runs:
                emission = adapt_run_pattern(run.pattern)
                lines.extend("  " + statement for statement in emission.statements)
                requirements.extend(emission.resource_requires)
            lines.append("  }")
        else:
            raise TypeError(f"NMLOOP.INSTRUCTION.UNSUPPORTED: {instruction!r}")
    return RecipeModuleEmission(tuple(lines), tuple(requirements))


__all__ = ["adapt_build_map", "adapt_nm_loop"]
