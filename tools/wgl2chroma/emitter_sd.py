"""
S100 .sd (YTEC) 向量文件生成器 (流式版本)。

与 Chroma .pat 共享同一套 WGLDesign / IR 与折叠逻辑 (fold_io)。
差异只在"怎么写出来":
  - pin 头 = HEAD[PIN_NAME]: ... END_HEAD;  (每 pin 一行)
  - 数据段 = @@PATTERN_DEFINE ... @@END_PATTERN_DEFINE
  - 每拍一行: <前缀 START:/END:/空> + 字符串 + ';' [+ ' TIMING_SET <wft>;'] [// 注释]
  - timing 为 sticky: 仅在 WFT 切换时输出 TIMING_SET (首拍必带)
  - 不做 RPT: 每拍真实展开成一行 (含 repeat N 展开、scan shift 逐行)
  - 数据字符统一从固定列开始: 行首 '\t' + 宽度 30 的前缀
    (START: 右对齐到 30 列 = 24 空格; END: = 26 空格; 中间行 = 30 空格)

折叠/电平规则与 .pat 完全一致 (drive 0/1 优先, expect L/H, 否则 X);
scan 输出注入 0/1 -> L/H 同 .pat。
"""

from typing import List, Tuple, Dict, Optional, IO
from .ir import WGLDesign, wft_name_strip
from .emitter import fold_io, expand_dittos


# YTEC 风格首行备注 (不被 S100 校验, 仅备注)
SD_BANNER = "//YTEC WGL Pattern Convert v1.1.0 (2024.11.13)"

# 数据字符前缀总宽 (不含行首 '\t'); 所有行(START:/END:/普通/label)右对齐到此宽度
# 注: YTEC 原格式为 30 列; 本工具按需求改为 10 列(数据列左移, 缩进更少)
_PREFIX_W = 10

# label 行前缀宽度(与普通行一致 = 10 列)
_LABEL_PREFIX_W = 10

# S100 .sd 单条 RPT 计数上限; 超出拆成多行
_RPT_MAX = 65535


class SdEmitter:

    def __init__(self, design: WGLDesign, pattern_name: Optional[str] = None,
                 emit_ascii_art: bool = True,
                 sticky_wft: bool = True,
                 extra_col_name: Optional[str] = None,
                 extra_col_value: str = '0',
                 insert_gap_on_wft_change: bool = False):
        """
        design        : 解析后的 WGLDesign (与 .pat 共用)
        pattern_name  : 仅用于内部注释; .sd 本身不强制 pattern 名
        emit_ascii_art: 是否在 @@PATTERN_DEFINE 下生成竖排 pin 名注释 (默认开)
        sticky_wft    : True 时 TIMING_SET 仅在切换时输出 (.sd 的固有行为)
        extra_col_name: 在每行向量末尾追加 1 列固定值的列名; None=不加
        extra_col_value: 附加列固定值 '0'/'1'
        insert_gap_on_wft_change: TIMING_SET 切换时插入一行全 X 空周期
                                  (附加列保持固定值); 最开头"无->A"不插
        """
        self.design = design
        if pattern_name is None:
            base = design.source_filename
            for ext in ('.wgl', '.WGL', '.Wgl'):
                if base.endswith(ext):
                    base = base[:-len(ext)]
                    break
            pattern_name = base or 'pattern'
        self.pattern_name = pattern_name
        self.emit_ascii_art = emit_ascii_art
        self.sticky_wft = sticky_wft
        self.extra_col_name = extra_col_name or None
        self.extra_col_value = '1' if str(extra_col_value) == '1' else '0'
        self.insert_gap_on_wft_change = insert_gap_on_wft_change

        # pin 顺序 = signal 段顺序 (与 .pat HEADER 同一套)
        self._pat_pins: List[str] = [s.name for s in design.signals]
        self._pin_idx_map: List[Tuple[int, Optional[int]]] = []
        self._build_pin_idx_map()

        # 折叠热路径预拆分 (同 .pat emitter 的优化)
        self._n_out = len(self._pin_idx_map)
        self._simple_map: List[Tuple[int, int]] = []
        self._bidir_map: List[Tuple[int, int, int]] = []
        for out_pos, (i_idx, o_idx) in enumerate(self._pin_idx_map):
            if o_idx is None:
                self._simple_map.append((out_pos, i_idx))
            else:
                self._bidir_map.append((out_pos, i_idx, o_idx))
        self._has_bidir = bool(self._bidir_map)
        self._fold_cache: Dict[str, str] = {}

        # 含附加列的输出 pin 头 + 全 X 空周期串
        self._out_pins: List[str] = list(self._pat_pins)
        if self.extra_col_name:
            self._out_pins.append(self.extra_col_name)
        self._gap_chars = 'X' * len(self._pat_pins)
        if self.extra_col_name:
            self._gap_chars += self.extra_col_value

    def _add_extra(self, chars: str) -> str:
        return chars + self.extra_col_value if self.extra_col_name else chars

    # ------------------------------------------------------------------
    # pin 索引映射 (与 .pat emitter 同逻辑: 把 signal 映射到 WGL pin_list 的列)
    # ------------------------------------------------------------------
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

    def _fold_to_chars(self, raw_chars: str, expanded) -> str:
        """折叠为 .sd 一行字符 (与 .pat 折叠完全一致)"""
        out = [''] * self._n_out
        exp = expanded
        for out_pos, src_idx in self._simple_map:
            out[out_pos] = exp[src_idx]
        if self._has_bidir:
            for out_pos, i_idx, o_idx in self._bidir_map:
                out[out_pos] = fold_io(raw_chars[i_idx], raw_chars[o_idx],
                                       exp[i_idx], exp[o_idx])
        return ''.join(out)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def emit(self) -> str:
        import io
        buf = io.StringIO()
        self.emit_to(buf)
        return buf.getvalue()

    def emit_to(self, fp: IO[str]):
        """流式写入 .sd (大文件内存恒定)。行尾用 CRLF (与样例一致)。"""
        w = fp.write
        nl = '\r\n'

        # --- 首行备注 + pin 头 ---
        w(SD_BANNER + nl)
        w('HEAD[PIN_NAME]:' + nl)
        names = self._out_pins
        for i, name in enumerate(names):
            sep = ';' if i == len(names) - 1 else ','
            w(f'\t{name}{sep}' + nl)
        w('END_HEAD;' + nl)

        # --- pattern 段 ---
        w('@@PATTERN_DEFINE' + nl)
        if self.emit_ascii_art:
            for line in self._pin_label_ascii_art():
                w(line + nl)
        self._write_vectors(fp, nl)
        w('@@END_PATTERN_DEFINE' + nl)

    def _pin_label_ascii_art(self) -> List[str]:
        """竖排 pin 名注释 (对齐到数据列, 仅注释用)。"""
        names = self._out_pins
        max_len = max(len(s) for s in names)
        pad = '\t' + ' ' * _PREFIX_W
        lines = []
        for row in range(max_len):
            chars = [name[row] if row < len(name) else ' ' for name in names]
            lines.append(pad + '//' + ''.join(chars).rstrip())
        return lines

    # ------------------------------------------------------------------
    # 数据行 (sticky TIMING_SET, 无 RPT, 逐行展开)
    # ------------------------------------------------------------------
    def _data_line(self, prefix_kw: str, chars: str, tset: Optional[str],
                   row_idx: int, cycle_idx: int, rpt: int = 1,
                   is_end: bool = False, prefix_w: Optional[int] = None) -> str:
        """组一行:
        '\t' + 右对齐前缀(START:/END:/空) + chars + ';'
             [+ 'TIMING_SET <wft>;'] [+ 'RPT <n>;'] + ' //r<行> <cyc>'
        TIMING_SET 写在 RPT 之前; rpt==1 时不写 RPT;
        END: 行(is_end=True)不写 RPT(按需求, 末行不带 RPT)。
        注释格式对齐 Chroma .pat: //r<数据行号> <起始cycle>。
        """
        prefix = prefix_kw.rjust(_PREFIX_W if prefix_w is None else prefix_w)
        # 普通行/START/END 对齐到 _PREFIX_W(30); label 行对齐到 _LABEL_PREFIX_W(10)
        line = '\t' + prefix + chars + ';'
        if tset is not None:
            line += f'TIMING_SET {tset};'
        if rpt > 1 and not is_end:
            line += f'RPT {rpt};'
        line += f' //r{row_idx} {cycle_idx}'
        return line

    def _write_vectors(self, fp: IO[str], nl: str):
        w = fp.write
        if self.design.pattern is None:
            raise ValueError("pattern 为空")

        pin_list_len = len(self.design.pattern.pin_list)
        prev = ['X'] * pin_list_len
        first_vec = True

        wgl_pl = self.design.pattern.pin_list
        idx_by_name_dir = {(n, d): idx for idx, (n, d) in enumerate(wgl_pl)}
        _O_MAP = {'0': 'L', '1': 'H'}

        emitted_wft: Optional[str] = None
        cycle_idx = 0          # 已写出(展开后)的 cycle 数, 用于注释
        row_idx = 0            # 输出数据行序号(0 起), 用于 //r<行> 注释
        first_emit = True      # 下一组是否是文件第一组(标 START:)

        # RPT 压缩状态机:
        #   累计连续且 (chars, wft) 相同的拍为一组 -> 一行 RPT N (N>65535 拆多行)。
        #   为了让"最后一组"标 END:, 延迟写出当前累计组, 直到它被打断或收尾。
        run_chars: Optional[str] = None
        run_wft: str = ''
        run_count: int = 0
        run_label: Optional[str] = None

        def _emit_chunks(chars: str, count: int, tset: Optional[str],
                         is_first: bool, is_end: bool, label: Optional[str] = None):
            """把 count 拍写成若干行(每行最多 _RPT_MAX), 维护 row_idx/cycle_idx。
            is_first: 该组第一行标 START:; is_end: 该组最后一行标 END:(且不带 RPT)。
            label: 非空时, 该组首行前缀改为 '<label>:'(右对齐到第10列, 覆盖 START/END)。"""
            nonlocal cycle_idx, row_idx
            remaining = count
            n_chunks = (count + _RPT_MAX - 1) // _RPT_MAX
            for chunk_i in range(n_chunks):
                this = min(remaining, _RPT_MAX)
                remaining -= this
                kw = 'START:' if (is_first and chunk_i == 0) else \
                     ('END:' if (is_end and chunk_i == n_chunks - 1) else '')
                pw = None
                if label and chunk_i == 0:
                    kw = label + ':'
                    pw = _LABEL_PREFIX_W       # label 行右对齐到第 10 列(缩进更少)
                this_tset = tset if chunk_i == 0 else None   # TIMING_SET 仅该组首行
                w(self._data_line(kw, chars, this_tset, row_idx, cycle_idx,
                                  rpt=this, is_end=(is_end and chunk_i == n_chunks - 1),
                                  prefix_w=pw)
                  + nl)
                cycle_idx += this
                row_idx += 1

        def _emit_group(chars: str, wft: str, count: int, is_first: bool, is_last: bool,
                        label: Optional[str] = None):
            """写出一组 count 个相同拍。label 非空时挂到该组首行前缀。
            - 带 TIMING_SET 标记 (切换) 且 count>1: 标记拍单独 1 行(不叠 RPT),
              余 count-1 拍另起组(可 RPT)。
            - 最后一组且 count>1: 末拍单独作 END:(不带 RPT)。"""
            nonlocal emitted_wft
            if self.sticky_wft:
                tset = None if (wft == emitted_wft) else wft
            else:
                tset = wft
            if tset is not None:
                emitted_wft = wft

            # --- 带 timing 标记的拍不叠 RPT: 剥出首拍, 余拍递归(此时已无标记) ---
            if tset is not None and count > 1:
                # 标记拍: 单独 1 行(is_first 归它), 不是最后一拍; label 挂到此首行
                _emit_chunks(chars, 1, tset, is_first=is_first, is_end=False, label=label)
                # 余 count-1 拍: 无标记, 正常(可 RPT / 末拍 END 拆分)
                _emit_group_no_mark(chars, count - 1, is_first=False, is_last=is_last)
                return

            if is_last and count > 1:
                _emit_chunks(chars, count - 1, tset, is_first=is_first, is_end=False, label=label)
                _emit_chunks(chars, 1, None, is_first=False, is_end=True)
            elif is_last:
                _emit_chunks(chars, 1, tset, is_first=is_first, is_end=True, label=label)
            else:
                _emit_chunks(chars, count, tset, is_first=is_first, is_end=False, label=label)

        def _emit_group_no_mark(chars: str, count: int, is_first: bool, is_last: bool):
            """写一组确定不带 TIMING_SET 的拍 (余拍); 仍处理 END 末拍拆分。"""
            if count <= 0:
                return
            if is_last and count > 1:
                _emit_chunks(chars, count - 1, None, is_first=is_first, is_end=False)
                _emit_chunks(chars, 1, None, is_first=False, is_end=True)
            elif is_last:
                _emit_chunks(chars, 1, None, is_first=is_first, is_end=True)
            else:
                _emit_chunks(chars, count, None, is_first=is_first, is_end=False)

        def _flush_run(is_last: bool):
            nonlocal run_chars, run_count, first_emit, run_label
            if run_chars is None:
                return
            _emit_group(run_chars, run_wft, run_count,
                        is_first=first_emit, is_last=is_last, label=run_label)
            first_emit = False
            run_chars = None
            run_count = 0
            run_label = None

        last_fed_wft: Optional[str] = None   # 上一拍 wft, 检测切换插空拍

        def _feed_raw(chars: str, wft: str, label: Optional[str] = None):
            nonlocal run_chars, run_wft, run_count, run_label
            if (run_chars is not None and chars == run_chars and wft == run_wft
                    and run_label is None and label is None):
                run_count += 1
            else:
                _flush_run(is_last=False)
                run_chars = chars
                run_wft = wft
                run_count = 1
                run_label = label

        def feed(chars: str, wft: str, label: Optional[str] = None):
            nonlocal last_fed_wft
            # timing 切换 → 插一行全 X 空周期(附加列保持固定值); 最开头"无->A"不插
            if (self.insert_gap_on_wft_change
                    and last_fed_wft is not None and wft != last_fed_wft):
                _feed_raw(self._gap_chars, wft)   # 空拍标"切换后"新 timing
            last_fed_wft = wft
            _feed_raw(self._add_extra(chars), wft, label=label)

        # --- 遍历 vectors ---
        for v in self.design.pattern.vectors:
            wft_pat = wft_name_strip(v.wft)

            if not v.is_scan:
                chars = v.chars
                rep = v.repeat
                if '-' not in chars:
                    first_vec = False
                    pat = self._fold_cache.get(chars)
                    if pat is None:
                        pat = self._fold_to_chars(chars, chars)
                        self._fold_cache[chars] = pat
                    prev = chars
                    _lbl = v.label
                    for _ in range(rep):
                        feed(pat, wft_pat, label=_lbl)
                        _lbl = None
                else:
                    expanded = expand_dittos(chars, prev, first_vec)
                    prev = expanded
                    first_vec = False
                    pat = self._fold_to_chars(chars, expanded)
                    _lbl = v.label
                    for _ in range(rep):
                        feed(pat, wft_pat, label=_lbl)
                        _lbl = None
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
                raw_template = list(v.chars)
                cur_raw = list(raw_template)
                _scan_lbl = v.label              # label 仅挂到首个 shift 拍
                for _ in range(v.repeat):
                    for k in range(shift_len):
                        for (i_pos, o_pos, in_str, out_str) in chain_info:
                            if i_pos is not None and k < len(in_str):
                                cur[i_pos] = in_str[k]
                                cur_raw[i_pos] = in_str[k]
                            if o_pos is not None and k < len(out_str):
                                cur[o_pos] = _O_MAP.get(o_bit := out_str[k], o_bit)
                                cur_raw[o_pos] = cur[o_pos]
                        feed(self._fold_to_chars(''.join(cur_raw), cur), wft_pat,
                             label=_scan_lbl)
                        _scan_lbl = None
                        cur_raw = list(raw_template)

                prev = list(template)

        # --- 收尾: 最后一组标 END: ---
        _flush_run(is_last=True)
