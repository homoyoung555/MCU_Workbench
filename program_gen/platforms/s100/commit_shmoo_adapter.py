"""S100 execution seam for platform-neutral persistent COMMIT Shmoo."""

from program_gen.core.commit_shmoo import CommitShmooPlan


def execute_commit_shmoo(
    plan: CommitShmooPlan,
    *,
    begin_step,
    commit_field,
    pgm_pages,
    end_step,
) -> None:
    for point in plan.points:
        begin_step(point.step)
        for write in point.field_writes:
            commit_field(write)
        for action in point.physical_actions:
            pgm_pages(action.pages)
        end_step(point.step)


def write_commit_shmoo(code_name, f, plan, *, state, copy_file,
                       pattern_capture, load_register,
                       failed_uid_reerase=None) -> None:
    """Translate a typed persistent Shmoo plan to one S100 @@PLAN."""
    if code_name[state.i].split("_")[-1] != plan.cp:
        return
    f.write("\n@@PLAN " + plan.function_name.title() + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n")
    f.write("\tDISABLE_BY_MARK_NO = NULL;\n\tS_SETUP_FILE       = c:\\set.dat;\n\n")
    f.write("\tCALL_MACRO POWER_ON(_C_" + plan.vcc.upper() + ");\n")

    def begin_step(step):
        f.write("\n\t// COMMIT Shmoo STEP=" + str(step) + "\n")
        f.write("\t// LOG_ALIAS=STEP_" + str(step) + "\n")

    def commit_field(write):
        mask = ((1 << write.width) - 1) << write.lsb
        inverse = (~mask) & 0xFFFF
        value = write.value << write.lsb
        register = "REG_" + write.register.upper() + "[T_SOCKET]"
        f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n")
        f.write("\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
        f.write(
            "\t\t" + register + "=(" + register + "&0x"
            + format(inverse, "04X") + ")|0x" + format(value, "04X") + ";\n"
        )
        f.write("\t}\n")
        load_register(write.page, write.register)

    def pgm_pages(pages):
        for page in pages:
            result = pattern_capture("normal", page)
            for role in ("erase", "pgm", "read"):
                copy_file(
                    state.BASE_DIR + "\\pat_temp\\" + result[role] + ".sd",
                    state.OUT_DIR + "\\" + code_name[state.i],
                )
            f.write(
                "\tRUN_PATTERN(" + result["erase"] + ":START," + result["erase"]
                + ":END,1,TS_5MHZ);\n"
            )
            f.write(
                "\tRUN_PATTERN(" + result["pgm"] + ":START," + result["pgm"]
                + ":END,1,TS_5MHZ);\n"
            )
            f.write(
                "\tRUN_PATTERN(" + result["read"] + ":START," + result["read"]
                + ":END,1,TS_5MHZ);\n"
            )
            if page.casefold() == "uid" and failed_uid_reerase is not None:
                failed_uid_reerase(result)

    execute_commit_shmoo(
        plan,
        begin_step=begin_step,
        commit_field=commit_field,
        pgm_pages=pgm_pages,
        end_step=lambda step: None,
    )
    f.write("\tCALL_MACRO POWER_OFF();\n")
    f.write("@@END_PLAN\n\n")
