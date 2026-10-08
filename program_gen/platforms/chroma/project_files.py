# Chroma 平台：.dec 引脚文件与电源引脚处理。
import io
import os
from program_gen import state as G


def process_pin_name(pin_name):
    """处理引脚名称：提取 IO 端口名或保留原值（与 S100 同一逻辑）。

    PAD_PC[13] / PAD_PD_8 → PC13 / PD8；含 GND 的引脚返回 None（不进 dec）；
    其余原样返回。两平台现读同一张 PIN DEC（pad 名为 PAD_Px[n] 形态），
    故引脚名处理逻辑与 S100 platforms/s100/project_files.py 保持一致。"""
    import re
    pin_str = str(pin_name).strip()
    if "GND" in pin_str.upper():
        return None
    match = re.search(r'(P[A-FY])[\[_<](\d+)', pin_str, re.IGNORECASE)
    if match:
        return f"{match.group(1).upper()}{match.group(2)}"
    return pin_str


def _relay_pad_names(cp_no, pin_cp, pin_pad, pin_x, pin_y):
    """按"有没有 XY 坐标"识别 relay/utility 通道（用户裁决 2026-07-06，替换掉原来
    "名字里含不含 UR" 的判断）：真实焊盘在 PIN DEC 里一定有 `X [um]`/`Y [um]` 物理坐标，
    relay（如继电器共用通道，两个 site 共用同一通道号那种）不是真实焊盘，坐标必为空——
    这个信号比人工填的名字更本质，名字可能漏填/不叫 "UR" 但坐标必然如实反映"有没有
    物理焊盘"。返回该 CP 下坐标全空的 pad 名集合；`pin_x`/`pin_y` 为 None（老母本/
    PIN DEC SINGEL 没有这两列）时返回空集合——单 site 场景本就不存在"多 site 共享通道"
    的问题，不需要特殊处理。"""
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


def cp_has_kp_relay(cp_no):
    """该 CP 的 dec 是否会声明 KP（与本文件生成 dec 时判断 KP 行的口径一致，见下方
    dec 生成逻辑里的 "Trace 不带 F0/F1 标记...没有 KP 继电器轨迹，跳过 KP 行"）：
    单 site 固定回退 KP=2501（总会声明）；多 site 则要求 Trace 带 F0/F1 继电器标记，
    否则说明本产品未接 KP relay（如 L_PCD2509V1），dec 端跳过 KP 声明——
    writers.py/startup.py 里所有 SET_CBIT(KP,...) 都要跟着跳过，否则编译报 C2065。"""
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_trace = G.col("PIN_DEC_128", "Trace")
    pin_site = G.col("PIN_DEC_128", "Site")
    sites = {pin_site[u] for u in range(len(pin_cp)) if pin_cp[u] == cp_no}
    if cp_no not in ("CP1", "CP2"):
        return False
    if len(sites) == 1:
        return True
    # The multi-site DEC renderer only derives KP relay channels for CP1.
    # CP2 can contain F0/F1 trace annotations but does not append a KP row.
    return cp_no == "CP1" and any(
        pin_cp[u] == cp_no
        and ("F0" in str(pin_trace[u]) or "F1" in str(pin_trace[u]))
        for u in range(len(pin_cp))
    )


def VCC_pin_rebuild(pin_dec_num):
    """返回 POWER_ON 需强制上电的电源轨名（与 dec 的 MLDPS 同名，故引用一致）：
    - 电源脚识别：pad 名含 "V"（VCC*/VDDD/VREFP/VCCA…）且 trace 非 GND
      （不依赖 "F"——旧 XXXF1 格式才有 F，单 site 电源是纯通道号）；
    - 每个通道用"首个出现的 pad 名"作代表（共享通道只回一条，如 256→VCC4、257→VREFP）；
    - **排除 VDDD**（核电内部稳压、dec 里定义为 MLDPS 但不外供，与 S100 prj_power_pins 一致）。"""
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_site = G.col("PIN_DEC_128", "Site")
    pin_trace = G.col("PIN_DEC_128", "Trace")
    pin_pad = G.col("PIN_DEC_128", "E/C(Pad Name)")
    rail = {}     # trace -> 代表 pad 名（首个出现）
    order = []    # 保持通道首次出现顺序
    for u in range(len(pin_site)):
        if pin_cp[u] == pin_dec_num and pin_site[u] == 1 \
                and "V" in str(pin_pad[u]).upper() and "GND" not in str(pin_trace[u]).upper():
            tr = pin_trace[u]
            if tr not in rail:
                rail[tr] = pin_pad[u]
                order.append(tr)
    return [rail[tr] for tr in order if str(rail[tr]).upper() != "VDDD"]


def vcc_rails_str(code_name):
    """OS/PDR 等对全部电源轨整体 force 时引用的轨名串（如 "VCC4+VREFP"），与 POWER_ON 同源。
    原代码这些位置写死 "VCC"，但 PIN DEC 无此 pad（定义的是 VCC4/VREFP）→ 力压到不存在的轨。
    CP2 的 PIN DEC 复用 CP1 电源行（与 startup 的 POWER_ON 一致），故 CP2→CP1。"""
    cp = code_name.split("_")[-1]
    if cp == "CP2":
        cp = "CP1"
    return "+".join(VCC_pin_rebuild(cp))


def dec_file_created(code_name, only=None):
    # //////////////////////////////////////////////DEC文件生成 start///////////////////////////////////////////////////////
    # code_name: 本次生成的程序名列表（与 VERSION 行同序）。生产=各 CP 程序名；
    # 实验室=各 CP 的单 site 程序名（1SLAB token）。dec 写进 OUT_DIR 下对应程序的 pat/。
    # only: 只生成这些 VERSION 行下标对应的程序（None=全部，跟 code_name 下标一一对应，
    # 用于"只生成某个 CP"——不选中的程序对应下标直接跳过，不动它已有的 pat/pin.dec）。
    new_pin_name = []
    # 幂等重置：支持同一进程内多次生成（实验室 + 生产两 pass），避免跨 pass 累积
    G.pin_dec.clear()
    G.F0_C.clear()
    G.F1_C.clear()
    G.F1_R.clear()
    # PIN DEC 近 3000 行：列提升到循环外（原先每个元素访问都全列转换，是最大性能热点）
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_site = G.col("PIN_DEC_128", "Site")
    pin_trace = G.col("PIN_DEC_128", "Trace")
    pin_pad = G.col("PIN_DEC_128", "E/C(Pad Name)")
    _has_xy = "X [um]" in G.PIN_DEC_128.columns and "Y [um]" in G.PIN_DEC_128.columns
    pin_x = G.col("PIN_DEC_128", "X [um]") if _has_xy else None
    pin_y = G.col("PIN_DEC_128", "Y [um]") if _has_xy else None
    G.a.clear()
    for j in range(len(pin_cp)):
        G.a.append(pin_cp[j])
    [G.pin_dec.append(i) for i in G.a if i not in G.pin_dec]
    G.a = []

    for cyc in range(len(G.pin_dec)):
        G.pinname.clear()
        G.dict_1.clear()
        G.x.clear()
        G.s.clear()
        G.F0_R.clear()
        G.a.clear()
        G.data.clear()
        G.size.clear()
        G.site.clear()
        first_pad = {}   # trace -> 首个出现的引脚名（共享电源轨的代表名用）
        for j in range(len(pin_site)):
            if pin_cp[j] == G.pin_dec[cyc]:
                if pin_site[j] == 1 and "GND" not in str(pin_trace[j]):
                    processed = process_pin_name(pin_pad[j])
                    if processed is not None:
                        G.pinname.append(processed)
                        G.data.append(pin_trace[j])
                        if pin_trace[j] not in first_pad:
                            first_pad[pin_trace[j]] = processed

        G.dict_1 = dict(zip(G.pinname, G.data))

        for key in G.dict_1.keys():
            if G.dict_1[key] not in G.a:
                G.a.append(G.dict_1[key])
            elif G.dict_1[key] not in new_pin_name:
                new_pin_name.append(G.dict_1[key])
        G.dict_1 = dict(zip(G.data, G.pinname))

        G.a.clear()
        G.s.clear()
        G.pinname = list(G.dict_1.values())

        if G.pin_dec[cyc] == "CP1":
            for j in range(len(G.col("KP_RELAY", "F0 Channel"))):
                G.F0_C.append(G.col("KP_RELAY", "F0 Channel")[j])
                G.F1_C.append(G.col("KP_RELAY", "F1 Channel")[j])
                G.F0_R.append(G.col("KP_RELAY", "KP RELAY F0")[j])
                G.F1_R.append(G.col("KP_RELAY", "KP RELAY F1")[j])
            G.dict_F0 = dict(zip(G.F0_C, G.F0_R))
            G.dict_F1 = dict(zip(G.F1_C, G.F1_R))
        for j in range(len(G.pinname)):
            for u in range(len(pin_site)):
                if pin_cp[u] == G.pin_dec[cyc]:
                    if process_pin_name(pin_pad[u]) == G.pinname[j]:
                        G.item.append(pin_trace[u])
            [G.a.append(i) for i in G.item if i not in G.a]

            G.s.append(G.a)
            G.item.clear()
            G.a = [1, 2]
            G.a.clear()
        [G.x.append(i) for i in G.s if i not in G.x]
        G.F0_R = []

        # 共享通道的电源轨用"首个出现的 pad 名"作代表（与 S100 一致），不再合成 VCCn。
        # 例：trace 256→VCC4、257→VREFP。POWER_ON 也引用这些名字（见 VCC_pin_rebuild）。
        for shared_trace in new_pin_name:
            G.dict_1[shared_trace] = first_pad[shared_trace]
        G.pinname = list(G.dict_1.values())
        new_pin_name.clear()

        # UR relay（按 XY 坐标判断，见 _relay_pad_names；不再按名字含不含 "UR"，用户
        # 2026-07-06 裁决——名字是人填的，可能漏填/不叫 "UR"，坐标才是"有没有真实
        # 物理焊盘"的本质信号）不能走上面的共享通道去重逻辑——去重是给电源轨设计的
        # （同 trace 的多个 site 只留一个代表值），UR relay 恰恰需要保留每个 site 各自的通道号
        # （允许多个 site 共用同一通道，如两两一组），去重会把这种"重复"错当成"共享"吞掉。
        # 这里按 Site 顺序直接从 PIN DEC 重新取一遍该 CP、该 pad 名的 Trace 值，不去重覆盖回 G.x。
        relay_names = _relay_pad_names(G.pin_dec[cyc], pin_cp, pin_pad, pin_x, pin_y)
        G.relay_j.clear()
        for j in range(len(G.pinname)):
            if str(G.pinname[j]).replace("/", "").strip() in relay_names:
                G.relay_j.append(j)
                ur_rows = sorted(
                    ((int(pin_site[u]), pin_trace[u]) for u in range(len(pin_cp))
                     if pin_cp[u] == G.pin_dec[cyc] and pin_pad[u] == G.pinname[j]),
                    key=lambda r: r[0])
                if ur_rows:
                    G.x[j] = [str(trace) for _, trace in ur_rows]

        for j in range(len(G.x)):
            for i in range(len(G.x[j])):
                try:
                    if G.pin_dec[cyc] == "CP1":
                        if "F0" in G.x[j][i]:
                            G.F0_R.append(str(G.dict_F0[G.x[j][i]]))
                            G.x[j][i] = str(G.x[j][i].split("F")[0])
                        elif "F1" in G.x[j][i]:
                            G.F0_R.append(str(G.dict_F1[G.x[j][i]]))
                            G.x[j][i] = str(G.x[j][i].split("F")[0])
                        elif "F" in str(G.x[j][i]):
                            G.x[j][i] = str(G.x[j][i]).split("F")[0]
                    else:
                        G.x[j][i] = str(G.x[j][i].split("F")[0])
                    if "*" in G.x[j][i]:
                        G.x[j][i] = str(G.x[j][i].split("*")[0])
                except:
                    G.x[j][i] = str(G.x[j][i])

        # Trace 不带 F0/F1 标记的表格（如 L_PCD2509V1）没有 KP 继电器轨迹，跳过 KP 行
        if G.pin_dec[cyc] == "CP1" and G.F0_R:
            G.x.append(G.F0_R)
            G.pinname.append("KP")
        elif G.pin_dec[cyc] in ("CP1", "CP2") and not G.F0_R and G.x and len(G.x[0]) == 1:
            # 单 site lab：KP 正常用 VCC 的 F0/F1 去 KP RELAY 表查，但单 site 的 trace 无 F0/F1 标记
            # → 查不到 → F0_R 空、KP 未定义。用户裁决：单 site lab 的 CP1/CP2 固定写 KP=2501。
            G.x.append(["2501"] * len(G.x[0]))
            G.pinname.append("KP")
        # UR relay 不再硬编码某个 CP 生成——PIN DEC 里只要真有 XY 坐标为空的行，前面的
        # 通用逐 pin 循环（103-145 行）就已经把它当普通 pad 名收进 G.pinname/G.x 了，
        # 这里不用再补一次；具体渲染成 UR 还是普通 IO，交给下面渲染阶段按 G.relay_j
        # （已在上面按 XY 坐标判断好）来判断。下面要插入 "// Site" 占位列，把 G.relay_j
        # 存的下标同步 +1（插入发生在下标计算之后，不然后面渲染阶段会对错位置）。
        G.relay_j[:] = [j + 1 for j in G.relay_j]
        for z in range(len(G.x[0])):
            G.site.append(str(z))
        G.x.insert(0, G.site)
        G.pinname.insert(0, "// Site")
        # for j in range(len(x)):
        #     print(x[j], pinname[j], j)
        # for j in range(len(pinname)):
        #     print(pinname[j], j)
        # NRST 复位脚改名：数据驱动读 VERSION["NRST PIN"]（与 S100 同一写法），
        # 不再硬编码 "PF2"。process_pin_name 已把 pad 名规整为逻辑名（如 PD11）。
        nrst_pin = G.col("VERSION", "NRST PIN")[0]
        for j in range(len(G.pinname)):
            if G.pinname[j] == nrst_pin:
                G.pinname[j] = "NRST"

            G.size.append(len(G.pinname[j]))
        with io.StringIO() as f:
            f.write("DEC_MODE APAS;\n\n")
            f.write("PIN_LIST(CP_" + str(len(G.x[0])) + "S)\n{\n")
            for j in range(len(G.x)):
                if "S" in G.x[j][0]:
                    G.pinname[j] = "//" + G.pinname[j]
                if len(G.pinname[j]) < max(G.size):
                    G.pinname[j] = " " * (max(G.size) - len(G.pinname[j])) + G.pinname[j]
                f.write("   " + G.pinname[j] + " = ")
                pin_clean = G.pinname[j].replace("/", "").strip()
                is_ur = pin_clean == "KP" or j in G.relay_j
                for i in range(len(G.x[j])):
                    if len(G.x[j][i]) < 4:
                        G.x[j][i] = " " * (4 - len(G.x[j][i])) + str(G.x[j][i])
                    if i == len(G.x[j]) - 1 and j != 0:
                        if "V" in G.pinname[j]:
                            f.write(str(G.x[j][i]) + " = " + str(j + 1) + " = MLDPS;")
                        elif is_ur:
                            # UR 仅给专用的 KP（继电器）/ XY 坐标为空的行（G.relay_j，
                            # 2026-07-06 起改按坐标判断，不再依赖名字含不含 "UR"）；
                            # 不再无条件给最后一行（否则单 site 下最后一个真实脚被误标 UR）
                            f.write(str(G.x[j][i]) + " =   = UR;")
                        else:
                            f.write(str(G.x[j][i]) + " = " + str(j + 1) + " = IO;")

                    else:
                        if j == 0 and i == len(G.x[j]) - 1:
                            f.write(str(G.x[j][i]))
                        else:
                            f.write(str(G.x[j][i]) + ":")
                f.write("\n")
            f.write("}\n\n")
            f.write("PIN_GROUP\n{\n")
            for j in range(len(G.pinname)):
                G.pinname[j] = ''.join([i.strip(' ') for i in G.pinname[j]])
            f.write("   ODD_pins  = ")
            G.data.clear()
            for j in range(len(G.pinname)):
                if G.pinname[j] != "//Site" and "TP" not in G.pinname[j] and "V" not in G.pinname[j] and j != len(
                        G.pinname) - 1:
                    if j % 2 == 0:
                        G.data.append(G.pinname[j])
            for j in range(len(G.data)):
                if j != len(G.data) - 1:
                    f.write(G.data[j] + "+")
                else:
                    f.write(G.data[j] + ";\n")
            G.data.clear()
            f.write("   EVEN_pins = ")
            for j in range(len(G.pinname)):
                if G.pinname[j] != "//Site" and "TP" not in G.pinname[j] and "V" not in G.pinname[j] and j != len(
                        G.pinname) - 1:
                    if j % 2 == 0:
                        continue
                    else:
                        G.data.append(G.pinname[j])
            for j in range(len(G.data)):
                if j != len(G.data) - 1:
                    f.write(G.data[j] + "+")
                else:
                    f.write(G.data[j] + ";\n")
            f.write("}\n\n")
            dec_text = f.getvalue()

        # dec 写进各程序自己的 pat/ 文件夹，统一命名 "pin.dec"——与 .pat 头部固定的
        # SET_DEC_FILE "pin.dec" 及 .pln 引用一致（CRAFT patcmp 按 .pat 里的名字找 dec，
        # 名字不符就报 "fail to call dec compiler"）。每个程序各有独立 pat/，同名不冲突。
        for v in range(len(code_name)):
            if only is not None and v not in only:
                continue
            if str(G.col("VERSION", "CP num")[v]) == str(G.pin_dec[cyc]):
                prog = str(code_name[v])
                pat_dir = G.OUT_DIR + "\\" + prog + "\\pat"
                os.makedirs(pat_dir, exist_ok=True)
                with open(pat_dir + "\\" + "pin.dec", 'w') as out:
                    out.write(dec_text)
