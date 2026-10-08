# S100 平台：ADC-swd 族（F4）生成器。
#
# 落地依据（2026-07-20 用户裁决 + 上机验证参考）：
#   - **满通道数组 + 生成期 if 守卫**：外部工具的 capture pattern 抓的是**全通道**、缓冲区
#     按 IN 号固定 16bit/通道偏移，程序必须按最大通道数写、`index` 恒等于 capture 位置
#     （`index*16`），否则通道顺序错位（用户 Chroma 上机验证坐实）。force/judge 只对**已
#     引出**(pin 在 PIN DEC)的通道；judge 用生成期算好的 `if((index==a)||...)` 守卫，未引出
#     通道在数组里占位但不判不打印。
#   - **S100 datalog 只能走方案2**（用户明确）：全局 `chanl_ADCn_item[]`/`_C_ADCn_limit_*[]`/
#     `_C_LOG_MSG_ADCn` + `@@START_UP` 里 `SET_CSV_LOG_ALIAS` 预注册 CSV 列（Chroma 靠
#     `JUDGE_VARIABLE` 内联，S100 的 `C_COMPARE` 动态别名需先注册列）。
#   - 结构参照 golden `temp/LAB_PY32F420A.../Z_*.prg` 的 @@PLAN ADC1/ADC2_VCC_Test。
#
# ADC sheet：ADC/CH/force/limit；ADC+CH 到 IOMUX.ADC 反查 pin。limit 为分通道码域容差，
# 中心 `round(force/vcc*分辨率)`，上下限为中心 ± limit（旧母本兼容 IOMUX 三列）。
#
# 全局表 + CSV 注册由 s100/startup.py 调 `adc_global_decls`/`adc_csv_setup` 注入；@@PLAN 由
# main.py swd 分派调 `adc_test_write`。INIT/CAP pattern 是外部工具生成，pat_temp 没有则
# copy_file 落占位假图形（能编过、非真实向量，上机前需覆盖）。
import re

import analog_sweep as A
from program_gen import state as G
from program_gen.platforms.s100.capture import parse_cap_cfg
from program_gen.platforms.s100.pattern_files import copy_file
from program_gen.platforms.s100.writers import _keil_step_write

_ADC_ITEM = "Adc_Test"


def _present_pins(cp_no):
    """本 CP 引出的 IO 短名集合。惰性 import dc_io_pins——避免 project_files 反过来 import
    本模块（加 ADCn_PPMU_GROUP 定义）时的循环 import。"""
    from program_gen.platforms.s100.project_files import dc_io_pins
    return set(dc_io_pins(cp_no))


def is_adc_force(fv_fi):
    """FV/FI 是否为 ADC force 标识（ADC1/ADC2/…）——main.py 按此把 swd 行分派到本 writer。"""
    return bool(re.match(r'ADC\d+$', str(fv_fi).strip(), re.I))


def _iomux_short(pin):
    """IOMUX pin 名（PA00-WKUP/PC13-TAMPER…）→ pin.dec 短名（PA0/PC13）。非 Pxx 原样返回。"""
    base = str(pin).split("-")[0].strip()
    m = re.match(r'(P[A-FY])0*(\d+)$', base, re.I)
    return (m.group(1).upper() + m.group(2)) if m else base


def _parse_adc_force(force_cell, adc_num):
    """ADC FORCE 单元格 → 该 ADC 的激励电压(float)。单值直接用；共用通道两 ADC 不同写
    'ADC1=1.0,ADC2=1.2'，按 adc_num 取（缺则抛异常暴露母本漏填）。"""
    s = str(force_cell).strip()
    if "=" in s:
        d = {}
        for part in s.split(","):
            k, v = part.split("=", 1)
            d[k.strip().upper()] = v.strip()
        key = "ADC" + str(adc_num)
        if key not in d:
            raise ValueError("_parse_adc_force: 共用通道 force '" + s + "' 缺 " + key)
        return float(d[key])
    return float(s)


def _adc_channels_full(adc_num, present_pins):
    """读 ADC sheet（旧母本回退 IOMUX），返回该 ADC 的**满通道**列表（按 IN 号升序、不过滤）：
    [(in_num, chan_name, force_val, force_pin_or_None, present_bool, adc_limit), ...]。
    - 外部通道：force_pin=归一化短名；present=该 pin 在 present_pins（PIN DEC 引出）。
    - 内部通道（IOMUX pin 名 INT_*）：force_pin=None、present=True（无物理 pin，恒判）。
    - adc_limit：该通道对称容差（码），取自 ADC `limit` 列（分通道卡控）。
    同一 IN 号只保留一条（IN 唯一）。"""
    chans = {}
    for row in A.adc_source_rows(G.wb):
        adc = row["adc"]
        if adc is None or not str(adc).strip():
            continue
        pin_raw = str(row["pin"]).strip()
        force_val = None
        adc_limit = None
        for part in str(adc).split("/"):
            m = re.match(r'ADC(12|\d)_IN(\d+)$', part.strip(), re.I)
            if not m:
                continue
            adc_tag, in_num = m.group(1), int(m.group(2))
            if adc_tag != str(adc_num) and adc_tag != "12":
                continue
            if force_val is None:
                force_val = _parse_adc_force(row["force"], adc_num)
                lv = row["limit"]
                if lv is None or str(lv).strip() == "":
                    raise ValueError("_adc_channels_full: pin '" + pin_raw + "' 的 limit 列空缺")
                adc_limit = int(float(str(lv).strip()))
            if pin_raw.upper().startswith("INT_"):
                name = pin_raw[4:].strip() or pin_raw
                chans[in_num] = (in_num, name, force_val, None, True, adc_limit)
            else:
                short = _iomux_short(pin_raw)
                chans[in_num] = (in_num, short, force_val, short, short in present_pins, adc_limit)
    return [chans[k] for k in sorted(chans)]


def _adc_limits(chans, vcc_num, resolution):
    """逐通道限值（码）：中心=round(force/vcc*分辨率)，对称叠加该通道 ADC LIMIT 容差
    （down=中心-limit、up=中心+limit）。分通道卡控（2026-07-21 母本加 ADC LIMIT 列）。"""
    downs, ups = [], []
    for _in, _name, force, _pin, _present, limit in chans:
        center = int(round((force / vcc_num) * resolution))
        downs.append(center - limit)
        ups.append(center + limit)
    return downs, ups


def _adc_sub_rows(cp_no, entry_mode=None):
    """本 CP 的 Adc_Test swd 行（按 FLOW 原序），每行一个 ADC（FV/FI=ADC1/ADC2…）。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == _ADC_ITEM and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] in ("swd", "keil")
            and (entry_mode is None or flow_mode[k] == entry_mode)]


def has_adc(cp_no):
    return bool(_adc_sub_rows(cp_no))


def _adc_num_of(z):
    m = re.search(r'\d+', str(G.col("FLOW", "FV/FI")[z]).strip())
    if not m:
        raise ValueError("adc: FV/FI='" + str(G.col("FLOW", "FV/FI")[z]) + "' 无 ADC 编号")
    return int(m.group(0))


def _vcc_num():
    return float(G.col("VERSION", "vcc typ")[G.i])


def _adc_ctx(z, present_pins):
    """一个 ADC 的生成上下文：编号、满通道、限值（多处复用：全局表/CSV/@@PLAN）。"""
    adc_num = _adc_num_of(z)
    chans = _adc_channels_full(adc_num, present_pins)
    resolution = int(G.col("FLOW", "target")[z])
    downs, ups = _adc_limits(chans, _vcc_num(), resolution)
    return adc_num, chans, downs, ups


def _keil_sram_loop_write(f, adc_num, n, judge_idx, base):
    """Emit one S100 runtime SRAM loop using aliases registered in @@START_UP."""
    guard = "||".join("K==%d" % idx for idx in judge_idx) if judge_idx else "0"
    f.write("\tfor(int K=0;K<%d;K++)\n\t{\n" % n)
    f.write("\t\tif(%s)\n\t\t{\n" % guard)
    f.write("\t\t\tRead_SRAM(%s+K*4);\n" % hex(base).upper())
    f.write('\t\t\tsprintf(_C_LOG_MSG_ADC%d,"ADC%d_MEAN_%%s_Verify",chanl_ADC%d_item[K]);\n'
            % (adc_num, adc_num, adc_num))
    f.write("\t\t\tC_COMPARE(GBX2, DOWN_LIMIT=_C_ADC%d_limit_down[K], "
            "UP_LIMIT=_C_ADC%d_limit_up[K], LOG_ALIAS=_C_LOG_MSG_ADC%d);\n"
            % (adc_num, adc_num, adc_num))
    f.write("\t\t}\n\t}\n\n")


# =====================================================================
# 方案2：全局表 + @@START_UP CSV 注册（由 s100/startup.py 调用，gated by has_adc）
# =====================================================================

def adc_global_decls(cp_no):
    """ADC 全局表 C 声明文本（写进 item_variable_created）：每 ADC 一组满通道数组。"""
    rows = _adc_sub_rows(cp_no)
    if not rows:
        return ""
    present = _present_pins(cp_no)
    out = ["\n//////////////////// ADC channel table (full channels, order = IN# = capture offset) ////////////////////"]
    for z in rows:
        adc_num, chans, downs, ups = _adc_ctx(z, present)
        n = len(chans)
        names = '", "'.join(c[1] for c in chans)
        out.append('char chanl_ADC%d_item[%d][48]={"%s"};' % (adc_num, n, names))
        out.append('int  _C_ADC%d_limit_up[%d]  ={%s};' % (adc_num, n, ",".join(str(v) for v in ups)))
        out.append('int  _C_ADC%d_limit_down[%d]={%s};' % (adc_num, n, ",".join(str(v) for v in downs)))
        out.append('char _C_LOG_MSG_ADC%d[128]={0};' % adc_num)
    out.append("")
    return "\n".join(out) + "\n"


def adc_csv_setup(cp_no):
    """@@START_UP 里的 SET_CSV_LOG_ALIAS 预注册循环（每 ADC 一段，注册每通道 CSV 列+限值）。"""
    rows = _adc_sub_rows(cp_no)
    if not rows:
        return ""
    present = _present_pins(cp_no)
    out = ["\t//////////////////// ADC CSV alias pre-register (scheme 2) ////////////////////"]
    for z in rows:
        adc_num, chans, _d, _u = _adc_ctx(z, present)
        n = len(chans)
        out.append("\tfor(int item=0;item<%d;item++)\n\t{" % n)
        out.append('\t\tsprintf(_C_LOG_MSG_ADC%d,"ADC%d_MEAN_%%s_Verify",chanl_ADC%d_item[item]);'
                   % (adc_num, adc_num, adc_num))
        out.append("\t\tSET_CSV_LOG_ALIAS(LOG_ALIAS=_C_LOG_MSG_ADC%d, DOWN_LIMIT=_C_ADC%d_limit_down[item], UP_LIMIT=_C_ADC%d_limit_up[item], LOG_UNIT=NA);" % (adc_num, adc_num, adc_num))
        out.append("\t}")
    out.append("")
    return "\n".join(out) + "\n"


def adc_pin_group_defs(cp_no):
    """@@PIN_GROUP_TABLE 里的 `ADCn_PPMU_GROUP` 定义文本（每 ADC = 已引出的 force 外部
    pin，保序去重）。由 project_files.write_prj_file 调用（LOGIC_DRIVE_PIN 要 PinGroup 名）。
    仅本 CP 有 Adc_Test 时非空。"""
    rows = _adc_sub_rows(cp_no)
    if not rows:
        return ""
    present = _present_pins(cp_no)
    out = []
    for z in rows:
        adc_num, chans, _d, _u = _adc_ctx(z, present)
        fps = []
        for _in, _name, _force, pin, ppresent, _limit in chans:
            if ppresent and pin is not None and pin not in fps:
                fps.append(pin)
        if fps:
            out.append("\tADC%d_PPMU_GROUP, [%s];" % (adc_num, ",".join(fps)))
    return ("\n".join(out) + "\n") if out else ""


# =====================================================================
# @@PLAN Adc_Test（每 ADC 一段，各自 POWER_ON/OFF；由 main.py swd 分派调用）
# =====================================================================

def _emit_adc_block(f, z, product, swd_pin, present, entry_mode, dest_dir):
    adc_num, chans, downs, ups = _adc_ctx(z, present)
    n = len(chans)
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    resolution = int(G.col("FLOW", "target")[z])
    force_pins, judge_idx = [], []
    for i, (_in, _name, _force, pin, ppresent, _limit) in enumerate(chans):
        if ppresent:
            judge_idx.append(i)
            if pin is not None and pin not in force_pins:
                force_pins.append(pin)

    f.write("\t////////////////////adc%d_test////////////////////\n" % adc_num)
    f.write("\tCALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")
    _driven = set()
    for _in, _name, force, pin, ppresent, _limit in chans:
        if ppresent and pin is not None and pin not in _driven:
            _driven.add(pin)
            f.write("\tLOGIC_SET_DRV_LEVEL(%s, %gV, 0.0V, 0.0V, VR1);\n" % (pin, force))
    if force_pins:
        # LOGIC_DRIVE_PIN 需 PinGroup 名，不接受内联 + 脚列表（YT5100 编译实证）；
        # ADCn_PPMU_GROUP 由 project_files 写进 @@PIN_GROUP_TABLE（成员=同一批 present force pin）。
        f.write("\tLOGIC_DRIVE_PIN(ADC%d_PPMU_GROUP, DRIVE_ENABLE, HIGH);\n" % adc_num)
    f.write("\tWAIT(5MS);\n\n")

    if entry_mode == "keil":
        prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
        get_pin = G.col("VERSION", "GET PIN")[G.i]
        if prefix:
            _keil_step_write(f, z, get_pin, dest_dir, entry_only=True,
                             emit_banner=False, step_override=prefix)
        sheet_step = A.adc_step(G.wb, adc_num)
        if not sheet_step:
            raise ValueError("ADC%d: mode=keil 时 ADC sheet 的 step 必填" % adc_num)
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True,
                         emit_banner=False, step_override=sheet_step)
        cap_pattern, base, total_bits, bits_per_data = parse_cap_cfg(
            G.col("FLOW", "cap_cfg")[z])
        if str(cap_pattern).strip().upper() != "SRAM" or base is None or total_bits is None:
            raise ValueError("ADC%d: mode=keil 时 cap_cfg 必须为 SRAM-地址-总bit-位宽" % adc_num)
        if total_bits // bits_per_data != n:
            raise ValueError("ADC%d: cap_cfg 数据数 %d 与 ADC sheet 通道数 %d 不一致"
                             % (adc_num, total_bits // bits_per_data, n))
        _keil_sram_loop_write(f, adc_num, n, judge_idx, base)
        if suffix:
            _keil_step_write(f, z, get_pin, dest_dir, entry_only=True,
                             emit_banner=False, step_override=suffix)
        if force_pins:
            f.write("\tLOGIC_DRIVE_PIN(ADC%d_PPMU_GROUP, DRIVE_DISABLE);\n" % adc_num)
        f.write("\tCALL_MACRO POWER_OFF();\n\n")
        return

    init_pat = "%s_ADC%d_TEST_INIT" % (product, adc_num)
    cap_pat = "%s_ADC%d_CH_CAP" % (product, adc_num)
    f.write("\tRUN_PATTERN(%s:START,%s:END,1,TS_500K);\n\n" % (init_pat, init_pat))
    f.write("\tLOGIC_SET_AC_DATALOG(%s:START,%s:END,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\n" % (cap_pat, cap_pat))
    f.write('\tLOGIC_DAQ_TRANSFER_SETTING(%s, "1", TRIG=PTN_TRIG,ACLOG_FILTER_BY_PTN_TRIG_MODE);\n' % swd_pin)
    f.write("\tRUN_PATTERN(%s:START,%s:END,1,TS_500K);\n" % (cap_pat, cap_pat))
    f.write("\tLOGIC_DAQ_DATA_READ(DATA_COUNT=%d);\n\n" % (n * 16))

    # 通道循环 K、bit 循环 J（2026-07-21 用户裁决：两平台数据处理变量统一为 Chroma 的
    # K/J；循环边界/缓冲机制仍各自平台——S100 从 Sys_SW_BUFFER_DATA 取 15bit、不跳）。
    guard = "||".join("K==%d" % i for i in judge_idx) if judge_idx else "0"
    f.write("\tint adc_data%d[MAX_SITE][%d]={0};\n\tchar log_msg%d[32];\n\tdouble temp%d=0.0;\n" % (adc_num, n, adc_num, adc_num))
    f.write("\tfor(int K=0;K<%d;K++)\n\t{\n" % n)
    f.write("\t\tif(%s)\n\t\t{\n" % guard)
    f.write("\t\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t\t\t{\n")
    f.write("\t\t\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
    f.write("\t\t\t\tadc_data%d[T_SOCKET][K]=0;\n" % adc_num)
    f.write("\t\t\t\tfor(int J=0;J<15;J++)\n")
    f.write("\t\t\t\t\tadc_data%d[T_SOCKET][K] += (int)Sys_SW_BUFFER_DATA[T_SOCKET][J+(K*16)]<<J;\n" % adc_num)
    f.write('\t\t\t\tsprintf(_C_LOG_MSG_ADC%d,"ADC%d_MEAN_%%s_Verify",chanl_ADC%d_item[K]);\n' % (adc_num, adc_num, adc_num))
    f.write("\t\t\t\tGBX[1+1024*T_SOCKET]=adc_data%d[T_SOCKET][K];\n" % adc_num)
    f.write('\t\t\t\ttemp%d=(adc_data%d[T_SOCKET][K]/%d.0)*%g;\n' % (adc_num, adc_num, resolution, _vcc_num()))
    f.write('\t\t\t\tsprintf(log_msg%d,"S%%d_ADC%d_CH%%d = %%0.3f",T_SOCKET,K,temp%d);\n' % (adc_num, adc_num, adc_num))
    f.write("\t\t\t\tWRITELN(log_msg%d);\n" % adc_num)
    f.write("\t\t\t}\n")
    f.write("\t\t\tC_COMPARE(GBX2, DOWN_LIMIT=_C_ADC%d_limit_down[K], UP_LIMIT=_C_ADC%d_limit_up[K], LOG_ALIAS=_C_LOG_MSG_ADC%d);\n" % (adc_num, adc_num, adc_num))
    f.write("\t\t}\n\t}\n\n")

    if force_pins:
        f.write("\tLOGIC_DRIVE_PIN(ADC%d_PPMU_GROUP, DRIVE_DISABLE);\n" % adc_num)
    f.write("\tCALL_MACRO POWER_OFF();\n\n")


def adc_test_write(code_name, f, z):
    """@@PLAN Adc_Test：同 item+CP 多个 sub 行（ADC1/ADC2…）合成一个 @@PLAN，每 ADC 一段
    （各自 POWER_ON/OFF）。只在整组入口行触发一次。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    rows = _adc_sub_rows(cp_no, entry_mode)
    if z != rows[0]:
        return
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    swd_pin = str(G.col("VERSION", "SWD PIN")[G.i]).strip()
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    present = _present_pins(cp_no)
    hbin = G.col("FLOW", "Hbin")[z]
    if entry_mode == "keil":
        copy_file(G.BASE_DIR + "\\pat_temp\\sram_capture.sd", dest_dir)

    plan = _ADC_ITEM.title()
    f.write("@@PLAN " + plan + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n\tDISABLE_BY_MARK_NO = NULL;\n"
            "\tS_SETUP_FILE       = c:\\set.dat;\n\tREMARK             = " + plan + "; \n\n")
    for z2 in rows:
        adc_num = _adc_num_of(z2)
        if entry_mode == "swd":
            for suffix in ("_TEST_INIT", "_CH_CAP"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" + "%s_ADC%d%s.sd"
                          % (product, adc_num, suffix), dest_dir)
        _emit_adc_block(f, z2, product, swd_pin, present, entry_mode, dest_dir)
    f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
