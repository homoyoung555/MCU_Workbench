"""Chroma：FREQ 独立 sheet 的 CP3 功能频率族生成器。"""

import analog_sweep as A
from program_gen import state as G
from program_gen.core import clock_force
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen.platforms.chroma.writers import (
    Force_Judge,
    _keil_step_write,
    _emit_clock_force_off_plan,
    _emit_clock_force_plan,
)


def is_freq_row(z):
    """FLOW.FV/FI=FREQ 表示该入口行从独立 FREQ sheet 展开。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "FREQ"


def _swd_pat_name(product, mode):
    parts = str(mode).strip().split("_")
    stem = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    return product + "_SWD_" + stem


def freq_test_write(code_name, f, z, pat_dir):
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

    product = str(G.col("VERSION", "product name")[G.i]).strip()
    cp_no = G.col("FLOW", "CP NO")[z]
    meas_pin = str(G.col("FLOW", "meas pin")[z]).strip()
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    function_name = item.title()

    # TEST_PRO 按既有 Chroma 规则调用 item.title()（Clock_Check_Test/Pll_Test）。
    f.write("\n" + function_name + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item + '";\n\n')
    f.write("  POWER_ON(" + vcc + ");\n\n")
    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "keil" and prefix:
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)

    for case in cases:
        mode = case["mode"]
        f.write("  ////////////////////" + mode.lower() + "////////////////////\n")
        if entry_mode == "swd":
            pat_name = _swd_pat_name(product, mode)
            copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".pat", pat_dir)
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                    '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
        else:
            if not case["step"] or case["step"] == "/":
                raise ValueError("FREQ keil: %s/%s 缺少 step" % (item, case["source"]))
            _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                             step_override=case["step"])

        clock_plan = None
        if clock_force.is_clock_force_cell(case["force"]):
            clock_plan = clock_force.chroma_cell_plan(case["force"], cp_no)
            _emit_clock_force_plan(f, clock_plan, pat_dir)
        Force_Judge(
            case["unit"], meas_pin, "/", case["target"], 0, "FORCE", "FREQ",
            case["down_limit"], case["up_limit"], f,
        )
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + mode.lower() + '";\n')
        Force_Judge(
            case["unit"], meas_pin, "/", case["target"], 0, "JUDGE", "FREQ",
            case["down_limit"], case["up_limit"], f,
        )
        f.write("  SET_TFTM_MODE(" + meas_pin + ", SCHMITT_OFF);\n\n")
        if clock_plan:
            _emit_clock_force_off_plan(f, clock_plan)

    if entry_mode == "keil" and suffix:
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                         step_override=suffix)
    f.write("  POWER_OFF();\n}\n")
