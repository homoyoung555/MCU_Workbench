"""S100 COMP 族：单一大 compare pattern + `_C_` 动态标签，支持 SWD/Keil。"""
import io
import os

import analog_sweep as A
from program_gen import state as G
from program_gen.core import comp as C
from program_gen.core.encoding import resolve_vcc_value
from program_gen.platforms.s100.writers import _keil_step_write


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


def _stub(path):
    if os.path.isfile(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clk, swd = (G.col("VERSION", col)[G.i] for col in ("CLK PIN", "SWD PIN"))
    # S100 工程会把 VERSION 中的复位物理 pad（例如 PD11）统一改名为 NRST。
    # 占位 pattern 必须使用工程最终名字，否则合法母本也会在 pattern 预编译时报
    # "not definition in PinDefineTable"。
    nrst = "NRST"
    with open(path, "w", newline="\n") as out:
        out.write(f"HEAD[PIN_NAME]:\n\n{clk},{swd},{nrst};\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n")
        out.write("START:XXX;\n      XXX;RPT 100;\n  END:XXX;\n@@END_PATTERN_DEFINE\n")


def package_cases(z):
    source_cases = A.comp_cases(G.wb, required=True)
    vcc_name = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc = resolve_vcc_value(vcc_name, G.col("VERSION", "vcc min")[G.i],
                            G.col("VERSION", "vcc typ")[G.i], G.col("VERSION", "vcc max")[G.i])
    from program_gen.platforms.s100.project_files import dc_io_pins
    return C.compile_cases(source_cases, dc_io_pins(G.col("FLOW", "CP NO")[z]), vcc)


def comp_test_write(code_name, f, z):
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    plan = str(G.col("FLOW", "item")[z]).strip().title()
    vcc_name = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc = resolve_vcc_value(vcc_name, G.col("VERSION", "vcc min")[G.i],
                            G.col("VERSION", "vcc typ")[G.i], G.col("VERSION", "vcc max")[G.i])
    unit = str(G.col("FLOW", "UNIT")[z]).strip().lower()
    if unit not in ("pat", "v"):
        raise ValueError("COMP FLOW.UNIT 只支持 pat 或 V")
    dest = G.OUT_DIR + "\\" + code_name[G.i]
    cases = package_cases(z)
    if not cases:
        return
    pattern_h = C.compare_pattern_name(product, "H")
    pattern_l = C.compare_pattern_name(product, "L")
    if unit == "pat":
        C.write_compare_pattern(os.path.join(dest, pattern_h + ".sd"), pattern_h, cases, "s100", "H")
        C.write_compare_pattern(os.path.join(dest, pattern_l + ".sd"), pattern_l, cases, "s100", "L")
    f.write("@@PLAN " + plan + "\n\tSITE_SEQUENCE = OFF;\n\tGO_THROUGH = ON;\n"
            "\tDISABLE_BY_MARK_NO = NULL;\n\tS_SETUP_FILE = c:\\set.dat;\n\tREMARK = " + plan + ";\n\n")
    f.write("\tchar _C_comp_st[96], _C_comp_sp[96];\n")
    if entry_mode == "swd":
        init = _init_name(product, z)
        _stub(os.path.join(dest, init + ".sd"))
        f.write("\tCALL_MACRO POWER_ON(_C_" + vcc_name + ");\n")
        f.write("\tRUN_PATTERN(" + init + ":START," + init + ":END,1,TS_500K);\n")
    f.write("\tfor(int comp_index=0;comp_index<" + str(len(cases)) + ";comp_index++)\n\t{\n")
    if entry_mode != "swd":
        f.write("\t\tCALL_MACRO POWER_ON(_C_" + vcc_name + ");\n")
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    if entry_mode == "keil" and prefix:
        _keil_step_indented(f, "\t", z, get_pin, dest, entry_only=True,
                            emit_banner=False, step_override=prefix)
    f.write("\t\tswitch(comp_index)\n\t\t{\n")
    for index, case in enumerate(cases):
        f.write("\t\t\tcase " + str(index) + ":\n")
        if entry_mode == "swd":
            cfg = C.config_pattern_name(product, case)
            _stub(os.path.join(dest, cfg + ".sd"))
            f.write("\t\t\t\tRUN_PATTERN(" + cfg + ":START," + cfg + ":END,1,TS_500K);\n")
        else:
            _keil_step_indented(f, "\t\t\t", z, get_pin, dest, entry_only=True,
                                emit_banner=False, step_override=case["step"])
        if unit == "pat":
            for pin, level in case["levels"].items():
                f.write("\t\t\t\tLOGIC_SET_DRV_LEVEL(" + pin + ", " + _v(level["vih"])
                        + ", " + _v(level["vil"]) + ", 0.0V, VR1);\n")
        else:
            for pin, value in case["forward_forces"].items():
                f.write("\t\t\t\tLOGIC_PPMU_FV(" + pin + ", " + _v(value) + ", E2, I2);\n")
            low, high = C.measurement_limits(case, vcc)
            f.write("\t\t\t\tLOGIC_PPMU_FI(" + case["out_pin"] + ", 0UA, E1, I1);\n")
            f.write("\t\t\t\tLOGIC_PPMU_MV(" + case["out_pin"] + ", DOWN_LIMIT=" + _v(low)
                    + ", UP_LIMIT=" + _v(high) + ", LOG_ALIAS=COMP_" + str(index + 1)
                    + "_Verify, LOG_UNIT=V);\n")
            for pin, value in case["reverse_forces"].items():
                f.write("\t\t\t\tLOGIC_PPMU_FV(" + pin + ", " + _v(value) + ", E2, I2);\n")
            reverse_case = dict(case, expect="L")
            low, high = C.measurement_limits(reverse_case, vcc)
            f.write("\t\t\t\tLOGIC_PPMU_MV(" + case["out_pin"] + ", DOWN_LIMIT=" + _v(low)
                    + ", UP_LIMIT=" + _v(high) + ", LOG_ALIAS=COMP_" + str(index + 1)
                    + "_Reverse_Verify, LOG_UNIT=V);\n")
        f.write("\t\t\t\tbreak;\n")
    f.write("\t\t}\n")
    if unit == "pat":
        f.write('\t\tsprintf(_C_comp_st,"' + pattern_h + ':s%03d_st",comp_index+1);\n')
        f.write('\t\tsprintf(_C_comp_sp,"' + pattern_h + ':s%03d_sp",comp_index+1);\n')
        f.write("\t\tRUN_PATTERN(_C_comp_st,_C_comp_sp,1,VIH_5MHZ);\n")
        f.write('\t\tsprintf(_C_comp_st,"' + pattern_l + ':s%03d_st",comp_index+1);\n')
        f.write('\t\tsprintf(_C_comp_sp,"' + pattern_l + ':s%03d_sp",comp_index+1);\n')
        f.write("\t\tRUN_PATTERN(_C_comp_st,_C_comp_sp,1,VIH_5MHZ);\n")
    if entry_mode == "keil" and suffix:
        _keil_step_indented(f, "\t", z, get_pin, dest, entry_only=True,
                            emit_banner=False, step_override=suffix)
    if entry_mode != "swd":
        f.write("\t\tCALL_MACRO POWER_OFF();\n")
    f.write("\t}\n")
    if entry_mode == "swd":
        f.write("\tCALL_MACRO POWER_OFF();\n")
    f.write("\n\tCONDITION\n\t\tIF_FAIL\n\t\tREJECT_BIN = "
            + str(G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")
