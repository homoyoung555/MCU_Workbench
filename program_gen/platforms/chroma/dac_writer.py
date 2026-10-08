# Chroma 平台：DAC 族生成器 —— 与 chroma/opa_writer.py 同构（配置图形 link + PPMU 测输出脚）。
#
# 机制（参考 golden `temp/LAB_PY32F420A_.../Z_*.prg` 的 @@PLAN DAC_test）：DAC 无输入 force，
# 配置图形设 DAC（选实例+模式+码值）→ 直接 PPMU 测 DAC_OUT 脚电压 → 判显式 down/up 限值。
#   POWER_ON(VCC_TYP) → RELAY_ON(dac 脚, PPMU_PDCL) → JUDGE_PAT(<prod>_DAC_GPIO_INIT)
#   → 逐 dac 脚 FORCE_I_PPMU(0uA)（用户裁决 2026-07-24：两平台都 0uA，非 golden 的 -0.1uA）
#   → 每 mode×pin：JUDGE_PAT(<prod>_DAC_<mode>_<pin>_Test) + 逐 code{ JUDGE_PAT(CODE_<code>)
#     + target=hex(code)/FLOW.target×参考电压（VREFxPy=x.yV；其他 mode=VERSION[FLOW.Vcc]）
#     + 按 calc_limit 三写法计算后
#     + JUDGE_V_PPMU(pin, dn, up) }
# 母本 DAC sheet：mode / step / code / down_limit / up_limit（一行一 mode×code）；
# mode∈{BUFFOFF,BUFFON,VREF}，pin 从 IOMUX DAC 列遍历 ∩ 本程序出针（analog_sweep.dac_pins，
# 同 OPA 可用实例过滤）。配置图形是外部 SWD 工具产物，Chroma 只 JUDGE_PAT link 不 copy
# （plncmp 不校验引用存在性）。mode×pin Python 展开、code 走 C 循环（sprintf 拼 CODE 名 + S:
# 运行时引用，同 opa_writer），代码短。
import re

import analog_sweep as A
from program_gen import state as G
from program_gen.core import encoding as E
from program_gen.platforms.chroma.dc_scan_writer import _pin_dec_io_order
from program_gen.platforms.chroma.writers import _keil_step_write


def is_dac_row(z):
    """FLOW 行是否 DAC 族——FV/FI 哨兵 "DAC"（对位 opa 的 is_opa_row）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "DAC"


def _lim(cell):
    """已计算的数值限值 → Chroma 数值串。"""
    s = str(cell or "").strip()
    return s[:-1] if s[-1:].upper() == "V" else (s or "0")


def _cvar(mode):
    """mode → C 标识符安全的数组名前缀（非字母数字→_）。"""
    return "dac_" + re.sub(r"[^0-9A-Za-z]", "_", mode).lower()


def dac_test_write(code_name, f, z, pat_dir):
    """生成一个 DAC 测试项；FLOW.mode 支持 swd/keil。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    roles = A.build_iomux_roles(G.wb)
    real_pins = set(_pin_dec_io_order(pat_dir))
    pins = A.dac_pins(roles, real_pins)
    cases = A.dac_cases(G.wb, required=True)
    if not pins:
        raise ValueError("FLOW 已引用 DAC 族，但 IOMUX DAC_OUT 没有映射到本 CP 的出针")
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    item = G.col("FLOW", "item")[z]
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    vcc_value = E.resolve_vcc_value(
        vcc,
        G.col("VERSION", "vcc min")[G.i],
        G.col("VERSION", "vcc typ")[G.i],
        G.col("VERSION", "vcc max")[G.i],
    )
    resolution = G.col("FLOW", "target")[z]
    relay_grp = "+".join(pins)

    f.write("\n" + item + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n"
            '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item + '";\n\n')
    f.write("  char dac_st[64],dac_sp[64];\n\n")
    f.write("  POWER_ON(" + vcc + ");\n\n")
    f.write("  RELAY_ON(" + relay_grp + ", PPMU_PDCL, 2mS);\n\n")

    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "swd":
        init_name = product + "_DAC_GPIO_INIT"
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + init_name + '";\n'
                '  JUDGE_PAT(' + init_name + ',__' + init_name + ');\n\n')
    elif prefix:
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)
    for p in pins:
        f.write("  FORCE_I_PPMU(" + p + ", 0uA, @200uA, ,6V, -2V ,3mS);\n")   # 0uA（用户裁决）
    f.write("  WAIT(10mS);\n")

    for case in cases:
        mode = case["mode"]
        codes = [
            (code, step) + E.calc_dac_limits(
                code, resolution, vcc_value, low_cell, high_cell, mode=mode
            )
            for code, step, low_cell, high_cell in case["codes"]
        ]
        for p in pins:
            if entry_mode == "swd":
                n = len(codes)
                cv = _cvar(mode)
                f.write("\n  char " + cv + "_code[" + str(n) + "][8]={"
                        + ",".join('"' + c + '"' for c, _, _, _ in codes) + "};\n")
                f.write("  double " + cv + "_dn[" + str(n) + "]={"
                        + ",".join(_lim(dn) for _, _, dn, _ in codes) + "};\n")
                f.write("  double " + cv + "_up[" + str(n) + "]={"
                        + ",".join(_lim(up) for _, _, _, up in codes) + "};\n")
                cfg = product + "_DAC_" + mode + "_" + p + "_Test"
                f.write('\n  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + cfg + '";\n'
                        '  JUDGE_PAT(' + cfg + ',__' + cfg + ');\n')
                f.write("  for(int c=0;c<" + str(n) + ";c++)\n  {\n")
                f.write('    sprintf(dac_st,"' + product + '_DAC_CODE_%s:START",' + cv + '_code[c]);\n')
                f.write('    sprintf(dac_sp,"' + product + '_DAC_CODE_%s:END",' + cv + '_code[c]);\n')
                f.write('    DATALOG_MSG=dac_st;\n    JUDGE_PAT(S:dac_st,S:dac_sp);\n')
                f.write("    JUDGE_V_PPMU(" + p + ", " + cv + "_dn[c], " + cv + "_up[c], 2mS);\n")
                f.write("  }\n")
            else:
                for code, sheet_step, dn, up in codes:
                    if not sheet_step or sheet_step == "/":
                        raise ValueError("DAC keil: %s/%s 缺少 step" % (mode, code))
                    _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                                     step_override=sheet_step)
                    f.write('  DATALOG_MSG="DAC_%s_%s_%s_Verify";\n' % (mode, p, code))
                    f.write("  JUDGE_V_PPMU(%s, %s, %s, 2mS);\n" % (p, _lim(dn), _lim(up)))

    if entry_mode == "keil" and suffix:
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                         step_override=suffix)
    f.write("\n  RELAY_OFF(" + relay_grp + ", PPMU_PDCL, 2mS);\n")
    f.write("  POWER_OFF();\n}\n")
