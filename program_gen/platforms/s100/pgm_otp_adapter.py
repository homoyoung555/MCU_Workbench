"""S100 Adapter for the shared native PGMOTP Recipe Module."""

from program_gen.core.otp_program import PgmOtpModulePlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
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
    lines = []
    if uid:
        lines.extend((
            "\t{",
            "\tint uidActiveSites[MAX_SITE],uidReadFailed[MAX_SITE];",
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            "\t\tuidActiveSites[T_SOCKET]=Sys_ActiveSite[T_SOCKET];",
            "\t\tuidReadFailed[T_SOCKET]=0;",
            "\t}",
        ))
    lines.append(f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});")
    lines.extend(line for emission in initial[:2] for line in emission.statements)
    for operation in plan.page_program.page_operations:
        for step in operation.steps:
            if step.action == "RE_ERASE":
                continue
            lines.extend(adapt_run_pattern(step.run).statements)
            if operation is uid and step.action == "READ_CHECK":
                lines.extend((
                    "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
                    "\t{",
                    "\t\tuidReadFailed[T_SOCKET]=uidActiveSites[T_SOCKET] && Sys_DriverResult[T_SOCKET]<0.5;",
                    "\t}",
                ))
    lines.append("\tCALL_MACRO POWER_OFF();")

    cleanup = ()
    if uid is not None:
        re_erase = next(step for step in uid.steps if step.action == "RE_ERASE")
        cleanup = (
            adapt_run_pattern(plan.enter_fbist_mode),
            adapt_run_pattern(plan.set_all_final_vposp),
            adapt_run_pattern(re_erase.run),
        )
        lines.extend((
            "\t// Re-erase failed UID sites only",
            "\t{",
            "\t\tint uidReeraseRequired=0;",
            "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t\t{",
            "\t\t\tif(!uidReadFailed[T_SOCKET])",
            "\t\t\t{",
            "\t\t\t\tSys_ActiveSite[T_SOCKET]=0;",
            "\t\t\t\tcontinue;",
            "\t\t\t}",
            "\t\t\tSys_ActiveSite[T_SOCKET]=1;",
            "\t\t\tuidReeraseRequired=1;",
            "\t\t}",
            "\t\tif(uidReeraseRequired==1)",
            "\t\t{",
            f"\t\t\tCALL_MACRO POWER_ON(_C_{plan.power_profile});",
            *("\t\t" + line for emission in cleanup for line in emission.statements),
            "\t\t\tCALL_MACRO POWER_OFF();",
            "\t\t}",
            "\t}",
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            "\t\tSys_ActiveSite[T_SOCKET]=uidActiveSites[T_SOCKET];",
            "\t\tif(uidReadFailed[T_SOCKET]) SYS_SetTestResult(FAIL,T_SOCKET);",
            "\t}",
            "\t}",
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
