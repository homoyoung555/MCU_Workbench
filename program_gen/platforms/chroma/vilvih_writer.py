# Chroma 平台：DC_VIHVIL_Test（VIL/VIH 阈值测试）的 keil 侧 pattern 生成算法
# （2026-07-14，见 .Codex/handoffs/2026-07-07-analog-test-family-classification-
# decision.md）。
#
# 算法来源：用户提供 `temp/DC/vilvih.txt`（文字规则）+ 两份真实参考 pattern
# `temp/DC/IO_VIL_VIH_1_F407V1.pat`/`IO_VIL_VIH_2_F407V1.pat`（85 管脚真实
# 产品，用逐位解码脚本反推验证过）。核心思路：
#   1. 把这颗芯片的真实管脚（排除 NRST）按 PA0..PA15,PB0..PB15,...,PF0..PF4
#      端口字母+编号排序，得到"正序"列表；"倒序"就是正序反过来。
#   2. VILVIH1：上排=正序、下排=倒序；VILVIH2：上排=倒序、下排=正序。
#   3. 从中间切开，总数是偶数时上下排各留一半；总数是奇数时，VILVIH1 让
#      上排多留一个（"保留上排中间PIN"），VILVIH2 让下排多留一个（"保留
#      下排中间PIN"）。
#   4. 上排=输入管脚，交替填 1010...（从 1 开始）；如果上排是"多留一个"的
#      那一侧，最后一个元素**复制前一个的值**（不是继续交替）——这就是文档
#      里"两根输入都为同一电平，另一根输出=这两根的与"背后的真实实现：并不是
#      真的算与逻辑，是两根输入本来就被强制成同一个电平，输出自然跟着一致。
#   5. 下排=输出管脚，每个位置直接镜像对应位置输入管脚的电平（1→H，0→L）；
#      如果下排是"多留一个"的那一侧，最后一个元素同样复制前一个的值。
#   6. 第二遍（互补组）：所有 1/0 取反、H/L 跟着取反，其余结构不变。
import os
import re

from program_gen.platforms.chroma.dc_scan_writer import _pin_dec_io_order, _PIN_GROUP_RE
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen.platforms.chroma.writers import _keil_step_write
from program_gen import state as G

_PIN_RE = re.compile(r'^P([A-F])(\d+)$', re.IGNORECASE)


def _pin_sort_key(pin):
    m = _PIN_RE.match(pin.strip())
    if not m:
        raise ValueError("_pin_sort_key: 无法识别的管脚名 '" + pin + "'（需要形如 'PA0'）")
    return (m.group(1).upper(), int(m.group(2)))


def vilvih_real_pins(pins):
    """从真实管脚列表里挑出参与 VIL/VIH 排序的管脚（排除 NRST 及任何不是
    'P<A-F><数字>' 形态的管脚，如 TP/VCC 系），按端口字母+编号正序排列。"""
    real = []
    for p in pins:
        p = p.strip()
        if p == "NRST":
            continue
        if not _PIN_RE.match(p):
            continue
        real.append(p)
    real.sort(key=_pin_sort_key)
    return real


def _alternating_values(n, high, low):
    """长度 n 的交替序列，从 high 开始（high,low,high,low,...）。"""
    vals = []
    for i in range(n):
        vals.append(high if i % 2 == 0 else low)
    return vals


def build_vilvih_halves(real_pins, variant):
    """按 `variant`（1 或 2）算出 (upper_pins, lower_pins, upper_vals_A,
    lower_vals_A)——upper=输入管脚+电平（"1"/"0"），lower=输出管脚+期望电平
    （"H"/"L"），已处理奇数总数时"多出的一个复制前一个值"的规则。"""
    ascending = real_pins
    descending = list(reversed(real_pins))
    n = len(ascending)
    mid = n // 2
    if variant == 1:
        upper_src, lower_src = ascending, descending
    else:
        upper_src, lower_src = descending, ascending

    if n % 2 == 0:
        upper_pins, lower_pins = upper_src[:mid], lower_src[:mid]
    elif variant == 1:
        upper_pins, lower_pins = upper_src[:mid + 1], lower_src[:mid]
    else:
        upper_pins, lower_pins = upper_src[:mid], lower_src[:mid + 1]

    upper_vals = _alternating_values(len(upper_pins), "1", "0")
    if len(upper_pins) > len(lower_pins) and upper_vals:
        upper_vals[-1] = upper_vals[-2]  # 多出的一个复制前一个，不继续交替

    lower_vals = []
    for i in range(len(lower_pins)):
        if i < len(upper_pins):
            lower_vals.append("H" if upper_vals[i] == "1" else "L")
        else:
            lower_vals.append(lower_vals[-1])  # 多出的一个复制前一个
    return upper_pins, lower_pins, upper_vals, lower_vals


def _complement(vals, a, b):
    return [b if v == a else a for v in vals]


def vilvih_pattern_text(pattern_name, real_pins, variant):
    """生成一份完整的 `.pat` 文件内容（`SET_DEC_FILE`+`HEADER`+`SPM_PATTERN`），
    结构逐字对齐真实参考 `IO_VIL_VIH_1_F407V1.pat`/`IO_VIL_VIH_2_F407V1.pat`
    （用解码脚本核对过）：
      Row1: 全 X + TS1
      Row2/3: caseA 输入电平 + 全 X 输出，RPT 1000 / RPT 10000（settle）
      Row4~13（10 行）: caseA 输入电平 + caseA 输出期望电平（H/L）
      Row14: 全 X（caseA/caseB 之间的过渡）
      Row15/16: caseB 输入电平 + 全 X 输出，RPT 1000 / RPT 10000
      Row17~26（10 行）: caseB 输入电平 + caseB 输出期望电平
      Row27: 全 X + STOP
    """
    upper_pins, lower_pins, upper_a, lower_a = build_vilvih_halves(real_pins, variant)
    upper_b = _complement(upper_a, "1", "0")
    lower_b = _complement(lower_a, "H", "L")
    all_pins = upper_pins + lower_pins
    n_upper, n_lower = len(upper_pins), len(lower_pins)
    all_x = "X" * (n_upper + n_lower)

    def row(upper_vals, lower_vals):
        return "".join(upper_vals) + "".join(lower_vals)

    case_a_input_row = row(upper_a, ["X"] * n_lower)
    case_a_full_row = row(upper_a, lower_a)
    case_b_input_row = row(upper_b, ["X"] * n_lower)
    case_b_full_row = row(upper_b, lower_b)

    lines = []
    lines.append('SET_DEC_FILE"pin.dec"')
    lines.append("")
    lines.append("HEADER")
    # HEADER 管脚列表按参考文件风格每 16 个一行，逗号分隔，末尾分号。
    for i in range(0, len(all_pins), 16):
        chunk = all_pins[i:i + 16]
        lines.append(",".join(chunk) + ("," if i + 16 < len(all_pins) else ";"))
        lines.append("")
    lines.append("")
    lines.append("SPM_PATTERN(" + pattern_name + "){")
    lines.append("")
    lines.append("*" + all_x + "*TS1;")
    lines.append("*" + case_a_input_row + "*RPT 1000;")
    lines.append("*" + case_a_input_row + "*RPT 10000;")
    for _ in range(10):
        lines.append("*" + case_a_full_row + "*;")
    lines.append("*" + all_x + "*;")
    lines.append("*" + case_b_input_row + "*RPT 1000;")
    lines.append("*" + case_b_input_row + "*RPT 10000;")
    for _ in range(10):
        lines.append("*" + case_b_full_row + "*;")
    lines.append("*" + all_x + "*STOP;")
    lines.append("")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_vilvih_pattern(pat_dir, pattern_name, real_pins, variant):
    text = vilvih_pattern_text(pattern_name, real_pins, variant)
    os.makedirs(pat_dir, exist_ok=True)
    with open(os.path.join(pat_dir, pattern_name + ".pat"), "w", encoding="utf-8") as fh:
        fh.write(text)


def vilvih_test_write(code_name, f, z, pat_dir):
    """DC_VIHVIL_Test（VIL/VIH 阈值测试）keil 侧：pattern 内容算法生成，不依赖
    外部工具（2026-07-14 用户裁决）。swd 侧不动——继续走通用
    `swd_pattern_write`（swd 的 pattern 由外部工具生成，只需要 link，机制早就
    有）。同 item+CP 下按 FLOW 原始行序分配 variant（第 1 行→VILVIH1，
    第 2 行→VILVIH2），两阶段各自独立一次 `POWER_VIHL_ON`/`POWER_OFF`
    （用户裁决，对齐早前真实参考 `.pln` 写法，不是普通 `POWER_ON`）。入口
    触发复用 `_keil_step_write(entry_only=True)`（跟 DC 扫描族同一套，母本
    这两行 step 目前没有 "T"，纯触发发码）。"""
    item_name = G.col("FLOW", "item")[z]
    if item_name != "DC_VIHVIL_Test":
        return
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "keil"):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    rows = [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "keil"]
    if z != rows[0]:
        return  # 非整组入口，让路

    real_pins = vilvih_real_pins(_pin_dec_io_order(pat_dir, excluded_pins={"NRST"}))
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    product_name = G.col("VERSION", "product name")[G.i]

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((rows[0] + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')

    for idx, sub_z in enumerate(rows):
        variant = idx + 1
        pat_name = product_name + "_VILVIH" + str(variant)
        write_vilvih_pattern(pat_dir, pat_name, real_pins, variant)
        f.write("  POWER_VIHL_ON(" + G.col("FLOW", "Vcc")[sub_z].upper() + ");\n\n")
        _keil_step_write(f, sub_z, get_pin, pat_dir, emit_reset=False, entry_only=True)
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
        f.write("  POWER_OFF();\n\n")

    f.write("}\n\n")


# =====================================================================
# DC_VIHVIL_Test swd 侧：5 个 pattern（1 个入口配置 + 4 个 LL/HH/HL/LH 捕获）
# 全部外部工具生成，生成器只管 link，不合成向量内容（2026-07-14 用户提供
# 真实参考 `temp/DC/VILVIH_SWD.txt`）。管脚分组 VILVIH_ODD/VILVIH_EVEN：
# 沿用 pin.dec 已有声明顺序，按管脚编号尾数奇偶分两组（"ODD"组=编号偶数、
# "EVEN"组=编号奇数——命名跟数值奇偶正好相反，是真实产品既有习惯，原样照抄
# 不改名字），排除 SWDIO（VERSION.SWD PIN）/SCLK（VERSION.CLK PIN）/NRST。
# =====================================================================

_VILVIH_CAP_CASES = [
    ("LL", "F0", "F0"),
    ("HH", "F1", "F1"),
    ("HL", "F1", "F0"),
    ("LH", "F0", "F1"),
]


def vilvih_odd_even_groups(pat_dir):
    swd_pin = G.col("VERSION", "SWD PIN")[G.i]
    clk_pin = G.col("VERSION", "CLK PIN")[G.i]
    excluded = {"NRST", swd_pin, clk_pin}
    pins = _pin_dec_io_order(pat_dir, excluded_pins=excluded)
    odd_group, even_group = [], []
    for p in pins:
        m = _PIN_RE.match(p)
        if not m:
            continue  # 非 "P<字母><数字>" 形态的管脚（如 TP）不参与分组
        num = int(m.group(2))
        (odd_group if num % 2 == 0 else even_group).append(p)
    return odd_group, even_group


def ensure_vilvih_odd_even_groups(pat_dir):
    """把 `vilvih_odd_even_groups` 算出的两组追加进 pat_dir/pin.dec 的
    `PIN_GROUP` 块（幂等：`VILVIH_ODD` 已存在就跳过）。"""
    odd_group, even_group = vilvih_odd_even_groups(pat_dir)
    dec_path = os.path.join(pat_dir, "pin.dec")
    with open(dec_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if "VILVIH_ODD" in text:
        return odd_group, even_group
    m = _PIN_GROUP_RE.search(text)
    if not m:
        raise ValueError("ensure_vilvih_odd_even_groups: " + dec_path + " 找不到 PIN_GROUP 块")
    insert = ("   VILVIH_ODD  = " + "+".join(odd_group) + ";\n"
              + "   VILVIH_EVEN = " + "+".join(even_group) + ";\n")
    new_text = text[:m.end(1)] + "\n" + insert.rstrip("\n") + m.group(2) + text[m.end(2):]
    with open(dec_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return odd_group, even_group


def vilvih_swd_test_write(code_name, f, z, pat_dir):
    """DC_VIHVIL_Test 的 swd 侧：入口 link 一个配置 pattern
    （`<产品名>_SWD_VILVIH_Test`），再依次切换 `VILVIH_ODD`/`VILVIH_EVEN`
    的驱动电平（F0=低/F1=高）+ link 对应的捕获 pattern
    （`<产品名>_VILVIH_CAP_LL/HH/HL/LH`）。共用一次上下电（对齐参考程序
    `VILVIH_SWD.txt`，不像 keil 侧那样两阶段各自独立开关电——swd 这边只有
    一次 `POWER_ON`/`POWER_OFF`，中间靠 5 次 `JUDGE_PAT` 依次跑）。"""
    item_name = G.col("FLOW", "item")[z]
    if item_name != "DC_VIHVIL_Test":
        return
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "swd"):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    rows = [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "swd"]
    if z != rows[0]:
        return  # 非整组入口，让路

    ensure_vilvih_odd_even_groups(pat_dir)
    product_name = G.col("VERSION", "product name")[G.i]
    vcc = G.col("FLOW", "Vcc")[rows[0]].upper()

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((rows[0] + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    f.write("  POWER_ON(" + vcc + ");\n\n")

    entry_name = product_name + "_SWD_VILVIH_Test"
    copy_file(G.BASE_DIR + "\\pat_temp\\" + entry_name + ".pat", pat_dir)
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + entry_name + '";\n'
            '  JUDGE_PAT(' + entry_name + ',__' + entry_name + ');\n\n')

    for case, odd_mode, even_mode in _VILVIH_CAP_CASES:
        f.write("  PIN_MODE(VILVIH_ODD," + odd_mode + ",EDGE,MASK,IO_ON,OFF);\n")
        f.write("  PIN_MODE(VILVIH_EVEN," + even_mode + ",EDGE,MASK,IO_ON,OFF);\n\n")
        pat_name = product_name + "_VILVIH_CAP_" + case
        copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".pat", pat_dir)
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')

    f.write("  POWER_OFF();\n}\n\n")
