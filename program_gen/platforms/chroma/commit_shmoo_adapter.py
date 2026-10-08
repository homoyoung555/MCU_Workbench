"""Chroma execution seam for platform-neutral persistent COMMIT Shmoo."""

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
                       uid_failed_site_reerase=None) -> None:
    """Translate a typed persistent Shmoo plan to one Chroma function."""
    if code_name[state.i].split("_")[-1] != plan.cp:
        return
    f.write("\n" + plan.function_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((plan.flow_row_index + 1) * 100) + ";\n")
    f.write("  POWER_ON(" + plan.vcc.upper() + ");\n")

    def begin_step(step):
        f.write("\n  // COMMIT Shmoo STEP=" + str(step) + "\n")
        f.write("  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG=\"STEP_"
                + str(step) + "\";\n")

    def commit_field(write):
        mask = ((1 << write.width) - 1) << write.lsb
        inverse = (~mask) & 0xFFFF
        value = write.value << write.lsb
        register = "REG_" + write.register.upper() + "[SOCKET]"
        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
        f.write(
            "    " + register + "=(" + register + "&0x"
            + format(inverse, "04X") + ")|0x" + format(value, "04X") + ";\n"
        )
        f.write("  }\n")
        load_register(write.page, write.register)

    def pgm_pages(pages):
        for page in pages:
            result = pattern_capture("normal", page)
            for role in ("erase", "pgm", "read"):
                copy_file(
                    state.BASE_DIR + "\\pat_temp\\" + result[role] + ".pat",
                    state.OUT_DIR + "\\" + code_name[state.i] + "\\pat",
                )
                f.write("  JUDGE_PAT(" + result[role] + ",__"
                        + result[role] + ");\n")
            if page.casefold() == "uid" and uid_failed_site_reerase is not None:
                uid_failed_site_reerase(
                    f, result, vcc=plan.vcc, restore_power=True
                )

    execute_commit_shmoo(
        plan,
        begin_step=begin_step,
        commit_field=commit_field,
        pgm_pages=pgm_pages,
        end_step=lambda step: None,
    )
    f.write("  POWER_OFF();\n}\n\n")
