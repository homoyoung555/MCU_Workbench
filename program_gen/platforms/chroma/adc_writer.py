# Chroma 平台：ADC-swd 族（F4）生成器。
#
# 母本填法（2026-07-16 起，limit 2026-07-21 改）：
#   FLOW：item="Adc_Test"、FV/FI="ADC1"/"ADC2"（几个 ADC 填几行）、mode="swd"、
#         target=分辨率(如 4096=12bit)、Vcc=VCC_TYP、cap_cfg。
#         **low_range/high_range(limit) 不再填**——分通道容差由独立 ADC sheet 给。
#   ADC：ADC/CH/force/limit；ADC 列按 ADC1/ADC2 分组并允许向下继承，CH 与 ADC 组合到
#        IOMUX.ADC 反查 pin；force 填激励/期望电压，limit 填码域对称容差。
#        无 ADC sheet 时兼容读取旧 IOMUX ADC/ADC FORCE/ADC LIMIT 三列。
#   VERSION：SWD PIN=capture 管脚；product name=swd pattern 前缀。
#
# 生成结构对齐用户示例 temp/ADC/ADC-SWD.txt：每个 ADC 一段（各自 POWER_ON/OFF）——
# RELAY_ON 全通道 → 逐通道 FORCE_V_PPMU 阶梯电压 → INIT pattern link → capture 段
# (SET_CAPTURE_MEM_MODE + CAP pattern + READ_CAPTURE_MEM_BLOCK) → C 解包(每通道
# 16bit 拼值、跳过 8=don't care) → 逐通道判定(期望码=(force/VCC)*分辨率 ± 容差)。
# swd 的 INIT/CAP pattern 由外部工具生成、生成器只 JUDGE_PAT link（不 copy_file，
# 同 mode=swd 机制；plncmp 不校验 JUDGE_PAT 引用是否存在）。
import re

import analog_sweep as A
from program_gen import state as G
from program_gen.core import encoding as E
from program_gen.platforms.chroma.capture import parse_cap_cfg, capture_unpack_write
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen.platforms.chroma.scan_writer import _load_real_pins, _normalize_pin
from program_gen.platforms.chroma.writers import _keil_step_write


def is_adc_force(fv_fi):
    """FV/FI 是否为 ADC force 标识（ADC1/ADC2/…）——main.py 按此分派到本 writer
    （2026-07-16 用户裁决修正：force 来源/分派看 FV/FI，不看 measure pin。measure pin
    要留给"量测/比较对象"——pat 模式 compare 时它填比较管脚如 PA13+PA14，不能再兼做
    ADC force 标识）。取代早先的 is_adc_meas_pin。"""
    return bool(re.match(r'ADC\d+$', str(fv_fi).strip(), re.I))


def _stem(item_name, sub_raw):
    """swd/cap pattern 派生用的 stem：有 sub 用 sub、无 sub(=/)用 item，去掉最后一个
    下划线段（单段原样），同 writers.py:_swd_pat_name 规则。"""
    name_src = item_name if str(sub_raw).strip() == "/" else str(sub_raw).strip()
    parts = name_src.split("_")
    return "_".join(parts[:-1]) if len(parts) > 1 else parts[0]


def _iomux_short(pin):
    """IOMUX pin 名（PA01/PB04/PY00-NRST）→ pin.dec 短名（PA1/PB4/PY0）：去 "-后缀"、
    端口字母后数字去前导 0。非 Pxx 格式（如 INT_BUF）原样返回。"""
    base = str(pin).split("-")[0].strip()
    m = re.match(r'(P[A-FY])0*(\d+)$', base, re.I)
    return (m.group(1).upper() + m.group(2)) if m else base


def _parse_adc_force(force_cell, adc_num):
    """ADC FORCE 单元格 → 该 ADC 的期望电压(float)。单值 "2.5" 直接用；共用通道两
    ADC 不同写 "ADC1=1.0,ADC2=1.2"，按 adc_num 取对应值（取不到抛异常，母本漏填暴露）。"""
    s = str(force_cell).strip()
    if "=" in s:
        d = {}
        for part in s.split(","):
            k, v = part.split("=", 1)
            d[k.strip().upper()] = v.strip()
        key = "ADC" + str(adc_num)
        if key not in d:
            raise ValueError("_parse_adc_force: 共用通道 force '" + s + "' 缺 " + key + " 的值")
        return float(d[key])
    return float(s)


def _adc_channels(adc_num, real_pins):
    """读 ADC sheet（旧母本回退 IOMUX），返回该 ADC 的**满通道**列表（按 in_num 升序、不过滤）：
    [(in_num, force_pin_or_None, force_val, chan_name, present, adc_limit), ...]。
    - 外部通道：force_pin=归一化短名；present=该 pin 在 real_pins（PIN DEC 引出）。
    - 内部通道（INT_*）：force_pin=None、present=True（无物理 pin，恒判）。
    - adc_limit：该通道对称容差（码），取自 ADC `limit` 列。
    **满通道（不因没引出而砍）**：外部工具 capture 抓的是全通道、缓冲区按 IN 号固定
    16bit/通道偏移，程序必须按最大通道数写、K 恒等 capture 位置，否则错位（用户上机验证；
    2026-07-21 与 S100 对齐——force/judge 只对 present 通道，判定用 if 守卫）。"""
    chans = {}
    for row in A.adc_source_rows(G.wb):
        adc = row["adc"]
        if adc is None or not str(adc).strip():
            continue
        adc = str(adc).strip()
        pin_raw = str(row["pin"]).strip()
        force_val = None   # 惰性解析：只在真有归属本 ADC 的标签时才读 FORCE/LIMIT 单元格
        adc_limit = None
        # 一格可含多个 '/'-分隔标签（2026-07-17 用户裁决新写法，如
        # "ADC1_IN8/ADC12_IN15"=ADC1 原生号 + ADC12 共享号）。逐段独立解析、归属规则
        # 不变：斜杠 pin 在 ADC1 段出两个通道（原生 IN8 + 共享 IN15）、在 ADC2 段只出
        # 一个（共享 IN15）。同一物理 pin 的两通道 force/limit 相同（共用该行单一值）。
        for part in adc.split("/"):
            m = re.match(r'ADC(12|\d)_IN(\d+)$', part.strip(), re.I)
            if not m:
                continue
            adc_tag, in_num = m.group(1), int(m.group(2))
            # 归属：本 ADC 独占（ADC<num>_）或共用（ADC12_）
            if adc_tag != str(adc_num) and adc_tag != "12":
                continue
            if force_val is None:
                force_val = _parse_adc_force(row["force"], adc_num)
                lv = row["limit"]
                if lv is None or str(lv).strip() == "":
                    raise ValueError("_adc_channels: pin '" + pin_raw + "' 的 limit 列空缺")
                adc_limit = int(float(str(lv).strip()))
            # 通道名（DATALOG 用）：外部=短 pin 名、内部=去 INT_ 前缀——与 S100 的
            # chanl_ADCn_item 及上机验证参考（"PD10"/"BUFOUT"）一致（2026-07-21 用户裁决）。
            if pin_raw.upper().startswith("INT_"):
                chan_name = pin_raw[4:].strip() or pin_raw
                chans[in_num] = (in_num, None, force_val, chan_name, True, adc_limit)
            else:
                short = _normalize_pin(_iomux_short(pin_raw))
                chans[in_num] = (in_num, short, force_val, short, short in real_pins, adc_limit)
    return [chans[k] for k in sorted(chans)]


def _adc_group_rows(item_name, cp_no, entry_mode):
    """同 item+CP 下所有 mode=="swd" 的 ADC 行（按 FLOW 原序），每行一个 ADC（sub 区分）。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == entry_mode]


def _keil_sram_loop_write(f, adc_num, chans, judge_idx, base, vcc_num, resolution):
    """Emit the Chroma runtime SRAM loop; Read_SRAM returns through sram_data[]."""
    downs, ups = [], []
    for chan in chans:
        center = int(round((chan[2] / vcc_num) * float(resolution)))
        downs.append(center - chan[5])
        ups.append(center + chan[5])
    n = len(chans)
    guard = "||".join("K==%d" % idx for idx in judge_idx) if judge_idx else "0"
    f.write("    int adc_down_%d[%d]={%s};\n" %
            (adc_num, n, ",".join(str(value) for value in downs)))
    f.write("    int adc_up_%d[%d]={%s};\n" %
            (adc_num, n, ",".join(str(value) for value in ups)))
    f.write("    for(K=0;K<%d;K++)\n    {\n" % n)
    f.write("      if(%s)\n      {\n" % guard)
    f.write("        Read_SRAM(%s+K*4);\n" % hex(base).upper())
    f.write("        SOCKET_INC(FRZ_OFF)\n        {\n")
    f.write('          sprintf(log_msg,"ADC%d_%%s_Verify",adc_chanel[K]);\n' % adc_num)
    f.write("          JUDGE_VARIABLE(SOCKET,sram_data[SOCKET],adc_down_%d[K],adc_up_%d[K],log_msg);\n"
            % (adc_num, adc_num))
    f.write("        }\n      }\n    }\n\n")


def _write_one_adc(f, z, adc_num, stem, chans, product, swd_pin, vcc, resolution,
                   cap_cfg, entry_mode, pat_dir):
    """生成一个 ADC 的完整测试段（对照 temp/ADC/ADC-SWD.txt）。**满通道**：数组按最大通道
    数写、K 恒等 capture 位置；force/judge 只对已引出(present)通道，判定用生成期 if 守卫
    （2026-07-21 与 S100 对齐，修早先"压缩数组致 capture 错位"的 bug）。INIT 用 swd 派生
    入口名，capture 走通用 capture_unpack_write。用 C 块 { } 隔离本段局部数组。"""
    n = len(chans)
    forces = [("%g" % c[2]) for c in chans]
    names = [c[3] for c in chans]
    limits = [str(c[5]) for c in chans]
    # force/relay 只对已引出(present)的外部 pin，保序去重（同一颗 pin 只 RELAY/FORCE 一次）；
    # judge_idx=present 通道在满数组里的下标（生成 if 守卫用）。
    force_pins, judge_idx = [], []
    for i, c in enumerate(chans):
        if c[4]:  # present
            judge_idx.append(i)
            if c[1] is not None and c[1] not in force_pins:
                force_pins.append(c[1])

    f.write("  ////////////////////adc" + str(adc_num) + "_test////////////////////\n")
    f.write("  {\n")
    f.write("    double adc_force[" + str(n) + "] = {" + ", ".join(forces) + "};\n")
    f.write('    char adc_chanel[' + str(n) + '][48] = {"' + '", "'.join(names) + '"};\n')
    f.write("    int adc_limit[" + str(n) + "] = {" + ", ".join(limits) + "};\n")
    f.write("    int adc_data[MAX_SITE][" + str(n) + "];\n\n")

    f.write("    POWER_ON(" + str(vcc).upper() + ");\n\n")
    f.write("    RELAY_ON(" + "+".join(force_pins) + ",PPMU_PDCL,2mS);\n\n")
    _forced = set()
    for in_num, pin, fv, cname, present, limit in chans:
        if present and pin is not None and pin not in _forced:
            _forced.add(pin)
            f.write("    FORCE_V_PPMU(" + pin + ", " + ("%g" % fv) + "V,,@32mA,,2mS);//" + cname + "\n")
    f.write("\n")

    if entry_mode == "keil":
        prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
        get_pin = G.col("VERSION", "GET PIN")[G.i]
        if prefix:
            _keil_step_write(f, z, get_pin, pat_dir, entry_only=True,
                             emit_banner=False, step_override=prefix)
        sheet_step = A.adc_step(G.wb, adc_num)
        if not sheet_step:
            raise ValueError("ADC%d: mode=keil 时 ADC sheet 的 step 必填" % adc_num)
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True,
                         emit_banner=False, step_override=sheet_step)
        cap_pattern, base, total_bits, bits_per_data = parse_cap_cfg(cap_cfg, product, stem)
        if str(cap_pattern).strip().upper() != "SRAM" or base is None or total_bits is None:
            raise ValueError("ADC%d: mode=keil 时 cap_cfg 必须为 SRAM-地址-总bit-位宽" % adc_num)
        if total_bits // bits_per_data != n:
            raise ValueError("ADC%d: cap_cfg 数据数 %d 与 ADC sheet 通道数 %d 不一致"
                             % (adc_num, total_bits // bits_per_data, n))
        vcc_num = E.resolve_vcc_value(
            vcc,
            G.col("VERSION", "vcc min")[G.i],
            G.col("VERSION", "vcc typ")[G.i],
            G.col("VERSION", "vcc max")[G.i],
        )
        _keil_sram_loop_write(
            f, adc_num, chans, judge_idx, base, vcc_num, resolution
        )
        if suffix:
            _keil_step_write(f, z, get_pin, pat_dir, entry_only=True,
                             emit_banner=False, step_override=suffix)
        f.write("    RELAY_OFF(" + "+".join(force_pins) + ",PPMU_PDCL,2mS);\n")
        f.write("    POWER_OFF();\n")
        f.write("  }\n\n")
        return

    # INIT 入口：swd 自动派生 <产品名>_SWD_<stem>（用户裁决：ADC 入口归 swd 派生管）
    init_pat = product + "_SWD_" + stem
    f.write('    TEST_NO(TEST_NUM); DATALOG_MSG="' + init_pat + '";\n')
    f.write("    JUDGE_PAT(" + init_pat + ",__" + init_pat + ");\n\n")

    # capture：cap_cfg 给 pattern/位宽；总 bit=满通道数×位宽（满 capture，cap_cfg bit 段 '/'）
    cap_pattern, _base, total_bits, bits_per_data = parse_cap_cfg(cap_cfg, product, stem)
    cap_pattern, _base, total_bits, bits_per_data = parse_cap_cfg(cap_cfg, product, stem)
    if total_bits is None:
        total_bits = n * bits_per_data
    # 判定守卫：只对 present 通道判（未引出的在满数组里占位、解包但不判）；限值走该通道
    # ADC LIMIT（对称 temp_target ± adc_limit[K]，取代原 FLOW 统一 ±32）。
    guard = "||".join("K==%d" % i for i in judge_idx) if judge_idx else "0"
    judge_body = (
        '        if(' + guard + ')\n        {\n'
        + '          sprintf(log_msg,"ADC' + str(adc_num) + '_%s_Verify",adc_chanel[K]);\n'
        + "          temp_target = ((adc_force[K]/" + str(vcc).upper() + ")*" + str(resolution) + ");\n"
        + "          JUDGE_VARIABLE(SOCKET,adc_data[SOCKET][K],temp_target-adc_limit[K],temp_target+adc_limit[K],log_msg);\n"
        + '        }\n'
    )
    f.write("    SOCKET_INC(FRZ_OFF)\n    {\n")
    capture_unpack_write(f, swd_pin, cap_pattern, total_bits, bits_per_data,
                         "adc_data", judge_body, indent="      ")
    f.write("    }\n\n")

    f.write("    RELAY_OFF(" + "+".join(force_pins) + ",PPMU_PDCL,2mS);\n")
    f.write("    POWER_OFF();\n")
    f.write("  }\n\n")


def adc_test_write(code_name, f, z, pat_dir):
    """item in ADC_ITEMS 且 mode=="swd"：生成 ADC-swd 测试函数。同 item+CP 多个 sub
    行（ADC1/ADC2…）合成一个 Adc_Test() 函数，每 ADC 一段（各自 POWER_ON/OFF）。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    rows = _adc_group_rows(item_name, cp_no, entry_mode)
    if z != rows[0]:
        return   # 非整组入口，让路

    product = G.col("VERSION", "product name")[G.i]
    swd_pin = G.col("VERSION", "SWD PIN")[G.i]
    real_pins = _load_real_pins(pat_dir)
    if entry_mode == "keil":
        copy_file(G.BASE_DIR + "\\pat_temp\\sram_cpature.pat", pat_dir)

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((rows[0] + 1) * 100) + ";\n")
    f.write('  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '";\n\n')
    f.write("  char log_msg[48];\n")
    f.write("  int temp_cap_data[1024];\n")
    f.write("  int temp_target = 0;\n\n")

    for r in rows:
        fvfi = str(G.col("FLOW", "FV/FI")[r]).strip()
        m = re.search(r'\d+', fvfi)
        if not m:
            raise ValueError("adc_test_write: FV/FI='" + fvfi + "' 无 ADC 编号（应为 ADC1/ADC2…）")
        adc_num = int(m.group(0))
        stem = _stem(item_name, G.col("FLOW", "sub")[r])
        chans = _adc_channels(adc_num, real_pins)
        _write_one_adc(f, r, adc_num, stem, chans, product, swd_pin,
                       G.col("FLOW", "Vcc")[r], G.col("FLOW", "target")[r],
                       G.col("FLOW", "cap_cfg")[r], entry_mode, pat_dir)

    f.write("}\n\n\n")
