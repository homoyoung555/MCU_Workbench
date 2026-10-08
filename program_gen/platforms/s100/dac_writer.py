# S100 平台：DAC 族生成器 —— 与 chroma/dac_writer.py 对位、贴 golden `Z_*.prg` 的 @@PLAN DAC_test。
#
# 机制同 Chroma（无输入 force，配置图形 link + PPMU 测 DAC_OUT）。**S100 逐档展开**（mode×pin×
# code 三层 Python 展开、literal RUN_PATTERN + LOGIC_PPMU_MV），不用 C 循环——同 OPA S100 先例，
# 且 golden 本身展开、DOWN/UP_LIMIT 用 C 变量在 YT5100 未验证，展开最稳。
#   CALL_MACRO POWER_ON(_C_VCC_TYP) → RUN_PATTERN(<prod>_DAC_GPIO_INIT) → 逐 dac 脚
#   LOGIC_PPMU_FI(0UA, E2, I1)（用户裁决 2026-07-24：0uA，非 golden 的 -0.1UA）→ WAIT
#   → 每 mode×pin：RUN_PATTERN(<prod>_DAC_<mode>_<pin>_Test) + 逐 code{ RUN_PATTERN(CODE_<code>)
#     + target=hex(code)/FLOW.target×参考电压（VREFxPy=x.yV；其他 mode=VERSION[FLOW.Vcc]）
#     + 再按 calc_limit 三写法算 DOWN/UP_LIMIT
#     + LOGIC_PPMU_MV(pin, ..., LOG_ALIAS=DAC_<mode>_<pin>_<code>_Verify, LOG_UNIT=V) }
#   → CALL_MACRO POWER_OFF → CONDITION IF_FAIL REJECT_BIN=<Hbin>
# 配置/CODE 图形是外部 SWD 工具产物，copy_file 进程序目录（缺源走占位兜底），RUN_PATTERN 引用
# 须能在 .prj PATTERN_NAME 登记（不同于 Chroma JUDGE_PAT）。pin 从 IOMUX DAC 列遍历 ∩ 本 CP
# 出针（analog_sweep.dac_pins）。母本 DAC sheet：mode/step/code/down_limit/up_limit（见 dac_cases）。
import analog_sweep as A
from program_gen import state as G
from program_gen.core import encoding as E
from program_gen.platforms.s100.pattern_files import copy_file
from program_gen.platforms.s100.writers import _keil_step_write


def is_dac_row(z):
    """FLOW 行是否 DAC 族——FV/FI 哨兵 "DAC"（与 Chroma 同一约定）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "DAC"


def _present_pins(cp_no):
    """本 CP 引出的 IO 短名集合（惰性 import dc_io_pins，避免循环 import，同 opa_writer）。"""
    from program_gen.platforms.s100.project_files import dc_io_pins
    return set(dc_io_pins(cp_no))


def _lim(cell):
    """已计算的数值限值 → S100 电压字面量。"""
    s = str(cell or "").strip()
    if not s:
        return "0V"
    return s if s[-1:].upper() == "V" else (s + "V")


def dac_test_write(code_name, f, z):
    """@@PLAN Dac_Test；FLOW.mode 支持 swd/keil。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    roles = A.build_iomux_roles(G.wb)
    pins = A.dac_pins(roles, _present_pins(cp_no))
    cases = A.dac_cases(G.wb, required=True)
    if not pins:
        raise ValueError("FLOW 已引用 DAC 族，但 IOMUX DAC_OUT 没有映射到本 CP 的出针")
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    plan = str(G.col("FLOW", "item")[z]).strip().title()
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc_value = E.resolve_vcc_value(
        vcc,
        G.col("VERSION", "vcc min")[G.i],
        G.col("VERSION", "vcc typ")[G.i],
        G.col("VERSION", "vcc max")[G.i],
    )
    resolution = G.col("FLOW", "target")[z]
    hbin = G.col("FLOW", "Hbin")[z]
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]

    f.write("@@PLAN " + plan + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n\tDISABLE_BY_MARK_NO = NULL;\n"
            "\tS_SETUP_FILE       = c:\\set.dat;\n\tREMARK             = " + plan + "; \n\n")
    f.write("\tCALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")

    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "swd":
        init_name = product + "_DAC_GPIO_INIT"
        copy_file(G.BASE_DIR + "\\pat_temp\\" + init_name + ".sd", dest_dir)
        f.write("\tRUN_PATTERN(" + init_name + ":START," + init_name + ":END,1,TS_500K);\n")
    elif prefix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)
    for p in pins:
        f.write("\tLOGIC_PPMU_FI(" + p + ", 0UA, E2, I1);\n")   # 0uA（用户裁决）
    f.write("\tWAIT(10MS);\n")

    for case in cases:
        mode, codes = case["mode"], case["codes"]
        for p in pins:
            f.write("\n\t//////////////// DAC " + mode + " " + p + " ////////////////\n")
            if entry_mode == "swd":
                cfg = product + "_DAC_" + mode + "_" + p + "_Test"
                copy_file(G.BASE_DIR + "\\pat_temp\\" + cfg + ".sd", dest_dir)
                f.write("\tRUN_PATTERN(" + cfg + ":START," + cfg + ":END,1,TS_500K);\n")
            for code, sheet_step, low_cell, high_cell in codes:
                dn, up = E.calc_dac_limits(
                    code, resolution, vcc_value, low_cell, high_cell, mode=mode
                )
                if entry_mode == "swd":
                    cpat = product + "_DAC_CODE_" + code
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + cpat + ".sd", dest_dir)
                    f.write("\tRUN_PATTERN(" + cpat + ":START," + cpat + ":END,1,TS_500K);\n")
                else:
                    if not sheet_step or sheet_step == "/":
                        raise ValueError("DAC keil: %s/%s 缺少 step" % (mode, code))
                    _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                                     step_override=sheet_step)
                f.write("\tLOGIC_PPMU_MV(" + p + ", DOWN_LIMIT=" + _lim(dn) + ", UP_LIMIT=" + _lim(up)
                        + ", LOG_ALIAS=DAC_" + mode + "_" + p + "_" + code + "_Verify, LOG_UNIT=V);\n")

    if entry_mode == "keil" and suffix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=suffix)
    f.write("\n\tCALL_MACRO POWER_OFF();\n\n")
    f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
