"""Chroma Adapter for the shared SETVPOSP Recipe Module."""

from __future__ import annotations

from program_gen.core.set_vposp import SetVpospPlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
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
    lines = ["  SOCKET_INC(FRZ_OFF)", "  {"]
    for pump, labels in grouped.items():
        labels_by_width = {}
        for label in labels:
            labels_by_width.setdefault(label.bit_width, []).append(label)
        for width, width_labels in labels_by_width.items():
            lines.append(
                f"    convert_to_string({pump.symbol}[SOCKET],{width},"
                "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);"
            )
            for label in width_labels:
                lines.extend((
                    f"    for(I=0;I<{label.bit_width};I++)",
                    "    {",
                    f"      WRITE_PAT_MEM(SOCKET,{plan.swd_pin},"
                    f"{label.pattern_identity}:{label.chroma_start_label}+I,,"
                    "BUFF_W_P[I]);",
                    "    }",
                ))
    lines.append("  }")
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=run.resource_requires,
    )


__all__ = ["adapt_set_vposp"]
