# S100 平台：DC 扫描族（F2）生成器 —— 对位 chroma/dc_scan_writer.py。
#
# 2026-07-17 起分批补齐（用户裁决「做一个补一个」）：Leakage/RPDRPU/VOLVOH 已落地；
# 2026-07-20 补 VIHVIL（keil+swd，实现在 vilvih_writer.py，此处仅分派）。DC-scan 家族
# 已全部实现，_STUB_PLAN_ITEMS 里只剩 Hsi_Verify。
#
# 真实 golden 参考：`temp/Y_PY32E407.../Y_*.prg` 的 @@PLAN DC_leakage_Test /
# DC_RPDRPU_Test / IO_VOH_VOL_2P7V —— 核心是 `LOGIC_PPMU_FV`(施压) + `LOGIC_PPMU_MI`
# / `LOGIC_PPMU_MV`(量测+判定+按 pin 记录)。**LOG_ALIAS 用内建 `[PINGROUP]` token
# 按 pin 展开日志名，前缀是静态串——不需要动态变量/startup sprintf**（那套是 ADC
# 因通道名非标准 pin 才要，用户 2026-07-17 明确的约束在此正好用 [PINGROUP] 化解）。
#
# 母本 DC_Leakage_Test 是 mode=keil（step 如 `HL-222-1-T`）：触发部分（H/L 序列+发码）
# 复用 s100/writers.py:_keil_step_write(entry_only=True)（跳过字面 T），量测部分是本
# 文件按 golden 生成的 ODD/EVEN 交叉 PPMU。pin 分组 Leakage_ODD/EVEN_pins 由
# s100/project_files.py 写进 @@PIN_GROUP_TABLE（排除 NRST）。
import re

from program_gen import state as G
from program_gen.core.encoding import calc_limit
from program_gen.core.input_normalization import token_key
from program_gen.platforms.s100.writers import _keil_step_write
from program_gen.platforms.s100.project_files import dc_pin_group_list
from program_gen.platforms.s100.vilvih_writer import _vilvih_write, vilvih_swd_write

# 已实现：Leakage、RPDRPU、VOLVOH、VIHVIL（keil+swd，2026-07-20）。
DC_SCAN_ITEMS = {
    "DC_Leakage_Test": {"low_sub": "Leakage_Low_Test", "high_sub": "Leakage_High_Test"},
    "DC_RPDRPU_Test": {"low_sub": "RPD_Test", "high_sub": "RPU_Test"},
    "DC_VOLVOH_Test": {"low_sub": "VOL_Test", "high_sub": "VOH_Test"},
    "DC_VIHVIL_Test": {"sub1": "VIHVIL1", "sub2": "VIHVIL2"},
}


def _canonical_dc_item(item_name):
    wanted = token_key(item_name)
    return next((name for name in DC_SCAN_ITEMS if token_key(name) == wanted), None)


def is_dc_scan_item(item_name):
    return _canonical_dc_item(item_name) is not None


def _force_v(fvalue):
    """FLOW.FV/FI → S100 PPMU_FV 的施压值：纯数字（可带 V/mV）用字面量（如 `0V`/`3.3V`），
    命名电平（如 `VCC_MAX`）用 `_C_<NAME>` 常量引用（同 golden `_C_VCC_MAX`）。"""
    s = str(fvalue).strip()
    if re.match(r'^-?\d+(\.\d+)?\s*[mM]?[vV]?$', s):
        s = s.replace(" ", "")
        return s if s.upper().endswith("V") else s + "V"
    return "_C_" + s.upper()


def _vcc_arg(vcc):
    """POWER_ON 的 VCC 参数：命名电平（VCC_MAX/VCC_TYP…）→ `_C_<NAME>`；数字（如 `2.7V`/
    `2.7`）→ 去 V 的纯数字字面量（POWER_ON 宏形参是 double，直接吃数字）。"""
    s = str(vcc).strip()
    if re.match(r'^-?\d+(\.\d+)?\s*[vV]?$', s):
        return s.rstrip("vV").strip()
    return "_C_" + s.upper()


def _leakage_write(f, rows, dest_dir, get_pin, hbin):
    """Leakage @@PLAN：单次 POWER_ON..POWER_OFF 包住低/高两阶段（HIGH/LOW 之间不上下电，
    2026-07-17 用户裁决），每阶段 keil 触发→ODD/EVEN 交叉施压→LOGIC_PPMU_MI 判 nA→
    IO_ALLPINS 复位放电（不 DISCONNECT）。ODD 组施加本行 FV/FI、EVEN 组施加另一
    阶段（sibling）的 FV/FI（相邻管脚异压抓漏电，对位 chroma:_leakage_odd_even_write）。
    判据两组相同、来自本行 low/high（target 恒为 0：leakage 母本 target 填 "/"，限值走
    ±绝对偏移，同 chroma 传 0）。"""
    item_name = "DC_Leakage_Test"
    plan = item_name.title()
    f.write("@@PLAN " + plan + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n	GO_THROUGH         = ON;\n	DISABLE_BY_MARK_NO = NULL;\n"
        "	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = " + plan + "; \n\n")
    # 单次上下电包住 低/高 两阶段（2026-07-17 用户裁决：HIGH/LOW 之间不上下电，对齐
    # golden Y_PY32E407 的单 POWER_ON..POWER_OFF 结构）。VCC 取入口行的 Vcc 列。
    vcc = str(G.col("FLOW", "Vcc")[rows[0]]).strip().upper()
    f.write("	CALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")
    for sub_z in rows:
        sibling_z = rows[1] if sub_z == rows[0] else rows[0]
        fv_this = _force_v(G.col("FLOW", "FV/FI")[sub_z])
        fv_other = _force_v(G.col("FLOW", "FV/FI")[sibling_z])
        low_cell = G.col("FLOW", "low_range(%)")[sub_z]
        high_cell = G.col("FLOW", "high_range(%)")[sub_z]
        low = calc_limit(0, low_cell, high_cell, True)
        high = calc_limit(0, low_cell, high_cell, False)
        unit = str(G.col("FLOW", "UNIT")[sub_z]).strip().upper()   # nA -> NA
        sub_label = str(G.col("FLOW", "sub")[sub_z]).strip().lower()

        # 触发：HIGH 行 step 带 HL/发码（entry_only 跳过 T）；LOW 行 step 仅 "T" → 无输出。
        _keil_step_write(f, sub_z, get_pin, dest_dir, entry_only=True)
        # 交叉施压：ODD 施本行 FV/FI、EVEN 施 sibling 的（必须分组，不能用 IO_ALLPINS）。
        f.write("	LOGIC_PPMU_FV(Leakage_ODD_pins, " + fv_this + ", E2, I1);\n")
        f.write("	LOGIC_PPMU_FV(Leakage_EVEN_pins, " + fv_other + ", E2, I1);\n")
        f.write("	WAIT(2MS);\n")
        f.write("	LOGIC_PPMU_MI(Leakage_ODD_pins, DOWN_LIMIT=" + str(low) + unit + ", UP_LIMIT="
                + str(high) + unit + ", LOG_ALIAS=" + sub_label + "_odd_[PINGROUP], LOG_UNIT=" + unit + ");\n")
        f.write("	LOGIC_PPMU_MI(Leakage_EVEN_pins, DOWN_LIMIT=" + str(low) + unit + ", UP_LIMIT="
                + str(high) + unit + ", LOG_ALIAS=" + sub_label + "_even_[PINGROUP], LOG_UNIT=" + unit + ");\n")
        # 复位放电：两组都回 0，用 IO_ALLPINS 一行（2026-07-17 用户裁决）；DISCONNECT 去掉。
        f.write("	LOGIC_PPMU_FV(IO_ALLPINS, 0V, E2, I1);\n\n")
    f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


def _rpdrpu_write(f, rows, dest_dir, get_pin, hbin):
    """RPDRPU @@PLAN：RPU/RPD 两阶段**各自 POWER_ON..POWER_OFF**（两种引脚状态需上下电
    区分，用户裁决 2026-07-17），每阶段 keil 触发→对单组 IO_Rpd_Rpu 施压→PPMU_MI 判 uA
    （[PINGROUP] 按 pin 记录）→IO_ALLPINS 复位→POWER_OFF。
    施压值/限值/触发全读母本对应 sub 行（RPU_Test 施 VCC_TYP 判 +uA、RPD_Test 施 0V 判
    -uA，母本字面，不猜语义）。钳位档 E2/I5（golden Y_PY32E407 用 I6，2026-07-17 用户改 I5 消 PPMU MI 精度告警）。
    单组 IO_Rpd_Rpu（全 IO 去 NRST）由 project_files 写进 @@PIN_GROUP_TABLE。"""
    plan = "DC_RPDRPU_Test".title()
    f.write("@@PLAN " + plan + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n	GO_THROUGH         = ON;\n	DISABLE_BY_MARK_NO = NULL;\n"
        "	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = " + plan + "; \n\n")
    # RPU/RPD 是两种不同的引脚状态（keil/swd 触发把芯片配成不同 pull 配置），必须各自
    # POWER_ON..POWER_OFF 区分（2026-07-17 用户裁决）——不同于 Leakage（全程模拟态、
    # HIGH/LOW 引脚状态一致、只 force 电压不同，单次上下电即可）。
    for sub_z in rows:
        vcc = str(G.col("FLOW", "Vcc")[sub_z]).strip().upper()
        fv = _force_v(G.col("FLOW", "FV/FI")[sub_z])
        low_cell = G.col("FLOW", "low_range(%)")[sub_z]
        high_cell = G.col("FLOW", "high_range(%)")[sub_z]
        low = calc_limit(0, low_cell, high_cell, True)
        high = calc_limit(0, low_cell, high_cell, False)
        unit = str(G.col("FLOW", "UNIT")[sub_z]).strip().upper()   # uA -> UA
        sub_label = str(G.col("FLOW", "sub")[sub_z]).strip().lower()

        f.write("	CALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")
        _keil_step_write(f, sub_z, get_pin, dest_dir, entry_only=True)
        f.write("	LOGIC_PPMU_FV(IO_Rpd_Rpu, " + fv + ", E2, I5);\n")
        f.write("	WAIT(5MS);\n")
        f.write("	LOGIC_PPMU_MI(IO_Rpd_Rpu, DOWN_LIMIT=" + str(low) + unit + ", UP_LIMIT="
                + str(high) + unit + ", LOG_ALIAS=" + sub_label + "_[PINGROUP], LOG_UNIT=" + unit + ");\n")
        f.write("	WAIT(1MS);\n")
        f.write("	LOGIC_PPMU_FV(IO_ALLPINS, 0V, E2, I5);\n")
        f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


def _volvoh_write(f, rows, dest_dir, get_pin, hbin, cp_no):
    """VOLVOH @@PLAN：VOL/VOH 两阶段**各自 POWER_ON..POWER_OFF**（两种引脚状态需上下电
    区分）。强制电流 PPMU_FI 一次能带的管脚数有限，须把 IO 拆成 DC{n}_pins 组**逐组**
    施 FI→量 V→复位→**DISCONNECT 释放 PMU 通道**（用户裁决保留，逐组 FI 不释放会超
    PMU 通道预算，区别于 Leakage/RPDRPU 的一次量测）。分组用 project_files.dc_pin_group_list
    与 .prj @@PIN_GROUP_TABLE 同源。施压值(FI 电流)/限值(V)/触发全读母本 sub 行。钳位
    E2/I7(FI)、E2/I2(FV 复位) 照 golden Y_PY32E407 @@PLAN IO_VOH_VOL_2P7V。"""
    plan = "DC_VOLVOH_Test".title()
    f.write("@@PLAN " + plan + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n	GO_THROUGH         = ON;\n	DISABLE_BY_MARK_NO = NULL;\n"
        "	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = " + plan + "; \n\n")
    groups = dc_pin_group_list(cp_no)
    for sub_z in rows:
        vcc = _vcc_arg(G.col("FLOW", "Vcc")[sub_z])
        fi = str(G.col("FLOW", "FV/FI")[sub_z]).strip()   # 电流字面量（如 4mA/-4mA）
        low_cell = G.col("FLOW", "low_range(%)")[sub_z]
        high_cell = G.col("FLOW", "high_range(%)")[sub_z]
        low = calc_limit(0, low_cell, high_cell, True)
        high = calc_limit(0, low_cell, high_cell, False)
        unit = str(G.col("FLOW", "UNIT")[sub_z]).strip().upper()   # V
        sub_label = str(G.col("FLOW", "sub")[sub_z]).strip().lower()

        f.write("	CALL_MACRO POWER_ON(" + vcc + ");\n\n")
        _keil_step_write(f, sub_z, get_pin, dest_dir, entry_only=True)
        for name, _pins in groups:
            f.write("	LOGIC_PPMU_FI(" + name + ", " + fi + ", E2, I7);\n")
            f.write("	WAIT(1MS);\n")
            f.write("	LOGIC_PPMU_MV(" + name + ", DOWN_LIMIT=" + str(low) + unit + ", UP_LIMIT="
                    + str(high) + unit + ", LOG_ALIAS=" + sub_label + "_[PINGROUP], LOG_UNIT=" + unit + ");\n")
            f.write("	LOGIC_PPMU_FV(" + name + ", 0V, E2, I2);\n")
            f.write("	LOGIC_DISCONNECT_PPMU_PIN(" + name + ");\n")
        f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


def dc_scan_test_write(code_name, f, z, mode):
    """DC 扫描族 @@PLAN 入口。返回 True=已处理（本族），False=未实现的 DC 族
    （调用方回退给占位）。同 item+CP 多 sub 行只在入口行触发一次。"""
    item_name = G.col("FLOW", "item")[z]
    canonical_item = _canonical_dc_item(item_name)
    if canonical_item is None:
        return False
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == mode):
        return True
    cp_no = G.col("FLOW", "CP NO")[z]
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    rows = [k for k in range(len(flow_item))
            if token_key(flow_item[k]) == token_key(item_name) and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == mode]
    if z != rows[0]:
        return True   # 非入口行，让路
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    hbin = G.col("FLOW", "Hbin")[z]
    if canonical_item == "DC_Leakage_Test":
        _leakage_write(f, rows, dest_dir, get_pin, hbin)
    elif canonical_item == "DC_RPDRPU_Test":
        _rpdrpu_write(f, rows, dest_dir, get_pin, hbin)
    elif canonical_item == "DC_VOLVOH_Test":
        _volvoh_write(f, rows, dest_dir, get_pin, hbin, cp_no)
    elif canonical_item == "DC_VIHVIL_Test":
        # VIHVIL 分 keil / swd 两套（2026-07-20，见 vilvih_writer.py）：keil 算法生成
        # .sd + POWER_ON_VIHVIL；swd 照 Chroma 移植（不可验证）。按当前分派 mode 选。
        if mode == "swd":
            vilvih_swd_write(f, rows, dest_dir, get_pin, hbin, cp_no)
        else:
            _vilvih_write(f, rows, dest_dir, get_pin, hbin, cp_no)
    return True
