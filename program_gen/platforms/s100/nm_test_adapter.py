"""S100 NM_TEST emission from a detached upstream plan."""

from program_gen.core.flash_compare_plan import Operation
from program_gen.core.nm_test import NmTestMode, NmTestPlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_nm_test(plan: NmTestPlan) -> RecipeModuleEmission:
    lines = [f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});"]
    requirements = []
    for run in (plan.enter, plan.vposp):
        emission = adapt_run_pattern(run)
        lines.extend(emission.statements)
        requirements.extend(emission.resource_requires)
    for run in plan.runs:
        emission = adapt_run_pattern(run.pattern)
        commented = plan.mode is NmTestMode.REPAIR and run.operation is Operation.READ
        lines.extend("//" + line if commented else line for line in emission.statements)
        requirements.extend(emission.resource_requires)
    lines.append("\tCALL_MACRO POWER_OFF();")
    return RecipeModuleEmission(tuple(lines), tuple(requirements))
