# Chroma 平台：PVD 族（欠压中断阈值四点法）生成器。
#
# 背景：PVD=可编程欠压中断。VDD 跌破阈值时置 PVDO 标志（不复位，器件照常运行），由固件把
# PVDO 镜像到比较管脚（本产品 PA13/PA14），四点夹逼两个带迟滞的阈值（下降沿 Vf / 上升沿
# Vr）。物理/四点公式见 `analog_sweep.pvd_cases`（BOR.PNG 逐值验证）；BOR 是欠压复位、fbist
# 结构，与本项无关（记待办，本轮不动）。
#
# 母本填法（用户 program_PCD009_V0.9）：
#   FLOW：item="Pvd_Test"、mode="keil"、FV/FI="PVD"（哨兵，据此分派）、meas pin="PA13+PA14"、
#         UNIT="pat"、Vcc="VCC_MAX"（高压起点）、step="HL-222-15-X"（进入码模板，X←case 号）。
#   PVD sheet：每 case 两行 up/down，各 min/typ/max + limit(内缩量 guard) + expect(HH/LL) + step。
#
# 结构（每 case 一次上下电，用户裁决 2026-07-24）：C `for` 循环逐 case（照 opa_writer 的
# 数组+循环风格，避免 7×4 全展开的冗长）——**跨 case 唯一变的是①四点电压②进入码 case 号发送**
# （用户观察），其余（进入码固定段 HL-222-15、四点判据序列 ll/hh/hh/ll）循环体内只写一遍：
#   for(c) { POWER_ON(VCC_MAX) → 进入码固定段 + case 号(sprintf+S:) → 四点 POWER_Shmoo_ON(
#            pvd_v[c][p]) + JUDGE_PAT(compare) → POWER_OFF() }
# 电压走 double pvd_v[N][4] 数组、case 号走 int pvd_snd[N] + sprintf 出 send_num 标签 + `S:`
# 运行时引用（同 opa_writer 的 `JUDGE_PAT(S:pat_st,...)`）。判据 compare pattern
# （pa13pa14_compare_hh/ll）由本 writer 按 sweep 表 expect 生成（不靠 get_pin_patterns_created
# ——那里 target 列是 "PVD" 哨兵、非比较状态，已加护栏跳过）。**要求各 case 判据序列相同**
# （本产品 down/up expect 跨 case 一致）；若某产品逐 case 不同，断言会报错提示改 compare 名数组。
import analog_sweep as A
from program_gen import state as G
from program_gen.core.encoding import decimal_to_hex
from program_gen.platforms.chroma.pattern_files import (
    copy_file, copy_trig_pat, trig_disp, LEVEL_SEQ_RE, default_pulse, level_seq_pat_name, parse_pulse_width,
    _compare_pat_write)


def is_pvd_row(z):
    """FLOW 行是否 PVD 族——FV/FI 哨兵 "PVD"（对位 opa 的 is_opa_row，分派看 FV/FI）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "PVD"


def _emit_entry(f, template, get_pin, pat_dir, snd_var, st_buf, sp_buf):
    """在 case 循环体内发进入码：FLOW.step 模板（如 "HL-222-15-X"）按 '-' 逐 token 走——
      X token   → 可变 case 号发送：sprintf 出 Trig_send_num:s<HH>_ST/_SP 标签 + `S:`
                  运行时引用（case 号=int 数组 snd_var，%02X 与 decimal_to_hex 对齐）。
      电平序列  → 固定 JUDGE_PAT(Trig_<levels>_<width>)（每迭代同字面量）。
      裸数字    → 固定 JUDGE_PAT(Trig_send_num:s<HH>_ST,..._SP)。
    只认这三类（PVD 进入码组成），其余报错。PVD 触发无 <PIN>: 前缀=默认触发 → 显示名 Trig
    （不烤死真实 pin，2026-07-24），种子按真实 get_pin、拷进程序目录时改名。行首 4 空格=
    循环体缩进（reindent 会再统一）。"""
    disp = trig_disp(get_pin, True)          # PVD 恒默认触发
    toks = template.split("-")
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "X":
            base = disp + "_send_num"
            copy_trig_pat(get_pin + "_send_num", base, pat_dir)
            f.write('    sprintf(' + st_buf + ',"' + base + ':s%02X_ST",' + snd_var + ');\n')
            f.write('    sprintf(' + sp_buf + ',"' + base + ':s%02X_SP",' + snd_var + ');\n')
            f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG=' + st_buf + ';\n'
                    '    JUDGE_PAT(S:' + st_buf + ',S:' + sp_buf + ');\n\n')
        elif LEVEL_SEQ_RE.fullmatch(tok):
            levels = tok
            rpt, width = default_pulse()
            if i + 1 < len(toks) and parse_pulse_width(toks[i + 1]):
                rpt, width = parse_pulse_width(toks[i + 1])
                i += 1
            pat_real = level_seq_pat_name(get_pin, levels, width)
            pat = level_seq_pat_name(disp, levels, width)
            copy_trig_pat(pat_real, pat, pat_dir)
            f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + pat + '";\n'
                    '    JUDGE_PAT(' + pat + ',__' + pat + ');\n\n')
        elif tok.isdigit():
            hh = decimal_to_hex(int(tok))
            base = disp + "_send_num"
            copy_trig_pat(get_pin + "_send_num", base, pat_dir)
            f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + base + ':s' + hh + '_ST";\n'
                    '    JUDGE_PAT(' + base + ':s' + hh + '_ST,' + base + ':s' + hh + '_SP);\n\n')
        else:
            raise ValueError("pvd_writer: 进入码 token 无法识别 '%s'"
                             "（PVD.step 只支持电平序列/裸数字/X，实际模板 '%s'）" % (tok, template))
        i += 1


def pvd_test_write(code_name, f, z, pat_dir):
    """生成一个 PVD 测试项（mode=keil）。CP gate 同其它 keil writer。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "keil"):
        return
    cases = A.pvd_cases(G.wb, required=True)
    item = G.col("FLOW", "item")[z]
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    template = str(G.col("FLOW", "step")[z]).strip()
    meas_pin = str(G.col("FLOW", "meas pin")[z]).strip()          # "PA13+PA14"
    cmp_prefix = meas_pin.replace("+", "").lower()                # "pa13pa14"
    pin1, pin2 = (meas_pin.split("+", 1) + [""])[:2]

    # 各 case 判据序列必须一致（循环体内四点判据只写一遍）——本产品 down/up expect 跨 case
    # 相同（都是 down=HH/up=LL），故四点序列恒为 [反down, down, 反up, up]=ll/hh/hh/ll。若某
    # 产品逐 case 不同，此处报错提示改用 compare 名数组 + S: 展开（同 case 号发送的写法）。
    seq = [st for _, st in cases[0]["points"]]
    for c in cases:
        if [st for _, st in c["points"]] != seq:
            raise ValueError("pvd_writer: 各 case 判据序列不一致（case %s=%s vs case %s=%s）；"
                             "当前循环写法要求跨 case 相同，逐 case 不同需改 compare 名数组+S: 展开"
                             % (cases[0]["case"], seq, c["case"], [st for _, st in c["points"]]))

    # compare pattern（HH/LL 各一份到 pat_temp，幂等）——按 sweep 表 expect 生成，骨架同
    # get_pin_patterns_created 的 _compare_pat_write。
    for st in A.pvd_compare_states(G.wb):
        _compare_pat_write(G.BASE_DIR + "\\pat_temp\\" + cmp_prefix + "_compare_" + st.lower() + ".pat",
                           pin1.strip(), pin2.strip(), st)

    n = len(cases)
    volt_rows = ["{" + ",".join(v for v, _ in c["points"]) + "}" for c in cases]
    # case 号发送值取 PVD sheet step 列（模板 X 的替换来源，本产品=case 号）；int 化供 send_num。
    snd_vals = [str(int(c["step"])) for c in cases]

    f.write("\n" + item + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n"
            '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item + '";\n\n')
    f.write("  double pvd_v[" + str(n) + "][4]={" + ",".join(volt_rows) + "};\n")
    f.write("  int pvd_snd[" + str(n) + "]={" + ",".join(snd_vals) + "};\n")
    f.write("  char snd_st[48],snd_sp[48];\n\n")

    f.write("  for(int item=0;item<" + str(n) + ";item++)\n  {\n")
    f.write("    POWER_ON(" + vcc + ");\n\n")
    _emit_entry(f, template, get_pin, pat_dir, "pvd_snd[item]", "snd_st", "snd_sp")
    for p, (_, st) in enumerate(cases[0]["points"]):
        cmp_name = cmp_prefix + "_compare_" + st
        copy_file(G.BASE_DIR + "\\pat_temp\\" + cmp_name + ".pat", pat_dir)
        f.write("    POWER_Shmoo_ON(pvd_v[item][" + str(p) + "]);\n")
        f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + cmp_name + '";\n'
                '    JUDGE_PAT(' + cmp_name + ',__' + cmp_name + ');\n\n')
    f.write("    POWER_OFF();\n\n")
    f.write("  }\n}\n")
