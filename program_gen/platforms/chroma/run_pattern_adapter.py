"""Chroma Adapter for the global RUN Pattern Module."""

from __future__ import annotations

from program_gen.core.run_pattern import RunPatternPlan
from program_gen.platforms.chroma.pattern_emitter import emit_pattern_run
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_run_pattern(plan: RunPatternPlan) -> RecipeModuleEmission:
    name = plan.pattern.name
    standard = emit_pattern_run(name)
    return RecipeModuleEmission(
        statements=(
            *standard[:2],
            f"  JUDGE_PAT({_label_ref(name, plan.span.start_label)},"
            f"{_label_ref(name, plan.span.end_label)});",
            standard[-1],
        ),
        resource_requires=(ResourceRequirement(
            logical_identity=plan.pattern.logical_identity,
            relative_path=f"pat/{name}.pat",
            spec_identity=f"v13.pattern/1:chroma:{name}",
            purpose="RUN pattern",
        ),),
    )


def _label_ref(name: str, label: str) -> str:
    if label == "START":
        return name
    if label == "END":
        return f"__{name}"
    return f"{name}:{label}"


__all__ = ["adapt_run_pattern"]
