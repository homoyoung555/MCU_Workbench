# Chroma 平台：SCAN/Mbist 族测试项写出（2026-07-08，WGL 驱动，见
# .Codex/handoffs/2026-07-08-scan-mbist-family-design.md 的裁决记录）。
#
# 目录约定（人工只放原始文件，2026-07-08 用户裁决——转换+改名全部由生成器自动做，
# 不要求人工预转换；WGL/hex 平台无关，两平台共用同一份，不挂在各自程序目录下）：
#   V1.1/SCAN/<item>/*.wgl
#   V1.1/Mbist/<item>/*.wgl
#   V1.1/hex/*.hex（S100 侧要用时同理反查这一份，不重复放）
# FLOW 层极简：一行=一个测试项，mode="SCAN"/"Mbist"，其余标准列，不需要额外列。
#
# TS8～TS15 号位范围（2026-09-17 用户扩展至8组）；原分配规则（2026-07-08 用户裁决，纠正了最初"跨 pattern 文件对比去重"的
# 误判）：**每个 pattern 各自的 WGL 内部有几个 timeplate 就要用几个 TS**——1 个
# →只用 TS8；2 个→该 pattern 同时需要 TS8+TS9。每个 pattern 运行前都重新声明一次
# TS8（哪怕跟上一个 pattern 的值不一样也无所谓，直接覆盖定义），不跨 pattern 去重
# 共享——MARKERN/PIN_MODE 块因此是**每个 pattern 各自一份**，不是整个测试项共用
# 一份（老参考 `.pln` 里只有一份 MARKERN 块是那个旧产品凑巧全部 pattern 时序一致，
# 不能当通用规则）。
import os
import re
import sys
import tempfile

from program_gen.core.wgl_parse import (
    classify_pin_mode, discover_patterns, parse_async_clocks, parse_timeplates, wft_display_name,
)
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen.platforms.chroma.project_files import process_pin_name
from program_gen import state as G

# `wgl2chroma` 转换工具已原样拷进 `V1.1/tools/wgl2chroma/`（2026-07-08 用户裁决用
# 最新 V15），从这里按相对路径找，不依赖调用方有没有把 tools/ 塞进 sys.path。
_V1_1_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_TOOLS_DIR = os.path.join(_V1_1_ROOT, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from wgl2chroma.converter import convert_one  # noqa: E402

_GROUP_TS = [f"TS{i}" for i in range(8, 16)]
_GROUP_TS_VAR = {name: "fsclk_scan" + name[2:] for name in _GROUP_TS}
_HEADER_RE = re.compile(r'(HEADER\n)(.*?)(\n\n)', re.DOTALL)
_VECTOR_LINE_RE = re.compile(r'^(\s*)\*([^*]*)\*(.*)$')


def _folder(item, mode):
    """WGL 源目录（2026-07-08 用户裁决改为**两平台共用同一份**，不再各自平台
    目录下重复放一份——WGL/hex 是平台无关的原始文件，只有转换出来的 pattern 才
    分平台，所以直接放 `V1.1/SCAN|Mbist/<item>/`，不挂在 `Chroma_program`/
    `S100_program` 底下）。"""
    sub = "SCAN" if str(mode).strip().upper() == "SCAN" else "Mbist"
    return os.path.join(_V1_1_ROOT, sub, item)


def _normalize_pin(pin):
    """**2026-07-10 用户纠正**：`PD11` 不是幽灵管脚，它就是 `NRST`，只是改了名字
    ——跟 `dec_file_created`（project_files.py:249-254）同一条规则：这颗芯片的
    复位脚物理上是普通 IO pad（`VERSION["NRST PIN"]` 指定，这个母本是
    `"PD11"`），dec 文件生成时把它从物理 pad 名改写成功能名 `"NRST"`。WGL/
    `wgl2chroma` 吐出来的还是物理 pad 短名（`PD11`），SCAN/Mbist 生成器必须做
    同一次改名才能跟真实落地的 `pin.dec` 对上，不能当"这颗产品没有这个管脚"的
    幽灵管脚砍掉。"""
    nrst_pin = G.col("VERSION", "NRST PIN")[0]
    return "NRST" if pin == nrst_pin else pin


def _pin_exists(pin, real_pins):
    """用户对齐点①（2026-07-08）：WGL 提到的管脚不一定这颗产品真的有，必须反查
    确认，不能照单全收。**2026-07-10 修复**：原先直接按 CP 号在 `PIN_DEC_128`
    原始表里查，漏了 `dec_file_created`（project_files.py）内部"同一个 Trace 只
    留一个代表管脚名"的去重逻辑——真实反例：`PAD_PD[11]` 跟 `NRST` 在这颗芯片的
    单 site lab 探针表里共享同一个 Trace，`PIN_DEC_128` 两个都在，但真正落地的
    `pin.dec` 只留了 `NRST`，`PD11` 被去重掉了。照单全收会把已经不存在的 `PD11`
    写进 MARKERN/HEADER，CRAFT 编译报 `pin not declared in PIN LIST`（真实编译时
    发现，见 `.Codex/handoffs/2026-07-08-scan-mbist-family-design.md` 续12 后的
    验证记录）。改成直接查 `real_pins`（`_load_real_pins` 解析这次生成实际落地的
    `pin.dec`），保证跟 dec 文件真实内容一致，不用重新实现一遍去重逻辑。"""
    return pin in real_pins


def _load_real_pins(pat_dir):
    """解析这次生成已经落地的 `pat_dir/pin.dec`（`dec_file_created` 保证在
    `scan_test_write` 之前跑，main.py 里的调用顺序如此），拿 `PIN_LIST` 块里的
    管脚名集合——这是"这颗产品这次生成实际有哪些管脚"的唯一权威来源。"""
    dec_path = os.path.join(pat_dir, "pin.dec")
    with open(dec_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = re.search(r'PIN_LIST\([^)]*\)\s*\{(.*?)\}', text, re.DOTALL)
    if not m:
        raise ValueError("_load_real_pins: " + dec_path + " 找不到 PIN_LIST 块")
    pins = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        name = line.split("=", 1)[0].strip()
        if name:
            pins.add(name)
    return pins


def _fmt_period(period_ns):
    return ("%g" % period_ns) + "nS"


_MARKERN_FIELD_W = 20  # 2026-07-08 用户裁决：MARKERN 各字段对齐，不美观就改


def _fmt_edge(frac, ts_var):
    """frac==0 时写字面量 "0ns"（对齐参考 `.pln` 的写法）；否则写
    "<ts_var>*<frac>" 符号表达式（frac 是相对该 timeplate 自己 period 的比例，
    2026-07-08 用户裁决：只取小数点后 3 位，不要 `%g` 那种全精度长尾数）。"""
    if frac == 0:
        return "0ns"
    return ts_var + "*" + ("%.3f" % frac)


def _markern_line(ts_name, pin, info, ts_var):
    """按 WGL 解析出的边沿信息拼一行 MARKERN，各字段左对齐到固定宽度方便阅读
    （2026-07-08 用户裁决）。**推断依据**（2026-07-08，从真实 WGL 数据反推，
    非 ATE 手册确认，需要用户核实语义）：
    - 输入边沿只有一个 "S" ⇒ NRZ，没有独立的驱动窗口，drive 字段写 "0ns,"（空）。
    - 输入边沿是 3 个（D/U, S, D/U）⇒ RZ/RO，drive 字段 = 第 2(S)、第 3 个边沿的
      偏移（**2026-07-17 用户核实**：上升沿 DT0 取**中间的 S 点**、不是周期起点第 1
      个边沿的 0ns；下降沿 DT1 取第 3 个 D/U 沿。早先误取第 1 个 → DT0 恒为 0ns。
      PIN_MODE 的格式参数才区分 RZ/RO，MARKERN 本身对两者数值上一样）。
    - strobe 窗口 = 输出边沿里 "Q"（capture 点）那一个 + 紧跟其后的下一个边沿。
    """
    in_edges = info.get("input", [])
    codes = tuple(c for _, c in in_edges)
    if codes == ("S",):
        drive1, drive2 = "0ns", ""
    elif len(in_edges) == 3:
        drive1 = _fmt_edge(in_edges[1][0], ts_var)   # DT0=上升沿=中间 S 点（2026-07-17 用户核实）
        drive2 = _fmt_edge(in_edges[2][0], ts_var)   # DT1=下降沿=第 3 个 D/U 沿
    else:
        raise ValueError(
            "_markern_line: 管脚 " + pin + " 的输入边沿组合无法识别: " + str(in_edges))
    out_edges = info.get("output", [])
    q_idx = next((i for i, (_, c) in enumerate(out_edges) if c == "Q"), None)
    if q_idx is None or q_idx + 1 >= len(out_edges):
        raise ValueError(
            "_markern_line: 管脚 " + pin + " 的输出边沿里找不到 Q(strobe) 或缺收尾边沿: "
            + str(out_edges))
    strobe1 = _fmt_edge(out_edges[q_idx][0], ts_var)
    strobe2 = _fmt_edge(out_edges[q_idx + 1][0], ts_var)

    pin_field = (pin + ",").ljust(7)
    drive1_field = (drive1 + ",").ljust(_MARKERN_FIELD_W)
    drive2_field = ((drive2 + ",") if drive2 else ",").ljust(_MARKERN_FIELD_W)
    strobe1_field = (strobe1 + ",").ljust(_MARKERN_FIELD_W)
    return ("  MARKERN(" + ts_name + ", " + pin_field + " " + drive1_field + " " + drive2_field
            + "     ,   0ns,      ,   " + strobe1_field + " " + strobe2 + ");\n")


def _pin_mode_line(pin, info):
    mode = classify_pin_mode(info.get("input", []))
    return "  PIN_MODE(" + pin.ljust(6) + ", " + mode.ljust(3) + ", WINDOW, ENABLE, IO_NRZ, NORM);\n"


def _emit_timeplate_setup(f, ts_name, tp, real_pins):
    ts_var = _GROUP_TS_VAR[ts_name]
    f.write("  TIME " + ts_var + " = " + _fmt_period(tp["period_ns"]) + ";//" + ts_name + "\n")
    f.write("  RATEN(" + ts_name + ", " + ts_var + ");\n")
    live_pins = []
    for pin, info in tp["pins"].items():
        norm_pin = _normalize_pin(pin)
        if _pin_exists(norm_pin, real_pins) and "input" in info:
            live_pins.append((norm_pin, info))
    for pin, info in live_pins:
        f.write(_markern_line(ts_name, pin, info, ts_var))
    f.write("\n")
    for pin, info in live_pins:
        f.write(_pin_mode_line(pin, info))
    f.write("\n")


def _rename_one_pin(token):
    """`process_pin_name` 只认 `PAD_P<X>[<n>]`/`PAD_P<X>_<n>` 这种"口+数字"格式
    （`PAD_PA_15`→`PA15`），对 `wgl2chroma` 也会硬加 `PAD_` 前缀的非口线管脚（如
    `PAD_TP`）不识别、原样返回——这类直接退化成"去掉 `PAD_` 前缀"（2026-07-08
    实测发现，`PAD_TP` 需要变成 `TP` 才是这个母本 `pin.dec` 认得的名字）。"""
    renamed = process_pin_name(token)
    if renamed == token and token.startswith("PAD_"):
        renamed = token[len("PAD_"):]
    else:
        renamed = renamed or token
    return _normalize_pin(renamed)


def _rewrite_header_and_vectors(text, real_pins):
    """把 `wgl2chroma` 输出的 HEADER 管脚长名（`PAD_PA_15` 等）改写成项目
    `pin.dec` 用的短名（`PA15`），**并且严格按 PIN DEC 反查结果砍掉这颗产品真实
    不存在的"幽灵管脚"**（2026-07-08 用户裁决："一定要完成"，pattern 必须只
    包含真实管脚——用跟 `MARKERN`/`PIN_MODE` 同一个 `_pin_exists` 判据，两边天然
    对齐，不会出现"HEADER 砍了但 MARKERN 没砍"或反过来的不一致）。删掉一列管脚
    的同时，**每一拍向量行都要同步删掉对应位置的字符**（否则管脚数和每拍字符数
    对不上，编译会报错），这是文本层面的列删除，不改变保留下来的管脚/字符的
    相对顺序。"""
    m = _HEADER_RE.search(text)
    if not m:
        raise ValueError("_rewrite_header_and_vectors: 找不到 HEADER 管脚声明段")
    tokens = [t.strip() for t in m.group(2).replace("\n", " ").rstrip(";").split(",") if t.strip()]
    renamed = [_rename_one_pin(t) for t in tokens]
    keep_mask = [_pin_exists(p, real_pins) for p in renamed]
    kept_pins = [p for p, keep in zip(renamed, keep_mask) if keep]
    new_header = "  " + ", ".join(kept_pins) + ";"
    text = text[:m.start(2)] + new_header + text[m.end(2):]

    out_lines = []
    for line in text.splitlines(keepends=True):
        eol = ""
        body = line
        if body.endswith("\n"):
            body, eol = body[:-1], "\n"
        vm = _VECTOR_LINE_RE.match(body)
        if not vm:
            out_lines.append(line)
            continue
        prefix, data, suffix = vm.groups()
        if len(data) != len(keep_mask):
            raise ValueError(
                "_rewrite_header_and_vectors: 向量行字符数 " + str(len(data))
                + " 跟 HEADER 管脚数 " + str(len(keep_mask)) + " 对不上: " + body)
        kept_data = "".join(c for c, keep in zip(data, keep_mask) if keep)
        out_lines.append(prefix + "*" + kept_data + "*" + suffix + eol)
    return "".join(out_lines)


def _timeplates_equal(a, b):
    return abs(a["period_ns"] - b["period_ns"]) < 1e-9 and a["pins"] == b["pins"]


def _group_timeplates(timeplates):
    """把一个 pattern 自己 WGL 内声明的多个 timeplate **按内容去重**（2026-07-08
    真实反例 `dc_scan_chain_test_1.wgl` 声明了 3 个 timeplate——`tp_setup`/
    `tp_shift`/`tp_capture`，但 `tp_setup` 和 `tp_shift` 周期、每根管脚的边沿数据
    逐字节相同，只是取了两个不同名字，本质是同一套时序）。**声明数量不等于真正
    不同的时序数量**，要按内容分组，只有内容真不同的才各占一个 TS 号位——避免
    "3 个声明就要 3 个 TS 号位"的误判，用户确认"如果真不同才扩号位"。

    返回 [(representative_tp, [raw_name1, raw_name2, ...]), ...]，保持首次出现
    顺序；同组所有原始名字（`.pat` 里可能各自以字面 token 出现）后续都要被替换成
    同一个 TS 名。"""
    groups = []
    for tp in timeplates:
        for g_tp, names in groups:
            if _timeplates_equal(g_tp, tp):
                names.append(tp["name"])
                break
        else:
            groups.append((tp, [tp["name"]]))
    return groups


def _rename_timesets(text, groups, ts_names):
    """把 pattern 里每个 WGL timeplate 派生出的字面时序名（如 `default_WFT`）替换
    成 `TS8`～`TS15`（2026-07-08 用户裁决："Chroma 就是 TS8/TS9"，工具原生名字不能
    直接用）——`groups` 是 `_group_timeplates` 按内容去重后的结果，同一组内所有
    原始名字都要替换成同一个 TS 名（哪怕它们在 WGL 里叫不同名字）。"""
    for (tp, names), ts_name in zip(groups, ts_names):
        for raw_name in names:
            display = wft_display_name(raw_name)
            text = re.sub(r'\b' + re.escape(display) + r'\b', ts_name, text)
    return text


def _raw_convert(wgl_path, pat_name):
    """`convert_one` 的**原始输出**按 WGL 的 `size+mtime` 缓存在同 item 目录的
    `.cache/` 下——at-speed scan 的 WGL 可达 ~25MB，`convert_one` 实测约占整条
    转换链 75% 耗时（~1.4 s/MB），且**只依赖 WGL 本身、跟母本/`pin.dec` 无关**，
    所以缓存原始转换输出是安全的：后处理（`_rewrite_header_and_vectors` 砍幽灵
    管脚、`_rename_timesets` 改 TS 名）仍每次按当前 `pin.dec` 重做，母本换了产物
    依然正确。key 用 `size+mtime_ns` 而非文件哈希，免得为省时间反而先整读一遍
    25MB。`.cache/` 是**子目录**，`discover_patterns` 只 `os.listdir` 顶层且只认
    `.wgl`/`.pat`（wgl_parse.py），不会把缓存当成 pattern。"""
    st = os.stat(wgl_path)
    key = str(st.st_size) + "_" + str(st.st_mtime_ns)
    cache_dir = os.path.join(os.path.dirname(wgl_path), ".cache")
    cached = os.path.join(cache_dir, pat_name + "__" + key + ".pat")
    if os.path.isfile(cached):
        with open(cached, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    with tempfile.TemporaryDirectory() as tmp:
        raw_path = os.path.join(tmp, pat_name + ".pat")
        convert_one(wgl_path=wgl_path, out_path=raw_path, target="chroma", progress=None)
        with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    os.makedirs(cache_dir, exist_ok=True)
    prefix = pat_name + "__"       # WGL 变过后清掉这个 pattern 的旧 key，不留脏缓存
    for fn in os.listdir(cache_dir):
        if fn.startswith(prefix) and fn.endswith(".pat"):
            try:
                os.remove(os.path.join(cache_dir, fn))
            except OSError:
                pass
    with open(cached, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _convert_and_place(wgl_path, pat_name, groups, real_pins, dest_dir):
    """调用 `wgl2chroma` 把 WGL 转成 Chroma `.pat`（`_raw_convert` 带缓存），做
    三处后处理（管脚长名→项目短名+砍掉幽灵管脚列、WFT 派生时序名→TS8～TS15），
    落地到 `dest_dir`（2026-07-08 用户裁决：`SCAN`/`Mbist` 目录只放原始 `.wgl`，
    转换+改名+砍幽灵管脚全部由生成器自动做）。"""
    text = _raw_convert(wgl_path, pat_name)
    text = _rewrite_header_and_vectors(text, real_pins)
    text = _rename_timesets(text, groups, _GROUP_TS[:len(groups)])
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, pat_name + ".pat"), "w", encoding="utf-8") as fh:
        fh.write(text)


def scan_test_write(code_name, f, z, pat_dir):
    """SCAN/Mbist 族测试项函数体（2026-07-08 用户裁决落地）：可选进 scan 模式
    （`pat_temp/enter_scan_mode.pat` 真的存在才生成这一步，不是所有产品都需要，
    不能用占位假 pat 硬凑）→ 逐个 pattern 各自按自己 WGL 的 timeplate 数量声明
    TS8～TS15 + MARKERN + PIN_MODE → 可选外灌时钟（只认第一个 pattern 的
    async_clocks） → JUDGE_PAT 该 pattern → reset_pattern 收尾。**"值不变就不
    重复声明"**（2026-07-08 用户裁决）：跟上一次写进同一个 TS 号位的 timeplate
    内容（period+管脚边沿）一模一样就跳过，不是每个 pattern 都无条件重新声明
    一遍。"""
    # 按 CP 过滤（对齐全项目 99 处 writer 的惯例，见 writers.py:keil_pattern_write
    # 开头）：main.py 主循环遍历**全部** FLOW 行、不按 CP 过滤，靠各 writer 内部
    # 比对「当前程序 CP 后缀 == 该行 CP NO」跳过非本 CP 的行。scan_test_write 早先
    # 漏了这道 gate → 只生成 CP1 时，遍历到 CP3 的 scan/mbist 行也照样转换并把
    # pattern 落进 CP1 的 pat 目录（2026-07-17 用户报告的 bug）。
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify"
            and G.col("FLOW", "mode")[z] in ("scan", "mbist")):
        return
    item = G.col("FLOW", "item")[z]
    mode = G.col("FLOW", "mode")[z]
    vcc = G.col("FLOW", "Vcc")[z]
    folder = _folder(item, mode)
    patterns = discover_patterns(folder)
    if not patterns:
        raise ValueError("scan_test_write: " + folder + " 下没有找到任何 .wgl/.pat 文件")
    real_pins = _load_real_pins(pat_dir)

    f.write(item.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n  TEST_NO(TEST_NUM);DATALOG_MSG=\""
            + item + "\";\n\n")
    f.write("  POWER_ON(" + vcc.upper() + ");\n\n")
    # `enter_scan_mode` 不是所有产品都需要的固定步骤（2026-07-08 用户裁决：参考
    # 程序里有，但别的产品不一定有）——只有 `pat_temp` 下真的放了这份 seed pattern
    # 才生成这一步，不用 `copy_file` 的占位假 pat 兜底把它硬凑出来。
    enter_scan_mode_path = G.BASE_DIR + "\\pat_temp\\enter_scan_mode.pat"
    if os.path.isfile(enter_scan_mode_path):
        copy_file(enter_scan_mode_path, pat_dir)
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_scan_mode";\n'
                '  JUDGE_PAT(enter_scan_mode,__enter_scan_mode);\n\n')

    clock_pins = []
    clock_checked = False
    active_ts_content = {}  # ts_name -> 上一次写进这个号位的 timeplate（用于跳过
                             # "值没变、不用重新声明"，2026-07-08 用户裁决）
    for name, path, kind in patterns:
        if kind == "wgl":
            timeplates = parse_timeplates(path)
            groups = _group_timeplates(timeplates)
            if len(groups) > len(_GROUP_TS):
                raise ValueError(
                    "scan_test_write: pattern '" + name + "' 需要 " + str(len(groups))
                    + " 套不同的时序（已按内容去重），超过目前支持的 " + str(len(_GROUP_TS))
                    + " 个号位（TS8～TS15），请减少不同的时序组数。")
            for ts_name, (tp, _names) in zip(_GROUP_TS, groups):
                prev = active_ts_content.get(ts_name)
                if prev is None or not _timeplates_equal(prev, tp):
                    _emit_timeplate_setup(f, ts_name, tp, real_pins)
                    active_ts_content[ts_name] = tp

            if not clock_checked:
                clock_checked = True
                clock_pins = [(_normalize_pin(pin), freq) for pin, freq in parse_async_clocks(path)
                              if _pin_exists(_normalize_pin(pin), real_pins)]
                for pin, freq in clock_pins:
                    half_ns = 1e9 / (2 * freq)
                    f.write("  PIN_MODE(" + pin + ",FCLK,EDGE,MASK,IO_ON,OFF);\n")
                    f.write("  FRUN_CLK(" + pin + "," + ("%.2f" % (2 * half_ns)) + "nS,0nS,"
                            + ("%.2f" % half_ns) + "nS);\n")
                    f.write("  FRUN_CLK_MODE(" + pin + ",1,0,ON);\n")
                if clock_pins:
                    f.write("\n")

            _convert_and_place(path, name, groups, real_pins, pat_dir)
        else:
            # kind == "pat"：现成 pattern，没有 .wgl 可解析时序（2026-07-08 用户
            # 裁决："setup 有可能不是 wgl 文件，是直接给的现成 pattern"）——原样
            # 拷贝落地，不声明 TS/MARKERN/PIN_MODE（这份 pattern 假定已经是最终
            # 可用的，跟项目里其它人工维护的种子 pattern 同等对待）。
            copy_file(path, pat_dir)
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + name + '";\n'
                '  JUDGE_PAT(' + name + ',__' + name + ');\n\n')

    for pin, freq in clock_pins:
        f.write("  FRUN_CLK_MODE(" + pin + ",1,0,OFF);\n")
    if clock_pins:
        f.write("\n")

    f.write("  RELAY_ON(IO_ALLPINS,PDCL,2mS);\n")
    copy_file(G.BASE_DIR + "\\pat_temp\\reset_pattern.pat", pat_dir)
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="reset_pattern";\n'
            '  JUDGE_PAT(reset_pattern,__reset_pattern);\n\n')
    f.write("  POWER_OFF();\n}\n\n")
