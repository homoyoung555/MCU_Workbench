# WGL（Waveform Generation Language，DFT 工具如 Tessent Shell 的标准输出格式）解析器。
# 两平台共用（纯计算，不写文件，不生成测试程序代码——生成 MARKERN/PIN_MODE 等平台
# 相关代码是另一层，见 SCAN/Mbist 族的 writers，2026-07-08 用户提醒两平台写法不同）。
#
# 背景：SCAN/Mbist 测试项落地方案见
# .Codex/handoffs/2026-07-08-scan-mbist-family-design.md。用户确认的解析范围：只解析
# WGL 的 `Begin_async_clocks`（外灌时钟）+ `timeplate`（管脚驱动/strobe 时序表）两块，
# 向量数据（`pattern <name>(...) vector(...) := [...]`）不解析——那部分是已经由外部
# 工具转换好的 `.pat`/`.sd` 文件，不归这个解析器管。**WGL 文件可能有几十 MB**（真实
# 样本 `temp/wgl/ac_scan_scan_test_1.wgl` 约 20MB），两个解析函数都必须一读到该停的
# 关键字就 break，绝不能把整份文件读进内存或读到向量段。
import os
import re

from program_gen.platforms.chroma.project_files import process_pin_name

_TIME_MULT_TO_NS = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}

_ASYNC_CLOCK_LINE_RE = re.compile(
    r'^\{\s*([\w\[\]]+)\s*=\s*period:\s*([0-9.]+)\s*(ns|us|ms|s)\s*\}$', re.IGNORECASE)
_TIMEPLATE_HDR_RE = re.compile(
    r'^timeplate\s+(\S+)\s+period\s+([0-9.]+)\s*(ns|us|ms|s)\s*$', re.IGNORECASE)
_PIN_LINE_RE = re.compile(
    r'^"([^"]+)"(?:\[(\d+)\])?\s*:=\s*(input|output|bidir)\s*\[([^\]]*)\]\s*;\s*$', re.IGNORECASE)
_EDGE_RE = re.compile(r'([0-9.]+)\s*(ns|us|ms|s)\s*:\s*([A-Za-z])')

_KNOWN_PIN_MODES = {
    ("S",): "NRZ",
    ("D", "S", "D"): "RZ",
    ("U", "S", "U"): "RO",
}


def _to_ns(value, unit):
    return float(value) * _TIME_MULT_TO_NS[unit.lower()]


def _wgl_pin_name(quoted, index):
    """WGL 管脚 token（如 `"PAD_PA"[14]` / `"PAD_TP"`）→ 短管脚名（如 "PA14"/"TP"）。
    优先复用 `process_pin_name`（处理 "PAD_PA[14]" 这种带下标的真实焊盘）；对不带
    下标、`process_pin_name` 认不出的（如 "PAD_TP"），退化成"去掉 PAD_ 前缀"。非
    "PAD_" 开头的信号（如 "VCORE_RDY_OPT"，DFT 内部信号非真实芯片管脚）原样返回，
    调用方按需自行过滤。"""
    raw = quoted if index is None else quoted + "[" + index + "]"
    resolved = process_pin_name(raw)
    if resolved == raw and raw.upper().startswith("PAD_"):
        return raw[4:]
    return resolved


def parse_async_clocks(path):
    """解析 WGL 的 `Begin_async_clocks`/`End_async_clocks` 块（外灌时钟，2026-07-08
    用户裁决的解析范围之一）。该块固定在文件最前面几十行，读到 End 就停，不碰后面
    的大向量段。返回 [(pin, freq_hz), ...]；块不存在（该 pattern 不需要外灌时钟）
    时返回空列表。"""
    result = []
    in_block = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not in_block:
                if line == "{ Begin_async_clocks }":
                    in_block = True
                continue
            if line == "{ End_async_clocks }":
                break
            m = _ASYNC_CLOCK_LINE_RE.match(line)
            if not m:
                raise ValueError(
                    "parse_async_clocks: 无法识别的 async clock 行 '" + line + "'（" + path + "）")
            pad, value, unit = m.groups()
            pin = process_pin_name(pad)
            freq_hz = 1e9 / _to_ns(value, unit)
            result.append((pin, freq_hz))
    return result


def parse_timeplates(path):
    """解析 WGL 文件里**全部**的 `timeplate <name> period <T> ... end` 块（管脚
    驱动/strobe 时序表，2026-07-08 用户裁决的解析范围之二）。一读到 `pattern `
    开头的行（向量段开始）就停——真实样本单份文件可达 ~20MB，绝不能整份读入内存。

    **2026-07-08 用户澄清**：一份 WGL 文件可能声明**不止一个** `timeplate`（真实
    反例 `ac_scan_scan_test_1.wgl` 有 `_default_WFT_` 和 `_allclock_launch_
    capture_WFT_` 两个）——不是"同一测试项下不同 pattern 文件的 timeplate 要不要
    跨文件对比去重"（`timeplates_equal`/`group_timeplates` 那套，那是之前的误判），
    而是"单个 pattern 自己的 WGL 内部有几个 timeplate 就要用几个 TS 号位"：1 个
    →只用 TS8；2 个→该 pattern 同时需要 TS8+TS9。每个 pattern 运行前都各自重新
    声明一次 TS8（哪怕数值/管脚时序跟上一个 pattern 不一样也无所谓，直接覆盖定义，
    用户确认"重新定义"没问题）。

    返回 [{"name": str, "period_ns": float, "pins": {pin: {"input": [(frac, code),
    ...], "output": [(frac, code),...]}}}, ...]，按文件内出现顺序（一般 1~2 个）。
    frac 是边沿相对该 timeplate 自己 period_ns 的比例，供调用方按实际选定的 TS
    周期换算成 MARKERN 用的 `fsclk*frac` 形式。bidir 方向（只在 `signal` 声明块
    出现，无边沿内容）跳过。"""
    timeplates = []
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("pattern "):
                break
            m = _TIMEPLATE_HDR_RE.match(line)
            if m:
                name, value, unit = m.groups()
                current = {"name": name, "period_ns": _to_ns(value, unit), "pins": {}}
                timeplates.append(current)
                continue
            m = _PIN_LINE_RE.match(line)
            if not m:
                continue
            quoted, index, direction, edges_str = m.groups()
            direction = direction.lower()
            if direction == "bidir":
                continue
            if current is None:
                raise ValueError(
                    "parse_timeplates: 在声明 period 之前就出现了管脚时序行 '" + line
                    + "'（" + path + "）")
            pin = _wgl_pin_name(quoted, index)
            edges = []
            for em in _EDGE_RE.finditer(edges_str):
                value, unit, code = em.groups()
                edges.append((_to_ns(value, unit) / current["period_ns"], code.upper()))
            current["pins"].setdefault(pin, {})[direction] = edges
    if not timeplates:
        raise ValueError("parse_timeplates: 没找到 timeplate 声明（" + path + "）")
    return timeplates


_SUFFIX_RE = re.compile(r'^(.*_)(\d+)$')


def discover_patterns(folder):
    """按 `V1.1/SCAN|Mbist/<item>/` 子目录扫描文件，返回
    [(pattern_name, source_path, kind), ...]，按该测试项的运行顺序排好。

    **三角色命名约定**（2026-07-08 用户裁决，"以后所有产品都会是这三个角色"，
    不局限于字面含 "testsetup" 这一种拼法）：
    - **setup**：文件名含 "setup"（不要求"test"+"setup"连在一起，真实样本
      `ac_scan_setup` 就没有"test"）——排最前。
    - **chain**（可选）：文件名含 "chain"——排 setup 之后、其余 pattern 之前。
    - **其余（scan_test_N 等）**：要求以 `_<数字>` 结尾，按数字升序排在最后。
    三类都不匹配的文件名直接报错，不猜顺序。

    **kind 区分 "wgl" 还是 "pat"**（2026-07-08 用户裁决："setup 有可能不是 wgl
    文件，是直接给的现成 pattern"）：同一个 pattern 名字优先找 `.wgl`（能重新
    解析时序、也能重新转换）；没有 `.wgl` 但有 `.pat` 时退化为直接使用现成
    pattern（不解析时序，调用方应该跳过这个 pattern 的 TS/MARKERN 声明，直接
    拷贝落地）。目录里可能混有 `.sd`（S100 素材，两平台共用同一批原始文件），
    这里只认 `.wgl`/`.pat`，忽略 `.sd`。"""
    all_names = set()
    for fn in os.listdir(folder):
        stem, ext = os.path.splitext(fn)
        if ext.lower() in (".wgl", ".pat"):
            all_names.add(stem)

    def _source(name):
        wgl = os.path.join(folder, name + ".wgl")
        if os.path.isfile(wgl):
            return wgl, "wgl"
        pat = os.path.join(folder, name + ".pat")
        if os.path.isfile(pat):
            return pat, "pat"
        raise ValueError("discover_patterns: 找不到 '" + name + "' 对应的 .wgl/.pat")

    setup = sorted(n for n in all_names if "setup" in n.lower())
    chain = sorted(n for n in all_names if "chain" in n.lower() and n not in setup)
    rest = [n for n in all_names if n not in setup and n not in chain]
    # 只有一个"其余"文件时（如 Mbist 常见只有一个 pattern，命名不一定带数字后缀，
    # 真实反例 `MemoryBist_P1`），没有顺序歧义，不强制要求数字后缀。
    if len(rest) > 1:
        unknown = [n for n in rest if not _SUFFIX_RE.match(n)]
        if unknown:
            raise ValueError(
                "discover_patterns: " + folder + " 下有文件名既不属于 setup/chain，也不是"
                " '..._<数字>' 结尾，无法确定运行顺序：" + str(unknown))
        rest.sort(key=lambda n: int(_SUFFIX_RE.match(n).group(2)))
    ordered = setup + chain + rest
    result = []
    for name in ordered:
        path, kind = _source(name)
        result.append((name, path, kind))
    return result


def wft_display_name(raw_name):
    """把 `parse_timeplates()` 里 `timeplate` 声明捕获到的原始名字（可能带引号，
    如 `"_default_WFT_"`）转成 `wgl2chroma` 转换工具实际写进 `.pat`/`.sd` 向量行
    的那个字面 token（2026-07-08 用户裁决：这个名字要在生成器里改成 `TS8`/`TS9`
    才能用，改名前必须先精确复现工具自己的派生规则才能对上要替换的文本）。
    规则跟 `wgl2chroma/ir.py:wft_name_strip` 完全一致：去掉两侧引号，再
    `str.strip("_")`（去掉全部前导/后置下划线，不是只去一个）。"""
    return raw_name.strip('"').strip("_")


def classify_pin_mode(edges):
    """按输入方向的边沿代码序列分类 NRZ/RZ/RO（2026-07-08 用户提供真实 WGL 核实
    的对应关系：`(S,)`→NRZ、`(D,S,D)`→RZ、`(U,S,U)`→RO，字母跟参考 `.pln` 注释
    "S/XWX"/"DSD/XWX"/"USU/XWX" 是同一套编码）。遇到未知组合直接报错，不猜——
    真实 WGL 可能有本文档没见过的第四种角色，需要人工确认后再扩展
    `_KNOWN_PIN_MODES`，不能静默归错类。"""
    codes = tuple(code for _, code in edges)
    mode = _KNOWN_PIN_MODES.get(codes)
    if mode is None:
        raise ValueError(
            "classify_pin_mode: 未知的边沿代码组合 " + str(codes)
            + "，需要人工确认对应 NRZ/RZ/RO 中的哪一类（或是否是新角色）")
    return mode
