"""S100 Adapter for the global RUN Pattern Module."""

from __future__ import annotations

from program_gen.core.run_pattern import RunPatternPlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_run_pattern(plan: RunPatternPlan) -> RecipeModuleEmission:
    name = plan.pattern.name
    return RecipeModuleEmission(
        statements=(
            f"\tRUN_PATTERN({name}:{plan.span.start_label},"
            f"{name}:{plan.span.end_label},1,"
            f"{plan.timing_profile});",
        ),
        resource_requires=(ResourceRequirement(
            logical_identity=plan.pattern.logical_identity,
            relative_path=f"{name}.sd",
            spec_identity=f"v13.pattern/1:s100:{name}",
            purpose="RUN pattern",
        ),),
    )


__all__ = ["adapt_run_pattern"]
