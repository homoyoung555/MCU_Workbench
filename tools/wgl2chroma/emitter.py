"""
Chroma3380P .pat 文件生成器 (流式版本)。

大文件 (100万+ cycle) 内存恒定, 不再把所有 cycle 存进 list.
"""

from typing import List, Tuple, Dict, Optional, IO
from .ir import WGLDesign, WGLVector, wft_name_strip

# Chroma .pat 单条 RPT 计数上限; 超出自动拆成多行 (与 .sd 后端一致)
_RPT_MAX = 65535

# SET_DEC_FILE 固定引用的 .dec 文件名 (写死, 与 pattern 名 / dec_filename 参数无关)
_DEC_FILE = 'pin.dec'


def fold_io(i_raw: str, o_raw: Optional[str],
            i_exp: str, o_exp: Optional[str]) -> str:
    """
    合并 input 侧和 output 侧为单个 .pat 字符。

    规则 (从 tbridge 样例验证):
        纯 input pin (o_raw is None): 直接取 i_exp

        bidir pin:
          I_raw 是显式 drive ('0'/'1', 非'-'):
            → 输出 I_raw 值 (drive 模式, 忽略 O 侧)
          I_raw 是 '-' (继承):
            O_raw 是显式 'L'/'H' → 输出 L/H (expect)
            O_raw 是显式 'X'     → 输出 X (tristate)
            O_raw 也是 '-'       → 用展开后的值 fold
    """
    if o_raw is None:
        # 纯 input pin
        return i_exp

    # bidir pin
    if i_raw in ('0', '1'):
        # I 侧有显式 drive → drive 模式
        return i_raw
    if i_raw == '-':
        # I 侧继承 → 由 O 侧决定
        if o_raw in ('L', 'H'):
            return o_raw
        if o_raw in ('0', '1'):
            return 'L' if o_raw == '0' else 'H'
        if o_raw == 'X':
            return 'X'
        if o_raw == '-':
            # 两边都继承 → 用展开后的值
            if i_exp in ('0', '1'):
                return i_exp
            if o_exp is not None and o_exp in ('L', 'H'):
                return o_exp
            if i_exp in ('L', 'H'):
                return i_exp
            return 'X'
    # i_raw 是 'X' 或 'L'/'H' (少见)
    if o_raw in ('L', 'H'):
        return o_raw
    if i_raw in ('L', 'H'):
        return i_raw
    return 'X'


def expand_dittos(chars: str, prev: List[str], first_vector: bool) -> List[str]:
    out = []
    for i, c in enumerate(chars):
        if c == '-':
            out.append('X' if first_vector else prev[i])
        else:
            out.append(c)
    return out


class PatEmitter:

    def __init__(self, design: WGLDesign, pattern_name: Optional[str] = None,
                 dec_filename: Optional[str] = None,
                 emit_ascii_art: bool = False,
                 sticky_wft: bool = True,
                 wft_continuation: Optional[str] = None,
                 extra_col_name: Optional[str] = None,
                 extra_col_value: str = '0',
                 insert_gap_on_wft_change: bool = False):
        self.design = design
        self.sticky_wft = sticky_wft   # True: timing 仅在切换时输出(只保留首次切换标志)
        # 附加列: 在每行向量末尾追加 1 列固定值 (drive 0/1); None=不加
        self.extra_col_name = extra_col_name or None
        self.extra_col_value = '1' if str(extra_col_value) == '1' else '0'
        # timing 切换时插入一行全 X 空周期 (附加列保持固定值); 最开头"无->A"不插
        self.insert_gap_on_wft_change = insert_gap_on_wft_change
        # timing 沿用(未切换)那一拍, 替代 ` * <wft>` 的内容:
        #   None / ''   → 方案A: 直接省略 timing 字段           (` * <data>;`)
        #   其它字符串  → 方案B: 原样插入该串(含你想要的前导空格), 如 ' *' → (` * <data> *;`)
        self.wft_continuation = wft_continuation or ''
        if pattern_name is None:
            base = design.source_filename
            for ext in ('.wgl', '.WGL', '.Wgl'):
                if base.endswith(ext):
                    base = base[:-len(ext)]
                    break
            pattern_name = base or (design.pattern.name if design.pattern else 'pattern')
        self.pattern_name = pattern_name
        if dec_filename is None:
            dec_filename = f"./{pattern_name}.dec"
        self.dec_filename = dec_filename
        self.emit_ascii_art = emit_ascii_art

        self._pat_pins: List[str] = [s.name for s in design.signals]
        self._pin_idx_map: List[Tuple[int, Optional[int]]] = []
        self._build_pin_idx_map()

        # --- 性能优化: 预拆分 简单pin / bidir pin ---
        # 简单 pin (纯 input / 纯 output): 输出 = expanded[src_idx], 无需 fold_io
        # bidir pin: 仍走完整 fold_io
        self._n_out = len(self._pin_idx_map)
        self._simple_map: List[Tuple[int, int]] = []        # (out_pos, src_idx)
        self._bidir_map: List[Tuple[int, int, int]] = []    # (out_pos, i_idx, o_idx)
        for out_pos, (i_idx, o_idx) in enumerate(self._pin_idx_map):
            if o_idx is None:
                self._simple_map.append((out_pos, i_idx))
            else:
                self._bidir_map.append((out_pos, i_idx, o_idx))
        self._has_bidir = bool(self._bidir_map)
        # 无 ditto 的普通拍: 折叠结果只依赖 raw chars, 可缓存
        self._fold_cache: Dict[str, str] = {}

        # 含附加列的输出 pin 头 (附加列名加在最后)
        self._out_pins: List[str] = list(self._pat_pins)
        if self.extra_col_name:
            self._out_pins.append(self.extra_col_name)
        # 全 X 空周期的字符串 (原 pin 全 X + 附加列固定值)
        self._gap_chars = 'X' * len(self._pat_pins)
        if self.extra_col_name:
            self._gap_chars += self.extra_col_value

    def _add_extra(self, chars: str) -> str:
        """在折叠结果末尾拼接附加列固定值"""
        return chars + self.extra_col_value if self.extra_col_name else chars

    def _build_pin_idx_map(self):
        if self.design.pattern is None:
            raise ValueError("design.pattern 为空")
        wgl_pl = self.design.pattern.pin_list
        idx_by_name_dir: Dict[Tuple[str, str], int] = {}
        for i, (n, d) in enumerate(wgl_pl):
            idx_by_name_dir[(n, d)] = i

        for sig in self.design.signals:
            name = sig.name
            if sig.direction == 'input':
                i_idx = idx_by_name_dir.get((name, ''))
                if i_idx is None:
                    i_idx = idx_by_name_dir.get((name, 'I'))
                if i_idx is None:
                    raise ValueError(f"input pin {name!r} 在 WGL pattern 头中没找到")
                self._pin_idx_map.append((i_idx, None))
            elif sig.direction == 'output':
                o_idx = idx_by_name_dir.get((name, 'O'))
                if o_idx is None:
                    o_idx = idx_by_name_dir.get((name, ''))
                if o_idx is None:
                    raise ValueError(f"output pin {name!r} 在 WGL pattern 头中没找到")
                self._pin_idx_map.append((o_idx, None))
            else:
                i_idx = idx_by_name_dir.get((name, 'I'))
                o_idx = idx_by_name_dir.get((name, 'O'))
                if i_idx is None or o_idx is None:
                    raise ValueError(f"bidir pin {name!r} 找不到 :I 或 :O")
                self._pin_idx_map.append((i_idx, o_idx))

    def _fold_to_pat_chars(self, raw_chars: str, expanded) -> str:
        """把原始 + 展开后的字符 折叠为 .pat pin 字符串 (热路径, 已优化)。
        expanded 可以是 list 或 str (二者都支持索引取字符)。"""
        out = [''] * self._n_out
        exp = expanded
        # 1) 简单 pin: 直接索引, 不调用 fold_io (绝大多数 pin 走这里)
        for out_pos, src_idx in self._simple_map:
            out[out_pos] = exp[src_idx]
        # 2) bidir pin: 完整折叠逻辑
        if self._has_bidir:
            for out_pos, i_idx, o_idx in self._bidir_map:
                out[out_pos] = fold_io(raw_chars[i_idx], raw_chars[o_idx],
                                       exp[i_idx], exp[o_idx])
        return ''.join(out)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def emit(self) -> str:
        """返回完整 .pat 字符串 (小文件用)"""
        import io
        buf = io.StringIO()
        self.emit_to(buf)
        return buf.getvalue()

    def emit_to(self, fp: IO[str]):
        """流式写入 .pat 到文件对象 (大文件用, 内存恒定)"""
        w = fp.write
        for line in self._header_lines():
            w(line + '\n')
        w('\n')
        self._write_spm_pattern(fp)

    def _header_lines(self) -> List[str]:
        from datetime import datetime
        now = datetime.now().strftime('%m/%d/%Y at %H:%M:%S')
        lines = [
            '//',
            f'// File       : {self.pattern_name}.pat',
            f'// Created At : {now}',
            f'// Created By : wgl2chroma',
            f'// Source WGL : {self.design.source_filename}',
            f'// Section    : Chroma 3380 Pattern File',
            '//',
            '',
            f'SET_DEC_FILE "{_DEC_FILE}"',   # 固定 pin.dec (忽略 dec_filename)
            '',
        ]
        lines.extend(self._emit_pin_header())
        return lines

    def _emit_pin_header(self) -> List[str]:
        lines = ['HEADER']
        names = self._out_pins
        max_width = 95
        cur_line = '  '
        for i, name in enumerate(names):
            is_last = (i == len(names) - 1)
            sep = ';' if is_last else ','
            piece = name + sep
            if len(cur_line) + len(piece) + 1 > max_width and cur_line.strip():
                lines.append(cur_line.rstrip())
                cur_line = '  '
            if cur_line.strip():
                cur_line += ' '
            cur_line += piece
        if cur_line.strip():
            lines.append(cur_line.rstrip())
        return lines

    def _emit_pin_label_ascii_art(self) -> List[str]:
        names = self._pat_pins
        max_len = max(len(s) for s in names)
        lines = []
        for row in range(max_len):
            chars = [name[row] if row < len(name) else ' ' for name in names]
            line = '// ' + ''.join(chars).rstrip()
            if line.strip() != '//':
                lines.append(line)
        return lines

    # ------------------------------------------------------------------
    # 流式 SPM_PATTERN (RPT 压缩 + 行尾注释)
    # ------------------------------------------------------------------

    @staticmethod
    def _chroma_tail(is_switch: bool, wft: str, micro: str) -> str:
        """生成 Chroma 行 pattern_data 之后、分号之前的字段: *[ts_name, micro_ins]。
        - 切换行(is_switch): '* <ts_name>' [+ ', <micro>']  (例 '* tp_setup, RPT 65535')
        - 延续行:            '*' + <micro> (无逗号无空格)     (例 '*RPT 24489' / '*')
        micro 取 '' / 'RPT n' / 'STOP'。"""
        if is_switch:
            t = f'* {wft}'
            if micro:
                t += f', {micro}'
            return t
        return f'*{micro}'

    def _write_spm_pattern(self, fp: IO[str]):
        from datetime import datetime
        w = fp.write

        w(f'SPM_PATTERN ({self.pattern_name}) {{\n')
        if self.emit_ascii_art:
            for line in self._emit_pin_label_ascii_art():
                w(line + '\n')
        date_str = datetime.now().strftime('%a %b %d %H:%M:%S %Y')
        w(f'// DATE: {date_str}\n')
        w(f'// WGL : {self.design.source_filename}\n')
        # CRAFT 把未被跳转引用的 ``name::`` 当作需配对的 marker；短 WGL 若起止间
        # 没有普通向量会报 ``name_sp unmatch``。这两个名字只是转换诊断信息，运行时
        # 不引用，故保留为注释，不能作为可执行 label 写入 .pat。
        w(f'// {self.pattern_name}_st::\n')

        if self.design.pattern is None:
            raise ValueError("pattern 为空")

        pin_list_len = len(self.design.pattern.pin_list)
        prev = ['X'] * pin_list_len
        first_vec = True

        wgl_pl = self.design.pattern.pin_list
        idx_by_name_dir = {(n, d): idx for idx, (n, d) in enumerate(wgl_pl)}
        _O_MAP = {'0': 'L', '1': 'H'}

        # --- RPT 状态机 ---
        pending_chars: Optional[str] = None
        pending_wft: str = ''
        pending_count: int = 0
        pending_label: Optional[str] = None   # 该组向量上的 label (单独成行写在数据行前)
        row_idx = 0
        cycle_idx = 0
        last_chars: str = self._gap_chars
        last_wft: str = 'default_WFT'
        emitted_wft: Optional[str] = None   # 当前在输出流中"已生效"的 WFT

        def flush():
            nonlocal pending_chars, pending_count, row_idx, cycle_idx, emitted_wft
            nonlocal pending_label
            if pending_chars is None:
                return
            # Chroma 格式: ' *<pattern_data>' + '*[ts_name, micro_ins]' + ';'
            # ts_name 仅在切换那一行带(sticky); 非 sticky 每行都带。
            first_is_switch = (not self.sticky_wft) or (pending_wft != emitted_wft)
            if first_is_switch:
                emitted_wft = pending_wft
            # label: 单独一行写在该组数据行上方
            if pending_label:
                w(f'{pending_label}:\n')
            # RPT 上限 _RPT_MAX: 超出拆成多行; ts_name 仅首行带
            remaining = pending_count
            first_chunk = True
            while remaining > 0:
                this = _RPT_MAX if remaining > _RPT_MAX else remaining
                remaining -= this
                is_switch = first_is_switch if first_chunk else (not self.sticky_wft)
                micro = '' if this == 1 else f'RPT {this}'
                tail = self._chroma_tail(is_switch, pending_wft, micro)
                if this == 1:
                    w(f' *{pending_chars}{tail}; // r{row_idx}  {cycle_idx}\n')
                else:
                    w(f' *{pending_chars}{tail};\n')
                cycle_idx += this
                row_idx += 1
                first_chunk = False
            pending_chars = None
            pending_count = 0
            pending_label = None

        last_fed_wft: Optional[str] = None   # 上一拍(送入 push)的 wft, 用于检测切换插空拍

        def _effective_wft() -> Optional[str]:
            """当前"已生效"WFT: 有未刷出的 pending 组则取其 wft, 否则取已刷出的 emitted_wft。"""
            return pending_wft if pending_chars is not None else emitted_wft

        def _marks_timing(wft: str) -> bool:
            """这一拍是否是"带 timing 标记且应单独成行"的拍。
            仅 sticky 模式下、真正切换(wft != 已生效)时为 True;
            非 sticky 模式每拍都带 timing, 若也拆分则 RPT 全废, 故不拆(返回 False)。"""
            if not self.sticky_wft:
                return False
            return wft != _effective_wft()

        def push(chars: str, wft: str, force_break: bool = False, count: int = 1,
                 label: Optional[str] = None):
            nonlocal pending_chars, pending_wft, pending_count
            nonlocal last_chars, last_wft, last_fed_wft
            # --- timing 切换 → 插入一行全 X 空周期(附加列保持固定值) ---
            # 最开头"无->A"(last_fed_wft is None)不插; 之后每次 A->B(B!=A)插一行
            if (self.insert_gap_on_wft_change
                    and last_fed_wft is not None and wft != last_fed_wft):
                # 空拍标"切换后"的新 timing wft, force_break 确保不与邻拍 RPT 合并
                _push_raw(self._gap_chars, wft, force_break=True, count=1)
            last_fed_wft = wft
            # --- 附加列: 拼在折叠结果末尾; label 随该拍带入(强制不与邻拍合并) ---
            _push_raw(self._add_extra(chars), wft, force_break=force_break, count=count,
                      label=label)

        def _push_raw(chars: str, wft: str, force_break: bool = False, count: int = 1,
                      _no_split: bool = False, label: Optional[str] = None):
            nonlocal pending_chars, pending_wft, pending_count, pending_label
            nonlocal last_chars, last_wft
            # 带 TIMING_SET 标记的那一拍不叠加 RPT:
            # 若这组会带标记且 count>1, 先单独写 1 拍(带标记), 余 count-1 拍另起组
            if (not _no_split) and count > 1 and _marks_timing(wft):
                _push_raw(chars, wft, force_break=True, count=1, _no_split=True,
                          label=label)
                # 余拍另起组(已标记过, 不再拆), 内部仍可压成一个 RPT
                _push_raw(chars, wft, force_break=True, count=count - 1, _no_split=True)
                return
            last_chars = chars
            last_wft = wft
            # label 拍不与邻拍合并(保证 label 精确对应该拍); 普通拍照常 RPT 合并
            if (pending_chars is not None
                    and chars == pending_chars
                    and wft == pending_wft
                    and not force_break
                    and pending_label is None and label is None):
                pending_count += count
            else:
                flush()
                pending_chars = chars
                pending_wft = wft
                pending_count = count
                pending_label = label
            # 推进"已生效 WFT"(累积期), 与 flush 里 emitted_wft 的语义一致
            if self.sticky_wft:
                cur_effective_wft = wft
            else:
                cur_effective_wft = wft

        # --- 遍历 WGL vectors ---
        for v in self.design.pattern.vectors:
            wft_pat = wft_name_strip(v.wft)

            if not v.is_scan:
                chars = v.chars
                rep = v.repeat
                if '-' not in chars:
                    # 无 ditto: 折叠只依赖 chars → 缓存; prev 直接用 str(免 list 分配)
                    first_vec = False
                    pat = self._fold_cache.get(chars)
                    if pat is None:
                        pat = self._fold_to_pat_chars(chars, chars)
                        self._fold_cache[chars] = pat
                    prev = chars
                    push(pat, wft_pat, count=rep, label=v.label)   # repeat N → 一次性计入 RPT
                else:
                    expanded = expand_dittos(chars, prev, first_vec)
                    prev = expanded
                    first_vec = False
                    push(self._fold_to_pat_chars(chars, expanded), wft_pat, count=rep,
                         label=v.label)
            else:
                template = expand_dittos(v.chars, prev, first_vec)
                first_vec = False

                chain_names = set(v.scan_inputs.keys()) | set(v.scan_outputs.keys())
                shift_len = 0
                for cn in chain_names:
                    if cn in v.scan_inputs:
                        shift_len = max(shift_len, len(v.scan_inputs[cn]))
                    if cn in v.scan_outputs:
                        shift_len = max(shift_len, len(v.scan_outputs[cn]))

                chain_info = []
                for cn in chain_names:
                    chain = self.design.scanchains.get(cn)
                    if chain is None:
                        continue
                    i_pos = idx_by_name_dir.get((chain.scan_in_pin, 'I'))
                    if i_pos is None:
                        i_pos = idx_by_name_dir.get((chain.scan_in_pin, ''))
                    o_pos = idx_by_name_dir.get((chain.scan_out_pin, 'O'))
                    if o_pos is None:
                        o_pos = idx_by_name_dir.get((chain.scan_out_pin, ''))
                    in_str = v.scan_inputs.get(cn, 'X' * shift_len)
                    out_str = v.scan_outputs.get(cn, 'X' * shift_len)
                    chain_info.append((i_pos, o_pos, in_str, out_str))

                cur = list(template)
                # raw 模板: scan 子句本身的 chars (含 '-')
                raw_template = list(v.chars)
                cur_raw = list(raw_template)
                scan_lbl = v.label              # label 仅挂到该 scan 的首个 shift 拍
                for _ in range(v.repeat):       # repeat N: 整个 shift 序列重复 N 次
                    for k in range(shift_len):
                        for (i_pos, o_pos, in_str, out_str) in chain_info:
                            if i_pos is not None and k < len(in_str):
                                cur[i_pos] = in_str[k]
                                cur_raw[i_pos] = in_str[k]  # 注入是"显式"
                            if o_pos is not None and k < len(out_str):
                                cur[o_pos] = _O_MAP.get(o_bit := out_str[k], o_bit)
                                cur_raw[o_pos] = cur[o_pos]  # 注入也是"显式"
                        pat_chars = self._fold_to_pat_chars(
                            ''.join(cur_raw), cur)
                        push(pat_chars, wft_pat,
                             force_break=(k == shift_len - 1), label=scan_lbl)
                        scan_lbl = None
                        # 重置 cur_raw 为模板 (每拍重新注入)
                        cur_raw = list(raw_template)

                prev = list(template)

        # 末尾约定(与 tbridge 一致): 最后一拍直接作为 _sp:: 的 STOP 行,
        # 不再额外重复一行。其余 (count-1) 拍照常进 _st::。
        stop_label = None
        if pending_chars is not None:
            stop_chars = pending_chars
            stop_wft = pending_wft
            if pending_count >= 2:
                pending_count -= 1   # 留 1 拍给 STOP
                flush()              # 其余 (count-1) 拍进 _st:: (label 在 flush 内输出)
            else:
                stop_label = pending_label  # 仅 1 拍 → 全给 STOP; label 移到 STOP 行前
                pending_chars = None # 不进 _st::
                pending_count = 0
                pending_label = None
        else:
            # 没有任何 cycle 的极端情况
            stop_chars = last_chars
            stop_wft = last_wft

        w(f'// {self.pattern_name}_sp::\n')
        if stop_label:
            w(f'{stop_label}:\n')
        stop_is_switch = (not self.sticky_wft) or (stop_wft != emitted_wft)
        w(f' *{stop_chars}{self._chroma_tail(stop_is_switch, stop_wft, "STOP")};\n')
        w('}\n')
