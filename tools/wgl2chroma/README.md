# WGL → Chroma3380P Pattern 转换工具

把 Mentor Tessent 导出的 WGL Pattern 文件 (.wgl) 自动转换为
Chroma 3380P ATE 的 Pattern 文件 (.pat),支持单文件和批量。

---

## 1. 环境要求

- Python 3.8+ (Windows / Linux / macOS 均可)
- Tkinter (Python 标准库,Windows 自带;Ubuntu 上若缺需 `sudo apt install python3-tk`)
- 无任何第三方依赖

---

## 2. 启动 GUI

把 `wgl2chroma/` 目录放到任意位置,然后在该目录的**父目录**执行:

```bash
python -m wgl2chroma
```

或直接运行 GUI 模块:

```bash
python wgl2chroma/gui.py
```

**Windows 排错提示**:若双击 `gui.py` 出现"闪退"(窗口一闪而过),请改双击包内的 **`run_gui.bat`** —— 它运行后不会自动关闭,任何报错都会留在窗口里;同时启动失败时会在 `gui.py` 同目录生成 **`startup_error.log`**。最常见原因:① 当前 Python 缺少 tkinter (Tk) 支持(重装官方 Python 并勾选 tcl/tk);② 只把 `gui.py` 单独拷出来运行(必须与 `converter.py`/`emitter.py`/`parser.py`/`ir.py`/`__init__.py` 在同一文件夹)。

---

## 3. GUI 操作

1. **输入区**:
   - 点击 **"选择文件…"** 一次选多个 .wgl 文件
   - 或点击 **"选择目录…"** 递归扫描目录下所有 .wgl 文件
2. **输出区**:
   - 默认勾选 **"与输入同目录"**,输出 .pat 与 .wgl 并列
   - 取消勾选后可指定独立的输出目录
3. **选项**:
   - **"生成竖排 pin 名注释"**: 在 SPM_PATTERN 块内加上 ASCII 艺术注释 (可读性,但 pin 名很长时不太美观,默认关闭)
   - **"timing 仅切换时输出 (只保留首次切换标志)"**: 默认勾选。勾选时 timing 字段只在 WFT 发生切换的那一拍输出,后续拍沿用("sticky timing"),文件更小、加载更快;取消勾选则每拍都带 timing (旧行为,便于与旧 .pat 逐位回归对照)
4. 点击 **"开始转换"**,日志区会显示每个文件的处理状态

> ### ⚠ 重要:"timing 切换插入空周期" (gap) 怎么选
>
> 在 WFT (timing) 真正切换的那一拍前,YTEC 参考流程会插入一行**全 X 空周期**并把
> 新 timing 的 `TIMING_SET` 标在这空拍上。本工具该选项 (附加列 / 空周期设置区)
> **默认关闭**。用 PT104 真实样例对照 YTEC 产出的参考 `.sd` 实测,结论是
> **不同 pattern 类型要求不同**:
>
> | pattern 类型 (WGL 头 `test_set_type`) | 是否插空周期 | 说明 |
> |---|---|---|
> | **scan 类** (如 `EDT_SCAN_TEST`,dcscan) | **要勾选(开)** | 否则切换点少一拍,和 YTEC 参考对不上 |
> | **IJTAG / MemoryBIST** (如 `IJTAG_TEST`,mbist) | **不勾选(关)** | 勾了会多出空周期,反而对不上 |
>
> 实测依据:`dc_scan_scan_test_1` 开 gap 后与 YTEC 参考 `.sd` **逐字节一致**;
> `MemoryBist_P1` 关 gap 才与参考一致。**转 scan pattern 记得勾上,转 IJTAG/BIST
> 保持不勾。** 命令行对应 `insert_gap_on_wft_change=True/False`。该规则目前基于这
> 两类参考;若有其它类型 YTEC 参考,建议先用 `tools/regression.py` 比对确认。

> ### label 标签 (识别注释标记并插入顺延序号)
>
> 在"label 标签"设置区填两栏: **识别标记文本** = WGL 注释里的文本(如 `Measure Iddq All`),
> **label 名前缀** = 生成的 label 名(如 `M_Iddq`)。工具会找到每处 `{ ...标记文本... }` 注释,
> 给紧随其后的向量打上顺延 label(`M_Iddq_1`, `M_Iddq_2` …):
> - `.pat`: label 单独成一行写在该向量上方 → `M_Iddq_1:`
> - `.sd`: 所有行(普通行/START:/END:/label)数据均右对齐到第 10 列(YTEC 原为 30 列, 本工具按需求改为 10 列, 数据内容不变)
>
> 两栏留空 = 不插 label(输出与旧版一致)。被打 label 的向量不会被 RPT 合并。

---

## 4. 命令行 (无 GUI) 用法

也可以脚本批量调用:

```python
from wgl2chroma.converter import convert_one

# 单个文件
convert_one(
    wgl_path='input.wgl',
    out_path='output.pat',          # 可省,默认与 wgl 同名
    # 注: SET_DEC_FILE 已固定写死为 "pin.dec"; dec_filename 参数保留但被忽略
    emit_ascii_art=False,           # 是否输出竖排 pin 名注释
    sticky_wft=True,                # timing 仅在切换时输出;False=每拍都带(旧行为)
    target='chroma',                # 'chroma'→Chroma .pat (默认); 'sd'→S100 (YTEC) .sd
    label_marker=None,              # 识别此注释标记(如 'Measure Iddq All'), 给其后向量打 label
    label_base=None,                # label 名前缀(如 'M_Iddq' → M_Iddq_1, M_Iddq_2 …)
    progress=print,                 # 进度回调,可省
)
```

---

## 5. 转换规则要点 (技术摘要)

| WGL 元素 | 处理方式 |
|---|---|
| `signal ... end` | 展开 bus,生成 .pat HEADER pin 列表 |
| `scancell ... end` | 完全忽略 (内部 cell 定义) |
| `scanchain name[...]` | 记录链入口/出口 pin (用于 scan shift 注入) |
| `timeplate "_NAME_" ... end` | 提取名称,去首尾下划线 → .pat WFT 名称 |
| `scanstate ... end` | 建立 chain I/O 字符串变量表 |
| `pattern NAME (pin_list)` | pin_list 决定 vector 字符位顺序 |
| `vector(+, "_WFT_") := [chars];` | 一个普通 cycle |
| `scan(+, "_WFT_") := [tpl], input[c:Ix], output[c:Ox]...;` | **N 个 shift cycle** (N = chain 长度),模板基底 + 每拍替换 ScanIn pin / ScanOut pin |

**关键语义**:
- WGL 的 `-` 字符:首拍 → `X`;后续拍 → 沿用前值
- WGL 双侧字符 (`:I` 和 `:O`) 折叠为 .pat 单字符: drive (`0/1`) 优先于 expect (`L/H`),否则 `X`
- scanstate 中的 `0`/`1` 在 ScanOut (O 侧) 注入时映射为 `L`/`H`
- scan 段结束后,下一个 `-` 继承的是 scan 模板拍的状态,**不是**最后一拍 shift 的状态
- WFT 命名:`_default_WFT_` → `default_WFT` (去首尾下划线,固定约定)
- **timing 输出 (sticky timing)**:默认仅在 WFT 切换时输出 timing 字段 (` * <data> * <wft>;`),后续相同 timing 的拍不重复 —— 即"只保留首次切换标志"。未切换那一拍如何写由 `wft_continuation` 决定:
  - **方案A (默认, `wft_continuation=None`/留空)**:直接省略 timing 字段 → ` * <data>;`
  - **方案B (`wft_continuation=' *'` 等记号)**:原样插入该串替代 ` * <wft>` → ` * <data> *;`(记号含前导空格与否、具体形式以机台 Pattern Compiler spec 为准)
  - 需每拍都带 timing 时设 `sticky_wft=False`(GUI 取消勾选)
- **RPT 压缩**:连续且 (波形 + WFT) 完全相同的拍合并为 ` * <data> [* <wft>], RPT N;`。RPT **不跨 timing 合并** (波形相同但 timing 不同的拍会拆开)。**RPT 计数上限 65535**,超出自动拆成多行 (`.pat` 与 `.sd` 一致;如 90003 → `RPT 65535` + `RPT 24468`)
- **Chroma `.pat` 行格式**:` *<pattern_data>*[ts_name, micro_ins];`(`*` 紧贴数据)。切换行 ` *data* ts_name, RPT n;`;延续行 ` *data*RPT n;`(无逗号), 单拍 ` *data*;`, 末拍 ` *data*STOP;`
- **SET_DEC_FILE**:`.pat` 头固定输出 `SET_DEC_FILE "pin.dec"`(写死, 与 pattern 名无关)

---

## 6. 验证结果

用提供的 `ac_scan_1_1.wgl` 样例验证: **前 2759 个 cycle 与原始 .pat 文件 100% 逐位匹配** (这是原 .pat 截断到 Pattern 4 后的全部内容)。WGL 完整内容还包括 Pattern 5 (20 个额外 cycle),工具会正确输出。

---

## 7. 项目结构

```
wgl2chroma/
├── __init__.py        # 包元信息
├── __main__.py        # 支持 python -m wgl2chroma 启动
├── ir.py              # 内部数据结构 (Signal/ScanChain/Timeplate/Pattern...)
├── parser.py          # WGL 解析器 (Mentor Tessent 方言)
├── emitter.py         # .pat 生成器 (Chroma)
├── emitter_sd.py      # .sd 生成器 (S100 / YTEC)
├── converter.py       # 单文件转换入口
└── gui.py             # Tkinter GUI (批量)
```

---

## 8. 已知局限 / 后续可扩展

- 仅在 Mentor Tessent 2019.4 风格的 WGL 上验证过;其他厂商 (Synopsys / Cadence) 的 WGL 方言若出现差异,可能需要在 `parser.py` 中补充。
- 当前 WGL 只观察到一种 WFT 在使用 (`_default_WFT_`);若同一 pattern 切换多个 WFT,工具已支持 (每行输出对应的 WFT),但需要真实样例验证。
- `.dec` 文件需要用户自行准备,工具只在 .pat 中生成 `SET_DEC_FILE "./xxx.dec"` 引用行。
- 默认开启 sticky timing (timing 仅切换时输出) 与 RPT 压缩;若机台 Pattern Compiler 不接受省略 timing 的行或 RPT 语法,需调整 (见下方更新日志的验证提示)。
- 输出 .pat 不含 "Pattern N TesterCycle K" 段边界注释 (这是原 tbridge 工具内部统计信息,对 ATE 加载无影响)。

如需补充功能或遇到不识别的 WGL 方言,请提供新样例继续完善。

---

## 9. 更新日志

完整版本演进 (V1→V6 / 0.1.0→0.5.0) 见同目录的 **`CHANGELOG.md`**。最新版 0.5.0 修复了真实 Tessent WGL 方言 (WFT 名引号可选、`repeat N` 前缀、STOP 行约定),`ac_scan_0.wgl` 周期数据与 tbridge 参考 `.pat` 100% 逐位一致。
