"""
WGL 文件解析器（Mentor Tessent 方言）。

策略：
- 先做一次预处理：剥离 {...} 注释（这些是 WGL 的"花括号注释"）
- 然后按 block 头识别 (signal/scancell/scanchain/timeplate/scanstate/pattern)
- 每个 block 用专门的子解析器
- scancell 段直接跳过，timeplate 内容只取名字和 period

WGL 字符层级：
- 文件可能很大（本样例 4500 行 / 330KB），但解析复杂度主要在 pattern 段
- pattern 段内的 vector/scan 子句字符串可能横跨多行，必须先做行拼接
"""

import re
from typing import List, Tuple, Optional, Iterator
from .ir import (
    WGLDesign, Signal, ScanChain, Timeplate,
    WGLPattern, WGLVector
)


# 删除空白用的 translate 表(比 re.sub(r'\s+','') 快约 9x)
_WS_DELETE = {ord(c): None for c in ' \t\r\n\f\v'}

# label 标记哨兵: 用户指定的标记注释 {..marker..} 会被替换成它,
# 这样能穿过 strip_brace_comments 存活, 又不含 {}/]/; 不干扰 clause 正则。
_LABEL_SENTINEL = '\x01@LBL@\x01'


# --------------------------------------------------------------------------
# 预处理：剥离 {...} 注释，处理续行
# --------------------------------------------------------------------------

def strip_brace_comments(text: str) -> str:
    """
    剥离 WGL 的 {...} 注释（可能嵌套）。
    优化：用正则在 C 层迭代剥离最内层 {...}，逐层外扩，
    替代逐字符 Python 循环（大文件可快约一个数量级）。
    限制同旧实现：不处理字符串字面量内的花括号（样例中未出现）。
    """
    if '{' not in text:
        return text
    inner = re.compile(r'\{[^{}]*\}')
    while '{' in text:
        new_text = inner.sub('', text)
        if new_text == text:
            # 仍有 '{' 但无法配对（不成对括号）→ 防死循环
            break
        text = new_text
    return text


# --------------------------------------------------------------------------
# Bus 名展开：  "PAD_PA"[15..0]  →  ["PAD_PA_15", ..., "PAD_PA_0"]
#              "PAD_PA"[8]      →  ["PAD_PA_8"]
#              "PAD_TP"         →  ["PAD_TP"]
# --------------------------------------------------------------------------

_BUS_RANGE_RE = re.compile(r'"([^"]+)"\s*\[\s*(\d+)\s*\.\.\s*(\d+)\s*\]')
_BUS_SINGLE_RE = re.compile(r'"([^"]+)"\s*\[\s*(\d+)\s*\]')
_PLAIN_NAME_RE = re.compile(r'"([^"]+)"(?!\s*\[)')


def expand_pin_ref(ref: str) -> List[str]:
    """
    给一个 pin 引用字符串（含引号 + 可选 bus index），返回展开后的 pin 名列表。
    返回名字采用下划线连接（与 .pat HEADER 风格一致）。
    """
    ref = ref.strip().rstrip(',').strip()
    m = _BUS_RANGE_RE.match(ref)
    if m:
        base, hi, lo = m.group(1), int(m.group(2)), int(m.group(3))
        # WGL 经常写 [15..0]（从高到低）
        if hi >= lo:
            return [f"{base}_{i}" for i in range(hi, lo - 1, -1)]
        else:
            return [f"{base}_{i}" for i in range(hi, lo + 1)]
    m = _BUS_SINGLE_RE.match(ref)
    if m:
        return [f"{m.group(1)}_{m.group(2)}"]
    m = _PLAIN_NAME_RE.match(ref)
    if m:
        return [m.group(1)]
    raise ValueError(f"无法解析 pin 引用: {ref!r}")


# --------------------------------------------------------------------------
# 主解析器
# --------------------------------------------------------------------------

class WGLParser:
    """逐 block 解析 WGL 文件。"""

    def __init__(self, text: str, source_filename: str = "",
                 label_marker: Optional[str] = None,
                 label_base: Optional[str] = None):
        # 保留原始文本（用于行号/调试），同时构造"无注释"版本用于解析
        self.raw_text = text
        # label: 把含 marker 文本的 {..} 注释替换成哨兵(在剥注释前), 以便定位到其后向量
        self._label_base = label_base if (label_marker and label_base) else None
        if label_marker and label_base:
            mpat = re.compile(r'\{[^{}]*' + re.escape(label_marker) + r'[^{}]*\}')
            text = mpat.sub(_LABEL_SENTINEL, text)
        self.clean_text = strip_brace_comments(text)
        self.design = WGLDesign(source_filename=source_filename)

    def parse(self) -> WGLDesign:
        # 只在 pattern 之前的头部切片上跑各 header 段解析器,
        # 避免对整个(百万拍) pattern 体反复全文正则扫描
        mpat = re.search(r'\bpattern\s+\w+\s*\(', self.clean_text)
        self._header_text = self.clean_text[:mpat.start()] if mpat else self.clean_text
        self._parse_signal_section()
        self._parse_scanchain_section()
        self._parse_timeplates()
        self._parse_scanstate_section()
        self._parse_pattern_section()
        return self.design

    # ------------------------------------------------------------------
    # signal 段
    # ------------------------------------------------------------------
    def _parse_signal_section(self):
        """
        签名形如:
            waveform chip_top
                signal
                    "VCORE_RDY_OPT"[1..0] : input initialp[N];
                    "PAD_PA"[15..0] : bidir initialp[N];
                    ...
                end
        """
        m = re.search(r'\bsignal\b(.*?)\bend\b', self._header_text, re.DOTALL)
        if not m:
            raise ValueError("找不到 signal 段")
        body = m.group(1)
        # 每条语句以 ; 结尾
        for stmt in body.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            # stmt 形如:  "PAD_PA"[15..0] : bidir initialp[N]
            mref = re.match(r'(.+?)\s*:\s*(input|output|bidir)\b', stmt)
            if not mref:
                continue
            ref = mref.group(1)
            direction = mref.group(2)
            for pin_name in expand_pin_ref(ref):
                self.design.signals.append(Signal(pin_name, direction))

    # ------------------------------------------------------------------
    # scanchain 段
    # ------------------------------------------------------------------
    def _parse_scanchain_section(self):
        """
        scanchain
            edt_top_channel1_chain[ "PAD_PA"[8], "edt_top_channel1/cell_442",
                ..., "edt_top_channel1/cell_0", "PAD_PA"[10]];
            edt_top_channel2_chain[...];
        end
        """
        # 注意：可能不存在（非 scan pattern）
        m = re.search(r'\bscanchain\b(.*?)\bend\b', self._header_text, re.DOTALL)
        if not m:
            return
        body = m.group(1)
        # 每条链以 ];  结尾
        # 用一个简单的 state machine：找出每个 "name[" 到对应 "]" 块
        i = 0
        while i < len(body):
            # 找 chain_name[
            m2 = re.search(r'(\w+)\s*\[', body[i:])
            if not m2:
                break
            chain_name = m2.group(1)
            start = i + m2.end()  # '[' 之后
            # 找配对 ']'
            depth = 1
            j = start
            while j < len(body) and depth > 0:
                if body[j] == '[':
                    depth += 1
                elif body[j] == ']':
                    depth -= 1
                j += 1
            inner = body[start:j-1]
            # inner 是 chain 元素列表（"PIN_NAME"[idx] 或 "cell_xxx/xxx" 等，逗号分隔）
            # 提取所有引号里的引用 + bus index 一并保留
            tokens = self._extract_pin_refs(inner)
            if len(tokens) < 2:
                i = j
                continue
            scan_in = self._normalize_pin_ref(tokens[0])
            scan_out = self._normalize_pin_ref(tokens[-1])
            # 中间是 cell 数量
            chain_len = len(tokens) - 2
            self.design.scanchains[chain_name] = ScanChain(
                name=chain_name,
                scan_in_pin=scan_in,
                scan_out_pin=scan_out,
                length=chain_len,
            )
            i = j

    @staticmethod
    def _extract_pin_refs(text: str) -> List[str]:
        """提取所有形如 "name" 或 "name"[idx] 的引用,保留出现顺序"""
        results = []
        pos = 0
        # 匹配  "stuff"  或者 "stuff"[idx]
        # 先匹配带 index，再匹配纯名字
        pat = re.compile(r'"([^"]+)"(?:\s*\[\s*(\d+)\s*\])?')
        for m in pat.finditer(text):
            base = m.group(1)
            idx = m.group(2)
            if idx is not None:
                results.append(f'"{base}"[{idx}]')
            else:
                results.append(f'"{base}"')
        return results

    @staticmethod
    def _normalize_pin_ref(ref: str) -> str:
        """ '"PAD_PA"[8]' → 'PAD_PA_8',  '"VREFN"' → 'VREFN' """
        names = expand_pin_ref(ref)
        if len(names) != 1:
            raise ValueError(f"pin 引用 {ref!r} 展开成 {names}, 期望单个")
        return names[0]

    # ------------------------------------------------------------------
    # timeplate
    # ------------------------------------------------------------------
    def _parse_timeplates(self):
        """
        timeplate "_NAME_" period 40ns
            ...
        end
        """
        pattern = re.compile(
            r'\btimeplate\s+"?([^"\s]+)"?\s+period\s+([\d.]+)\s*ns(.*?)\bend\b',
            re.DOTALL
        )
        for m in pattern.finditer(self._header_text):
            name = m.group(1)
            period = float(m.group(2))
            from .ir import wft_name_strip
            tp = Timeplate(
                name_wgl=name,
                name_pat=wft_name_strip(name),
                period_ns=period,
            )
            self.design.timeplates[name] = tp

    # ------------------------------------------------------------------
    # scanstate 段
    # ------------------------------------------------------------------
    def _parse_scanstate_section(self):
        """
        scanstate
            Iedt_top_channel1_sts000000_000002 := groupedt_group1edt_top_channel1 (0
                000...0
                000...001111111110000...0);
            Oedt_top_channel1_sts000000_000002 := ... (X
                XXX...X);
            ...
        end

        语句结构: <var_name> := <group_name> (<bitstring>);
        bitstring 可能跨多行,需要拼接。
        """
        m = re.search(r'\bscanstate\b(.*?)\bend\b', self._header_text, re.DOTALL)
        if not m:
            return
        body = m.group(1)
        # 用 ';' 切语句
        for stmt in body.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            # stmt = "VAR := GROUP (BITS"  (注意 ')' 已被 ';' 切走？不,';' 在 ')' 之后)
            # 实际:  VAR := GROUP (bits)
            mstmt = re.match(
                r'(\w+)\s*:=\s*\w+\s*\((.*)\)\s*$',
                stmt, re.DOTALL
            )
            if not mstmt:
                continue
            var_name = mstmt.group(1)
            bits = mstmt.group(2)
            # 去除所有空白/换行
            bits = bits.translate(_WS_DELETE)
            self.design.scanstates[var_name] = bits

    # ------------------------------------------------------------------
    # pattern 段
    # ------------------------------------------------------------------
    def _parse_pattern_section(self):
        """
        pattern NAME(pin_list_with_direction)
            vector(+, "_WFT_") := [chars];
            scan(+, "_WFT_") := [chars],
            output[chain: Ovar],
            input[chain: Ivar],
            ...;
            ...
        end
        """
        # 注意：pattern 块以 'end' 结尾，但 timeplate 已被消费过。
        # 我们查找 'pattern <Name>(' 开始位置
        mstart = re.search(r'\bpattern\s+(\w+)\s*\(', self.clean_text)
        if not mstart:
            raise ValueError("找不到 pattern 段")
        name = mstart.group(1)
        # 找配对 ')'
        i = mstart.end()
        depth = 1
        while i < len(self.clean_text) and depth > 0:
            if self.clean_text[i] == '(':
                depth += 1
            elif self.clean_text[i] == ')':
                depth -= 1
            i += 1
        pin_list_text = self.clean_text[mstart.end():i-1]
        # 解析 pin_list
        pat_obj = WGLPattern(name=name)
        pat_obj.pin_list = self._parse_pattern_pin_list(pin_list_text)

        # body 从 i 开始到对应 'end'  —— 由于 pattern 是文件最后一个块，
        # 我们贪婪取到最后一个 'end'
        rest = self.clean_text[i:]
        mbody_end = re.search(r'\bend\b\s*$', rest)
        if mbody_end:
            body = rest[:mbody_end.start()]
        else:
            # 找最后一个 'end' （可能后面还有空白）
            ends = list(re.finditer(r'\bend\b', rest))
            if ends:
                body = rest[:ends[-1].start()]
            else:
                body = rest

        pat_obj.vectors = self._parse_pattern_body(body)
        self.design.pattern = pat_obj

    def _parse_pattern_pin_list(self, text: str) -> List[Tuple[str, str]]:
        """
        pin_list_text 形如:
            "VCORE_RDY_OPT"[1], "VCORE_RDY_OPT"[0], "PAD_PA"[15]:I, ..., "VREFP":I,
            "PAD_PA"[15]:O, ..., "VREFP":O
        每个元素是 "name" 或 "name"[idx]，可选 :I / :O 后缀。
        """
        result: List[Tuple[str, str]] = []
        # 按逗号切（但要注意 "name"[idx] 里不会有逗号）
        # 用正则一次性 finditer 出所有 token:
        token_re = re.compile(
            r'"([^"]+)"(?:\s*\[\s*(\d+)\s*\])?(?:\s*:\s*([IO]))?'
        )
        for m in token_re.finditer(text):
            base = m.group(1)
            idx = m.group(2)
            direction = m.group(3) or ''   # '' / 'I' / 'O'
            pin_name = f"{base}_{idx}" if idx is not None else base
            result.append((pin_name, direction))
        return result

    # ---- pattern body 解析（vector / scan 子句） ----

    # 单 vector 子句:   vector(+, "_WFT_") := [ chars ];
    # 单 scan 子句:    scan(+, "_WFT_") := [ chars ],  output[..],input[..]...;
    # vector 字符串可跨多行。我们用更稳健的策略:
    # - 把 body 按 ';' 切片，每片是一个完整子句
    # - 在片内识别 'vector(' 或 'scan(' 关键字

    # 一次性匹配整条子句(可选 repeat 前缀 + 头 + 到分号的尾巴), finditer 一遍扫完。
    #   group1=repeat(可空)  group2=kind  group3=wft  group4=chars  group5=尾巴
    # WFT 名引号可选; chars 内不含 ']' 故用 [^\]]* 避免回溯。
    _CLAUSE_FULL_RE = re.compile(
        r'(?:\brepeat\s+(\d+)\s+)?'
        r'\b(vector|scan)\s*\(\s*\+\s*,\s*"?([^"\s,()]+)"?\s*\)\s*:=\s*\[([^\]]*)\]([^;]*);'
    )
    _SCAN_IO_RE = re.compile(
        r'\b(input|output)\s*\[\s*(\w+)\s*:\s*(\w+)\s*\]'
    )

    # loop N ... end  (单层, 不嵌套, 仅出现在 pattern 段内)
    # 非贪婪到最近的 'end' (因不嵌套, 最近 end 即配对 end)。
    _LOOP_RE = re.compile(r'\bloop\s+(\d+)\b(.*?)\bend\b', re.DOTALL)

    def _expand_loops(self, body: str) -> str:
        """把 body 中的 'loop N ... end' 块就地展开成 N 份块内文本。
        单层不嵌套; 展开后内部 vector/scan/repeat 子句照常被 _CLAUSE_FULL_RE 解析。"""
        if 'loop' not in body:
            return body
        return self._LOOP_RE.sub(
            lambda m: m.group(2) * int(m.group(1)), body)

    def _parse_pattern_body(self, body: str) -> List[WGLVector]:
        body = self._expand_loops(body)      # 先展开 loop N...end
        vectors: List[WGLVector] = []
        scanstates = self.design.scanstates
        label_n = 0
        last_end = 0
        for m in self._CLAUSE_FULL_RE.finditer(body):
            # label: 本 clause 与上一 clause 之间若出现哨兵, 给本向量打标记
            lbl = None
            if self._label_base is not None:
                gap = body[last_end:m.start()]
                cnt = gap.count(_LABEL_SENTINEL)
                if cnt:
                    label_n += cnt
                    lbl = '%s_%d' % (self._label_base, label_n)
            last_end = m.end()
            rep = int(m.group(1)) if m.group(1) else 1
            kind = m.group(2)
            chars = m.group(4).translate(_WS_DELETE)   # 去空格(快)
            if kind == 'vector':
                # 非 scan 拍: 不分配 scan dict
                vectors.append(WGLVector(wft=m.group(3), chars=chars, repeat=rep,
                                         label=lbl))
                continue
            # scan 拍: 解析尾巴里的 input[chain:var]/output[chain:var]
            v = WGLVector(wft=m.group(3), chars=chars, is_scan=True,
                          scan_inputs={}, scan_outputs={}, repeat=rep, label=lbl)
            for mio in self._SCAN_IO_RE.finditer(m.group(5)):
                io_kind, chain_name, var_name = mio.group(1), mio.group(2), mio.group(3)
                bits = scanstates.get(var_name)
                if bits is None:
                    raise ValueError(
                        f"scan 子句引用了未定义的 scanstate 变量: {var_name}")
                if io_kind == 'input':
                    v.scan_inputs[chain_name] = bits
                else:
                    v.scan_outputs[chain_name] = bits
            vectors.append(v)
        return vectors


def parse_wgl_file(path: str, label_marker: Optional[str] = None,
                   label_base: Optional[str] = None) -> WGLDesign:
    """便利函数：从文件路径解析。label_marker/label_base 见 WGLParser。"""
    import os
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    parser = WGLParser(text, source_filename=os.path.basename(path),
                       label_marker=label_marker, label_base=label_base)
    return parser.parse()
