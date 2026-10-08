"""
WGL → Chroma3380P .pat 转换工具 GUI (Tkinter)

特性:
- 支持选择单个 .wgl 文件或包含 .wgl 的目录 (批量)
- 输出目录可选 (默认与输入同目录)
- 选项: 是否生成 ASCII pin 名注释 等
- 转换日志显示
- 多线程执行,UI 不卡顿
"""

import os
import sys
import threading
import traceback


# ----------------------------------------------------------------------
# 启动防护: 任何启动异常都写日志 + 尽量弹窗 + 控制台暂停, 避免双击时一闪而过
# ----------------------------------------------------------------------
def _report_fatal(title: str, text: str):
    log_path = '(未能写入日志)'
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'startup_error.log')
        with open(log_path, 'w', encoding='utf-8') as fp:
            fp.write(title + '\n\n' + text)
    except Exception:
        pass
    # 尽量弹窗(tkinter 不可用时自动跳过)
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        _r = _tk.Tk()
        _r.withdraw()
        _mb.showerror(title, text + '\n\n错误日志: ' + log_path)
        _r.destroy()
    except Exception:
        pass
    # 控制台打印 + 暂停(双击运行时窗口不会立即消失)
    try:
        sys.stderr.write('\n' + title + '\n' + text + '\n')
    except Exception:
        pass
    try:
        input('\n启动失败。错误已写入: %s\n按回车键退出...' % log_path)
    except Exception:
        pass


# tkinter 导入(缺失时给出可读提示, 而不是闪退)
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:
    _report_fatal(
        '启动失败: 当前 Python 缺少 tkinter (Tk) 支持',
        '请重装 Windows 官方 Python (默认自带 tcl/tk);\n'
        '若为精简版/嵌入版/conda 环境, 执行 conda install tk 或重装并勾选 tcl/tk。\n\n'
        + traceback.format_exc())
    sys.exit(1)


def _load_convert_one():
    """稳健加载 convert_one。
    - 作为包运行 (python -m wgl2chroma / wgl2chroma.gui): 相对导入
    - 直接双击 / python gui.py: 按"实际文件夹名"导入, 不硬编码包名,
      文件夹被改名或多层解压也能正常运行
    """
    if __package__ not in (None, ''):
        from .converter import convert_one
        return convert_one
    import importlib
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(pkg_dir)
    pkg_name = os.path.basename(pkg_dir)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module(pkg_name + '.converter').convert_one


# 延迟到 main() 中加载并赋给本模块全局, 避免顶层导入失败导致无法捕获的闪退
convert_one = None


class WglToChromaGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('WGL → Chroma3380P Pattern 转换工具')
        self.geometry('820x720')
        self.minsize(720, 620)

        # 状态变量
        self.input_paths_var = tk.StringVar()  # 显示用 (路径串)
        self.output_dir_var = tk.StringVar()
        self.same_dir_var = tk.BooleanVar(value=True)
        self.target_var = tk.StringVar(value='Chroma .pat')   # 输出格式
        self.ascii_art_var = tk.BooleanVar(value=False)
        self.sticky_wft_var = tk.BooleanVar(value=True)   # timing 仅在切换时输出
        self.extra_col_name_var = tk.StringVar(value='')   # 附加列名(空=不加)
        self.extra_col_val_var = tk.StringVar(value='0')   # 附加列固定值 0/1
        self.gap_var = tk.BooleanVar(value=False)          # timing 切换插空周期
        self.label_marker_var = tk.StringVar(value='')     # 要识别的标记注释文本
        self.label_base_var = tk.StringVar(value='')       # label 名前缀
        self.input_files = []   # 实际待处理的 .wgl 文件路径列表

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}
        cell = {'padx': 4, 'pady': 5}      # grid 单元内边距 (统一)

        # ── 输入: 文件 / 目录 ────────────────────────────────────────────
        frm_top = ttk.LabelFrame(self, text='输入 (.wgl 文件或目录)')
        frm_top.pack(fill='x', **pad)
        frm_top.columnconfigure(0, weight=1)
        ttk.Entry(frm_top, textvariable=self.input_paths_var, state='readonly').grid(
            row=0, column=0, sticky='ew', padx=(8, 4), pady=8)
        ttk.Button(frm_top, text='选择文件…', command=self.on_select_files).grid(
            row=0, column=1, **cell)
        ttk.Button(frm_top, text='选择目录…', command=self.on_select_dir).grid(
            row=0, column=2, padx=(4, 8), pady=5)

        # ── 输出: 目录 + 目标格式 ───────────────────────────────────────
        frm_out = ttk.LabelFrame(self, text='输出')
        frm_out.pack(fill='x', **pad)
        frm_out.columnconfigure(1, weight=1)
        # 第 1 行: 同目录开关 + 输出目录 + 选择按钮
        ttk.Checkbutton(frm_out, text='与输入同目录', variable=self.same_dir_var,
                        command=self._toggle_out_dir).grid(
            row=0, column=0, sticky='w', padx=8, pady=5)
        self.out_dir_entry = ttk.Entry(frm_out, textvariable=self.output_dir_var)
        self.out_dir_entry.grid(row=0, column=1, sticky='ew', **cell)
        self.out_dir_btn = ttk.Button(frm_out, text='选择…', command=self.on_select_out_dir)
        self.out_dir_btn.grid(row=0, column=2, padx=(4, 8), pady=5)
        # 第 2 行: 目标测试机
        ttk.Label(frm_out, text='目标测试机:').grid(row=1, column=0, sticky='w', padx=8, pady=5)
        self.fmt_combo = ttk.Combobox(frm_out, textvariable=self.target_var,
                                      values=['Chroma .pat', 'S100 .sd'],
                                      state='readonly', width=14)
        self.fmt_combo.grid(row=1, column=1, sticky='w', **cell)
        self.fmt_combo.bind('<<ComboboxSelected>>', lambda e: self._on_target_change())
        ttk.Label(frm_out, text='(Chroma=3380P .pat;  S100=YTEC .sd)').grid(
            row=1, column=2, sticky='w', padx=(4, 8), pady=5)
        self._toggle_out_dir()  # 应用初始状态

        # ── 转换选项 (含 Chroma 专属项, 网格对齐) ───────────────────────
        frm_opt = ttk.LabelFrame(self, text='转换选项')
        frm_opt.pack(fill='x', **pad)
        frm_opt.columnconfigure(2, weight=1)
        ttk.Checkbutton(frm_opt, text='生成竖排 pin 名注释',
                        variable=self.ascii_art_var).grid(
            row=0, column=0, columnspan=3, sticky='w', padx=8, pady=5)
        ttk.Checkbutton(frm_opt, text='timing 仅切换时输出 (只保留首次切换标志)',
                        variable=self.sticky_wft_var).grid(
            row=1, column=0, columnspan=3, sticky='w', padx=8, pady=5)
        self._on_target_change()   # 应用初始灰显状态

        # ── 附加列 / 空周期 (对 .pat 和 .sd 都生效) ─────────────────────
        frm_extra = ttk.LabelFrame(self, text='附加列 / 空周期 (.pat 与 .sd 都生效)')
        frm_extra.pack(fill='x', **pad)
        ttk.Label(frm_extra, text='末尾追加列名:').grid(row=0, column=0, sticky='w', padx=8, pady=5)
        ttk.Entry(frm_extra, textvariable=self.extra_col_name_var, width=16).grid(
            row=0, column=1, sticky='w', **cell)
        ttk.Label(frm_extra, text='固定值:').grid(row=0, column=2, sticky='w', padx=(12, 4), pady=5)
        frm_rb = ttk.Frame(frm_extra)
        frm_rb.grid(row=0, column=3, sticky='w', pady=5)
        ttk.Radiobutton(frm_rb, text='0', variable=self.extra_col_val_var,
                        value='0').pack(side='left', padx=2)
        ttk.Radiobutton(frm_rb, text='1', variable=self.extra_col_val_var,
                        value='1').pack(side='left', padx=2)
        ttk.Checkbutton(frm_extra, text='timing 切换时插入全X空周期 (附加列保持固定值)',
                        variable=self.gap_var).grid(
            row=1, column=0, columnspan=4, sticky='w', padx=8, pady=5)

        # ── label 标签 (识别 WGL 注释标记 → 插入顺延 label; .pat 与 .sd 都生效) ──
        frm_lbl = ttk.LabelFrame(
            self, text='label 标签 (识别注释标记并插入顺延序号; .pat 与 .sd 都生效)')
        frm_lbl.pack(fill='x', **pad)
        frm_lbl.columnconfigure(1, weight=1)
        ttk.Label(frm_lbl, text='识别标记文本:').grid(row=0, column=0, sticky='w', padx=8, pady=5)
        ttk.Entry(frm_lbl, textvariable=self.label_marker_var).grid(
            row=0, column=1, sticky='ew', **cell)
        ttk.Label(frm_lbl, text='(WGL 注释内文本, 例 Measure Iddq All; 留空=不插 label)').grid(
            row=0, column=2, sticky='w', padx=(4, 8), pady=5)
        ttk.Label(frm_lbl, text='label 名前缀:').grid(row=1, column=0, sticky='w', padx=8, pady=5)
        ttk.Entry(frm_lbl, textvariable=self.label_base_var, width=16).grid(
            row=1, column=1, sticky='w', **cell)
        ttk.Label(frm_lbl,
            text='(例 M_Iddq → M_Iddq_1, M_Iddq_2 …;  .pat 单独成行 / .sd 前缀列)').grid(
            row=1, column=2, sticky='w', padx=(4, 8), pady=5)

        # ── 按钮区 + 进度条 ─────────────────────────────────────────────
        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill='x', **pad)
        self.btn_run = ttk.Button(frm_btn, text='开始转换', command=self.on_run)
        self.btn_run.pack(side='left', padx=8, pady=4)
        ttk.Button(frm_btn, text='清空日志', command=self.on_clear_log).pack(
            side='left', padx=4, pady=4)

        self.progress = ttk.Progressbar(frm_btn, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=8, pady=4)

        # 日志框
        frm_log = ttk.LabelFrame(self, text='日志')
        frm_log.pack(fill='both', expand=True, **pad)
        self.log_text = tk.Text(frm_log, wrap='none', height=18)
        self.log_text.pack(side='left', fill='both', expand=True, padx=(8, 0), pady=8)
        log_scroll = ttk.Scrollbar(frm_log, orient='vertical',
                                   command=self.log_text.yview)
        log_scroll.pack(side='right', fill='y', padx=(0, 8), pady=8)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        # 状态栏
        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(self, textvariable=self.status_var,
                  anchor='w', relief='sunken').pack(fill='x', side='bottom')

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _target_key(self):
        return 'sd' if self.target_var.get().startswith('S100') else 'chroma'

    def _on_target_change(self):
        """切换输出格式回调。当前 Chroma / .sd 已无专属可灰显选项, 保留以兼容事件绑定。"""
        return

    def _toggle_out_dir(self):
        if self.same_dir_var.get():
            self.out_dir_entry.configure(state='disabled')
            self.out_dir_btn.configure(state='disabled')
        else:
            self.out_dir_entry.configure(state='normal')
            self.out_dir_btn.configure(state='normal')

    def on_select_files(self):
        paths = filedialog.askopenfilenames(
            title='选择 WGL 文件 (可多选)',
            filetypes=[('WGL files', '*.wgl *.WGL'), ('所有文件', '*.*')],
        )
        if not paths:
            return
        self.input_files = list(paths)
        self._refresh_input_display()

    def on_select_dir(self):
        d = filedialog.askdirectory(title='选择包含 .wgl 文件的目录')
        if not d:
            return
        wgls = []
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith('.wgl'):
                    wgls.append(os.path.join(root, f))
        wgls.sort()
        if not wgls:
            messagebox.showwarning('提示', '所选目录中未找到 .wgl 文件')
            return
        self.input_files = wgls
        self._refresh_input_display()

    def on_select_out_dir(self):
        d = filedialog.askdirectory(title='选择输出目录')
        if d:
            self.output_dir_var.set(d)

    def _refresh_input_display(self):
        n = len(self.input_files)
        if n == 1:
            self.input_paths_var.set(self.input_files[0])
        else:
            first = os.path.basename(self.input_files[0]) if self.input_files else ''
            self.input_paths_var.set(f'已选 {n} 个文件 (例: {first})')
        self._log(f'已选 {n} 个 WGL 文件')

    def on_clear_log(self):
        self.log_text.delete('1.0', 'end')

    def on_run(self):
        if not self.input_files:
            messagebox.showwarning('提示', '请先选择 WGL 文件或目录')
            return
        if not self.same_dir_var.get():
            od = self.output_dir_var.get().strip()
            if not od:
                messagebox.showwarning('提示', '请填写输出目录或勾选"与输入同目录"')
                return

        # 禁用按钮，开线程
        self.btn_run.configure(state='disabled')
        self.progress.configure(maximum=len(self.input_files), value=0)
        t = threading.Thread(target=self._run_batch, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # 批量转换 (后台线程)
    # ------------------------------------------------------------------
    def _run_batch(self):
        files = list(self.input_files)
        same_dir = self.same_dir_var.get()
        out_dir = self.output_dir_var.get().strip()
        ascii_art = self.ascii_art_var.get()
        sticky_wft = self.sticky_wft_var.get()
        target = self._target_key()
        out_ext = '.sd' if target == 'sd' else '.pat'
        extra_name = self.extra_col_name_var.get().strip() or None
        extra_val = self.extra_col_val_var.get()
        gap = self.gap_var.get()
        label_marker = self.label_marker_var.get().strip() or None
        label_base = self.label_base_var.get().strip() or None

        ok_count = 0
        err_count = 0
        self._log('='*60)
        self._log(f'批量转换开始: {len(files)} 个文件 → {out_ext}')

        for i, wgl in enumerate(files, 1):
            self._set_status(f'[{i}/{len(files)}] {os.path.basename(wgl)} ...')
            try:
                base = os.path.basename(wgl)
                for ext in ('.wgl', '.WGL', '.Wgl'):
                    if base.endswith(ext):
                        base = base[:-len(ext)]
                        break
                if same_dir:
                    out_path = os.path.join(os.path.dirname(os.path.abspath(wgl)),
                                            base + out_ext)
                else:
                    out_path = os.path.join(out_dir, base + out_ext)

                convert_one(
                    wgl_path=wgl,
                    out_path=out_path,
                    emit_ascii_art=ascii_art,
                    sticky_wft=sticky_wft,
                    target=target,
                    extra_col_name=extra_name,
                    extra_col_value=extra_val,
                    insert_gap_on_wft_change=gap,
                    label_marker=label_marker,
                    label_base=label_base,
                    progress=self._log,
                )
                ok_count += 1
            except Exception as ex:
                err_count += 1
                self._log(f'  ❌ 错误: {ex}')
                self._log(traceback.format_exc())
            self._set_progress(i)

        self._log('-' * 60)
        self._log(f'完成: 成功 {ok_count}, 失败 {err_count}')
        self._set_status(f'完成: 成功 {ok_count}, 失败 {err_count}')
        self.after(0, lambda: self.btn_run.configure(state='normal'))
        if err_count == 0:
            self.after(0, lambda: messagebox.showinfo('完成',
                f'已成功转换 {ok_count} 个文件'))
        else:
            self.after(0, lambda: messagebox.showwarning('完成 (含错误)',
                f'成功 {ok_count}, 失败 {err_count}, 详见日志'))

    # ------------------------------------------------------------------
    # 线程安全的 UI 更新
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        def _do():
            self.log_text.insert('end', msg + '\n')
            self.log_text.see('end')
        self.after(0, _do)

    def _set_status(self, msg: str):
        self.after(0, lambda: self.status_var.set(msg))

    def _set_progress(self, value: int):
        self.after(0, lambda: self.progress.configure(value=value))


def main():
    global convert_one
    # 1) 加载转换模块
    try:
        convert_one = _load_convert_one()
    except Exception:
        _report_fatal(
            '启动失败: 无法导入转换模块 (converter/emitter/parser/ir)',
            '请确认 gui.py 与 converter.py、emitter.py、parser.py、ir.py、'
            '__init__.py 在同一个文件夹内 (不要单独把 gui.py 拷出来)。\n\n'
            + traceback.format_exc())
        sys.exit(1)
    # 2) 初始化并运行界面
    try:
        app = WglToChromaGUI()
        app.mainloop()
    except Exception:
        _report_fatal('启动失败: 界面初始化出错', traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
