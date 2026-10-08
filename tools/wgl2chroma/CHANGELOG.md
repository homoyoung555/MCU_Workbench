# 变更日志 (CHANGELOG)

WGL → Chroma3380P Pattern 转换工具。
版本号见 `__init__.py` 的 `__version__`；下表附各次交付的发布包名以便追溯。

| 包名 | 版本 | 主题 |
|---|---|---|
| wgl2chroma (V1) | 0.1.0 | 原始基线 |
| wgl2chroma_260520V1 | 0.1.0 | 用户验证可正常打开的基线 (内容同 0.1.0) |
| wgl2chroma_260531V2 | 0.2.0 | sticky timing + 首轮提速 |
| wgl2chroma_260531V3 | 0.2.0 | GUI 启动防护 / run_gui.bat |
| wgl2chroma_260531V4 | 0.3.0 | timing 延续记号参数化 (方案B) |
| wgl2chroma_260531V5 | 0.4.0 | parser 提速 ~3× + 降内存 |
| wgl2chroma_260531V6 | 0.5.0 | 修复真实 Tessent WGL 方言 |
| wgl2chroma_260619V14 | 0.7.5 | 工程地基(诊断/回归/覆盖矩阵) + 真实样例金标准 + gap 文档 |
| wgl2chroma_260619V15 | 0.8.5 | .pat RPT65535+label+行格式(*紧贴数据); .sd 前缀第10列; SET_DEC_FILE 固定 pin.dec |

---

## 0.8.5 — Chroma .pat 去掉 `*` 与数据间空格 (V15)

调整 `.pat` 行内空格, 让 `*` 紧贴 pattern_data:
- 前导星号: ` * <data>` → ` *<data>`(`*` 后不再有空格)。
- 切换行第二星号: ` * <ts_name>` → `* <ts_name>`(`*` 前不再有空格, 后仍保留一个空格)。
- 即整行: ` *<pattern_data>*[ <ts_name>, ] <micro_ins>;`
  - 切换行 ` *<data>* tp_setup, RPT 21;`
  - 延续行 ` *<data>*RPT 65535;` / ` *<data>*;` / ` *<data>*STOP;`
- 仅改 `emitter.py`(flush / STOP / `_chroma_tail` 的空格)。`.sd` 不变。
- 回归 7/7 全绿(.pat golden 已重新冻结)。
## 0.8.4 — SET_DEC_FILE 固定为 "pin.dec" (V15)

Chroma `.pat` 头部 `SET_DEC_FILE` 行固定写死为 `SET_DEC_FILE "pin.dec"`,
不再随 pattern 名 / `dec_filename` 参数变化(此前为 `"./<pattern名>.dec"`)。
- 仅改 `emitter.py`(新增常量 `_DEC_FILE = 'pin.dec'`)。`dec_filename` 参数在
  `convert_one` / `PatEmitter` 中保留以兼容旧调用, 但**不再影响输出**。
- **移除** GUI "SET_DEC_FILE 后缀" 输入(已无意义); `_on_target_change` 改为空操作
  (Chroma / .sd 已无专属可灰显选项)。
- 仅影响 `.pat`; `.sd` 不变。回归 7/7 全绿(.pat golden 已重新冻结)。
- 注: `SET_DEC_FILE` 与文件名之间为单个空格(沿用原格式)。

## 0.8.3 — Chroma .pat 行格式: *pattern_data*[ts_name, micro_ins]; (V15)

按机台正确格式调整 Chroma `.pat` 数据行: 第二个 `*` 作为 pattern_data 与
`[ts_name, micro_ins]` 字段的固定分隔符。
- 切换行(timing 切换 / 非 sticky): ` * <data> * <ts_name>, <micro_ins>;`
  (例 ` * XXXX...XXX * tp_setup, RPT 65535;`) —— 与旧版相同。
- 延续行(sticky 未切换): ` * <data>*<micro_ins>;`(`*` 直接接 micro, 无逗号无空格):
  - RPT 行 ` * <data>*RPT 24489;`(旧版 ` * <data>, RPT 24489;`)
  - 单拍行 ` * <data>*; // r..`(旧版 ` * <data>; // r..`)
  - STOP 行 ` * <data>*STOP;`(旧版 ` * <data>, STOP;`)
- 仅影响 `.pat`; `.sd` 不变。仅改 `emitter.py`(新增 `_chroma_tail`)。
- **移除** "timing 延续记号"(wft_continuation / 方案B)的 GUI 输入与用法: 新格式下
  延续分隔符固定为 `*`, 该参数已无意义(`convert_one` / `PatEmitter` 仍保留参数名
  以兼容旧调用, 但不再影响输出)。
- 用真实 `dc_scan_chain_test_1.wgl` 验证, _st:: 前 3 行与目标格式逐字符一致;
  回归 7/7 全绿。

## 0.8.2 — .sd 全行前缀宽度 30 → 10 (V15)

把 `.sd` 所有行(普通行 / `START:` / `END:` / label)的前缀对齐宽度由 30 列统一改为
**10 列**(数据列整体左移、缩进更少, 各类行数据列对齐一致)。仅改 `emitter_sd.py`
(`_PREFIX_W = 10`)。
- **注意**: YTEC 工具原格式为 30 列缩进; 本改动后 `.sd` 缩进**有意与 YTEC 不同**
  (数据内容 / RPT / TIMING_SET / START / END 关键字均不变, 只是行首空格变少)。
  回归里 mbist / dcscan 的 YTEC 比对相应改为 **数据级(content, 忽略行首缩进)**,
  仍逐行校验数据与 YTEC 完全一致。
- 上机前请确认 S100 / YTEC Pattern Compiler 接受 10 列缩进。
- 验证: 7/7 回归全绿(含两个 YTEC 数据级比对)。

## 0.8.1 — .sd label 前缀宽度 30 → 10 (V15)

仅调整 `.sd` 里 label 行的对齐宽度: label 由"右对齐到第 30 列"改为"右对齐到第 10 列"
(缩进更少, 不再与 START:/END: 同列)。**普通行 / START / END 仍右对齐到第 30 列不变**,
故 mbist / dcscan 的 YTEC 逐字节金标准不受影响。仅改 `emitter_sd.py`
(新增常量 `_LABEL_PREFIX_W = 10`; `.pat` 的 label 仍是单独成行, 不涉及列对齐)。
- 验证: 7/7 回归全绿; 无 label 的 `.sd` 输出逐字节不变。

## 0.8.0 — .pat RPT 上限 + label 标签 (V15)

两项功能改动 (首次真正改动转换逻辑, 故升 minor)。已有行为(无 label、RPT≤65535)
经回归保持逐位一致: sample_min .pat/.sd、mbist .sd、dcscan .sd 全部不变。

- **feature1: Chroma `.pat` 的 RPT 上限 = 65535**。此前 `.pat` 的 RPT 无上限
  (如 `repeat 90000` → `RPT 90003`), 现与 `.sd` 后端一致: 超 65535 自动拆多行
  (90003 → `RPT 65535` + `RPT 24468`); timing 标记仅拆分后首行带, 后续行用延续记号。
  ≤65535 时与旧版逐位一致。仅改 `emitter.py`。
  - 验证: mbist 真实样例 `.pat` 拆分后总 cycle(181678)与其 `.sd` 完全一致。
- **feature2: label 标签识别与插入** (`.pat` 与 `.sd` 都生效, 默认关闭)。
  - 识别 WGL 里用户指定的注释标记(如 `{ Measure Iddq All }`), 给紧随其后的向量打
    顺延 label(前缀 + `_1/_2/…`, 如 `M_Iddq_1`, `M_Iddq_2`)。
  - `.pat`: label 单独成行写在该向量数据行上方(`M_Iddq_1:`)。
  - `.sd`: label 占前缀列、右对齐到第 30 列(与 START:/END: 同列), 数据列保持对齐。
  - 被打 label 的向量强制不参与 RPT 合并, 保证 label 精确对应该拍。
  - 接口: `convert_one(..., label_marker='Measure Iddq All', label_base='M_Iddq')`;
    GUI 新增"label 标签"设置区两个输入框(识别标记文本 / label 名前缀)。
  - 仅改 `parser.py`(标记注释在剥注释前替换成哨兵, 不影响其它注释) /
    `ir.py`(WGLVector 加 `label`) / `converter.py` / 两个 emitter / `gui.py`。
  - 验证: 真实 `iddq_stuck_1.wgl`(300 处 Measure Iddq All)→ `.pat`/`.sd` 各生成
    300 个顺延 label, 位置与标记一一对应。
- 回归新增 `sample_feat` 用例锁定两项功能(label + RPT 拆分), 现 7/7 全绿
  (含 mbist/dcscan 两个 YTEC 逐字节金标准, 引擎对它们输出不变)。

## 0.7.5 — 工程地基 + 真实样例回归基线 (V14)

启动"逐步覆盖 WGL_spec / 真实样例验证"工程。**转换逻辑零变更**:`parser.py` /
`emitter.py` / `emitter_sd.py` / `converter.py` / `ir.py` / `gui.py` /
`__main__.py` 与 0.7.3 **逐位一致**(已 diff 核验),输出 `.pat` / `.sd` 不变。
本版只新增"只读"工具、回归资产与文档,不改任何现有行为。

- **新增 `wgl2chroma/diagnostics.py`(未识别构造扫描器)**:在不参与转换路径的前提下
  扫描 WGL,报告当前 parser **无法消费、会被静默丢弃** 的构造,杜绝"输出看似正常、
  实则少周期/数据错位却无提示"。检测:多 pattern 块、`vector` 地址漏匹配(只认
  `vector(+, 名字)`)、`call`/`subroutine`/`skip`、命名 `loop`、`feedback`、
  `format`/`group`/`include` 等。`python -m wgl2chroma.diagnostics <file.wgl>`。
- **新增 `tools/regression.py`(逐位回归框架)+ `tests/golden/`**:把"输出与参考逐位
  一致"从手工 diff 固化成一键门禁。支持 per-case 转换参数、exact(逐字节金标准)/
  normalized(抹时间戳)两种比对、包外大文件可选用例(设 `WGL_SAMPLES_DIR`)。
  **定为后续每次升版的强制门禁。**
- **真实样例纳入金标准**:把 Tessent 2022.1 真实产出的 `MemoryBist_P1.wgl` 及其
  YTEC 参考 `.sd` 纳入 `tests/golden`,逐字节比对;自制 `sample_min` 覆盖
  signal/scancell/scanchain/timeplate/scanstate/vector(含 ditto)/repeat/scan/loop。
- **实测结论(PT104 真实样例)**:`MemoryBist_P1`(IJTAG)与 `dc_scan_scan_test_1`
  (scan)转出的 `.sd` 均与 YTEC 参考 **逐字节完全一致** —— 核心引擎在真实 EDA 输出
  上正确。`diagnostics` 扫过 acscan/dcscan/iddq/mbist 全部 5 类代表文件:**零漏匹配、
  无不支持构造**,即实际 Tessent WGL 不含 spec 的 vector 三元组/call/多 pattern 等。
- **发现并文档化 gap 规则**:WFT 切换插空周期(`insert_gap_on_wft_change`)的正确取值
  **因 pattern 类型而异** —— scan 类(EDT_SCAN_TEST)需 **开**、IJTAG/BIST 需 **关**,
  否则与 YTEC 参考对不上。已写入 README「⚠ 重要」一节;按约定保持手动开关、未自动化。
- **新增 `COVERAGE_MATRIX.md`**:对照 spec BNF 标注 已支持/部分/不支持/暂不做 + 优先级,
  作为后续升版路线图。结合真实样例诊断,P0 项(三元组 vector/多 pattern/call)对当前
  实际文件非必需,优先级随事实下调。
- 回归门禁:`python tools/regression.py` 全绿(5/5,含两个 YTEC 逐字节金标准)。

## 0.7.3 — GUI 界面排布优化 (V13)

纯界面改动，**转换逻辑零变更**（parser / emitter / emitter_sd / converter / ir 均未动），输出 `.pat` / `.sd` 与 0.7.2 逐位一致。

- **改用 grid 网格布局**：各设置区内的 label / 输入框 / 说明文字按列对齐，替代原先全部 `side='left'` 顺排导致的参差不齐。
- **合并精简分区**：原 6 个堆叠 LabelFrame → 4 个。
  - “输出目录”与“输出格式”合并为 **输出**（同目录开关 + 输出路径一行，目标测试机一行）。
  - “选项”与独立的“timing 延续记号”整块合并为 **转换选项**：`SET_DEC_FILE 后缀` 与 `timing 延续记号` 两行左对齐成网格，Chroma 专属项在 `.sd` 下灰显逻辑不变。
- **窗口加大** 820×560 → 820×660（minsize 720×580），设置区更紧凑，**日志区获得更多纵向空间**。
- 所有控件变量 / 事件回调 / 批量转换线程逻辑（`_run_batch` / `convert_one` 调用）完全未变，仅重写 `_build_ui` 与 `_on_target_change` 的灰显控件清单。

## 0.7.2 — timing 切换拍不叠加 RPT (V12)

- `.pat` 与 `.sd`：带 TIMING_SET / WFT 标记的那一拍 (即 sticky 模式下真正发生 timing 切换的拍) 不参与 RPT 压缩 —— 单独成 1 行 (不带 RPT)，该向量剩余重复拍另起一行压缩。
  - 例：timing 切到 G1_2 后连续 5 个相同向量 → `<v>;TIMING_SET G1_2;` (1 拍) + `<v>;RPT 4;`。
- 仅 sticky 模式生效：非 sticky (.pat 每拍都带 timing) 不拆分，否则 RPT 失去意义；`.sd` 始终 sticky，故按切换拆分。
- 与既有功能正交：单 WFT 文件不受影响 (sticky=False 仍与 tbridge bit-exact；sticky=True 正常 RPT)；与 65535 拆分、END 无 RPT、附加列、插空周期均兼容。
- 仅改 `emitter.py` / `emitter_sd.py`。

## 0.7.1 — 支持 loop N ... end 块展开 (V11)

- 修复 WGL `loop N ... end` 块未展开的问题：该块把内部多条 vector 整体重复 N 次，此前被漏处理。现在 parser 在解析 pattern body 前先将 `loop N ... end` 就地展开成 N 份块内文本，再正常解析。
- 单层、不嵌套；loop 块仅在 pattern 段内；展开后这些拍照常走 RPT 压缩 (.pat/.sd 一致)；与 `repeat N` 可叠加 (loop M × repeat K = M·K)。
- 仅改 `parser.py` (新增 `_expand_loops`)；emitter / IR / 两个后端不变。
- 验证：loop 多条 / loop 在结尾(双 end) / loop 内含 repeat 均正确；展开后 .pat/.sd RPT 压缩正常；无 loop 的 `ac_scan_0` 仍与 tbridge bit-exact。

## 0.7.0 — 附加列 + timing 切换空周期 (V10)

对 `.pat` 与 `.sd` 两个后端同时新增 (默认关闭, 向后兼容):

- **末尾附加 1 列**：列名由 GUI 输入框填写，固定值 0/1 (drive)，拼在每行向量字符串末尾；pin 头末尾同步加该列名。
- **timing 切换插入空周期**：WFT 真正切换 (A→B, A≠B) 时，在切换点前插入一行全 X 空周期 (原 pin 全 X、附加列保持固定值)，该空拍标“切换后”的新 timing；最开头“无→A”不插，之后每次切换都插；scan shift 中间也照插。
- 空拍 chars 独特，自然不与邻拍 RPT 合并。`.sd` 的 RPT/65535 拆分/END 无 RPT 逻辑不受影响。
- 接口：`convert_one(..., extra_col_name=, extra_col_value='0'|'1', insert_gap_on_wft_change=)`；GUI 新增“附加列 / 空周期”设置区。
- 验证：关闭新功能时 `.pat` 仍与 tbridge bit-exact、`.sd` 仍与 `.pat` 一致 (零影响)；开启后 .pat/.sd 的附加列、空周期、TIMING_SET 归属、首次切换豁免均符合预期。parser/IR 未改。

## 0.6.2 — .sd 注释格式 + END 行调整 (V9)

- `.sd` 行尾注释改为对齐 Chroma .pat 风格：`//r<数据行号> <起始cycle>` (行号、cycle 均 0 起)，替代原 `// cycle n`。
- **END: 行不再带 RPT**。若最后一组向量重复多次，自动拆成「前 count-1 拍 (可带 RPT) + 最后 1 拍作 END: (无 RPT)」；与 65535 拆分叠加时也正确 (如末组 70000 → `RPT 65535` + `RPT 4464` + `END:` 单拍)。
- 验证：`ac_scan_0.wgl` 展开后仍与 tbridge `.pat` 逐位一致；末组 count>1、跨 65535、单拍等边界均通过。仅改 `emitter_sd.py`。

## 0.6.1 — .sd 增加 RPT 压缩 (V8)

`.sd` 后端现在做 RPT 压缩 (此前为逐拍展开)。

- 连续且 (chars + TIMING_SET) 相同的拍合并为 `<chars>;[TIMING_SET <wft>;]RPT <n>;`；`n==1` 时不写 RPT。
- **RPT 上限 65535**，超出自动拆成多行 (如 90000 → `RPT 65535` + `RPT 24465`)，拆分块共享同一 TIMING_SET (仅首块输出)。
- TIMING_SET 切换会打断 RPT (chars 相同但 timing 不同的拍不合并)；TIMING_SET 写在 RPT 之前。
- START: / END: 行可带 RPT。scan 段与功能段一视同仁压缩。
- 验证：`ac_scan_0.wgl` 转出的 `.sd` 展开 RPT 后与 tbridge 参考 `.pat` 逐位一致 (4390 拍)；RPT>65535 拆分、timing 打断、START 带 RPT 均通过单测。仅改 `emitter_sd.py`。

## 0.6.0 — 新增 S100 (.sd) 输出后端 (V7)

WGL 既可转 Chroma `.pat`，也可转 S100 (YTEC) `.sd`。源头都是 WGL，故 parser + IR + 折叠/scan/repeat 逻辑 100% 复用，仅新增输出后端。

- 新增 `emitter_sd.py` (`SdEmitter`，流式)：`HEAD[PIN_NAME]: ... END_HEAD;` pin 头 + `@@PATTERN_DEFINE ... @@END_PATTERN_DEFINE` 数据段；每拍一行，首拍 `START:`、末拍 `END:`，数据字符统一对齐到固定列 (行首 `\t` + 宽 30 前缀)；CRLF 行尾。
- timing 为 sticky：`TIMING_SET <wft>` 仅在 WFT 切换时输出 (首拍必带)，名字与 WGL timeplate 一一对应。不做 RPT，每拍真实展开。
- 折叠/电平规则与 `.pat` 完全一致 (drive 0/1 优先、expect L/H、scan 输出 0/1→L/H)。
- `convert_one(..., target='chroma'|'sd')`，默认 `chroma` (现有调用不受影响)；GUI 增加“输出格式”下拉 (Chroma .pat / S100 .sd)，`.sd` 下灰显 Chroma 专属项 (SET_DEC_FILE 后缀 / timing 延续记号)。
- 验证：用 `ac_scan_0.wgl` 生成的 `.sd` 数据流与已对齐 tbridge 的 `.pat` **逐位完全一致** (4390 拍)；`emitter.py`/`parser.py`/`ir.py` 未改，Chroma 路径仍 bit-exact。
- 注：`.sd` 首行 YTEC 备注仅作注释 (不被 S100 校验)；行尾注释简化为 `// cycle <n>`。

## 0.5.0 — 真实方言修复 (V6)

用真实样例 `ac_scan_0.wgl` 实测，转换后周期数据与 tbridge 参考 `.pat` **100% 逐位一致**。修复三个一直存在的方言问题 (非某次提速引入)：

- **WFT / timeplate 名引号可选**。此前写死名字必须带引号 `"..."`；真实文件常写成 `vector(+, test_setup_WFT)` / `timeplate test_setup_WFT` (无引号)，导致 vector 一条都匹配不上、`vectors=0`、输出近乎空。
- **支持 `repeat N vector(...)` 重复前缀**。此前忽略 `repeat`，RPT 次数全错；现正确展开，`repeat N` 高效计入 RPT (O(1)，`repeat 4000` 也不展开成 4000 个对象)。
- **STOP 行约定对齐 tbridge**。最后一拍直接作为 `_sp:: ... STOP;`，不再额外重复一行 (旧逻辑会把末拍既放进 `_st::` 又复制一份当 STOP)。

已知差异 (无害)：输出行尾 `//` 注释格式与 tbridge 略不同 (本工具 `// r<行> <cycle>`，tbridge 另带时间列与 1-based 行号)，不影响 ATE 加载。

## 0.4.0 — parser 提速 ~3× + 降内存 (V5)

在 ~43MB / 25 万拍含 scan 的样例上：用时 7.5s → 2.5s，峰值对象内存 288MB → 191MB；输出除运行时间戳外逐位一致 (vector 与 scan 两条路径均回归)。

- 每 vector 去空格 `re.sub(r'\s+','')` → `str.translate` (约 9× 快)。
- signal / scanchain / timeplate / scanstate 段只在 **pattern 之前的头部切片**上解析，不再对整个百万拍 pattern 体反复全文正则扫描。
- pattern 体 `split(';') + 逐条 search` → **单次 `finditer`** 一遍扫完，不再构建百万条语句字符串。
- `WGLVector` 改 `__slots__`，非 scan 拍不分配 scan 字典 (惰性)。
- emitter 未改：sticky timing / 折叠 / RPT 行为不变。

## 0.3.0 — timing 延续记号参数化 / 方案B (V4)

- 新增 `wft_continuation` 参数 (`PatEmitter` / `convert_one`)，GUI 增加 "timing 延续记号" 输入框。
- `sticky_wft=True` 且 timing 未切换那一拍，用该串替代 ` * <wft>`：
  - 留空 / `None` → **方案A**：省略 timing 字段 (` * <data>;`)。
  - 填记号 (如 ` *`) → **方案B**：原样插入 (` * <data> *;`，形式以机台 spec 为准)。
- 便于适配不同机台对 "timing 沿用" 的写法要求。

## (V3) — GUI 启动防护 (版本仍 0.2.0)

排查 "双击 gui.py 闪退"。逐字节 diff 确认改动未损坏文件、编码 UTF-8 无 BOM、纯 LF；闪退源于启动异常被双击控制台瞬间吞掉 (典型：缺 tkinter，或单独拷出 gui.py 导致导入失败)。

- `gui.py` 加**启动防护**：任何启动异常都写 `startup_error.log`、尽量弹窗、控制台暂停等回车，不再瞬间消失。
- 导入改为**按实际文件夹名导入**，文件夹改名 / 多层解压也能运行。
- 新增 **`run_gui.bat`** (ASCII + CRLF)：双击启动，窗口不自动关，报错留屏。
- 类主体与功能逻辑未改。

## 0.2.0 — sticky timing + 首轮提速 (V2)

- **timing 只保留首次切换标志 (sticky timing)**：timing 字段仅在 WFT 切换时输出，相同 timing 的后续拍省略；新增 `sticky_wft` 开关 (默认 `True`)，GUI 对应 "timing 仅切换时输出" 复选框。`sticky_wft=False` 回到每拍带 timing 的旧行为，便于逐位回归。
- **提速**：
  - emitter 折叠热路径预拆分简单 pin / bidir pin，纯 input/output pin 不再逐拍调用 `fold_io`；无 ditto 的重复拍折叠结果缓存 (输出与旧逻辑逐位一致，2 万随机用例回归)。
  - parser `strip_brace_comments` 由逐字符 Python 循环改为 C 层正则逐层剥离 (配对括号下与旧实现等价)。
- RPT 不跨 timing 合并 (波形相同但 timing 不同的拍会拆开)。

## 0.1.0 — 原始基线 (V1)

Mentor Tessent WGL → Chroma 3380P `.pat` 转换工具初版：WGL 解析器 (signal / scanchain / timeplate / scanstate / pattern)、`.pat` 流式生成器 (RPT 压缩、bidir 折叠、scan shift 展开)、单文件 `convert_one`、Tkinter 批量 GUI。在 `ac_scan_1_1.wgl` 样例上前 2759 cycle 与原始 `.pat` 逐位匹配。

---

## ⚠️ 上机前通用验证清单

1. **逐位回归优先**：用已对齐样例，GUI **取消勾选** "timing 仅切换时输出" (`sticky_wft=False`) 转一遍，与旧 / 参考 `.pat` 逐位比对，确认解析/提速改动未改变既有结果。
2. **sticky timing 合法性**：确认机台 Pattern Compiler 接受不带 timing 字段的行 (` * <data>;`) 并按 "沿用上一拍 WFT" 解释；否则用方案B (`wft_continuation`) 或 `sticky_wft=False`。
3. **STOP 行**：确认 ` * <data>, STOP;` (含末拍直接作 STOP 的约定) 被接受。
4. **多 WFT 真机回读**：含真实 timing 切换的 WGL，在 ATE 上确认切换点 period/edge 在 "打标记那一拍" 生效并保持。
5. **新方言**：遇到转不出内容的 WGL，提供 `.wgl` (有参考 `.pat` 更佳) 以便扩展解析器。
