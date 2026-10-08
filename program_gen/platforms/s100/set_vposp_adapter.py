"""S100 Adapter for the shared SETVPOSP Recipe Module."""

from __future__ import annotations

from program_gen.core.set_vposp import SetVpospPlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_set_vposp(plan: SetVpospPlan) -> RecipeModuleEmission:
    run = adapt_run_pattern(plan.run_pattern)
    if plan.should_run:
        return run
    if not plan.updates:
        return RecipeModuleEmission()

    grouped = {}
    for update in plan.updates:
        grouped.setdefault(update.pump, []).append(update.label)
    lines = []
    for pump, labels in grouped.items():
        lines.append(f"\tCALL_MACRO write_pat_temp_arry({pump.symbol});")
        for label in labels:
            lines.append(
                "\tLOGIC_WRITE_PATTERN_MEMORY("
                f"{label.pattern_identity}:{label.s100_start_label},"
                f"{label.pattern_identity}:{label.s100_end_label},"
                f"{plan.swd_pin},GB1,BIT_COUNT={label.bit_width},"
                "SERIAL,MSB_LSB);"
            )
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=run.resource_requires,
    )


__all__ = ["adapt_set_vposp"]
