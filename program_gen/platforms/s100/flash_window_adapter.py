"""S100 Adapters for FLASH_WINDOW shared Recipe Modules."""

from program_gen.core.flash_window import (
    BuildMapPlan,
    NmLoopPlan,
    NmLoopPowerOff,
    NmLoopPowerOn,
    NmLoopRepeat,
    NmLoopRun,
)
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_build_map(plan: BuildMapPlan) -> RecipeModuleEmission:
    lines = [
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
    ]
    current_page = None
    for register in plan.registers:
        if register.page != current_page:
            lines.extend((
                "",
                f"\t\t////////////////////////{register.page} page address map///////////////////////////",
                "",
            ))
            current_page = register.page
        target = f"REG_{register.register.upper()}[T_SOCKET]"
        if register.description:
            lines.append(f"\t\t//{register.description}")
        lines.append(f"\t\t//Default = 0x{register.default_storage_word:08X}")
        terms = (
            f"({term.symbol}[T_SOCKET]<<{term.lsb})"
            if term.symbol is not None else f"({term.value}<<{term.lsb})"
            for term in register.terms
        )
        lines.extend((f"\t\t{target}={'+'.join(terms)};", ""))
    lines.append("\t}")
    return RecipeModuleEmission(statements=tuple(lines))


def adapt_nm_loop(plan: NmLoopPlan) -> RecipeModuleEmission:
    lines = []
    requirements = []
    for instruction in plan.instructions:
        if isinstance(instruction, NmLoopPowerOn):
            lines.append(f"\tCALL_MACRO POWER_ON(_C_{instruction.profile.upper()});")
        elif isinstance(instruction, NmLoopPowerOff):
            lines.append("\tCALL_MACRO POWER_OFF();")
        elif isinstance(instruction, NmLoopRun):
            emission = adapt_run_pattern(instruction.pattern)
            lines.extend(emission.statements)
            requirements.extend(emission.resource_requires)
        elif isinstance(instruction, NmLoopRepeat):
            lines.extend((f"\tfor(I=0;I<{instruction.count};I++)", "\t{"))
            for run in instruction.runs:
                emission = adapt_run_pattern(run.pattern)
                lines.extend("\t" + statement for statement in emission.statements)
                requirements.extend(emission.resource_requires)
            lines.append("\t}")
        else:
            raise TypeError(f"NMLOOP.INSTRUCTION.UNSUPPORTED: {instruction!r}")
    return RecipeModuleEmission(tuple(lines), tuple(requirements))


__all__ = ["adapt_build_map", "adapt_nm_loop"]
