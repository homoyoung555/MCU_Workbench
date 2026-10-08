# S100 平台：.hed/.prj/.dec/.tim 工程文件与引脚映射。
import os
import re
from program_gen.core.clock_force import s100_group3_half_period_ns
from program_gen import state as G


def VCC_pin_rebuild(pin_dec_num):
    vccpinname = []
    G.data.clear()
    G.a.clear()
    new_pin_name = []

    for u in range(len(G.col("PIN_DEC_128", "Site"))):
        if G.col("PIN_DEC_128", "CP NO")[u] == pin_dec_num:
            if G.col("PIN_DEC_128", "Site")[u] == 1 and "F" in str(G.col("PIN_DEC_128", "Trace")[u]):
                raw_pad_name = G.col("PIN_DEC_128", "E/C(Pad Name)")[u]
                processed_name = process_pin_name(raw_pad_name)
                if processed_name is not None:
                    vccpinname.append(processed_name)
                    G.data.append(G.col("PIN_DEC_128", "Trace")[u])

    dict_1 = dict(zip(vccpinname, G.data))

    for key in dict_1.keys():
        if dict_1[key] not in G.a:
            G.a.append(dict_1[key])
        elif dict_1[key] not in new_pin_name:
            new_pin_name.append(dict_1[key])
    dict_1 = dict(zip(G.data, vccpinname))
    # print(new_pin_name)
    for j in range(len(new_pin_name)):
        if len(new_pin_name) == 1:
            dict_1[new_pin_name[j]] = "VCC"
        else:
            dict_1[new_pin_name[j]] = "VCC" + str(j + 1)
    vccpinname = list(dict_1.values())
    new_pin_name.clear()
    return vccpinname


def process_pin_name(pin_name):
    """处理引脚名称，提取IO端口或保留原值"""
    import re
    pin_str = str(pin_name).strip()
    
    if "GND" in pin_str.upper():
        return None
    
    # 母本 pad 名既有 ``PAD_PD<13>``，也有 ``PAD_PD< 13>`` 这种尖括号后带空格的写法。
    # 两者必须都归一为 S100 pin.dec 可识别的 ``PD13``，不能把原始 pad 文本写进 .hed/.prj。
    io_pattern = r'(P[A-FY])[\[_<]\s*(\d+)'
    match = re.search(io_pattern, pin_str, re.IGNORECASE)
    if match:
        port = match.group(1).upper()
        num = match.group(2)
        return f"{port}{num}"
    
    return pin_str


def get_pin_data(cp_no):
    """获取指定CP的引脚数据"""
    pinname = []
    traces = []
    pad_nos = []
    cp_col = G.col("PIN_DEC_128", "CP NO")
    site_col = G.col("PIN_DEC_128", "Site")
    trace_col = G.col("PIN_DEC_128", "Trace")
    pad_col = G.col("PIN_DEC_128", "E/C(Pad Name)")
    pad_no_col = G.col("PIN_DEC_128", "Pad No.:")
    
    con_col_name = None
    for col_name in G.PIN_DEC_128.columns:
        if 'Con' in col_name or 'con' in col_name:
            con_col_name = col_name
            break
    con_col = list(G.PIN_DEC_128[con_col_name]) if con_col_name else []

    def _blank(value):
        return value is None or (isinstance(value, float) and value != value) or str(value).strip() == ""

    def _is_nc_without_connection(trace, row_index):
        """`NCxxx` 且 Con 为空表示该 pad 在该 CP 没有 tester 通道，不能写入 .prj。"""
        con_value = con_col[row_index] if row_index < len(con_col) else None
        return bool(re.fullmatch(r"NC\d+", str(trace).strip(), re.I)) and _blank(con_value)

    def _pin_has_no_connection(pin_name):
        rows = [u for u in range(len(cp_col))
                if cp_col[u] == cp_no and process_pin_name(pad_col[u]) == pin_name]
        return bool(rows) and all(_is_nc_without_connection(trace_col[u], u) for u in rows)
    
    unique_sites = sorted(set(site_col))
    if not unique_sites:
        return [], [], []
    
    def get_trace_key(trace, idx):
        trace = str(trace)
        dps_match = re.fullmatch(r"D(\d+)F\d*", trace.strip(), re.I)
        if dps_match:
            return f"LOGIC_DPS{dps_match.group(1)}"
        result = trace.split("F")[0]
        if "*" in result:
            result = result.split("*")[0]
        if result.isdigit():
            return result
        if result.startswith('N') and result[1:].isdigit():
            if idx < len(con_col):
                con_value = str(con_col[idx])
                if con_value.isdigit():
                    return con_value
                import re
                match = re.search(r'DPS(\d+)-(\d+)', con_value)
                if match:
                    return con_value
        return result
    
    def get_traces_for_pin(pin_name, site_val):
        pin_traces = []
        for u in range(len(cp_col)):
            if cp_col[u] == cp_no and site_col[u] == site_val and "GND" not in str(trace_col[u]):
                processed_pad = process_pin_name(pad_col[u])
                if processed_pad == pin_name:
                    pin_traces.append(trace_col[u])
        return list(dict.fromkeys(pin_traces))
    
    seen_trace_keys = {}
    for j in range(len(site_col)):
        if cp_col[j] == cp_no and site_col[j] == unique_sites[0] and "GND" not in str(trace_col[j]):
            processed_name = process_pin_name(pad_col[j])
            if processed_name is not None and not _pin_has_no_connection(processed_name):
                clean_name = processed_name.lstrip("/")
                all_site_traces = []
                for site_val in unique_sites:
                    site_traces = get_traces_for_pin(clean_name, site_val)
                    all_site_traces.append(site_traces)
                processed_trace_lists = [[process_trace_name(t, cp_no) for t in site_traces] for site_traces in all_site_traces]
                all_processed_traces = []
                for trace_list in processed_trace_lists:
                    all_processed_traces.extend(trace_list)
                trace_key = tuple(sorted(all_processed_traces))
                
                if trace_key not in seen_trace_keys:
                    pinname.append(processed_name)
                    traces.append(all_site_traces)
                    pad_nos.append(pad_no_col[j])
                    seen_trace_keys[trace_key] = processed_name
                else:
                    processed_name = "//" + clean_name
                    pinname.append(processed_name)
                    traces.append(all_site_traces)
                    pad_nos.append(pad_no_col[j])
    
    return pinname, traces, pad_nos


def process_trace_name(trace, cp_no=None):
    """处理Trace名称"""
    import re
    trace = str(trace)
    dps_match = re.fullmatch(r"D(\d+)F\d*", trace.strip(), re.I)
    if dps_match:
        return f"LOGIC_DPS{dps_match.group(1)}"
    result = trace.split("F")[0]
    if "*" in result:
        result = result.split("*")[0]
    
    if result.isdigit():
        return result
    
    if result.startswith('N') and result[1:].isdigit():
        trace_col = G.col("PIN_DEC_128", "Trace")
        cp_col = G.col("PIN_DEC_128", "CP NO")
        for i, t in enumerate(trace_col):
            if t == result and cp_col[i] == cp_no:
                for col_name in G.PIN_DEC_128.columns:
                    if 'Con' in col_name or 'con' in col_name:
                        con_value = str(G.PIN_DEC_128[col_name][i])
                        if con_value.isdigit():
                            return con_value
                        match = re.search(r'DPS(\d+)-(\d+)', con_value)
                        if match:
                            x1 = int(match.group(1))
                            x2 = int(match.group(2))
                            return f"LOGIC_DPS{(x1-1)*8+x2}"
        if cp_no in ["CP2", "CP3"]:
            for i, t in enumerate(trace_col):
                if t == result and cp_col[i] == "CP1":
                    for col_name in G.PIN_DEC_128.columns:
                        if 'Con' in col_name or 'con' in col_name:
                            con_value = str(G.PIN_DEC_128[col_name][i])
                            if con_value.isdigit():
                                return con_value
                            match = re.search(r'DPS(\d+)-(\d+)', con_value)
                            if match:
                                x1 = int(match.group(1))
                                x2 = int(match.group(2))
                                return f"LOGIC_DPS{(x1-1)*8+x2}"
    
    match = re.search(r'DPS(\d+)-(\d+)', result)
    if match:
        x1 = int(match.group(1))
        x2 = int(match.group(2))
        return f"LOGIC_DPS{(x1-1)*8+x2}"
    
    return result


def _relay_pad_names(cp_no, pin_cp, pin_pad, pin_x, pin_y):
    """按"有没有 XY 坐标"识别 relay/utility 通道（用户裁决 2026-07-06，跟 Chroma
    project_files.py 同款实现）：真实焊盘在 PIN DEC 里一定有 `X [um]`/`Y [um]` 物理
    坐标，relay（如继电器共用通道，多个 site 共用同一通道号那种）不是真实焊盘，坐标
    必为空。返回该 CP 下坐标全空的 pad 名集合；`pin_x`/`pin_y` 为 None（老母本/
    PIN DEC SINGEL 没有这两列）时返回空集合——单 site 场景本就不存在"多 site 共享
    通道"的问题，不需要特殊处理。"""
    if pin_x is None or pin_y is None:
        return set()

    def _blank(v):
        # 空单元格经 pandas 读出来是 float NaN（不是 None），NaN != NaN 恒真，
        # 用这个技巧判断，不用额外 import pandas/math。
        if v is None:
            return True
        if isinstance(v, float) and v != v:
            return True
        return str(v).strip() == ""

    names = set()
    for u in range(len(pin_cp)):
        if pin_cp[u] != cp_no:
            continue
        if _blank(pin_x[u]) and _blank(pin_y[u]):
            names.add(str(pin_pad[u]).strip())
    return names


def prj_power_pins(code_name):
    """真实需要上电的电源轨（名字含 "V"、未注释、排除 VDDD）。

    PIN DEC 中多个 VCC 与代表轨（如 VCC4）共用同一 DPS 通道，.prj 里以注释行
    存档（针卡有针但共通道）；上电/OS 等只能引用未注释的代表轨（用户裁决
    2026-06-12：本芯片=VCC4+VREFP）。VCC_pin_rebuild 的改名清单（VCC1/VCC2…）
    不可用于 .prg 引脚引用——那些名字未在 PIN_DEFINE_TABLE 定义。

    直接从 PIN DEC 源数据（get_pin_data）计算，复刻 .prj 生成时的判定
    （write_prj_file：name 含 "V" → pwr 行；name 以 // 开头 → 整行注释）。
    历史实现回读已生成的 .prj，但 _generate() 先写 .prg 后写 .prj，干净首跑时
    .prj 尚不存在 → except 静默返回空 → 逐轨电源指令丢失（顺序依赖 bug，被
    上一轮残留 .prj 掩盖）。改为源数据计算后与生成顺序无关、可干净复现。"""
    cp_no = code_name.split("_")[-1]
    pinname, _traces, _pad_nos = get_pin_data(cp_no)
    # 复刻 dec_file_created 对 pinname 的同款变换（表头 + NRST 改名），与写出的 .prj 一致
    pinname = ["//Pinname"] + list(pinname)
    nrst = G.col("VERSION", "NRST PIN")[0]
    pinname = ["NRST" if name == nrst else name for name in pinname]
    rails = [str(n).strip() for n in pinname
             if "V" in str(n) and not str(n).strip().startswith("//") and str(n).strip() != "VDDD"]
    # 不再静默兜底：解析不到电源轨 = PIN DEC 数据异常，产出无电源指令的 .prg 必错，显式报错。
    if not rails:
        raise RuntimeError(
            f"prj_power_pins：程序 {code_name}（CP {cp_no}）未解析到任何电源轨"
            f"（PIN_DEC_128 中名字含 V、未注释、非 VDDD 的代表轨）。请检查 PIN DEC 表数据。")
    return rails


def dc_io_pins(cp_no):
    """DC 扫描族用的 io 管脚顺序（与 write_prj_file 的 @@PIN_GROUP_TABLE io_pins 一致）：
    get_pin_data + NRST 改名 + 去表头/含TP/含V。dc_scan_writer（RPDRPU/VOLVOH 逐组
    PPMU）与 .prj 共用这一份，保证组名/成员对得上。"""
    pinname, _t, _p = get_pin_data(cp_no)
    nrst = G.col("VERSION", "NRST PIN")[0]
    pinname = ["NRST" if name == nrst else name for name in pinname]
    pinname_clean = [str(name).strip(" ") for name in pinname]
    return [name.lstrip("/") for name in pinname_clean
            if name not in ("//Pinname", "// Pinname") and "TP" not in name and "V" not in name]


def dc_pin_group_list(cp_no):
    """DC{n}_pins 分组 [(name, [pins]), ...]：io 按 8 一组、每组去 NRST、非空才算一组
    （复刻 write_prj_file 内联 DC 组生成逻辑）。VOLVOH 逐组 PPMU_FI 用。"""
    io_pins = dc_io_pins(cp_no)
    groups = []
    for i in range(0, len(io_pins), 8):
        chunk = [p for p in io_pins[i:i + 8] if p != "NRST"]
        if chunk:
            groups.append(("DC" + str(len(groups)) + "_pins", chunk))
    return groups


def write_hed_file(code_name, pinname):
    """生成.hed文件"""
    filepath = f"{G.OUT_DIR}\\{code_name}\\{code_name}.hed"
    with open(filepath, 'w') as f:
        f.write("HEAD[PIN_NAME]:\n")
        # 引脚清单全部以逗号分隔，TRIGPIN 必须在清单内（终结分号只在 END_HEAD）。
        # 原代码给最后一个引脚写分号、TRIGPIN 落在分号后 → pre.exe 报
        # "pin name: TRIGPIN not defined"（2026-06-12 编译器实证，旧验证程序为准）
        for j, name in enumerate(pinname):
            if name == "// Site":
                continue
            elif "V" in name:
                clean_name = name.lstrip("/")
                f.write(f"	//{clean_name},\n")
            else:
                f.write(f"	{name},\n")
        f.write("	TRIGPIN,\nEND_HEAD;\n")


def write_prj_file(code_name, pattern_sd, x, pinname, pad_nos, cp_no, relay_groups=None):
    """生成.prj文件"""
    filepath = f"{G.OUT_DIR}\\{code_name}\\{code_name}.prj"
    site_count = len(x[0]) if x else 0
    
    with open(filepath, 'w') as f:
        f.write("@@START_UP_TABLE\n")
        f.write(f"	TEST_DIE      = {site_count};\n    APG_NAME      = NULL;\n    PATTERN_NAME  = \n\n")
        
        for j, pat in enumerate(pattern_sd):
            suffix = "," if j != len(pattern_sd) - 1 else ";"
            f.write(f"{20*' '}{pat}{suffix}\n")
        
        f.write(f"\n    PROGRAM_NAME  = {code_name}.prg;\n")
        f.write(f"    PATTERN_HEAD  = {code_name}.hed;\n")
        f.write(f"    TIMING_NAME   = {code_name}.tim;\n")
        f.write("    SYSTEM_CLK    = 200Mhz;\n")
        f.write("    TESTER_TYPE   = 7D;\n")
        f.write("    BIN_MAP_TABLE = NEW_HARDWARE_BIN_STYLE;\n\n")
        f.write("@@END_START_UP_TABLE\n\n")
        
        f.write("@@PIN_DEFINE_TABLE\n\n")
        size = [len(name) for name in pinname]
        max_size = max(size) if size else 0
        
        all_traces = [str(trace) for trace_list in x for trace in trace_list]
        max_trace_len = max(len(trace) for trace in all_traces) if all_traces else 4
        if max_trace_len < 4:
            max_trace_len = 4
        
        io_pins = []
        pwr_pins = []
        for j, (name, trace_list) in enumerate(zip(pinname, x)):
            if "V" in name or (name.startswith("//") and "V" in name.lstrip("/")):
                pwr_pins.append((j, name, trace_list))
            else:
                io_pins.append((j, name, trace_list))
        
        sorted_pins = io_pins + pwr_pins
        
        for j, (orig_idx, name, trace_list) in enumerate(sorted_pins):
            if len(name) < max_size:
                name = " " * (max_size - len(name)) + name
            
            f.write(f"   {name} , ")
            
            for i, trace in enumerate(trace_list):
                trace = str(trace)
                if len(trace) < max_trace_len:
                    trace = " " * (max_trace_len - len(trace)) + trace
                # 行终结符：最后一个通道用 ";"，否则 ","。必须在所有分支统一判，
                # 否则单 site（只有 i==0 一个通道）永远走不到末尾的 ";" 分支，
                # 行会以 "," 结尾 → pre.exe 报 "TEST DIE vs Pin define table unmatch"。
                suffix = ";" if i == len(trace_list) - 1 else ","
                if i == 0 and j == 0:
                    f.write(f"pin_type, pin_no,     {trace}{suffix}")
                elif i == 0:
                    if "V" in name:
                        f.write(f"     pwr,{(7-len(str(pad_nos[orig_idx])))*' '}{pad_nos[orig_idx]},     {trace}{suffix}")
                    else:
                        f.write(f"      io,{(7-len(str(pad_nos[orig_idx])))*' '}{pad_nos[orig_idx]},     {trace}{suffix}")
                else:
                    f.write(f"{trace}{suffix}")
            f.write("\n")

        # TRIGPIN 是虚拟引脚（标记需动态修改/capture 的 pattern），必须在
        # PIN_DEFINE_TABLE 里以 SYS_SHARE_ 共享形式定义（用户给定格式 2026-06-12）：
        # 编号取未用值；通道选一个空闲号并按 site 数重复（各 site 共享同一通道）
        used_pin_nos = {int(str(n).strip()) for n in pad_nos if str(n).strip().isdigit()}
        trig_pin_no = (max(used_pin_nos) + 1) if used_pin_nos else 1
        used_channels = set()
        for trace_list in (x[1:] if x else []):
            for t in trace_list:
                ts = str(t).strip()
                if ts.isdigit():
                    used_channels.add(int(ts))
        trig_chan = 1
        while trig_chan in used_channels:
            trig_chan += 1
        chan = str(trig_chan)
        if len(chan) < max_trace_len:
            chan = " " * (max_trace_len - len(chan)) + chan
        trig_name = "SYS_SHARE_TRIGPIN"
        if len(trig_name) < max_size:
            trig_name = " " * (max_size - len(trig_name)) + trig_name
        f.write(f"   {trig_name} ,        i,{(7-len(str(trig_pin_no)))*' '}{trig_pin_no},")
        for i in range(site_count):
            suffix = ";" if i == site_count - 1 else ","
            lead = "     " if i == 0 else ""
            f.write(f"{lead}{chan}{suffix}")
        f.write("\n")

        f.write("@@END_PIN_DEFINE_TABLE\n\n")
        f.write("@@USER_RELAY_TABLE\n\n")
        # relay 通道（XY 坐标为空的 pad，见 dec_file_created/_relay_pad_names）按 site
        # 顺序逐个写一行，逗号分隔、分号收尾（用户给的格式，temp/S100relay.txxt）。
        for _relay_name, relay_row in (relay_groups or []):
            f.write("\t" + ",".join(str(t) for t in relay_row) + ";\n\n")
        f.write("@@END_USER_RELAY_TABLE\n\n")
        
        f.write("@@PIN_GROUP_TABLE\n\n")
        # USER_RELAY 调用消费具名 group；group 成员引用该 relay 的 Site1 编号。
        for relay_name, relay_row in (relay_groups or []):
            f.write(f'\t{relay_name},["{relay_row[0]}"];\n')
        pinname_clean = [name.strip(' ') for name in pinname]
        
        io_pins = [name.lstrip("/") for j, name in enumerate(pinname_clean) 
                   if name not in ["//Pinname", "// Pinname"] and "TP" not in name and "V" not in name]
        
        io_allpins = io_pins + (["TP"] if "TP" in pinname_clean else [])
        if io_allpins:
            f.write(f"	IO_ALLPINS, [{','.join(io_allpins)}];\n")
        
        odd_pins = [name.lstrip("/") for j, name in enumerate(pinname_clean) 
                    if name not in ["//Pinname", "// Pinname"] and "TP" not in name and "V" not in name and j % 2 == 0]
        if odd_pins:
            f.write(f"	ODD_pins, [{','.join(odd_pins)}];\n")
        
        even_pins = [name.lstrip("/") for j, name in enumerate(pinname_clean) 
                     if name not in ["//Pinname", "// Pinname"] and "TP" not in name and "V" not in name and j % 2 == 1]
        if even_pins:
            f.write(f"	EVEN_pins, [{','.join(even_pins)}];\n")

        # Leakage 专用 ODD/EVEN 分组（2026-07-17）：排除 NRST（漏电测试不测复位脚，
        # 对齐 chroma/dc_scan_writer.py:leakage_odd_even_groups）+ 按 io 顺序交替分两组。
        # 仅当母本真有 DC_Leakage_Test 时才写（否则不改动其它母本的 .prj 输出）。
        if "DC_Leakage_Test" in list(G.col("FLOW", "item")):
            leak_io = [p for p in io_pins if p != "NRST"]
            leak_even = leak_io[0::2]
            leak_odd = leak_io[1::2]
            if leak_odd:
                f.write(f"	Leakage_ODD_pins, [{','.join(leak_odd)}];\n")
            if leak_even:
                f.write(f"	Leakage_EVEN_pins, [{','.join(leak_even)}];\n")

        # RPDRPU 单组（2026-07-17）：全 IO 去 NRST，一组按 [PINGROUP] 逐 pin 判 uA。
        # 对齐 golden Y_PY32E407 @@PLAN DC_RPDRPU_Test 的 IO_Rpd_Rpu。仅当母本有该项才写。
        if "DC_RPDRPU_Test" in list(G.col("FLOW", "item")):
            rpu_io = [p for p in io_pins if p != "NRST"]
            if rpu_io:
                f.write(f"	IO_Rpd_Rpu, [{','.join(rpu_io)}];\n")

        # VILVIH_ODD/EVEN 分组（swd 侧，2026-07-20）：按管脚编号尾数奇偶分两组（命名与
        # 数值奇偶相反，照 chroma 既有习惯——"ODD"组=编号偶数），排除 NRST/SWD PIN/CLK PIN。
        # 仅当母本有 mode=swd 的 DC_VIHVIL_Test 行时才写（本母本 keil-only，不受影响；
        # 与 vilvih_writer.vilvih_odd_even_groups 同逻辑，保证组名/成员对得上）。
        if any(it == "DC_VIHVIL_Test" and md == "swd"
               for it, md in zip(G.col("FLOW", "item"), G.col("FLOW", "mode"))):
            import re as _re
            _excl = {"NRST", str(G.col("VERSION", "SWD PIN")[0]).strip(),
                     str(G.col("VERSION", "CLK PIN")[0]).strip()}
            _vodd, _veven = [], []
            for _p in io_pins:
                if _p in _excl:
                    continue
                _m = _re.match(r'^P([A-F])(\d+)$', _p, _re.IGNORECASE)
                if not _m:
                    continue
                (_vodd if int(_m.group(2)) % 2 == 0 else _veven).append(_p)
            if _vodd:
                f.write(f"	VILVIH_ODD, [{','.join(_vodd)}];\n")
            if _veven:
                f.write(f"	VILVIH_EVEN, [{','.join(_veven)}];\n")

        # ADCn_PPMU_GROUP（F4 ADC swd，2026-07-20）：每 ADC=已引出 force 外部 pin，
        # LOGIC_DRIVE_PIN 要 PinGroup 名。惰性 import 避免与 adc_writer 循环。
        from program_gen.platforms.s100.adc_writer import adc_pin_group_defs
        f.write(adc_pin_group_defs(cp_no))

        # OPA_INP0/INN/OUT_pins（F3 OPA swd，2026-07-23）：用户裁决 S100 也走 pin group；
        # 组成员按"可用实例"过滤（该 OPA 的 INP0 与 OUT 都出针才计入），与 Chroma 同源。
        from program_gen.platforms.s100.opa_writer import opa_pin_group_defs
        f.write(opa_pin_group_defs(cp_no))

        if cp_no == "CP3":
            dc_count = 0
            for i in range(0, len(io_pins), 8):
                dc_pins = [pin for pin in io_pins[i:i+8] if pin != "NRST"]
                if dc_pins:
                    f.write(f"	DC{dc_count}_pins, [{','.join(dc_pins)}];\n")
                    dc_count += 1
        
        f.write("\n@@END_PIN_GROUP_TABLE\n\n")
        
        f.write("@@BIN_MAP\n")
        f.write("	//SOFTWARE_BIN    HARDWARE_BIN       fail,     ink/sort\n")
        for j in range(1, 64):
            if j == 1:
                f.write(f"	 {j},                {j},                1,        0;\n")
            elif j < 10:
                f.write(f"	 {j},                {j},                0,        1;\n")
            else:
                f.write(f"	{j},               {j},                0,        1;\n")
        f.write("\n@@END_BIN_MAP\n\n")
        
        f.write("@@SOFTWARE_BIN_GOOD_DVC\n")
        f.write("	GOOD1=1,2;\n")
        f.write("@@END_SOFTWARE_BIN_GOOD_DVC\n")


def scan_real_pins(cp_no):
    """本 CP 真实管脚集合（短名 + NRST 改名），供 SCAN/Mbist 的 .sd 砍幽灵管脚用。
    复用 `dec_file_created` 的同一数据源 `get_pin_data`（不重造），保证"真实存在的
    管脚"判据跟最终 .hed/.dec 一致。"""
    pinname, _traces, _pad_nos = get_pin_data(cp_no)
    nrst = G.col("VERSION", "NRST PIN")[0]
    return {("NRST" if p == nrst else p) for p in pinname}


def dec_file_created(code_name, pattern_sd):
    cp_no = code_name.split("_")[-1]

    pinname, traces, pad_nos = get_pin_data(cp_no)
    if not pinname:
        return

    x = []
    for all_site_traces in traces:
        all_traces = []
        for site_traces in all_site_traces:
            all_traces.extend(list(site_traces))
        processed_traces = [process_trace_name(t, cp_no) for t in all_traces]
        x.append(processed_traces)

    # relay/utility 通道（XY 坐标为空，见 _relay_pad_names）跟真实焊盘分开处理：真实
    # 焊盘每个 site 的通道号必须唯一，relay 允许多个 site 共用同一通道号（如两两一组）
    # ——混在一起写进 @@PIN_DEFINE_TABLE 会被编译器判成 "Duplicate defined channel"
    # （2026-07-06 用户裁决，参照 temp/S100relay.txxt，写法见 write_prj_file 的
    # @@USER_RELAY_TABLE 段）。
    pin_cp_all = G.col("PIN_DEC_128", "CP NO")
    pin_pad_all = G.col("PIN_DEC_128", "E/C(Pad Name)")
    _has_xy = "X [um]" in G.PIN_DEC_128.columns and "Y [um]" in G.PIN_DEC_128.columns
    pin_x_all = G.col("PIN_DEC_128", "X [um]") if _has_xy else None
    pin_y_all = G.col("PIN_DEC_128", "Y [um]") if _has_xy else None
    relay_names = _relay_pad_names(cp_no, pin_cp_all, pin_pad_all, pin_x_all, pin_y_all)

    relay_groups = []
    kept_pinname, kept_x, kept_pad_nos = [], [], []
    for name, trace_list, pad_no in zip(pinname, x, pad_nos):
        if str(name).strip() in relay_names:
            relay_groups.append((str(name).strip(), trace_list))
        else:
            kept_pinname.append(name)
            kept_x.append(trace_list)
            kept_pad_nos.append(pad_no)
    pinname, x, pad_nos = kept_pinname, kept_x, kept_pad_nos
    if not pinname:
        return

    site = [f"Site{z}" for z in range(len(x[0]))]
    x.insert(0, site)
    pinname.insert(0, "//Pinname")
    pad_nos.insert(0, "")

    pinname = ["NRST" if name == G.col("VERSION", "NRST PIN")[0] else name for j, name in enumerate(pinname)]

    write_hed_file(code_name, pinname)
    write_prj_file(code_name, pattern_sd, x, pinname, pad_nos, cp_no, relay_groups)


def TEST_PRO(code_name):
    G.f.write("last_item_test()\n{\n")
    G.f.write('    printf("last item test finished !!");\n')
    G.f.write("}\n\n")
    G.f.write("TEST_PRO{\n  BEFORE_TEST: test_start;\n")
    w = []
    b = []
    q = []
    trash = []
    for j in range(len(G.col("FLOW", "item"))):
        w.append(G.col("FLOW", "item")[j].title())
        q.append(G.col("FLOW", "item")[j].title())
        b.append(G.col("FLOW", "CP NO")[j])
        if G.col("FLOW", "Bisection")[j] == "both" or G.col("FLOW", "Bisection")[j] == "both_m":
            if G.col("FLOW", "Bisection")[j] == "both_m":
                w.append("//"+G.col("FLOW", "item")[j].split("Trim")[0].title() + "Dac_Loop")
            else:
                w.append(G.col("FLOW", "item")[j].split("Trim")[0].title() + "Dac_Loop")
            q.append(G.col("FLOW", "item")[j].title())
            b.append(G.col("FLOW", "CP NO")[j])

    for j in range(len(w)):
        s = w[j]
        o = q[j]
        v = q[j]

        if len(w[j]) < 40:
            s += " " * (34 - len(w[j]))
            v += " " * (35 - len(q[j]))
            o = " " * 23 + ": #C(hw_" + o + " " * (35 - len(q[j]))
        if b[j] == code_name[G.i].split("_")[-1]:
            if s + b[j] not in trash:
                G.f.write("    " + s + "?" + o + "," + "sw_" + v + ");" + "\n")
                trash.append(s + b[j])
    G.f.write(
        "    last_item_test                    ?#C(all_pass,all_pass)  : #C(fail_last_item_test                   ,fail_last_item_test                   );\n")
    G.f.write("AFTER_TEST: test_end;\n\n")
    G.f.write("}\n")


_SCAN_FMT_MAP = {"NRZ": "NRZ", "RZ": "RZ", "RO": "RTO"}   # WGL 分类 → S100 DRV_FMT


def _scan_fmt_ns(v):
    """时序值格式化：整数不带小数点、小数保留（golden 有 40 也有 62.5）。"""
    return "%g" % round(float(v), 3)


def _scan_pin_norm(pin):
    """WGL 短管脚名 → S100 pin.dec 名：复位脚物理 pad（VERSION NRST PIN）改功能名
    NRST（对齐本文件既有 NRST 改名逻辑）。parse_timeplates 已把 PAD_PA_11 转成短名
    PA11，这里只补 NRST 改名。"""
    return "NRST" if pin == G.col("VERSION", "NRST PIN")[0] else pin


def _scan_ac_set_write(f, idx, ts_name, tp):
    """一个 WGL timeplate → 一个 @@AC_SET_<idx>（GROUP_2 内）。`ts_name`=带测试项
    前缀的时序名（2026-07-20 用户裁决走 golden 式每测试项独立命名，见
    scan_writer.scan_ts_name）。数值从 WGL frac×period 算：DRV_RS=第2沿(S点)、
    DRV_FL=第3沿、STB_RS=Q点（2026-07-19 用户裁决，与 Chroma DT0/DT1 同源）。NRZ
    管脚不单独声明、走 IO_ALLPINS 默认（golden 即如此，只 RZ/RTO 逐管脚列）。
    IO_ALLPINS 默认沿用本文件 GROUP_1/3 的 0.05/0.75/0.5×period 约定（golden 的
    调试后数值不复刻，2026-07-19 用户裁决）。"""
    from program_gen.core.wgl_parse import classify_pin_mode
    P = tp["period_ns"]
    f.write("\t\t@@AC_SET_" + str(idx) + "\n\t\t\t[NAME=" + ts_name + "]\n\t\t\t[TS]\n")
    f.write("\t\t\t\tPERIOD    = " + _scan_fmt_ns(P) + ";   //unit ns\n")
    f.write("\t\t\t\tIO_ALLPINS: {DRV_RS=" + _scan_fmt_ns(P * 0.05) + " }\n")
    f.write("\t\t\t\t\t    {DRV_FL=" + _scan_fmt_ns(P * 0.75) + "}\n")
    f.write("\t\t\t\t\t    {STB_RS=" + _scan_fmt_ns(P * 0.5) + "}\n")
    rzro = []   # 只逐个声明 RZ/RTO（NRZ 走 IO_ALLPINS 默认）
    for pin, info in tp["pins"].items():
        ie = info.get("input")
        if not ie or len(ie) != 3:
            continue
        oe = info.get("output", [])
        q = next((fr for fr, c in oe if c == "Q"), None)
        rzro.append((_scan_pin_norm(pin), ie[1][0] * P, ie[2][0] * P,
                     (q * P if q is not None else P * 0.5), classify_pin_mode(ie)))
    for pin, drv_rs, drv_fl, stb_rs, _m in rzro:
        f.write("\t\t\t\t\t  " + pin + ": {DRV_RS=" + _scan_fmt_ns(drv_rs) + " }\n")
        f.write("\t\t\t\t\t    {DRV_FL=" + _scan_fmt_ns(drv_fl) + "}\n")
        f.write("\t\t\t\t\t    {STB_RS=" + _scan_fmt_ns(stb_rs) + "}\n")
    f.write("\t\t\t[END_TS]\n\n\t\t\t[FMT]\n")
    f.write("\t\t\t\tIO_ALLPINS: {DRV_FMT=NRZ}\n")
    for pin, _rs, _fl, _stb, mode in rzro:
        f.write("\t\t\t\t\t  " + pin + ": {DRV_FMT=" + _SCAN_FMT_MAP[mode] + "}\n")
    f.write("\t\t\t[END_FMT]\n\t\t@@END_AC_SET_" + str(idx) + "\n\n")


def scan_group2_write(f, code_name):
    """SCAN/Mbist 时序写进 .tim 的 @@GROUP_2（2026-07-19 用户裁决：所有 SCAN/MBIST
    时序放 GROUP_2）。遍历本 CP 的 scan/mbist 行 → 各 pattern 的各 timeplate → 一个
    AC_SET。**按 timeplate 名去重**（用户裁决"定义过了就不再定义"）：同名只写首次
    遇到的定义，后续（哪怕内容不同，如 AC/DC 各自的 tp_setup）跳过。没有 scan/mbist
    行则整个 GROUP_2 不出现。"""
    from program_gen.platforms.s100.scan_writer import scan_group2_timesets
    # 有序时序列表（tim 的 AC_SET 编号 = .sd 的 G2_<编号>，同一来源，2026-07-20）。
    blocks = scan_group2_timesets(code_name)
    if not blocks:
        return
    f.write("\t@@GROUP_2\n")
    for idx, (full, tp) in enumerate(blocks, 1):
        _scan_ac_set_write(f, idx, full, tp)
    f.write("\t@@END_GROUP_2\n\n")


def tim_hed_write(code_name):
    with open(G.OUT_DIR + "\\" + code_name + "\\" + code_name + ".tim", 'w') as f:
        f.write("@@TIMING_DEFINE\n	@@GROUP_1\n		@@AC_SET_1\n			[NAME=TS_5MHZ]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = 200;   //unit ns\n")
        f.write("				IO_ALLPINS: {DRV_RS=10 }\n")
        f.write("						    {DRV_FL=150}\n")
        f.write("						    {STB_RS=100}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_RS=50 }\n")
        f.write("						    {DRV_FL=150}\n")
        f.write("						    {STB_RS=100} \n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_FMT=RZ}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_1\n\n")

        f.write("		@@AC_SET_2\n			[NAME=TS_500K]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = 2000;   //unit ns\n")
        f.write("				IO_ALLPINS: {DRV_RS=100 }\n")
        f.write("						    {DRV_FL=1500}\n")
        f.write("						    {STB_RS=1000}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_RS=500 }\n")
        f.write("						    {DRV_FL=1500}\n")
        f.write("						    {STB_RS=1000} \n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_FMT=RZ}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_2\n\n")

        f.write("		@@AC_SET_3\n			[NAME=TS_84uS]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = 84000;   //unit ns\n")
        f.write("				IO_ALLPINS: {DRV_RS=420  }\n")
        f.write("						    {DRV_FL=63000}\n")
        f.write("						    {STB_RS=42000}\n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_3\n\n")

        f.write("		@@AC_SET_4\n			[NAME=TS_erase]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = "+str(int((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5))+";   //unit ns 200ns=erase 2.5ms\n")
        f.write("				IO_ALLPINS: {DRV_RS="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.05))+" }\n")
        f.write("						    {DRV_FL="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.75))+"}\n")
        f.write("						    {STB_RS="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.5))+"}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_RS="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.25))+" }\n")
        f.write("						    {DRV_FL="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.75))+"}\n")
        f.write("						    {STB_RS="+str(int(((G.col("VERSION", "erase time(ms)")[0] / 0.0125) + 0.5)*0.5))+"} \n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_FMT=RZ}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_4\n\n")

        f.write("		@@AC_SET_5\n			[NAME=TS_pgm]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = "+str(int((G.col("VERSION", "program time(ms)")[G.i] / 0.0075) + 0.5))+";   //unit ns 200ns=pgm 1.5ms\n")
        f.write("				IO_ALLPINS: {DRV_RS="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.05))+" }\n")
        f.write("						    {DRV_FL="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.75))+"}\n")
        f.write("						    {STB_RS="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.5))+"}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_RS="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.25))+" }\n")
        f.write("						    {DRV_FL="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.75))+"}\n")
        f.write("						    {STB_RS="+str(int(((G.col("VERSION", "program time(ms)")[0] / 0.0075) + 0.5)*0.5))+"} \n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_FMT=RZ}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_5\n\n")

        f.write("		@@AC_SET_6\n			[NAME=VIH_5MHZ]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = 200;   //unit ns\n")
        f.write("				IO_ALLPINS: {DRV_RS=50  }\n")
        f.write("						    {DRV_FL=150 }\n")
        f.write("						    {STB_RS=100 }\n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_6\n\n")

        # 原代码把 TS_10MHZ 块编号误写为 AC_SET_2（重复定义），pre.exe 编译在
        # timing 阶段即中断且向量不编译——编号应为 7（2026-06-12 编译器实证）
        f.write("		@@AC_SET_7\n			[NAME=TS_10MHZ]\n			[TS ReserveEdges=14]\n")
        f.write("				PERIOD    = 100;   //unit ns\n")
        f.write("				IO_ALLPINS: {DRV_RS=5 }\n")
        f.write("						    {DRV_FL=75}\n")
        f.write("						    {STB_RS=50}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_RS=25 }\n")
        f.write("						    {DRV_FL=75 }\n")
        f.write("						    {STB_RS=50 } \n")
        f.write("			[END_TS]\n\n			[FMT]\n")
        f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
        f.write("					  "+G.col("VERSION", "CLK PIN")[0]+": {DRV_FMT=RZ}\n")
        f.write("			[END_FMT]\n		@@END_AC_SET_7\n\n")

        f.write("	@@END_GROUP_1\n\n")

        scan_group2_write(f, code_name)   # SCAN/Mbist 时序块（GROUP_2，2026-07-19）

        # GROUP_3：RCC/RTC 外灌时钟 <100kHz 降级分支专用（2026-07-07 用户裁决，独立
        # 分组、不接着 GROUP_1 加 AC_SET_8）。只在这个 CP 真有降级需求时才写，没有
        # 就整个 GROUP_3 都不出现。
        half_ns = s100_group3_half_period_ns(G.col("VERSION", "CP num")[G.i])
        if half_ns is not None:
            period_ns = int(round(2 * half_ns))
            f.write("	@@GROUP_3\n		@@AC_SET_1\n			[NAME=TS_FORCE_CLK]\n			[TS ReserveEdges=14]\n")
            f.write("				PERIOD    = " + str(period_ns) + ";   //unit ns, external-force clock pattern (downgrade)\n")
            f.write("				IO_ALLPINS: {DRV_RS=" + str(int(period_ns * 0.05)) + " }\n")
            f.write("						    {DRV_FL=" + str(int(period_ns * 0.75)) + "}\n")
            f.write("						    {STB_RS=" + str(int(period_ns * 0.5)) + "}\n")
            f.write("			[END_TS]\n\n			[FMT]\n")
            f.write("				IO_ALLPINS: {DRV_FMT=NF}\n")
            f.write("			[END_FMT]\n		@@END_AC_SET_1\n\n	@@END_GROUP_3\n\n")

        f.write("@@END_TIMING_DEFINE\n")


def get_sd_filenames_with_os(folder_path):
    """使用os模块获取 PATTERN_NAME 该列出的文件名列表：.sd 主 pattern + .sr 子程序
    （2026-07-07 用户裁决 RCC/RTC 外灌时钟 <600kHz 降级分支加了 R<pin>_clkloop.sr
    常驻子程序——编译实测坐实 .sr 不进 PATTERN_NAME 会报"SUB_CONT_ON label_name not
    found"，YT5100_Pre 必须先在 PATTERN_NAME 里"认识"这个 .sr 文件才能解析引用）。"""
    if not os.path.isdir(folder_path):
        raise ValueError(f"路径 '{folder_path}' 不是一个有效的文件夹")

    sd_filenames = [
        filename for filename in os.listdir(folder_path)
        if filename.endswith(('.sd', '.sr')) and os.path.isfile(os.path.join(folder_path, filename))
    ]
    return sd_filenames
