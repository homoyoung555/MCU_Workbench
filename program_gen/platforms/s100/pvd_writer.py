# S100 平台：PVD 族（欠压中断阈值四点法）生成器 —— 与 chroma/pvd_writer.py 对位。
#
# 母本填法与 Chroma 完全相同（平台无关的 PVD sweep 表，见 analog_sweep.pvd_cases）：
#   FLOW：item="Pvd_Test"、mode="keil"、FV/FI="PVD"（哨兵分派）、meas pin="PA13+PA14"、
#         UNIT="pat"、Vcc="VCC_MAX"（高压起点）、step="HL-222-15-X"（进入码模板，X←case 号）。
#   PVD sheet：每 case 两行 up/down，各 min/typ/max + limit(内缩量 guard) + expect(HH/LL) + step。
#
# 结构（每 case 一次上下电，C `for` 循环——用户裁决 2026-07-24"S100 也用拼接 pattern 格式"）：
#   for(c) { CALL_MACRO POWER_ON(_C_VCC_MAX) → 进入码固定段 HL-222-15 + case 号（sprintf 拼
#            send_num 标签 + RUN_PATTERN 字符串变量）→ 四点 CALL_MACRO POWER_ON(_C_pvd_v[...])
#            改 VCC 电平（S100 无 Chroma 的 POWER_Shmoo_ON，用 POWER_ON 走扫，同 Bor）+
#            RUN_PATTERN(PA13PA14_Cmp_<HH/LL>) → CALL_MACRO POWER_OFF() }
# **用户裁决 2026-07-24：只有传给 RUN_PATTERN 的字符串变量必须带 `_C_` 前缀**（`RUN_PATTERN(
# _C_PAT_ST,_C_PAT_SP,1,2)` 格式）——即 `_C_snd_st`/`_C_snd_sp`；循环变量(`item`)、电压数组
# (`pvd_v`)、case 号数组(`pvd_snd`)照 Bor 惯例裸名（Bor 的 `borFallingvoltage[I]` 传 POWER_ON
# 即裸名）。电压走 **2D** `double pvd_v[N][4]`（用户裁决：S100 支持二维、`[item][p]` 索引）。
# send_num 标签是 **3 位十进制**（s%03d，S100 风格，与 Chroma 的十六进制不同）；compare pattern
# 命名 `<PIN1><PIN2>_Cmp_<STATE>`（大写，同 `_emit_pin_compare`），由本 writer 按 expect 用
# `_compare_sd_write` 生成。判据 compare pattern 靠 @@PLAN 末尾 CONDITION IF_FAIL REJECT_BIN
# 收（同既有 keil pat 路径的 `_emit_pin_compare`，无显式 datalog）。get_pin_patterns_created 的
# PVD 哨兵护栏（target="PVD" 非比较状态）同 Chroma。**要求各 case 判据序列一致**。
import analog_sweep as A
from program_gen import state as G
from program_gen.platforms.s100.pattern_files import (
    copy_file, copy_trig_sd, trig_disp, LEVEL_SEQ_RE, default_pulse, level_seq_pat_name, parse_pulse_width,
    _compare_sd_write)


def is_pvd_row(z):
    """FLOW 行是否 PVD 族——FV/FI 哨兵 "PVD"（与 Chroma 同一约定）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "PVD"


def _emit_entry(f, template, get_pin, dest_dir, snd_var, st_buf, sp_buf):
    """@@PLAN 循环体内发进入码：FLOW.step 模板逐 token——
      X token   → 可变 case 号发送：sprintf 出 Trig_send_num:s<3位十进制>_st/_sp 标签到
                  `_C_` 前缀 char 变量 + RUN_PATTERN 字符串变量（用户裁决 2026-07-24）。
      电平序列  → 固定 RUN_PATTERN(Trig_<levels>_<width>:START/END)。
      裸数字    → 固定 RUN_PATTERN(Trig_send_num:s<3位十进制>_st/_sp)。
    只认这三类，其余报错。PVD 触发无 <PIN>: 前缀=默认触发 → 显示名 Trig（不烤死真实 pin，
    2026-07-24），种子按真实 get_pin、拷进程序目录时改名。行首 2 tab=循环体缩进（reindent 统一）。"""
    disp = trig_disp(get_pin, True)          # PVD 恒默认触发
    toks = template.split("-")
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "X":
            base = disp + "_send_num"
            copy_trig_sd(get_pin + "_send_num", base, dest_dir)
            f.write('\t\tsprintf(' + st_buf + ',"' + base + ':s%03d_st",' + snd_var + ');\n')
            f.write('\t\tsprintf(' + sp_buf + ',"' + base + ':s%03d_sp",' + snd_var + ');\n')
            f.write('\t\tRUN_PATTERN(' + st_buf + ',' + sp_buf + ',1,VIH_5MHZ);\n\n')
        elif LEVEL_SEQ_RE.fullmatch(tok):
            levels = tok
            rpt, width = default_pulse()
            if i + 1 < len(toks) and parse_pulse_width(toks[i + 1]):
                rpt, width = parse_pulse_width(toks[i + 1])
                i += 1
            pat_real = level_seq_pat_name(get_pin, levels, width)
            pat = level_seq_pat_name(disp, levels, width)
            copy_trig_sd(pat_real, pat, dest_dir)
            f.write('\t\tRUN_PATTERN(' + pat + ':START,' + pat + ':END,1,VIH_5MHZ);\n\n')
        elif tok.isdigit():
            label = "s%03d" % int(tok)
            base = disp + "_send_num"
            copy_trig_sd(get_pin + "_send_num", base, dest_dir)
            f.write('\t\tRUN_PATTERN(' + base + ':' + label + '_st,' + base + ':' + label
                    + '_sp,1,VIH_5MHZ);\n\n')
        else:
            raise ValueError("s100 pvd_writer: 进入码 token 无法识别 '%s'"
                             "（PVD.step 只支持电平序列/裸数字/X，实际模板 '%s'）" % (tok, template))
        i += 1


def pvd_test_write(code_name, f, z):
    """@@PLAN Pvd_Test（mode=keil）。CP gate 同其它 s100 keil writer。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "keil"):
        return
    cases = A.pvd_cases(G.wb, required=True)
    plan = str(G.col("FLOW", "item")[z]).strip().title()
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    hbin = G.col("FLOW", "Hbin")[z]
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    template = str(G.col("FLOW", "step")[z]).strip()
    meas_pin = str(G.col("FLOW", "meas pin")[z]).strip()          # "PA13+PA14"
    pin1, pin2 = (meas_pin.split("+", 1) + [""])[:2]
    pin1, pin2 = pin1.strip(), pin2.strip()
    cmp_prefix = pin1 + pin2                                       # "PA13PA14"
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]

    # 各 case 判据序列必须一致（循环体内四点判据只写一遍）——同 chroma/pvd_writer。
    seq = [st for _, st in cases[0]["points"]]
    for c in cases:
        if [st for _, st in c["points"]] != seq:
            raise ValueError("s100 pvd_writer: 各 case 判据序列不一致（case %s=%s vs case %s=%s）；"
                             "当前循环写法要求跨 case 相同，逐 case 不同需改 compare 名数组+RUN_PATTERN 变量展开"
                             % (cases[0]["case"], seq, c["case"], [st for _, st in c["points"]]))

    # compare pattern（HH/LL 各一份到 pat_temp，幂等）——按 sweep 表 expect 生成，命名/骨架同
    # _emit_pin_compare 的 <PIN1><PIN2>_Cmp_<STATE>。copy_file 进程序目录由 get_sd_filenames_with_os 登记。
    for st in A.pvd_compare_states(G.wb):
        _compare_sd_write(G.BASE_DIR + "\\pat_temp\\" + cmp_prefix + "_Cmp_" + st + ".sd", pin1, pin2, st)

    n = len(cases)
    # 2D 电压数组（用户裁决 2026-07-24：S100 用二维、更清晰、与 Chroma 一致）；行=case、列=四点。
    volt_rows = ["{" + ",".join(v for v, _ in c["points"]) + "}" for c in cases]
    snd_vals = [str(int(c["step"])) for c in cases]

    f.write("@@PLAN " + plan + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n\tDISABLE_BY_MARK_NO = NULL;\n"
            "\tS_SETUP_FILE       = c:\\set.dat;\n\tREMARK             = " + plan + "; \n\n")
    # 只有传给 RUN_PATTERN 的字符串变量带 `_C_` 前缀（用户裁决 2026-07-24）；循环变量/电压数组
    # 照 Bor 惯例裸名（Bor 的 borFallingvoltage[I] 传给 POWER_ON 即裸名）。
    f.write("\tdouble pvd_v[" + str(n) + "][4]={" + ",".join(volt_rows) + "};\n")
    f.write("\tint pvd_snd[" + str(n) + "]={" + ",".join(snd_vals) + "};\n")
    f.write("\tchar _C_snd_st[100],_C_snd_sp[100];\n\n")

    f.write("\tfor(int item=0;item<" + str(n) + ";item++)\n\t{\n")
    f.write("\t\tCALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")
    _emit_entry(f, template, get_pin, dest_dir, "pvd_snd[item]", "_C_snd_st", "_C_snd_sp")
    for p, (_, st) in enumerate(cases[0]["points"]):
        cmp_name = cmp_prefix + "_Cmp_" + st.upper()
        copy_file(G.BASE_DIR + "\\pat_temp\\" + cmp_name + ".sd", dest_dir)
        # S100 没有 Chroma 的 POWER_Shmoo_ON——用 CALL_MACRO POWER_ON(<电压>) 改 VCC 电平走扫
        # （同 Bor 欠压测试 `CALL_MACRO POWER_ON(borFallingvoltage[I])`，传数组元素；VCC 始终
        # 高于 POR 不复位、MCU 保持运行、固件 PVDO→PA13/PA14 映射不丢，迟滞记忆得以维持）。
        f.write("\t\tCALL_MACRO POWER_ON(pvd_v[item][" + str(p) + "]);\n")
        f.write("\t\tRUN_PATTERN(" + cmp_name + ":START," + cmp_name + ":END,1,VIH_5MHZ);\n\n")
    f.write("\t\tCALL_MACRO POWER_OFF();\n")
    f.write("\t}\n\n")
    f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
