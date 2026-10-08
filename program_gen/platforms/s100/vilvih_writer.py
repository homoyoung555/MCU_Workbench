# S100 平台：DC_VIHVIL_Test（VIL/VIH 输入门限测试）生成器 —— 对位
# chroma/vilvih_writer.py（2026-07-20）。
#
# 关键结论（读 golden `temp/Y_PY32E407.../IO_VIL_VIH_1/2_*.sd` 反推）：S100 `.sd`
# 的 HEAD 脚序（上排升序 + 下排降序）与向量值排布（上排输入 `1010...`、下排输出
# `HLHL...`、奇数总数时多留的那一根复制前一个值）与 Chroma 算法**逐字一致**，27 行
# 结构也完全对应。所以 Chroma 的 `build_vilvih_halves`/`_alternating_values`/`_complement`
# 算法**直接照搬**（平台无关的纯管脚运算），只把产物外壳从 Chroma `.pat`
# （`SET_DEC_FILE`+`HEADER`+`SPM_PATTERN`+`*vec*TS1`）翻成 S100 `.sd`
# （`HEAD[PIN_NAME]`+`@@PATTERN_DEFINE`+`START:/END:`+`RPT`，时序由 RUN_PATTERN 的
# 第 4 参 VIH_5MHZ 提供）。
#
# 算法本身（正序/倒序切上下排、上排交替 1010、下排镜像 H/L、奇数补复制前值、caseB
# 取反）见 chroma/vilvih_writer.py 顶部注释，此处不重复。为避免 s100→chroma 的跨平台
# import（chroma/vilvih_writer.py 顶部会拖 chroma 专属依赖），这里把 ~40 行纯函数照抄
# 一份到 s100 侧。
#
# keil 侧（本母本 program_pcd101_V1.8 唯一用到）：每 variant（VIHVIL1/2）各自
# `CALL_MACRO POWER_ON_VIHVIL` + keil 触发（_keil_step_write entry_only）+
# `RUN_PATTERN(<算法生成的 .sd>:START,...:END,1,VIH_5MHZ)`，单次 POWER_OFF 收尾
# （对齐 golden @@PLAN IO_VIL_VIH：两次 POWER_ON_VIHVIL、一次 POWER_OFF）。pass/fail
# 靠 pattern 里的期望比较态 + @@PLAN 收尾 CONDITION IF_FAIL（同其它 keil 项）。
#
# swd 侧（本母本无 swd VILVIH 行、无外部捕获 .sd，2026-07-20 用户裁决「照 Chroma 移植
# 结构、本轮不可验证」）：照 chroma/vilvih_writer.py:vilvih_swd_test_write 移植——入口
# 配置 pattern + LL/HH/HL/LH 四捕获 + VILVIH_ODD/EVEN 分组切驱动电平 + 单次上下电。
# 外部 .sd 缺失时 copy_file 会落占位假图形（同 S100 既有兜底）。**待有真正带 swd
# VILVIH 行的母本 + 真实外部捕获 .sd 时再上机验证**。
import os
import re

from program_gen import state as G
from program_gen.platforms.s100.writers import _keil_step_write
from program_gen.platforms.s100.project_files import dc_io_pins
from program_gen.platforms.s100.pattern_files import copy_file

_PIN_RE = re.compile(r'^P([A-F])(\d+)$', re.IGNORECASE)


# =====================================================================
# 平台无关的纯管脚算法（照抄 chroma/vilvih_writer.py，逐字等价）
# =====================================================================

def _pin_sort_key(pin):
    m = _PIN_RE.match(pin.strip())
    if not m:
        raise ValueError("_pin_sort_key: 无法识别的管脚名 '" + pin + "'（需要形如 'PA0'）")
    return (m.group(1).upper(), int(m.group(2)))


def vilvih_real_pins(pins):
    """从真实管脚列表里挑出参与 VIL/VIH 排序的管脚（排除 NRST 及任何不是
    'P<A-F><数字>' 形态的管脚），按端口字母+编号正序排列。"""
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
    return [high if i % 2 == 0 else low for i in range(n)]


def build_vilvih_halves(real_pins, variant):
    """按 `variant`（1 或 2）算出 (upper_pins, lower_pins, upper_vals, lower_vals)——
    upper=输入管脚+电平（"1"/"0"），lower=输出管脚+期望电平（"H"/"L"），已处理奇数
    总数时"多出的一个复制前一个值"的规则。逐字对位 chroma/vilvih_writer.py。"""
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


# =====================================================================
# S100 .sd 产物（与 golden IO_VIL_VIH_1/2_*.sd 结构对齐）
# =====================================================================

def vilvih_sd_text(pattern_name, real_pins, variant):
    """生成一份完整的 `.sd` 文件内容。27 行向量结构与 golden 一致：
      START: 全 X（TS 由 RUN_PATTERN 的 VIH_5MHZ 给）
      caseA 输入行 ×2（RPT 1000 / RPT 10000 settle）
      caseA 全行 ×10（输入电平 + 期望输出 H/L）
      全 X（caseA/caseB 过渡）
      caseB 输入行 ×2（RPT 1000 / RPT 10000）
      caseB 全行 ×10
      END: 全 X
    HEAD 只列参与的上排+下排管脚（升序上排 + 倒序下排），逗号分隔+尾逗号+END_HEAD
    （同 write_hed_file 约定，YT5100_Pre 接受；VILVIH .sd 不含 TRIGPIN，同 golden）。"""
    upper_pins, lower_pins, upper_a, lower_a = build_vilvih_halves(real_pins, variant)
    upper_b = _complement(upper_a, "1", "0")
    lower_b = _complement(lower_a, "H", "L")
    all_pins = upper_pins + lower_pins
    n_upper, n_lower = len(upper_pins), len(lower_pins)
    all_x = "X" * (n_upper + n_lower)

    def row(upper_vals, lower_vals):
        return "".join(upper_vals) + "".join(lower_vals)

    ca_in = row(upper_a, ["X"] * n_lower)
    ca_full = row(upper_a, lower_a)
    cb_in = row(upper_b, ["X"] * n_lower)
    cb_full = row(upper_b, lower_b)

    lines = []
    lines.append('// SET_DEC_FILE "pin.dec"')
    lines.append("")
    lines.append("HEAD[PIN_NAME]:")
    for p in all_pins:
        lines.append("	" + p + ",")
    lines.append("END_HEAD;")
    lines.append("")
    lines.append("@@PATTERN_DEFINE")
    lines.append("// SPM_PATTERN (" + pattern_name + ") {")
    lines.append("")
    lines.append("START:" + all_x + ";")
    lines.append("      " + ca_in + ";RPT 1000;")
    lines.append("      " + ca_in + ";RPT 10000;")
    for _ in range(10):
        lines.append("      " + ca_full + ";")
    lines.append("      " + all_x + ";")
    lines.append("      " + cb_in + ";RPT 1000;")
    lines.append("      " + cb_in + ";RPT 10000;")
    for _ in range(10):
        lines.append("      " + cb_full + ";")
    lines.append("  END:" + all_x + ";")
    lines.append("")
    lines.append("@@END_PATTERN_DEFINE")
    lines.append("")
    return "\n".join(lines)


def write_vilvih_sd(dest_dir, pattern_name, real_pins, variant):
    os.makedirs(dest_dir, exist_ok=True)
    text = vilvih_sd_text(pattern_name, real_pins, variant)
    with open(os.path.join(dest_dir, pattern_name + ".sd"), "w", encoding="utf-8") as fh:
        fh.write(text)


_PLAN_HEAD = (
    "	SITE_SEQUENCE      = OFF;\n	GO_THROUGH         = ON;\n	DISABLE_BY_MARK_NO = NULL;\n"
    "	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = ")


def _vilvih_write(f, rows, dest_dir, get_pin, hbin, cp_no):
    """keil 侧 @@PLAN：每 variant（VIHVIL1/2 = variant 1/2）算法生成一份 .sd 图形写进
    程序目录（由 get_sd_filenames_with_os 自动登记进 .prj），各自 CALL_MACRO
    POWER_ON_VIHVIL + keil 触发（entry_only 跳过字面 T）+ RUN_PATTERN，单次 POWER_OFF
    收尾（对齐 golden @@PLAN IO_VIL_VIH）。母本这两行量测列全 "/"，判据全在 pattern
    的期望比较态里，@@PLAN 收尾 CONDITION IF_FAIL 统一捕获。"""
    plan = "DC_VIHVIL_Test".title()
    f.write("@@PLAN " + plan + "\n")
    f.write(_PLAN_HEAD + plan + "; \n\n")
    real_pins = vilvih_real_pins(dc_io_pins(cp_no))
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    for idx, sub_z in enumerate(rows):
        variant = idx + 1
        pat_name = product + "_VILVIH" + str(variant)
        write_vilvih_sd(dest_dir, pat_name, real_pins, variant)
        vcc = str(G.col("FLOW", "Vcc")[sub_z]).strip().upper()
        f.write("	CALL_MACRO POWER_ON_VIHVIL(_C_" + vcc + ");\n\n")
        _keil_step_write(f, sub_z, get_pin, dest_dir, entry_only=True)
        f.write("	RUN_PATTERN(" + pat_name + ":START," + pat_name + ":END,1,VIH_5MHZ);\n\n")
    f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


# =====================================================================
# swd 侧（照 Chroma 移植，本轮不可验证）
# =====================================================================

# 四捕获 case：(名字, ODD 组驱动是否高, EVEN 组驱动是否高)。对位 chroma
# _VILVIH_CAP_CASES 的 F0(低)/F1(高)：LL 两组低、HH 两组高、HL 奇高偶低、LH 奇低偶高。
_VILVIH_CAP_CASES = [
    ("LL", False, False),
    ("HH", True, True),
    ("HL", True, False),
    ("LH", False, True),
]


def vilvih_odd_even_groups(cp_no):
    """按管脚编号尾数奇偶分两组（"ODD"组=编号偶数、"EVEN"组=编号奇数——命名跟数值
    奇偶正好相反，是真实产品既有习惯，原样照抄不改名），排除 SWD PIN/CLK PIN/NRST。
    逐字对位 chroma/vilvih_writer.py:vilvih_odd_even_groups。"""
    swd_pin = str(G.col("VERSION", "SWD PIN")[G.i]).strip()
    clk_pin = str(G.col("VERSION", "CLK PIN")[G.i]).strip()
    excluded = {"NRST", swd_pin, clk_pin}
    odd_group, even_group = [], []
    for p in dc_io_pins(cp_no):
        if p in excluded:
            continue
        m = _PIN_RE.match(p)
        if not m:
            continue
        num = int(m.group(2))
        (odd_group if num % 2 == 0 else even_group).append(p)
    return odd_group, even_group


def _vcc_drv(hi, vcc_const):
    """swd 捕获时某组驱动电平：hi=True → 驱动到 vcc（F1 高，用 @@PLAN 作用域内的
    命名电压常量 `_C_<VCC>`，**不能用 `_C_vccVolt`——那是 @@MACRO 形参、PLAN 里未定义**），
    False → 0V（F0 低）。"""
    return vcc_const if hi else "0.0V"


def vilvih_swd_write(f, rows, dest_dir, get_pin, hbin, cp_no):
    """swd 侧 @@PLAN：入口 link 一个配置 pattern（<产品名>_SWD_VILVIH_Test），再依次
    对 VILVIH_ODD/EVEN 两组切驱动电平（LL/HH/HL/LH）+ link 对应捕获 pattern
    （<产品名>_VILVIH_CAP_<case>）。共用一次上下电（对位 chroma
    vilvih_swd_test_write）。**不可验证**：本母本无 swd 行、外部捕获 .sd 缺失走占位。
    F0/F1 → S100 驱动电平切换（LOGIC_SET_DRV_LEVEL）是缺 golden 时的结构性近似，
    待真实 swd VILVIH golden 再核实。"""
    plan = "DC_VIHVIL_Test".title()
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    vcc = str(G.col("FLOW", "Vcc")[rows[0]]).strip().upper()

    f.write("@@PLAN " + plan + "\n")
    f.write(_PLAN_HEAD + plan + "; \n\n")
    f.write("	CALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")

    entry_name = product + "_SWD_VILVIH_Test"
    # copy_file 的 destination 必须是**目录**（内部自己拼文件名；占位兜底分支同此约定）。
    copy_file(G.BASE_DIR + "\\pat_temp\\" + entry_name + ".sd", dest_dir)
    f.write("	RUN_PATTERN(" + entry_name + ":START," + entry_name + ":END,1,TS_5MHZ);\n\n")

    for case, odd_hi, even_hi in _VILVIH_CAP_CASES:
        # 缺 golden：用 LOGIC_SET_DRV_LEVEL 把两组分别驱动到高/低（对位 chroma 的
        # PIN_MODE F1/F0），再跑对应捕获 pattern。
        f.write("	LOGIC_SET_DRV_LEVEL(VILVIH_ODD, " + _vcc_drv(odd_hi, "_C_" + vcc) + ", 0.0V, 0.0V, VR1);\n")
        f.write("	LOGIC_SET_DRV_LEVEL(VILVIH_EVEN, " + _vcc_drv(even_hi, "_C_" + vcc) + ", 0.0V, 0.0V, VR1);\n\n")
        pat_name = product + "_VILVIH_CAP_" + case
        copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".sd", dest_dir)
        f.write("	RUN_PATTERN(" + pat_name + ":START," + pat_name + ":END,1,VIH_5MHZ);\n\n")

    f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
