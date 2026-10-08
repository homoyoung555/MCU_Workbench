"""S100：FREQ 独立 sheet 的 CP3 功能频率族生成器。"""

import analog_sweep as A
from program_gen import state as G
from program_gen.core import clock_force
from program_gen.platforms.s100.pattern_files import copy_file
from program_gen.platforms.s100.writers import (
    _keil_step_write,
    _emit_clock_force_off_plan,
    _emit_clock_force_plan,
    _emit_freq_meas,
    _force_pass_write,
)


def is_freq_row(z):
    """FLOW.FV/FI=FREQ 表示该入口行从独立 FREQ sheet 展开。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "FREQ"


def _swd_pat_name(product, mode):
    parts = str(mode).strip().split("_")
    stem = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    return product + "_SWD_" + stem


def freq_test_write(code_name, f, z):
    """一个 FLOW 入口行 → 同名 FREQ 分组的全部 mode。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify"
            and entry_mode in ("swd", "keil")):
        return
    item = str(G.col("FLOW", "item")[z]).strip()
    cases = A.freq_cases(G.wb, item)
    if not cases:
        raise ValueError(f"FLOW {item} 使用 FV/FI=FREQ，但 FREQ sheet 没有同名分组")

    cp_no = G.col("FLOW", "CP NO")[z]
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    meas_pin = str(G.col("FLOW", "meas pin")[z]).strip()
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    hbin = G.col("FLOW", "Hbin")[z]
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    plan_name = item.title()

    f.write("@@PLAN " + plan_name + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n\tDISABLE_BY_MARK_NO = NULL;\n"
            "\tS_SETUP_FILE       = c:\\set.dat;\n\tREMARK             = " + plan_name + "; \n\n")
    f.write("\tCALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")
    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "keil" and prefix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)

    for case in cases:
        mode = case["mode"]
        f.write("\t////////////////////" + mode.upper() + "////////////////////\n")
        if entry_mode == "swd":
            pat_name = _swd_pat_name(product, mode)
            copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".sd", dest_dir)
            f.write("\tRUN_PATTERN(" + pat_name + ":START," + pat_name + ":END,1,TS_5MHZ);\n\n")
        else:
            if not case["step"] or case["step"] == "/":
                raise ValueError("FREQ keil: %s/%s 缺少 step" % (item, case["source"]))
            _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                             step_override=case["step"])

        clock_plan = None
        if clock_force.is_clock_force_cell(case["force"]):
            clock_plan = clock_force.s100_cell_plan(case["force"])
            _emit_clock_force_plan(f, clock_plan, dest_dir)
        _emit_freq_meas(
            f, case["unit"], meas_pin, "/", case["target"],
            case["down_limit"], case["up_limit"], mode,
        )
        if clock_plan:
            _emit_clock_force_off_plan(f, clock_plan)

    if entry_mode == "keil" and suffix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=suffix)
    f.write("\tCALL_MACRO POWER_OFF();\n")
    _force_pass_write(f, z)
    f.write("\n\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
