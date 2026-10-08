"""Chroma COMP 族：单一大 compare pattern + 动态标签，支持 SWD/Keil。"""
import io
import os

import analog_sweep as A
from program_gen import state as G
from program_gen.core import comp as C
from program_gen.core.encoding import resolve_vcc_value
from program_gen.platforms.chroma.pattern_files import write_placeholder_pat
from program_gen.platforms.chroma.scan_writer import _load_real_pins
from program_gen.platforms.chroma.writers import _keil_step_write


def is_comp_row(z):
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "COMP"


def _v(value):
    return ("%g" % float(value)) + "V"


def _init_name(product, z):
    sub = str(G.col("FLOW", "sub")[z]).strip()
    return product + "_" + sub if sub and sub != "/" else product + "_COMP_INIT"


def _keil_step_indented(f, indent, *args, **kwargs):
    """公共 step writer 按顶层格式输出；COMP 在嵌套块中调用时统一补调用层级缩进。"""
    buf = io.StringIO()
    _keil_step_write(buf, *args, **kwargs)
    for line in buf.getvalue().splitlines(keepends=True):
        f.write(indent + line if line.strip() else line)


def package_cases(z, pat_dir):
    source_cases = A.comp_cases(G.wb, required=True)
    vcc_name = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc = resolve_vcc_value(vcc_name, G.col("VERSION", "vcc min")[G.i],
                            G.col("VERSION", "vcc typ")[G.i], G.col("VERSION", "vcc max")[G.i])
    return C.compile_cases(source_cases, _load_real_pins(pat_dir), vcc)


def comp_test_write(code_name, f, z, pat_dir):
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    item = str(G.col("FLOW", "item")[z]).strip()
    vcc_name = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc = resolve_vcc_value(vcc_name, G.col("VERSION", "vcc min")[G.i],
                            G.col("VERSION", "vcc typ")[G.i], G.col("VERSION", "vcc max")[G.i])
    unit = str(G.col("FLOW", "UNIT")[z]).strip().lower()
    if unit not in ("pat", "v"):
        raise ValueError("COMP FLOW.UNIT 只支持 pat 或 V")
    cases = package_cases(z, pat_dir)
    if not cases:
        return
    pattern_h = C.compare_pattern_name(product, "H")
    pattern_l = C.compare_pattern_name(product, "L")
    if unit == "pat":
        C.write_compare_pattern(os.path.join(pat_dir, pattern_h + ".pat"), pattern_h, cases, "chroma", "H")
        C.write_compare_pattern(os.path.join(pat_dir, pattern_l + ".pat"), pattern_l, cases, "chroma", "L")
    f.write("\n" + item + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n"
            '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item + '";\n')
    f.write("  char comp_st[96],comp_sp[96];\n")
    if entry_mode == "swd":
        init = _init_name(product, z)
        write_placeholder_pat(pat_dir, init)
        f.write("  POWER_ON(" + vcc_name + ");\n")
        f.write('  JUDGE_PAT(' + init + ',__' + init + ');\n')
    f.write("  for(int comp_index=0;comp_index<" + str(len(cases)) + ";comp_index++)\n  {\n")
    if entry_mode != "swd":
        f.write("    POWER_ON(" + vcc_name + ");\n")
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    if entry_mode == "keil" and prefix:
        _keil_step_indented(f, "  ", z, get_pin, pat_dir, entry_only=True,
                            emit_banner=False, step_override=prefix)
    f.write("    switch(comp_index)\n    {\n")
    for index, case in enumerate(cases):
        f.write("      case " + str(index) + ":\n")
        if entry_mode == "swd":
            cfg = C.config_pattern_name(product, case)
            write_placeholder_pat(pat_dir, cfg)
            f.write('        JUDGE_PAT(' + cfg + ',__' + cfg + ');\n')
        else:
            _keil_step_indented(f, "      ", z, get_pin, pat_dir, entry_only=True,
                                emit_banner=False, step_override=case["step"])
        if unit == "pat":
            f.write("        SET_LEVELN(comp_lvl, IO_ALLPINS, 0V, " + _v(vcc) + ", "
                    + _v(vcc * 0.45) + ", " + _v(vcc * 0.55)
                    + ", 0uA, 0uA, " + _v(vcc * 0.5) + ", , );\n")
            for pin, level in case["levels"].items():
                f.write("        SET_LEVELN(comp_lvl, " + pin + ", " + _v(level["vil"])
                        + ", " + _v(level["vih"])
                        + ", " + _v(vcc * 0.45) + ", " + _v(vcc * 0.55)
                        + ", 0uA, 0uA, " + _v(vcc * 0.5) + ", , );\n")
            f.write("        LEVELS(comp_lvl,3mS);\n")
        else:
            for pin, value in case["forward_forces"].items():
                f.write("        FORCE_V_PPMU(" + pin + ", " + _v(value)
                        + ", @2mA, 6V, -2V, 3mS);\n")
            low, high = C.measurement_limits(case, vcc)
            f.write("        FORCE_I_PPMU(" + case["out_pin"] + ", 0uA, @200uA, 6V, -2V, 3mS);\n")
            f.write("        JUDGE_V_PPMU(" + case["out_pin"] + ", " + str(low) + ", " + str(high) + ", 2mS);\n")
            for pin, value in case["reverse_forces"].items():
                f.write("        FORCE_V_PPMU(" + pin + ", " + _v(value)
                        + ", @2mA, 6V, -2V, 3mS);\n")
            reverse_case = dict(case, expect="L")
            low, high = C.measurement_limits(reverse_case, vcc)
            f.write("        JUDGE_V_PPMU(" + case["out_pin"] + ", " + str(low) + ", " + str(high) + ", 2mS);\n")
        f.write("        break;\n")
    f.write("    }\n")
    if unit == "pat":
        f.write('    sprintf(comp_st,"' + pattern_h + ':s%03d_st",comp_index+1);\n')
        f.write('    sprintf(comp_sp,"' + pattern_h + ':s%03d_sp",comp_index+1);\n')
        f.write("    TEST_NUM++; TEST_NO(TEST_NUM); DATALOG_MSG=comp_st;\n")
        f.write("    JUDGE_PAT(S:comp_st,S:comp_sp);\n")
        f.write('    sprintf(comp_st,"' + pattern_l + ':s%03d_st",comp_index+1);\n')
        f.write('    sprintf(comp_sp,"' + pattern_l + ':s%03d_sp",comp_index+1);\n')
        f.write("    TEST_NUM++; TEST_NO(TEST_NUM); DATALOG_MSG=comp_st;\n")
        f.write("    JUDGE_PAT(S:comp_st,S:comp_sp);\n")
    if entry_mode == "keil" and suffix:
        _keil_step_indented(f, "  ", z, get_pin, pat_dir, entry_only=True,
                            emit_banner=False, step_override=suffix)
    if entry_mode != "swd":
        f.write("    POWER_OFF();\n")
    f.write("  }\n")
    if entry_mode == "swd":
        f.write("  POWER_OFF();\n")
    f.write("}\n")
