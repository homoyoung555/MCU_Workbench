"""Chroma Adapter for the shared native PGMOTP Recipe Module."""

from program_gen.core.otp_program import PgmOtpModulePlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_pgm_otp(plan: PgmOtpModulePlan) -> RecipeModuleEmission:
    uid = next(
        (operation for operation in plan.page_program.page_operations if "RE_ERASE" in operation.actions),
        None,
    )
    initial = (
        adapt_run_pattern(plan.enter_fbist_mode),
        adapt_run_pattern(plan.set_all_final_vposp),
        *(
            adapt_run_pattern(step.run)
            for operation in plan.page_program.page_operations
            for step in operation.steps
            if step.action != "RE_ERASE"
        ),
    )
    lines = ["  {", "  LUINT shift_site;"] if uid else []
    lines.append(f"  POWER_ON({plan.power_profile});")
    lines.extend(line for emission in initial[:2] for line in emission.statements)
    for operation in plan.page_program.page_operations:
        for step in operation.steps:
            if step.action == "RE_ERASE":
                continue
            lines.extend(adapt_run_pattern(step.run).statements)
            if operation is uid and step.action == "READ_CHECK":
                lines.extend((
                    "  SOCKET_INC(FRZ_OFF)",
                    "  {",
                    "    shift_site[SOCKET]=(JUDGE_RESULT_MS[SOCKET]==FAIL)?1:0;",
                    "  }",
                ))
    lines.append("  POWER_OFF();")

    cleanup = ()
    if uid is not None:
        re_erase = next(step for step in uid.steps if step.action == "RE_ERASE")
        cleanup = (
            adapt_run_pattern(plan.enter_fbist_mode),
            adapt_run_pattern(plan.set_all_final_vposp),
            adapt_run_pattern(re_erase.run),
        )
        lines.extend((
            "  // Re-erase failed UID sites only",
            "  SOCKET_SET(B:shift_site,FRZ_OFF)",
            "  {",
            f"    POWER_ON({plan.power_profile});",
            *("    " + line for emission in cleanup for line in emission.statements),
            "    POWER_OFF();",
            "  }",
            "  }",
        ))
    return RecipeModuleEmission(
        tuple(lines),
        _unique_resources((*initial, *cleanup)),
    )


def _unique_resources(emissions):
    selected = {}
    for emission in emissions:
        for requirement in emission.resource_requires:
            selected.setdefault(requirement.logical_identity, requirement)
    return tuple(selected.values())


__all__ = ["adapt_pgm_otp"]
