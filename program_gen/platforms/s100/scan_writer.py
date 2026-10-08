# S100 平台：SCAN/Mbist 族测试项 @@PLAN 写出（2026-07-19，WGL 驱动，见
# .Codex/handoffs/2026-07-19-s100-scan-mbist-design.md）。与 Chroma
# （chroma/scan_writer.py）同源，但输出体系不同：S100 走 @@PLAN + RUN_PATTERN +
# .tim 的 @@GROUP_2/AC_SET，不是 Chroma 的 TIME/MARKERN/JUDGE_PAT。时序声明写在
# .tim（project_files.py:scan_group2_write），本模块只写 .prg 的 @@PLAN。
#
# 2026-07-19 用户裁决：这次先写 .tim/.prg；.sd 向量转换（wgl2chroma target="sd"）
# 与多 timeplate 的逐拍时序切换后续在 pattern 层做，本模块不碰 .sd。
import os
import re
import shutil
import sys
import tempfile

from program_gen.core.wgl_parse import discover_patterns, parse_async_clocks, parse_timeplates
from program_gen import state as G

# WGL 源目录两平台共用（V1.1/SCAN|Mbist/<item>/，2026-07-08 用户裁决），从本文件
# 相对路径算 V1.1 根，不依赖 G.BASE_DIR（那是各平台的 S100_program 根）。
_V1_1_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_TOOLS_DIR = os.path.join(_V1_1_ROOT, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from wgl2chroma.converter import convert_one  # noqa: E402


def scan_folder(item, mode):
    """WGL 源目录 V1.1/SCAN|Mbist/<item>/。"""
    sub = "SCAN" if str(mode).strip().upper() == "SCAN" else "Mbist"
    return os.path.join(_V1_1_ROOT, sub, item)


def scan_patterns_ordered(item, mode):
    """本测试项按运行顺序排好的 pattern 列表（复用 wgl_parse.discover_patterns，
    平台无关）。.tim（GROUP_2 时序）和 .prg（RUN_PATTERN 顺序）两处要用同一份，
    收口在这里，避免两边各扫一次目录得到不同顺序。"""
    folder = scan_folder(item, mode)
    patterns = discover_patterns(folder)
    if not patterns:
        raise ValueError("scan(s100): " + folder + " 下没有找到任何 .wgl/.pat 文件")
    return patterns


def scan_ts_prefix(item):
    """时序名的测试项前缀（2026-07-20 用户裁决走 golden 式"每测试项独立命名"）。
    golden 靠 DFT 给不同测试项不同 timeplate 名（DCScan=tp_setup、ACScan=tp_acscan）
    天然不撞名；但本批母本 WGL 的 AC/DC/Mbist 三个测试项都用了 tp_setup/tp_shift/
    tp_capture（DFT 这次生成撞名），故生成器按测试项加前缀区分，GROUP_2 每测试项各
    留一整套、不丢内容（NRST 的 RTO 也保住）。如 AC_SCAN_Test→acscan、DC_SCAN_Test→
    dcscan、Mbist_Test→mbist。"""
    p = item.lower()
    if p.endswith("_test"):
        p = p[:-len("_test")]
    return p.replace("_", "")


def scan_ts_name(item, tp_name):
    """带测试项前缀的时序名——.tim 的 [NAME=]、.prg 的 RUN_PATTERN 第4参用这个。
    （.sd 向量行不用名字、用 G2_<编号>，见 scan_group2_timesets/G2 编号。）"""
    return scan_ts_prefix(item) + "_" + tp_name


def scan_group2_timesets(code_name):
    """本 CP 的 GROUP_2 有序时序列表 [(full_name, tp), ...]，按测试项前缀去重后的
    首次出现顺序。**.tim（`@@AC_SET_<idx>`）与 .sd（向量行 `TIMING_SET G2_<idx>`）
    两处共用这一份**——S100 的 .sd 用 `G<组>_<号>` 编号引用时序（对齐 flash pattern
    的 `TIMING_SET G1_1` 写法，2026-07-20 用户裁决："用 GROUP 编号、不用名字"），
    编号就是这个列表里的位置（idx，从 1 起），所以 tim 的 AC_SET 编号必须跟 .sd 的
    G2 编号来自同一份有序列表，否则对不上。"""
    cp_suffix = code_name.split("_")[-1]
    flow_item = G.col("FLOW", "item")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    flow_cp = G.col("FLOW", "CP NO")
    defined = set()
    out = []
    for z in range(len(flow_item)):
        if flow_type[z] != "verify" or flow_mode[z] not in ("scan", "mbist"):
            continue
        if flow_cp[z] != cp_suffix:
            continue
        for _name, path, kind in scan_patterns_ordered(flow_item[z], flow_mode[z]):
            if kind != "wgl":
                continue
            for tp in parse_timeplates(path):
                full = scan_ts_name(flow_item[z], tp["name"])
                if full in defined:
                    continue
                defined.add(full)
                out.append((full, tp))
    return out


def scan_test_write(code_name, f, z, pat_dir):
    """type=="verify" 且 mode in ("scan","mbist") 的 SCAN/Mbist 测试项 @@PLAN。
    结构照 golden（temp/LAB_PY32F420A.../Z_*.prg）：POWER_ON → WAIT → [TMU 外灌]
    → 逐个 RUN_PATTERN(<pat>:START,<pat>:END,2,<主时序名>) → [外灌关] → POWER_OFF
    → CONDITION IF_FAIL REJECT_BIN。

    - GROUP=2（用户裁决：所有 SCAN/MBIST 时序放 GROUP_2，RUN_PATTERN 第 3 参=2）。
    - 主时序名 = 该 pattern WGL 的**第一个** timeplate 名；一个 pattern 有多个
      timeplate 时的逐拍切换在 .sd 里做（2026-07-19 用户裁决，本函数只给主时序名）。
    - 外灌走 TMU（`LOGIC_SET_FREE_RUN_CLOCK_PIN`，>=600kHz；scan 的 16MHz 满足，
      复用 2026-07-07 RCC/RTC 已验证的写法）。golden 那版把外灌写进 pattern 是因为
      老机台不支持 TMU，新机台支持，直接 TMU（用户裁决）。
    - `pat_dir` 暂未用（本次不落地 .sd），保留签名给后续 .sd 转换用。
    - CP 过滤由 main.py 调用点负责（S100 惯例：`flow_cp[No]==cp_suffix` 才调）。
    """
    item = G.col("FLOW", "item")[z]
    mode = G.col("FLOW", "mode")[z]
    vcc = G.col("FLOW", "Vcc")[z]
    hbin = G.col("FLOW", "Hbin")[z]
    patterns = scan_patterns_ordered(item, mode)

    # 外灌时钟：只认第一个含 .wgl 的 pattern 的 async_clock（整个测试项一套外灌）。
    clocks = []
    for name, path, kind in patterns:
        if kind == "wgl":
            clocks = list(parse_async_clocks(path))
            break

    f.write("@@PLAN " + item.title() + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n")
    f.write("\tDISABLE_BY_MARK_NO = NULL;\n")
    f.write("\tS_SETUP_FILE       = c:\\set.dat;\n")
    f.write("\tREMARK             = " + item.title() + ";\n\n")
    f.write("\tCALL_MACRO POWER_ON(_C_" + str(vcc).upper() + ");\n")
    f.write("\tWAIT(3MS);\n\n")
    for pin, freq in clocks:
        f.write("\tLOGIC_SET_FREE_RUN_CLOCK_PIN(" + pin + "," + str(int(round(freq))) + ");\n")
    if clocks:
        f.write("\n")
    for name, path, kind in patterns:
        ts_name = ""
        if kind == "wgl":
            # 带测试项前缀的主时序名（= 该 pattern 第一个 timeplate；多 timeplate 逐拍切换在 .sd）
            ts_name = scan_ts_name(item, parse_timeplates(path)[0]["name"])
        f.write("\tRUN_PATTERN(" + name + ":START," + name + ":END,2," + ts_name + ");\n")
    f.write("\n")
    for pin, freq in clocks:
        f.write("\tLOGIC_SET_FREE_RUN_CLOCK_PIN(NULL," + str(int(round(freq))) + ");\n")
    if clocks:
        f.write("\n")
    f.write("\tCALL_MACRO POWER_OFF();\n")
    f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


# ---------------------------------------------------------------------------
# .sd 向量转换（2026-07-20 用户裁决：写完 tim/prg 后做 .sd）——wgl2chroma 出 .sd +
# 后处理（管脚短名/NRST/砍幽灵、TIMING_SET 名→G2_<编号>）+ 落地程序目录。关键：
# S100 .sd 用 `TIMING_SET G<组>_<号>` 编号引用时序（对齐 flash pattern 的 G1_1 写法，
# 用户裁决"用 GROUP 编号、不用名字"），编号取自 scan_group2_timesets 的有序列表
# （跟 .tim 的 @@AC_SET_<idx> 同源，保证对齐）。
# ---------------------------------------------------------------------------
_SD_HEAD_RE = re.compile(r'(HEAD\[PIN_NAME\]:\n)(.*?)(\nEND_HEAD;)', re.DOTALL)
_SD_VEC_RE = re.compile(r'^(\s*)((?:START:|END:)?)([X01LHZ]+)(;.*)$')
_SD_TS_RE = re.compile(r'TIMING_SET\s+(\w+)\s*;')


def _sd_short_pin(pad):
    """.sd HEAD 的长名 → 短名：PAD_PA_11→PA11、PAD_TP→TP（去 PAD_ 前缀 + 去下划线）。"""
    p = pad[4:] if pad.startswith("PAD_") else pad
    return p.replace("_", "")


def _raw_convert_sd(wgl_path, name):
    """convert_one(target="sd") 原始输出按 WGL size+mtime 缓存（.sd 达 ~95MB、转换
    很慢，同 Chroma 侧 _raw_convert 思路；只缓存 convert 原始输出，后处理每次按当前
    真实管脚/时序编号重做，母本换了产物仍正确）。缓存文件名带 `__sd__` 跟 Chroma 的
    `.pat` 缓存分开，互不覆盖。"""
    st = os.stat(wgl_path)
    key = str(st.st_size) + "_" + str(st.st_mtime_ns)
    cache_dir = os.path.join(os.path.dirname(wgl_path), ".cache")
    cached = os.path.join(cache_dir, name + "__sd__" + key + ".sd")
    if os.path.isfile(cached):
        with open(cached, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, name + ".sd")
        convert_one(wgl_path=wgl_path, out_path=raw, target="sd", progress=None)
        with open(raw, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    os.makedirs(cache_dir, exist_ok=True)
    pre = name + "__sd__"
    for fn in os.listdir(cache_dir):        # WGL 变过则清旧 key
        if fn.startswith(pre) and fn.endswith(".sd"):
            try:
                os.remove(os.path.join(cache_dir, fn))
            except OSError:
                pass
    with open(cached, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _rewrite_sd(text, item, real_pins, ts_index):
    """.sd 后处理：① HEAD 长名→短名+NRST 改名+砍幽灵（不在 real_pins 的删）；② 每拍
    向量行按同一 keep_mask 删对应字符（管脚数与每拍字符数一致）；③ `TIMING_SET
    <WGL时序名>` → `TIMING_SET G2_<编号>`（带测试项前缀查 ts_index）。"""
    nrst = G.col("VERSION", "NRST PIN")[0]
    m = _SD_HEAD_RE.search(text)
    if not m:
        raise ValueError("scan .sd(s100): 找不到 HEAD[PIN_NAME] 段")
    pads = [t.strip().rstrip(";").rstrip(",").strip() for t in re.split(r'[,\n]', m.group(2))]
    pads = [p for p in pads if p]
    short = []
    for p in pads:
        s = _sd_short_pin(p)
        short.append("NRST" if s == nrst else s)
    keep = [s in real_pins for s in short]
    kept = [s for s, k in zip(short, keep) if k]
    new_head = "\n".join("\t" + p + ("," if i < len(kept) - 1 else ";") for i, p in enumerate(kept))
    text = text[:m.start(2)] + new_head + text[m.end(2):]   # group1 已含 "HEAD[PIN_NAME]:\n"，不再补 \n

    def _ts_sub(mm):
        n = ts_index.get(scan_ts_name(item, mm.group(1)))
        return ("TIMING_SET G2_" + str(n) + ";") if n else mm.group(0)

    out = []
    for line in text.splitlines(keepends=True):
        eol = "\n" if line.endswith("\n") else ""
        body = line[:-1] if eol else line
        vm = _SD_VEC_RE.match(body)
        if not vm or len(vm.group(3)) != len(keep):
            out.append(line)
            continue
        ind, tag, data, suffix = vm.groups()
        kept_data = "".join(c for c, k in zip(data, keep) if k)
        out.append(ind + tag + kept_data + _SD_TS_RE.sub(_ts_sub, suffix) + eol)
    return "".join(out)


def scan_sd_convert(code_name, pat_dir):
    """本 CP 所有 SCAN/Mbist 测试项：每个 wgl pattern 转 .sd（带缓存）+ 后处理 + 落地
    程序目录（S100 .sd 放程序根，不像 Chroma 的 pat/ 子目录）。**必须在 main.py 测试
    项循环之后、get_sd_filenames_with_os 之前调用**（.sd 要落地才能登记进 .prj 的
    PATTERN_NAME）。CP 过滤：只处理 flow_cp==本 CP 的 scan/mbist 行。"""
    from program_gen.platforms.s100.project_files import scan_real_pins
    cp_suffix = code_name.split("_")[-1]
    ts_index = {full: i for i, (full, _tp) in enumerate(scan_group2_timesets(code_name), 1)}
    if not ts_index:
        return
    real_pins = scan_real_pins(cp_suffix)
    flow_item = G.col("FLOW", "item")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    flow_cp = G.col("FLOW", "CP NO")
    for z in range(len(flow_item)):
        if flow_type[z] != "verify" or flow_mode[z] not in ("scan", "mbist"):
            continue
        if flow_cp[z] != cp_suffix:
            continue
        item = flow_item[z]
        for name, path, kind in scan_patterns_ordered(item, flow_mode[z]):
            dest = os.path.join(pat_dir, name + ".sd")
            if kind == "wgl":
                text = _rewrite_sd(_raw_convert_sd(path, name), item, real_pins, ts_index)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                shutil.copy(path, dest)   # 现成文件（少见），原样落地
