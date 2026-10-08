# Chroma 平台：F2（DC 扫描族）管脚分组算法（2026-07-10，见
# .Codex/handoffs/2026-07-07-analog-test-family-classification-decision.md 续9起）。
#
# 用户裁决：管脚分组算法自动切分（不走母版人工指定列）——
#   ① NRST 不参与所有 DC 测试，分组前先排除；
#   ② 每组默认 8 根，无硬件强制上限（用户建议值，可调）；
#   ③ 预留"特殊pin编辑列"给个别判据/卡控不一致的管脚（列名/格式后续再定，
#      这里先占位，暂不接入）。
import os
import re

from program_gen.core.encoding import calc_limit
from program_gen.core.input_normalization import token_key
from program_gen.platforms.chroma.writers import Force_Judge, _keil_step_write, _swd_pat_name
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen import state as G

_GROUP_SIZE = 8
_PIN_LIST_RE = re.compile(r'PIN_LIST\([^)]*\)\s*\{(.*?)\}', re.DOTALL)
_PIN_GROUP_RE = re.compile(r'(PIN_GROUP\s*\{.*?)(\n\})', re.DOTALL)


_DC_EXCLUDED_PINS = {"NRST", "TP"}


def _pin_dec_io_order(pat_dir, excluded_pins=_DC_EXCLUDED_PINS):
    """解析已落地的 pat_dir/pin.dec 的 PIN_LIST 块，按声明顺序返回真实 IO 管脚名
    （排除 MLDPS 电源轨管脚、排除 `excluded_pins`、排除注释/占位行）——分组要
    保持稳定顺序，不能用 set。跟 scan_writer.py:_load_real_pins 同源但多做了
    IO 类型过滤+排除，两处都读同一份 pin.dec，暂不合并成共用函数（用途不同：
    那边要的是"存在性"集合，这边要的是"顺序+类型过滤"列表）。**2026-07-10
    用户从真实生成结果里发现：TP 也要跟 NRST 一样排除**（TP 是测试专用点，
    不是 DC 扫描该测的普通 IO）——默认排除集合是 DC 族用的
    `{"NRST","TP"}`；`vilvih_writer.py` 的 VIL/VIH 算法只排除 NRST（规则
    文档没提排除 TP），传自己的 `excluded_pins` 覆盖默认值。"""
    dec_path = os.path.join(pat_dir, "pin.dec")
    with open(dec_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = _PIN_LIST_RE.search(text)
    if not m:
        raise ValueError("_pin_dec_io_order: " + dec_path + " 找不到 PIN_LIST 块")
    pins = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        name, _, rest = line.partition("=")
        name = name.strip()
        pin_type = rest.rstrip(";").split("=")[-1].strip()
        if not name or pin_type != "IO" or name in excluded_pins:
            continue
        pins.append(name)
    return pins


def dc_pin_groups(pat_dir, group_size=_GROUP_SIZE):
    """F2 管脚分组：按 pin.dec 声明顺序把真实 IO 管脚（已排除 NRST/TP）切成
    组，组名固定 DC1_pins/DC2_pins/...。**2026-07-10 用户裁决改算法**：不是
    死板地"每组固定 group_size 根、剩下的塞进最后一组"（那样会出现最后一组
    特别小的怪现象，如 18 根按 8/8/2 切）——改成先算需要几组
    （`ceil(总数/group_size)`），再把总数尽量平均分到这几组（如 18 根 3 组
    → 6/6/6，19 根 3 组 → 7/6/6），保证每组都 <= group_size 且组间数量差
    最多 1。"""
    pins = _pin_dec_io_order(pat_dir)
    n = len(pins)
    if n == 0:
        return []
    num_groups = -(-n // group_size)  # ceil(n / group_size)
    base, extra = divmod(n, num_groups)
    groups = []
    idx = 0
    for g in range(num_groups):
        size = base + (1 if g < extra else 0)
        groups.append(("DC" + str(g + 1) + "_pins", pins[idx:idx + size]))
        idx += size
    return groups


def _insert_pin_groups(pat_dir, groups):
    """把 `groups`（[(name,[pin,...]),...]）追加进 pat_dir/pin.dec 的
    PIN_GROUP 块（幂等：组名已存在就跳过）——`ensure_dc_pin_groups`/
    `ensure_leakage_odd_even_groups` 共用这一段插入逻辑。"""
    dec_path = os.path.join(pat_dir, "pin.dec")
    with open(dec_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if groups and groups[0][0] in text:
        return  # 已经插过，幂等跳过
    m = _PIN_GROUP_RE.search(text)
    if not m:
        raise ValueError("_insert_pin_groups: " + dec_path + " 找不到 PIN_GROUP 块")
    insert = "".join("   " + name + " = " + "+".join(pins) + ";\n" for name, pins in groups)
    new_text = text[:m.end(1)] + "\n" + insert.rstrip("\n") + m.group(2) + text[m.end(2):]
    with open(dec_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)


def ensure_dc_pin_groups(pat_dir, group_size=_GROUP_SIZE):
    """把 `dc_pin_groups` 算出的分组追加进 pat_dir/pin.dec 的 PIN_GROUP 块（幂等：
    组名已存在就跳过，避免同一程序里 RPDRPU/VOLVOH 两个 F2 测试项各自调用时
    重复插入——这两项共用同一套分组，不是各自独立算一遍）。返回
    dc_pin_groups 的结果，供调用方（各测试项 writer）按组名循环生成代码。"""
    groups = dc_pin_groups(pat_dir, group_size)
    _insert_pin_groups(pat_dir, groups)
    return groups


def leakage_odd_even_groups(pat_dir):
    """Leakage 专用管脚分组（2026-07-13 用户裁决，不跟 RPDRPU/VOLVOH 共用
    DC1..DCN 分组）：按 pin.dec 声明顺序（已排除 NRST/TP）交替分成
    `Leakage_ODD_pins`/`Leakage_EVEN_pins` 两组——不能直接复用 pin.dec 里
    现成的 `ODD_pins`/`EVEN_pins`（那两个含 NRST，Leakage 测试不能测 NRST），
    所以新开一对专属分组，名字加 `Leakage_` 前缀区分。"""
    pins = _pin_dec_io_order(pat_dir)
    even = pins[0::2]
    odd = pins[1::2]
    return [("Leakage_EVEN_pins", even), ("Leakage_ODD_pins", odd)]


def ensure_leakage_odd_even_groups(pat_dir):
    """把 `leakage_odd_even_groups` 算出的分组追加进 pin.dec（幂等）。"""
    groups = leakage_odd_even_groups(pat_dir)
    _insert_pin_groups(pat_dir, groups)
    return groups


# F2 三个测试项 + 各自的低/高阶段 sub 命名（2026-07-10 用户裁决：读 sub 列字面值
# 判断阶段，不是行序；真实母本 `program_PCD009_V0.5.xlsx` 填的 sub 字面量是
# "<Kind>_Low_Test"/"<Kind>_High_Test" 这种风格，不是最初设想的裸词，按实测
# 母本改成跟它一致）。**force 值统一直接读该行 FV/FI 列、判据单位统一直接读
# UNIT 列**（2026-07-10 实测母本发现：Leakage/RPDRPU 两项母本也照样填了
# FV/FI，不是当初设想的"生成器硬编码 0V/VCC"；UNIT 列除 uA/V 外还会出现
# nA——`_dc_phase_fvalue_unit`/`kind` 这套按 item 分支猜测 force 值的逻辑
# 整个删掉，直接读母本更简单也更对）。
# `shared_swd_pattern`（2026-07-10 用户裁决，参考真实 SWD pattern 库
# `03_offline_mcu_ate/.../pattern.xlsx` 的 summary sheet：RPD/RPU、VOL/VOH
# 各自独立编号，唯独 Leakage 只有一个 pattern）：Leakage 的 SWD 配置 pattern
# 不区分低/高阶段（管脚配置一样，只是 PPMU force 值不同），只 link 一次、
# 名字用 item 派生（不带 sub 后缀）；RPD/RPU、VOL/VOH 两阶段管脚/芯片内部配置
# 真的不同，各自独立 pattern（沿用 sub 派生命名）。
DC_SCAN_ITEMS = {
    "DC_Leakage_Test": {"low_sub": "Leakage_Low_Test", "high_sub": "Leakage_High_Test",
                         "shared_swd_pattern": True, "shared_stem": "Leakage"},
    "DC_RPDRPU_Test": {"low_sub": "RPD_Test", "high_sub": "RPU_Test",
                        "shared_swd_pattern": False},
    "DC_VOLVOH_Test": {"low_sub": "VOL_Test", "high_sub": "VOH_Test",
                        "shared_swd_pattern": False},
}


def _dc_scan_spec(item_name):
    wanted = token_key(item_name)
    return next((spec for name, spec in DC_SCAN_ITEMS.items() if token_key(name) == wanted), None)


def is_dc_scan_item(item_name):
    return _dc_scan_spec(item_name) is not None


def _sub_label(sub_z):
    """DATALOG_MSG/注释横幅用的可读标签：sub 列填了就用 sub，sub=="/" 时退回
    用 item 本身（跟 `_keil_step_write`/`_swd_pat_name` 同一条既有规则）。"""
    sub_raw = str(G.col("FLOW", "sub")[sub_z]).strip()
    item_name = G.col("FLOW", "item")[sub_z]
    label = item_name if sub_raw == "/" else sub_raw
    return label.lower()


def _write_sub_banner(f, sub_z):
    """跟 `_keil_step_write` 同样的"////label////"横幅注释（2026-07-10 用户从
    真实生成结果里发现 swd 分支完全没有这行，不像 keil 分支那样有 sub 名做
    区隔）——swd 分支自己写 PPMU 循环、没经过 `_keil_step_write`，这里补上
    同款注释。"""
    f.write("  ////////////////////" + _sub_label(sub_z) + "////////////////////\n")


def _dc_group_loop(f, z, num_groups, fvalue, judge_unit):
    """针对一个 sub 阶段，用运行时 `for` 循环遍历所有管脚组做 FORCE+JUDGE+收尾
    归零（2026-07-13 用户提供新写法，见 `temp/DC/Chroma 示例代码`：Chroma
    内置 `GetPinChannel`/`GetPGChannel` 能在运行时按字符串名字反查
    `PIN_GROUP` 通道数组，配合 `sprintf` 拼 `"DC%d_pins"`，不用像原来那样
    按管脚组数在 Python 侧展开成 N 段重复代码——管脚组再多，生成的 `.pln`
    代码量也不变）。`GetPinbyName` 辅助函数由 `startup.py:_dc_group_helper_write`
    每个 CP 声明一次；`temp_group`/`log_msg` 两个 char 数组由调用方
    `dc_scan_test_write` 在函数体开头声明一次。

    force 值/判据单位直接读该行 FV/FI、UNIT 列；判据限值来自
    low_range(%)/high_range(%)（`calc_limit` 绝对限值分支，target 不参与）；
    量程改用判据限值的绝对值选档（代替 target），`Force_Judge` 内部按
    judge_unit（"A" in type / "V" in type）自动分派力压判流还是力流判压。
    **每个管脚组各自一次 `TEST_NUM++`+`DATALOG_MSG`**（`sprintf` 动态拼
    `<sub标签>_dc<N>`，2026-07-10 用户裁决保留：每组独立 TEST_NUM，不是
    像新示例那样整段共用一个）。`RELAY_ON`/`RELAY_OFF` 用 `PPMU_PDCL`
    （2026-07-13 用户裁决，替换原来的 `PPMU`）。"""
    low_cell = G.col("FLOW", "low_range(%)")[z]
    high_cell = G.col("FLOW", "high_range(%)")[z]
    low_limit = calc_limit(0, low_cell, high_cell, True)
    high_limit = calc_limit(0, low_cell, high_cell, False)
    magnitude = max(abs(low_limit), abs(high_limit))
    label = _sub_label(z)
    f.write("  for(I=1;I<=" + str(num_groups) + ";I++)\n  {\n")
    f.write('    sprintf(temp_group,"DC%d_pins",I);\n')
    f.write("    GetPinbyName(temp_group);\n")
    f.write("    TEST_NUM++;\n")
    f.write('    sprintf(log_msg,"' + label + '_dc%d",I);\n')
    f.write("    TEST_NO(TEST_NUM); DATALOG_MSG=log_msg;\n")
    f.write("    RELAY_ON(MT_GROUP_PINS, PPMU_PDCL, 2mS);\n")
    Force_Judge(judge_unit, "MT_GROUP_PINS", fvalue, magnitude, 4, "FORCE", "PPMU", low_cell, high_cell, f)
    f.write("    WAIT(2mS);\n")
    Force_Judge(judge_unit, "MT_GROUP_PINS", fvalue, magnitude, 4, "JUDGE", "PPMU", low_cell, high_cell, f)
    f.write("    FORCE_V_PPMU(MT_GROUP_PINS, 0V, ,@2uA, , 2mS);\n")
    f.write("    RELAY_OFF(MT_GROUP_PINS, PPMU_PDCL, 2mS);\n")
    f.write("  }\n\n")


def _leakage_odd_even_write(f, z, fvalue_odd, fvalue_even, judge_unit):
    """Leakage 专用：`Leakage_ODD_pins`/`Leakage_EVEN_pins` 两组同时施加**相反**
    电压+判定（2026-07-13 用户裁决，参考真实 S100 数据 `leakage_EVEN`/
    `leakage_ODD` 交叉 force 的做法，见 .Codex/handoffs/2026-07-07-analog-
    test-family-classification-decision.md）：本阶段行的 FV/FI 施加到 ODD 组，
    EVEN 组同时施加"另一阶段"（sibling 行）的 FV/FI——两组物理相邻管脚同一
    时刻处于不同电压，专门抓相邻管脚间的漏电；判据两组一样，都来自本阶段行
    的 low_range/high_range。不用 DC1..DCN 那套运行时 for 循环（只有固定
    2 个组，不需要）。"""
    low_cell = G.col("FLOW", "low_range(%)")[z]
    high_cell = G.col("FLOW", "high_range(%)")[z]
    low_limit = calc_limit(0, low_cell, high_cell, True)
    high_limit = calc_limit(0, low_cell, high_cell, False)
    magnitude = max(abs(low_limit), abs(high_limit))
    label = _sub_label(z)
    f.write("  RELAY_ON(Leakage_ODD_pins, PPMU_PDCL, 2mS);\n")
    f.write("  RELAY_ON(Leakage_EVEN_pins, PPMU_PDCL, 2mS);\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label + '_odd";\n')
    Force_Judge(judge_unit, "Leakage_ODD_pins", fvalue_odd, magnitude, 0, "FORCE", "PPMU", low_cell, high_cell, f)
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label + '_even";\n')
    Force_Judge(judge_unit, "Leakage_EVEN_pins", fvalue_even, magnitude, 0, "FORCE", "PPMU", low_cell, high_cell, f)
    f.write("  WAIT(2mS);\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label + '_odd";\n')
    Force_Judge(judge_unit, "Leakage_ODD_pins", fvalue_odd, magnitude, 0, "JUDGE", "PPMU", low_cell, high_cell, f)
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label + '_even";\n')
    Force_Judge(judge_unit, "Leakage_EVEN_pins", fvalue_even, magnitude, 0, "JUDGE", "PPMU", low_cell, high_cell, f)
    f.write("  FORCE_V_PPMU(Leakage_ODD_pins, 0V, ,@2uA, , 2mS);\n")
    f.write("  FORCE_V_PPMU(Leakage_EVEN_pins, 0V, ,@2uA, , 2mS);\n")
    f.write("  RELAY_OFF(Leakage_ODD_pins, PPMU_PDCL, 2mS);\n")
    f.write("  RELAY_OFF(Leakage_EVEN_pins, PPMU_PDCL, 2mS);\n\n")


def dc_scan_test_write(code_name, f, z, pat_dir, mode):
    """F2（DC扫描族）测试项：Leakage/RPDRPU/VOLVOH 三选一，item+CP 下按 sub
    列分低/高两个阶段（2026-07-10 用户裁决，见 .Codex/handoffs/2026-07-07-
    analog-test-family-classification-decision.md 续9~续12）。触发机制跟阶段
    是否共享上下电耦合（用户裁决）：
    - `mode=="keil"`：每个阶段各自独立一次 POWER_ON/触发(HL+发码)/PPMU组循环/
      POWER_OFF（对齐项目已有 `_multi_hex_keil_write`"每行各自独立上下电"）。
    - `mode=="swd"`：整个 item 共用一次 POWER_ON/POWER_OFF，内部循环两个阶段，
      各自 `JUDGE_PAT` link 自己的 pattern 再做 PPMU 组循环（对齐 `swd_
      pattern_write` 的多 sub 共电写法）。
    入口触发的 token 处理（keil 的 HL/裸数字/W，swd 的固定 pattern link）复用
    `_keil_step_write`/`_swd_pat_name`——DC 行的 step 列不应该出现 "T"（PPMU
    组循环是本函数专门写的代码，不走 T token 的单 pin judge），`emit_reset=
    False`（DC 测试不需要 reset_pattern）。"""
    item_name = G.col("FLOW", "item")[z]
    spec = _dc_scan_spec(item_name)
    if spec is None:
        return
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == mode):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    rows = [k for k in range(len(flow_item))
            if token_key(flow_item[k]) == token_key(item_name) and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == mode]
    if z != rows[0]:
        return  # 非整组入口，让路

    # Leakage 用固定 2 组 ODD/EVEN 交叉 force（2026-07-13 用户裁决），不跟
    # RPDRPU/VOLVOH 共用 DC1..DCN 运行时循环。
    is_leakage = token_key(item_name) == token_key("DC_Leakage_Test")
    if is_leakage:
        ensure_leakage_odd_even_groups(pat_dir)
        groups = None
    else:
        groups = ensure_dc_pin_groups(pat_dir)
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    product_name = G.col("VERSION", "product name")[G.i]

    def _check_sub(sub_z):
        sub_raw = str(G.col("FLOW", "sub")[sub_z]).strip()
        if sub_raw not in (spec["low_sub"], spec["high_sub"]):
            raise ValueError("dc_scan_test_write: " + item_name + " 行 sub='" + sub_raw
                              + "' 不是预期的 '" + spec["low_sub"] + "'/'" + spec["high_sub"] + "'")

    def _run_phase(sub_z):
        _check_sub(sub_z)
        judge_unit = G.col("FLOW", "UNIT")[sub_z]
        if is_leakage:
            sibling_z = rows[1] if sub_z == rows[0] else rows[0]
            fvalue_this = str(G.col("FLOW", "FV/FI")[sub_z]).strip()
            fvalue_other = str(G.col("FLOW", "FV/FI")[sibling_z]).strip()
            _leakage_odd_even_write(f, sub_z, fvalue_this, fvalue_other, judge_unit)
        else:
            fvalue = str(G.col("FLOW", "FV/FI")[sub_z]).strip()
            _dc_group_loop(f, sub_z, len(groups), fvalue, judge_unit)

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((rows[0] + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    f.write("  char temp_group[48],log_msg[48];\n\n")

    if mode == "keil":
        for sub_z in rows:
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[sub_z].upper() + ");\n\n")
            # entry_only=True：DC 行 step 列常带字面 "T"（真实母本反例），但
            # PPMU 组循环是下面 _run_phase 自己写的代码，T token 交给
            # _keil_step_write 处理会拿 DC 行"target 留空"的惯例硬崩——只处理
            # 入口触发（HL/裸数字/W），T 跳过（2026-07-13）。
            _keil_step_write(f, sub_z, get_pin, pat_dir, emit_reset=False, entry_only=True)
            f.write("  RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
            _run_phase(sub_z)
            f.write("  POWER_OFF();\n\n")
    else:  # swd
        f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[rows[0]].upper() + ");\n\n")
        if spec["shared_swd_pattern"]:
            # Leakage：SWD 配置对低/高两阶段一样，只 link 一次（2026-07-10 用户
            # 裁决，参考真实 SWD pattern 库只有一个 PTxxx_SWD_Leakage 条目，
            # 不像 RPD/RPU、VOL/VOH 那样两阶段各自独立编号）。
            pat_name = product_name + "_SWD_" + spec["shared_stem"]
            copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".pat", pat_dir)
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                    '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
            f.write("  RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
            for sub_z in rows:
                _write_sub_banner(f, sub_z)
                _run_phase(sub_z)
        else:
            for sub_z in rows:
                pat_name = _swd_pat_name(product_name, item_name, sub_z)
                copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".pat", pat_dir)
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                        '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
                f.write("  RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
                _write_sub_banner(f, sub_z)
                _run_phase(sub_z)
        f.write("  POWER_OFF();\n\n")

    f.write("}\n\n")
