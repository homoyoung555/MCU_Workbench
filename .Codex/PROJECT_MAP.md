# PROJECT_MAP — MCU Workbench

## 当前状态（2026-09-16，独立迁移已完成）
- 源码D:\Code\MCU_Workbench；分支codex/workbench-migration，独立Git未commit/push；来源旧V1.4/codex/v1.4-source-baseline的当前含未提交改动快照。546来源文件原SHA未变。
- 运行资料D:\Code\MCU_Workbench_WORKSPACE。当前发布包包含程序生成、SCAN、SWD，已按用户后续授权重打包联测，生成器修订3；最新报告.Codex/reports/2026-09-16-swd-release.html。
- 入口：启动工作台.cmd → MCU_Workbench_App/MCU_Workbench_App.exe；源码入口gui/desktop.py，浏览器开发gui/server.py --port 8844。历史gui/launch.py不作为新入口。
- 最新交接（已按切换Codex目录更新，含SWD定位与未决范围）：.Codex/handoffs/2026-09-16-workbench-migration.html；验收：.Codex/reports/workbench-migration.html；原架构详细历史：.Codex/legacy/V1.4_PROJECT_MAP.md（历史路径属于原仓库）。

## 目录与调用关系
- gui/desktop.py：独立WebView2窗口 → gui/server.py::make_server(empty=True)，动态端口；desktop_smoke.py是真实包内验收。
- gui/workbench.html/js/css：工作台壳；program同源iframe保留草稿；SCAN独立转换及关联。gui/index.html是原程序编辑器，业务不改。
- gui/server.py::Session → WorkbookReader / ProductCompiler → gui/generation.py → program_gen原生平台装配。core提供typed事实，platforms提供Chroma/S100适配，platform_program组装完整程序。
- gui/scan_workspace.py管理输入/冻结任务/关联/失效，scan_conversion.py → tools/wgl2chroma；program_gen/core/scan_test.py和scan_test_assembly.py消费关联产物。
- preflight/为诊断；tests/保留既有回归，新增test_workbench_paths.py验证路径/环境覆盖/冻结路径/包资产；tools/为转换和编译封装；docs/与CONTEXT.md保留业务说明。
- gui/paths.py统一资源与运行资料：默认源码或分发根的并列MCU_Workbench_WORKSPACE；MCU_WORKBENCH_WORKSPACE显式覆盖。tests/workspace_paths.py一致；main.py新变量优先，兼容旧显式V14_WORKSPACE。
- gui/build_desktop.py构建MCU_Workbench_App并包含工作台三个资产；README说明交付；.gitignore排除包及临时产物。

## 运行资料
- input/622文件（约484MiB）包括母本/双平台Pattern/WGL等；golden/13299文件（约466MiB）；toolchains/26229文件（约8874MiB）原样独立复制，未调用厂商编译。
- outputs/scratch/staging/logs/cache为新运行数据。旧输出/用户草稿/浏览器缓存/旧包未自动导入，保留原目录。

## 本轮验证与边界
- 迁移合同先4 RED后4 GREEN；合并专项28 PASS+2子测试（73.69秒）。前端146/146，工作台公共及交互契约通过。
- 原组复制节点完整HTTP检查→保存→双平台源码生成1 PASS（83.82秒，221文件），运行目录新workspace/outputs/gui_runs/20260916_110550_eba4bd1119。
- 新EXE真实桌面25/25；287个应用代码对象与新源码一致，6静态资产SHA一致；622输入SHA逐文件一致。详见reports/migration-*.json与tmp/migration-*.log。
- 生产生成内核原样复制；原V1.4所有546来源文件未变。未跑全量、厂商编译、硬件上机。旧全量失败与S100错误不能标为已解决；工具链副本运行环境待后续验收。
- 构建工具借用旧桌面venv（仅构建环境）；交付EXE自带运行依赖。以上仅为迁移阶段验收；后续SWD开发见下节，不能沿用迁移验收结论。

## SWD 首期范围与只读核对（2026-09-16）
- 记录：.Codex/reports/2026-09-16-swd-compatibility.html。双平台独立生成，测试项具体Pattern引用到逻辑SWD的一次映射；资料导入、旧步骤Excel原格式往返、修订过期拦截；不新增测试项或硬件调试。
- Chroma来源：D:\Code\04_Chroma_MCU_program\temp\SWD生成器\SWD_PAT\SWD.py。源码发现网页Excel往返丢字段、S100路由过滤等待/CAP/SRAM、C_L硬件与生成掩码含义相反、encoding_v2现配置绑定py32f420。已只读核对四份Excel。首批已定PT104=PCD009（用户确认），资料冲突保留来源并由用户确认，不阻断独立生成；以下为历史只读核对结果。


- PT104/PCD009专项已追加同报告：母本VERSION product=PT104，程序名含PY32F420A；CP1/2/3为PA11/PA13/PD11，旧工具PA14/PA13/NRST。两份步骤库各100个PT104，79同名六字段一致，3个DAC仅改名，其余频率存在PA4/PA8差异。SVD与冻结metadata共同371寄存器中发现ADC1.SMPR3及RCC.CSR地址冲突，原Excel/头文件交叉证据见报告；不自动裁决。两平台M4核心序列归一化68行/1918周期一致，未做硬件等价验收。


- 最新用户决定：保留产品SWD/SWC管脚默认值，简单选择接口纳入首期；沿用用户已验证生成器，不新增反向解码验证；资料差异留存供用户确认。AGENT配置主线已定位旧工程scenarios/directive_agent.py → EncodingDB查询工具 → validate_request → Composer/PatternRow；另有Commander/PatternSkill及网页步骤编辑接口。未调用模型、未外发、未实现接入。完整历史索引在D:\Code\03_offline_mcu_ate\.Codex\PROJECT_MAP.md。


## SWD 实现阶段（历史）
- 用户已授权：资料导入、双平台生成/Excel往返、管脚选择、测试项Link；排除AGENT/硬件调试。主agent负责workspace/server/资源引用/UI集成；swd_generator负责gui/swd_generator.py与swd_legacy.py；swd_materials负责gui/swd_materials.py；swd_ui负责gui/swd.html/js。各自专项TDD，主agent审查；按用户最新要求仅模块专项、集成验证稍后；历史厂商诊断仍暂缓。


## SWD 首期源码结构（模块专项阶段历史）
- gui/swd.html/js：独立SWD页面，步骤Excel编辑/往返、管脚、资料差异确认、双平台产物下载；workbench.html/js增加导航与程序检查失效通知；index.html在具体Pattern引用处提供Link。
- gui/swd_workspace.py：持久化输入/配置/生成修订/程序SHA到Link；freeze向生成任务提供不可变双平台字节；改动过期、重新生成后需显式更新Link。资料重导入幂等。
- gui/swd_generator.py → gui/swd_legacy.py：纯函数封装既有Chroma/S100向量逻辑，禁止运行原SWD.py顶层；PT104=PCD009默认SWC/SWD/reset为PA14/PA13/NRST，可选择。
- gui/swd_materials.py：SVD/寄存器xlsx/h/c留存与解析，跨来源差异由用户确认；C/H仅支持直接指针地址与宏留存，不是完整C寄存器解析器，不接AGENT。
- gui/server.py路由/api/swd/*；gui/generation.py与program_gen/native_target_renderer.py → program_gen/core/swd_pattern.py → 既有PatternProducer；只替换明确Link资源，不新增测试项/FLOW/Bin。
- gui/build_desktop.py已补SWD静态资产，但未构建新包。tests/test_swd_generator.py、test_swd_materials.py、test_swd_link.py、test_swd_workspace.py为独立专项；用户要求稍后集成，未跑联合套件、HTTP端到端、厂商编译或硬件。

- SWD源码续接：.Codex/handoffs/2026-09-16-swd-first-implementation.html；专项24项通过，联合验证及新版打包待用户下一步安排。

- tests/swd_ui_contract.cjs：页面独立契约；Node运行通过，覆盖SHA修订、来源显示、Pattern向下填充、新行及删除首行后归属、临时ID不导出。Python专项24项及此契约全部通过，未做跨模块联测。


## SWD 最终包验收（2026-09-16，覆盖上述暂缓集成状态）
- 用户已保存关闭工作台；隔离目录构建的最终修订3包已替换MCU_Workbench_App，原启动工作台.cmd可用。旧包留存.scratch/swd-release/previous-package；中断候选包留存interrupted-candidate。
- 最终EXE真实WebView2 34/34通过（.scratch/swd-release/final-desktop/report.json，frozen=true）；包内276个gui/program_gen模块、8静态资产与当前源码一致（package-integrity.json）；build-staged.log记录最终构建。
- tests/test_swd_integration.py走真实PT104母本HTTP导入、Link、预览、保存重载、双平台完整生成、过期拒绝、显式重Link、失效引用解除：2/2通过，179.276秒。SWD模块组合26/26；程序页146/146，工作台与SWD契约通过。
- gui/swd_legacy.py修复两平台DRW抄录错误、S100命令分隔符，四命令及M4分别与原脚本一致。gui/swd_generator.py GENERATOR_REVISION=3，workspace修订包含版本使旧产物过期。legacy_comparison.py/json记录358项原纯函数只读兼容比较通过。
- gui/swd_workspace.py允许解除已删除/改名引用的旧Link，index.html对该目标只允许解除；gui/desktop_smoke.py覆盖真实SWD页面和Link弹窗。
- .scratch/swd-release/prepare_gate.py、compiler_gate.py为真实PT104 CP3 lab门禁脚本。Chroma C:/CRAFT的DEC、SWD PAT、完整PLN通过；工作区CRAFT副本无可靠输出。S100 PRJ/TIM/全部Pattern及PRG前端通过，最终C Compiler not found，无成功GSW；工具配置恢复原字节，未做硬件上机。
- 全量回归因运行中生成器修正而停止，未完成：462条通过行、17条失败/错误行含子测试，非完整统计且失败未全部归因。full-regression.log/status.json保留现场；最终仅重跑上述SWD及包验收，不能称全仓绿色。
- 最新报告.Codex/reports/2026-09-16-swd-release.html；源码交接已加历史说明。后续仍需S100 C编译环境、整仓失败归因/回归和机台验收。

## SWD 前端调整完成（2026-09-16）
- 最新报告.Codex/reports/2026-09-16-swd-ui.html；交接.Codex/handoffs/2026-09-16-swd-ui.html。用户明确表格对齐程序生成页，SVD编辑参考offline MCU ATE Web；三个使用起点可并存。
- gui/swd.html：程序页表格色值/网格/字体/冻结表头行号，固定保存生成工具栏，SVD原生选择弹窗；资料/配置/生成区保留。
- gui/swd.js：materials.registers.sources → SVD搜索/来源与外设筛选 → 按选择顺序插入草稿或替换指定行寄存器 → 既有save/generate。保留已有data/type/step；不同来源独立选择，缺失reset不推断；新步骤R且data留空。行号显示步骤顺序，物理行身份仍用于Excel保存；编辑高亮仅页面状态。
- tests/swd_ui_contract.cjs新增公开UI入口契约，RED→GREEN；浏览器真实选择/保存重载/双平台生成通过。模块26/26，更新安装包后的桌面回归34/34；证据.scratch/swd-ui/。测试仅隔离夹具。
- gui/swd.html/js已同步MCU_Workbench_App/_internal/gui，包内276模块+8资源一致；EXE/Python未改，旧前端备份.scratch/swd-ui/previous-assets。保存后重开工作台即可加载。未重跑厂商编译与全量回归，历史未通过边界继续保留。

## SWD 紧凑布局调整（2026-09-16，最新）
- 按用户截图仅修改gui/swd.html：步骤Excel、资料库、芯片配置移至表格上方；导入改小按钮，芯片/四管脚横向排列；“芯片与管脚”更名“芯片配置”。
- 取消页面下方“独立生成”卡片，现有生成结果/状态/预览DOM移入顶部“生成结果”原生details弹层；保留生成、预览、下载与过期信息，无JS或后端修改。
- node tests/swd_ui_contract.cjs通过；浏览器实际检查顶部布局及生成后结果入口通过。已同步安装包_internal/gui/swd.html，276模块+8静态资源一致；旧HTML留存.scratch/swd-ui/before-compact.html。本轮未重跑Python模块或34项桌面回归，前节为上一轮记录。

## SWD 单页与 Pattern 编辑器（2026-09-16，已完成）
- gui/swd.html/js：左侧 Excel/Pattern 导航、中央八列表格展示与双击/F2编辑；Pattern 模态草稿、步骤排序、外设寄存器树与32位位图；目录选择筛选 SVD/xlsx/h/c，PY32F420缓存按钮。
- gui/swd_workspace.py::create_pattern → save/export_excel；gui/server.py 新增 /api/swd/create 与 /api/swd/cache；gui/swd_materials.py 增加显式 svd_cache 解析。gui/data/py32f420_svd_cache.json 为旧缓存原文，SHA c068e728cdc121cce63abbb909cdb9a50e1bc2dd19c2e2bcfa1fab8c2ebcb2fa，47外设/525寄存器/3717字段；gui/build_desktop.py 打包该资源。
- tests/test_swd_authoring_http.py 验证无程序母本创建→缓存→保存→双平台生成；相关专项34项通过，Node契约通过。浏览器完整流程通过；已重新构建并替换原安装目录，WebView2 38/38通过（新增缓存/位图/创建/单屏），替换后276模块与9资源一致。报告 .Codex/reports/2026-09-16-swd-authoring.html，最新交接 .Codex/handoffs/2026-09-16-swd-authoring.html；旧包 .scratch/swd-authoring/previous-package。

- gui/desktop_smoke.py 新增实际包PY32F420缓存/位图/创建生成/单屏检查；tests/swd_ui_contract.cjs 覆盖草稿取消隔离、bit31及复合数据保护。固件目录真实浏览器上传及双击编辑通过；未重跑全仓或厂商编译。

## SWD 合并单元格创建修复（2026-09-16，已安装）
- 用户 pattern.xlsx 创建报 MergedCell.value read-only；tests/test_swd_workspace.py 新增公开创建回归已复现同一堆栈。
- gui/swd_generator.py::export_excel 在写入前解除目标页合并，按原物理行到新位置映射恢复连续且未包含不同编辑值的合并；行高按原位置快照恢复。保护新编辑值，其他工作表不改。
- gui/desktop_smoke.py 的步骤夹具加入合并单元格，覆盖安装包真实保存/创建链路。源码/测试4文件改动（含swd.js创建等待提示）；20项专项及Node契约通过。真实表副本1026步/102Pattern/88合并区域逐格保留，原文件SHA未改。重打包完成，候选276模块/9资源一致，实际WebView2桌面38/38通过；用户确认关闭后已替换根目录安装包，安装后276模块/9资源一致；旧包保留 .scratch/swd-merged-fix/previous-package。最新续接 .Codex/handoffs/2026-09-16-swd-merged-fix.html。

- 单纯编辑与末尾追加保留空白行和原物理位置，避免原export压缩空白行破坏合并。报告 .Codex/reports/2026-09-16-swd-merged-fix.html；证据 .scratch/swd-merged-fix/。

## SWD 创建及保存性能优化（2026-09-16，历史中间方案）
- gui/swd_generator.py::load_excel 改为只读流式解析选中页；export_excel 对无图表/表格/批注等关联资源的步骤页使用精简解析工作簿，回填目标页到原xlsx包，其余部件保留原字节；打印设置保留，旧calcChain清理并要求Excel重算；复杂关联页保留原完整处理路径。
- tests/test_swd_generator.py 增加非目标部件逐字节保留与计算链失效回归。22项相关测试通过；真实1026步表/88合并区域验证通过，22个非目标包部件完全一致。
- 隔离真实表测量：创建51.990秒→3.948秒，修改后保存43.592秒→3.827秒。证据 .scratch/swd-save-speed/。尚未替换安装包。

## SWD 草稿/保存/导出分离（2026-09-16，已安装）
- 覆盖前节仅优化Excel写入的交付计划：用户明确创建只新增草稿，保存只持久化工作台内容，下载才生成Excel。gui/swd_workspace.py::create_pattern 返回独立草稿，未保存新文档仅在会话pending中；save 校验并写workspace.json，原xlsx不重写。新增行用稳定负row标识，导出时转换为新物理行；旧工作区可直接读取。
- gui/swd.js 创建保留既有草稿且不触发保存；配置/缓存/差异确认不顺带保存或覆盖草稿；生成与下载在未保存时提示先保存。保存显式发生于保存步骤/保存Pattern。
- tests/test_swd_workspace.py、test_swd_generator.py、swd_ui_contract.cjs覆盖草稿隔离、无Excel保存、重载身份、原公式保护与导出；相关41项及Node契约通过。desktop_smoke.py增加创建草稿/保存不重写原Excel两项。
- 实际1026步+PY32F420资料缓存：创建0.074秒，保存0.095秒，添加步骤后保存0.091秒，重启后首次保存0.605秒；下载Excel3.239秒。原xlsx及22个无关部件未改。证据 .scratch/swd-save-speed/draft-final/timing.json；已安装最终 dist-draft 包，旧dist仅第一版加速候选，不可安装。

- 最终 dist-draft 候选实际 EXE/WebView2 验收40/40通过（desktop-draft/report.json）；276模块/9资源一致。用户确认关闭后已替换根目录 MCU_Workbench_App；安装后再次核验276模块/9资源一致，旧包保留 .scratch/swd-save-speed/previous-package。
- 本轮完成记录：.Codex/handoffs/2026-09-16-swd-save-speed.html；详细验证报告：.Codex/reports/2026-09-16-swd-save-speed.html。

- 新 Session 统一交接：.Codex/handoffs/2026-09-16-swd-session-handoff.html。新版已安装且核验通过，无待安装任务；该文档覆盖旧续接中等待关闭窗口的历史描述。

## SWD 编辑体验续接（2026-09-16，已安装）
- gui/swd.html/js：用户最终要求步骤第一行仅序号/地址，第二行操作/描述；增加地址/描述/已知寄存器名搜索与步骤号跳转，保留原编号。SVD改为Pattern模态框内非模态可移动/缩放浮窗；HTML拖放到属性区替换当前寄存器（保留data/type/step），到列表按上下半区插入；保留点击按钮替代入口。取消/保存关闭浮窗，全部修改保持草稿语义。
- 位图按既有生成器reset/data/step计算32位终值；数量不等沿用生成器逐位置1语义。点击已有字段保留位宽（写入等宽0b值），重叠字段修改最后覆盖者；字段外追加一位操作；不能解析显示破折号，不伪装成0。
- tests/swd_ui_contract.cjs：导航、浮窗、拖放、取消隔离、位图多移位/掩码位宽/重叠/bit31等公开交互回归RED→GREEN；node --check及Node契约通过。
- 真实浏览器基于1026步原表隔离副本验证搜索/跳转、位图、浮窗移动、拖放替换/插入、取消和保存刷新。浏览器保存的第二步经原生成器计算00011900，与页面一致。用户要求先界面验证，未跑Python套件、全仓、桌面EXE或厂商编译。
- 用户授权安装后重新检查工作台进程已退出；已将验证后的swd.html/js同步MCU_Workbench_App/_internal/gui。安装后276模块/9资源与源码一致，无Python/EXE变化。证据.scratch/swd-editor-ux/verification.json、ui-contract.log；ready-assets为本轮安装资源，previous-assets为安装前备份。通过原启动工作台.cmd重新打开即可使用。

## SVD 左右分栏（2026-09-16，已安装）
- 用户反馈浮窗遮挡：gui/swd.html以CSS Grid将打开的SVD和步骤编辑区左右并排，独立滚动；关闭SVD恢复全宽。gui/swd.js仅禁用嵌入状态标题拖动并更新提示，寄存器跨栏拖放不变。覆盖前节浮窗布局。
- node语法与SWD UI契约通过，真实浏览器已验证无重叠/跨栏拖放/关闭恢复；已同步安装版两个静态资源，276模块/9资源一致。证据及旧前端备份.scratch/swd-editor-split/；未停止用户进程，现有窗口需保存后重开。用户此前要求先界面验证，未跑Python套件或真实EXE回归。

## SVD 字段预览与两行位图（2026-09-16，已安装）
- gui/swd.js复用registerFieldsMarkup，在SVD侧选中寄存器即显示字段范围/名称/说明，无需先拖入或应用；缺少字段明确提示。原始寄存器描述和来源折叠保留。tests/swd_ui_contract.cjs覆盖预览先于应用且不修改步骤，以及换选无字段不残留旧字段。
- gui/swd.html位图所有布局固定16列两行（31–16、15–0），方框紧凑且最大26px；窄宽横向滚动。增加SVD字段详情高度，保留左右分栏。Node契约RED→GREEN，真实浏览器验证TIM2.CR1字段与位图行几何、无重叠；按用户要求未跑Python套件。
- 两静态资源已同步安装版，276模块/9资源一致。旧资源及证据.scratch/swd-field-preview/。现有窗口保存后重开加载，未结束用户进程。

- 后续精简（已安装）：按用户要求移除右侧重复字段说明表及其渲染/CSS，只在左侧SVD显示字段详情；右侧保留参数、两行位图及悬停字段名。node语法与UI契约通过，两静态资源已同步并逐字节核对；旧资源.scratch/swd-field-preview/before-remove-right。

## SWD 均衡布局（2026-09-16，已安装）
- 按用户标注，SVD+步骤导航合占左半，参数编辑占右半；三列34/16/50，最大1400x760。参数三列且输入框紧凑，位图区按内容宽度；窄屏退为两列并将步骤导航置于编辑区上方。
- SVD选中寄存器进入完整字段阅读区，隐藏筛选/树列表；新增返回列表按钮，保留选择。字段标题支持拖拽（drag监听统一到SVD面板），移除表头sticky避免遮挡，字段名不逐字换行。
- gui/swd.html/js及tests/swd_ui_contract.cjs更新；Node语法/契约通过，真实浏览器验证编辑区起点50%、无重叠、返回保留选择。两静态资源已同步，276模块/9资源一致；未跑Python套件或EXE回归。证据/备份.scratch/swd-balanced-layout/。

## SWD 字段与位图联动（2026-09-16，已安装）
- 本轮按用户授权实现评审前三项：gui/swd.html/js明确正在浏览/编辑地址，不一致提示尚未应用并禁用字段定位；字段长说明默认摘要，原文details展开，支持全部展开/收起；地址数值一致（兼容大小写及前导零）时点字段仅高亮合法32位范围，不改data。切换行/地址/来源自动清除旧高亮。
- tests/swd_ui_contract.cjs覆盖匹配/失配及高亮不改数据，RED→GREEN；真实浏览器验证TIM2.CR1失配禁用、应用后CMS仅高亮6/5位且data仍0X0000000F、说明展开收起。Node语法通过，按用户既有偏好未跑Python/全仓/EXE回归。
- 两静态资源已同步安装，276模块/9资源一致。旧资源与验证记录.scratch/swd-field-link/；用户窗口保存重开后生效。

## SWD 草稿恢复与复制（2026-09-16，已安装）
- gui/swd.js：编辑器维护按行对象的打开时字段快照，新步骤按创建时快照；已修改/新增标记与本次未保存状态，位图修改同样更新标记。恢复当前步骤只还原字段及资料来源，不改其他行或顺序。复制当前步骤插到下一行，保留数据/操作/位移，清除物理行及临时身份，保存才获得新行ID。
- gui/swd.html：复制步骤、恢复当前步骤及未保存标识；取消和Esc使用页面内继续编辑/放弃修改对话框，完全恢复且无结构变化时直接关闭。系统confirm在IAB验收阻塞后改为页面对话框。
- tests/swd_ui_contract.cjs公开入口RED→GREEN覆盖标记/恢复隔离/复制身份与独立修改/无隐式保存/取消和Esc保护。真实表隔离浏览器验证副本保存重载、原行不变、继续编辑与放弃BB后保留已保存AA，已核对后端持久化不同row身份。未跑Python套件/全仓/EXE回归。
- 已同步两静态资源，276模块/9资源一致；备份及证据.scratch/swd-draft-tools/。本轮3个源码/测试文件变更，无子代理。用户窗口保存后重开生效。

## SWD 资料区加宽与位图对齐（2026-09-16，已安装）
- gui/swd.html：按用户最终要求直接调整三栏为46/16/38，无放大按钮；参数、描述、位图区共享宽度与边缘，位图保持16列两行。宽屏筛选合为一行，树行距紧凑。
- gui/swd.js：单一资料来源不再逐行重复来源文字，悬停及详情保留；多来源仍显示来源以便区分；拖放提示精简。行为与草稿不变。
- node --check gui/swd.js、node tests/swd_ui_contract.cjs通过；1280x720浏览器验证参数与位图区边缘均801.234375至1256，SVD宽565.9、编辑区475.8，一屏约11项。未跑真实任务或Python回归。
- 两静态资源已同步安装版；276模块/9资源一致。证据及旧资源备份.scratch/swd-wider-tree/。覆盖此前34/16/50及位图按内容宽度的布局说明。

## SWD 行内操作与右侧字段预览（2026-09-17，已安装）
- gui/swd.html/js：压缩Pattern/SVD标题栏；移除步骤搜索/跳转和上下移按钮，新增移至列表顶部，各行独立拖动手柄/圆形删除按钮；拖放共用原寄存器drop路径，步骤按对象身份移动，边缘定时滚动，支持Alt+上下键。删除保持未删的当前步骤，删除当前项后选择邻项。
- Pattern编辑中SVD改为单选浏览，选中项旁显示替换/插入，应用后保留选中与树位置；移除左侧固定说明/操作栏。复用register-preview容器移入右侧位图下方，点击即显示字段，左树不再被详情替换；地址失配提示及字段定位保护保留。非Pattern入口保留原多选/应用流程。
- tests/swd_ui_contract.cjs：更新旧搜索/跳转契约，新增手柄/行内删除、排序对象与草稿隔离、行内插入/替换保留数据和预览测试。先RED后GREEN，node语法及UI契约通过。
- 浏览器1280x720实测树高494px、选择不改地址、右侧即时预览、插入保留选择、拖动第2步至第4步、行内删除、键盘排序与放弃后恢复。未跑Python套件/真实业务任务/EXE端到端。
- 已同步安装版两静态文件，276模块/9资源一致；备份及证据.scratch/swd-inline-editor/。本轮3个源码/测试文件，无子代理。覆盖此前步骤搜索/跳转与左侧详情阅读布局。

- 2026-09-17 未打开SVD时铺满右侧（已安装）：gui/swd.html增加仅无打开SVD面板时的max-width:none规则，参数/描述/位图统一占满编辑区；打开SVD仍按原分栏。浏览器1280x720验证未打开及关闭后宽864px、打开后454.765625px，位图保持两行；node tests/swd_ui_contract.cjs通过。仅同步HTML并逐字节核验，备份.scratch/swd-full-width/previous-assets/。

## SWD 批量生成与顶部文件选择（2026-09-17，已安装）
- gui/swd.html/js：按钮改为生成Pattern，范围为当前/勾选/当前Excel全部，默认仍为既有Chroma+S100。每个Pattern独立checkbox，按documentId保存页面内选择，搜索结果全选/清空；点击名称仅切换浏览。
- generate复用原/api/swd/generate逐项串行请求，顶部显示进度及成功/失败摘要，失败继续后续项，支持只重试当前文件上次失败项；未保存步骤阻止生成，不隐式保存。生成期间锁定文件/勾选/表格编辑；内核与后端未变。
- 移除左栏Excel卡片区，载入和文件下拉/Pattern数量移至顶部。资料库去除芯片专用按钮，cacheCatalog列表当前仅内置PY32F420，调用原缓存端点；以包内缓存SHA256识别已载入，兼容相同内容改名。新增内置缓存仍需扩充目录及对应后端入口，并非自动扫描磁盘。
- tests/swd_ui_contract.cjs：RED→GREEN覆盖范围、勾选/浏览隔离、按Excel隔离、失败继续/仅失败重试、脏步骤拦截及缓存指纹。node --check与UI契约通过；浏览器验证布局、两项勾选、空选禁用、全部范围及缓存载入识别。未跑实际批量生成/Python套件/EXE端到端。
- 已同步两静态资源，276模块/9资源一致；备份和证据.scratch/swd-batch-generation/。本轮3个源码/测试文件，无子代理。

- 2026-09-17 勾选生成交互修正与清空列表（已安装）：gui/swd.js在checkbox变更/搜索结果全选后自动切换selected范围，生成按钮显示实际项数，显式下拉仍可改当前/全部。gui/swd.html/js新增清空列表，隐藏现有generation ID并存localStorage（当前浏览器来源），保留后台文件/关联，新生成ID继续显示，关闭旧预览。tests/swd_ui_contract.cjs先RED后GREEN覆盖自动范围及清空后刷新/新结果/不删记录；Node语法与契约通过，浏览器验证勾选3项→selected→生成Pattern（3）。未运行实际批量生成。已同步HTML/JS，276模块/9资源一致；备份.scratch/swd-selection-fix/previous-assets/。本轮3个源码/测试文件。

- 最新续接文档（2026-09-17）：.Codex/handoffs/2026-09-17-swd-ui-handoff.html。本轮SWD界面迭代已安装收尾，无新待办；包含最终布局/批量生成语义、验证边界、localStorage来源隔离与前端队列限制、缓存目录维护及技能建议。临时目录同名副本遵循handoff技能，项目副本遵循本项目续接资料约定。

## 程序编译功能（2026-09-17，开发中）
- 用户确定选择程序文件夹，一个文件夹一个任务，可累计多个串行编译；建议仅依据厂商日志。
- gui/compiler_workspace.py 管理上传副本与任务；tests/test_compiler_workspace.py 覆盖上传路径隔离与入口识别，初始RED已复现并GREEN。独立页面由compiler_ui子代理负责，尚未安装。

- 编译开发续记：gui/compiler_runner.py 复用现有工具链环境/参数，保留日志并解析诊断；队列持久化在输出目录compiler下。gui/server.py新增鉴权/api/compiler/*，不依赖母本。gui/workbench.html/js新增入口，build_desktop.py新增资产，desktop.py增加编译期间关闭保护。新增tests/test_compiler_http.py；9项专项通过。gui/compiler.html/js及tests/compiler_ui_contract.cjs由子代理负责，尚在整合。真实编译证据将位于.scratch/compiler-feature/，安装版尚未更新。

## 程序编译功能（2026-09-17，已安装）
- 覆盖此前开发中状态。gui/compiler_workspace.py → compiler_runner.py → tools/chroma_compiler 与 s100_compiler 环境/参数：文件夹上传，一个文件夹一个入口，后端串行队列，独立副本，失败继续、结果持久化、原始日志及规则建议。运行资料 outputs/gui_runs/compiler；强制退出中断任务需显式重试。
- gui/compiler.html/js独立页面；server.py新增鉴权/api/compiler/*；workbench.html/js入口；build_desktop.py打包；desktop.py关闭保护及compiler自检范围；gui/compiler_smoke.py实际包验收。README记录工具链环境变量和布局限制。
- 20项Python联合专项通过，程序页146/146及工作台/SWD/新编译页契约通过；实际EXE/WebView2编译页6/6通过。首次沙箱主窗口失败，桌面环境重试通过。真实Chroma DEC/PAT/PLN完整通过；混合队列S100失败后Chroma成功。
- S100仍有明确环境阻塞：bcc32.exe版本标识Synaptics，与预期Borland不符，拒绝调用并报告修复建议；另一隔离Borland副本只能证明简单C++冒烟，完整GSW尚未通过。未修改工具链/全局cfg/注册表，不自动执行上传的编译器；后续需正确完整工具链。未跑全仓/旧完整桌面回归/机台。
- 用户确认退出后已替换MCU_Workbench_App；安装后281模块/11资源一致。旧包.scratch/compiler-feature/previous-package；证据同目录。详细报告.Codex/reports/2026-09-17-compiler-feature.html；最新交接.Codex/handoffs/2026-09-17-compiler-feature.html。主代理在UI子代理完成后接手，无源码并行冲突。

## Chroma 便携工具链接入（进行中）
- 用户要求先复用V1.2/Chroma_Compiler/portable的craft+msvc到本项目toolchains/chroma，使用相对位置设置CRAFT_HOME；启动工作台.cmd已接入，.gitignore排除工具链，README记录布局。原始V1.2资料不改，当前工作区数据目录不变。
- 用户已纠正验证范围：本轮必须用一个实际程序完成DEC/PAT/PLN编译；仅异机验证留待后续。复制及SHA证据.scratch/chroma-portable-import/，新工具链尚待真实编译，不能沿用旧C盘工具链通过结论。

## Chroma 便携工具链接入完成（2026-09-17）
- V1.2/Chroma_Compiler/portable/{craft,msvc}已复制到项目toolchains/chroma/{craft,msvc}；共5016文件，约1.78GiB，逐文件SHA256一致。原V1.2未改。启动工作台.cmd使用setlocal及相对路径CRAFT_HOME优先选择此副本；现有运行资料目录不变，直接EXE不经过此设置。无需重打包EXE。
- 真实PT104 CP3隔离副本DEC、全部PAT编译链接、PLN完整编译均通过，原程序SHA未改。验证进程PATH仅保留Windows/System32，移除INCLUDE/LIB/LIBPATH及VS/SDK变量；便携cl.bat调用包内msvc/setvars.bat。证据.scratch/chroma-portable-import/manifest.json、compile-result.json及jobs/*/compile.log。
- README已补部署方式，.gitignore排除/toolchains/；启动脚本旧版备份.scratch/chroma-portable-import/启动工作台.before.cmd。本轮变更3个配置/说明文件及地图，无子代理。按用户最新要求已做本机单程序完整编译，异机验证后续；S100原环境问题继续保留。

## S100 安装包修复排查（进行中）
- 用户提供D:/Code/TEMP/S100_Compiler_Portable(6).exe，7z解压到.scratch/s100-repair/extracted。初始bcc32.exe为Borland5.6、1398272字节SHA791E3C...18CED，原cfg硬编码旧机器路径；真实沙箱外基线走到C阶段报windows.h缺失。
- 后续发现bcc32.exe运行后变为2169856字节SHA404870...CC6F，与旧异常工具链相同。用户截图Synaptics.exe / Z:BCB6/Bin/fconvert.exe映像错误；定位未签名隐藏系统文件C:/ProgramData/Synaptics/Synaptics.exe，用户明确授权仅停止该路径进程并检查重启。已停止PID13136，暂未重启；未删系统文件/未改启动项。证据.scratch/s100-repair/file-identities.json等。
- 正在从原安装包重新解压到本项目toolchains/s100，等待配置修复与真实PRJ/PRG/GSW验证；不能沿用任何旧通过结论。

## S100 修复集成（2026-09-17）
- gui/compiler_runner.py 通过 tools/s100_compiler.compiler_environment 使用当前位置生成BCB头文件/库配置及PATH，finally恢复原cfg；tests/test_compiler_workspace.py补失败恢复测试，RED→GREEN，编译工作区/HTTP共8项通过。
- toolchains/s100来自用户安装包重新解压；启动工作台.cmd设置相对S100_HOME，README更新。真实PT104 PRJ/PRG编译两次通过，最新集成14.66秒，Errors0/Warnings22/GSW生成。编译后bcc32 SHA保持791E3C...18CED，可疑进程未见重启。仅停止已授权进程，未删除系统文件或修改启动项，不代表系统清理完成。
- 当前重打包中，尚未替换桌面版；证据.scratch/s100-repair/。本轮5个源码/测试/配置说明文件，无子代理。

## S100 修复完成并安装（2026-09-17）
- 覆盖上述打包中状态：新桌面包已安装到MCU_Workbench_App，旧包保留.scratch/s100-repair/previous-package。安装前后281模块/11资源与源码一致；真实EXE/WebView2编译页面6项验收通过。
- python -m pytest -q tests/test_s100_compiler.py tests/test_compiler_workspace.py tests/test_compiler_http.py：13通过；node tests/compiler_ui_contract.cjs通过。用户明确选择不跑全仓，仅本轮专项与安装验证。
- 工作台真实S100入口编译14.656秒通过，GSW921316字节，SHA A8677664AB17207E924C52C0DD33858356B73E6200144D281B85BC320F41FAF2。bcc32编译后SHA保持原始值，可疑进程后续复查未重启；系统文件及启动项未清理，异机验证未进行。
- 后续使用启动工作台.cmd：设置项目相对CRAFT_HOME及S100_HOME。完整分发保留启动脚本、MCU_Workbench_App和toolchains。最新交接.Codex/handoffs/2026-09-17-s100-repair.html。

## 编译 warning 折叠（2026-09-17，已安装）
- gui/compiler.js仅在显示层对warning按去除已识别文件行号前缀后的完整消息+原因+建议分组；保留警告代码和正文，不合并error。多项默认一张卡片，标次数，原生details展开全部位置和原文；原始诊断与日志不改。
- tests/compiler_ui_contract.cjs新增多文件/行号相同警告折叠、不同警告/错误隔离、默认关闭、原文保留及不修改诊断断言，RED→GREEN。node --check及UI契约通过；未跑真实浏览器、Python或厂商编译（纯显示调整）。
- 已同步MCU_Workbench_App/_internal/gui/compiler.js，281模块/11资源一致。旧JS备份.scratch/compiler-warning-fold/compiler.before.js。本轮2个源码/测试文件，无子代理。重开工作台载入新资源。

## 编译模式选择（2026-09-17，开发中）
- S100厂商实测：-pp与-g需已编译工程，-pn编PAT+TIM，-pno需在-de之后指定-fprogram/<名>.pn清单。单独-pno或后置-de会报Unknown并可能弹窗；已在隔离副本找到正确语法并验证零错误。仅PRG更新PG/dll而非GSW。
- gui/compiler_runner.py新增两平台模式表、按模式执行与新产物检查；compiler_workspace.py校验每任务模式、持久化，局部基于本任务lastSuccessfulRun副本，全部仍从上传源开始，失败不替换成功基线。
- gui/compiler.js/html新增每任务模式下拉及本次结果模式说明，保留warning折叠。tests/test_compiler_workspace.py及compiler_ui_contract.cjs新增RED→GREEN模式/复用/旧产物防误判测试。当前6个源码/测试文件；真实九模式队列正在验证，尚未安装。
- 只读子代理chroma_modes（Terra）核对Chroma DEC/PAT/PLN命令及原成功日志，不编辑文件。主代理拥有所有修改。证据.scratch/compiler-modes/。

## 两平台编译模式完成（2026-09-17，已安装）
- 覆盖上条开发中状态。S100全部/PRJ+PRG/仅PRG/PAT+TIM/仅PAT；Chroma全部/仅DEC/仅PAT/仅PLN。每任务下拉，start携带modes映射；后端原子校验平台兼容性并持久化，本次结果注明模式。局部仅证明所选阶段，ZIP含沿用依赖，失败不更新lastSuccessfulRun。
- 真实工作台上传与队列9/9通过：S100 all15.344s、prj_prg2.203s、prg2.360s、pat_tim13.297s、pat13.328s；Chroma all38.625s、dec3.000s、pat42.485s、pln7.625s。不可把时间当稳定性能基准。证据.scratch/compiler-modes/real-results.json及各模式日志、real-jobs。
- 16项pytest（test_compiler_workspace/test_compiler_http/test_s100_compiler）通过；Node语法/编译UI契约通过；gui/compiler_smoke.py新增模式下拉/每任务提交检查，实际EXE/WebView共8项通过。按用户既有选择未跑全仓、未做异机/机台验收。
- 已重打包安装MCU_Workbench_App，前后281模块/11资源一致。旧包.scratch/compiler-modes/previous-package。本轮8个源码/测试/说明文件（runner、workspace、compiler.js/html、两测试、compiler_smoke、README）；地图/交接另计。只读Chroma子代理无编辑冲突。S100初次-pno错误探测出现弹窗，最终正确命令已真实通过；无重试中的异常模式残留进程。
- 最新交接.Codex/handoffs/2026-09-17-compiler-modes.html。旧版已完成任务没有lastSuccessfulRun记录，局部模式前建议先全部编译一次；新任务各模式支持成功副本续用。

## 编译模式移到顶部（2026-09-17，进行中）
- 用户截图要求统一选择：gui/compiler.js/html移除任务卡片下拉，顶部S100/Chroma各一处选择；modeChoices按平台保存于页面，单个/批量start映射到所选任务，刷新保留，忙时禁用。工具链路径说明下移，结果历史模式仍保留。
- tests/compiler_ui_contract.cjs RED→GREEN覆盖无卡片下拉、顶部选择、刷新保留、混合队列同平台统一；Node语法通过。gui/compiler_smoke.py与README相应更新。本轮5个源码/测试/说明文件，正在重打包验收，未改后端或编译参数。
- 顶部统一模式候选包已完成8项真实EXE验收，281模块/11资源一致。用户安装版进程PID29788仍在运行，已请求用户退出，等待替换；候选.scratch/compiler-feature/package/dist/MCU_Workbench_App，验收.scratch/compiler-toolbar-modes/desktop-smoke.json。尚未安装。
- 用户确认退出后，顶部统一模式版已替换MCU_Workbench_App，安装后281模块/11资源一致；旧包.scratch/compiler-toolbar-modes/previous-package。覆盖上述等待安装状态。本轮无后端更改，未重跑Python或九模式厂商编译；前端契约及实际EXE8项验证通过。

## 桌面下载无反应修复（2026-09-17，进行中）
- gui/desktop.py在webview.start前设置ALLOW_DOWNLOADS=True。根因本地pywebview/edgechromium.on_download_starting默认Cancel=True，故有ZIP但点击无保存窗口；不是压缩失败。
- tests/test_gui_desktop.py新增默认禁用下载回归RED→GREEN；gui/compiler_smoke.py扩展真实按钮→WebView下载事件→保存ZIP逐字节一致验收，仅原生保存位置由替身自动选择。初次CLR属性不可写导致测试装置失败，改用模块WinForms代理后，修复前真实下载超时，修复后通过。
- 桌面/编译工作区/HTTP专项16通过；当前3个源码/测试文件。正在重打包，证据.scratch/compiler-download-fix/。未更改ZIP内容或编译过程。
- 下载修复候选包已完成真实EXE9项验收（含按钮触发保存完整ZIP，逐字节一致），281模块/11资源一致。当前用户安装版PID16468仍运行，已请求退出，等待替换；候选.scratch/compiler-feature/package/dist/MCU_Workbench_App，证据.scratch/compiler-download-fix/packaged/report.json。尚未安装。
- 用户确认退出后下载修复包已安装到MCU_Workbench_App，安装后281模块/11资源一致。旧包.scratch/compiler-download-fix/previous-package。覆盖上述待安装状态；点击编译输出现在允许WebView原生保存ZIP，既有成功任务无需重编译。验证：16项Python专项、实际桌面9项含ZIP保存字节一致；未跑全仓或重新运行九模式厂商验证。

## 编译清空历史列表（2026-09-17，进行中）
- 用户明确选择仅清空历史列表保留磁盘文件。gui/compiler_workspace.clear_history在无上传/排队/运行任务及活动worker时，将task.json写archived并移出内存；重启跳过archived，不删除source/run/log/ZIP。server.py增加鉴权POST /api/compiler/clear。
- gui/compiler.html/js顶部清空列表按钮，上传/编译/提交期间禁用，成功清除选中/勾选/详情日志并刷新，新任务正常出现。前端失败保留列表并显示错误。
- tests/test_compiler_workspace.py/test_compiler_http.py/compiler_ui_contract.cjs覆盖持久化隐藏/文件保留/忙时阻止/鉴权/详情清空；17项Python及Node契约通过，功能RED→GREEN。gui/compiler_smoke.py加入真实按钮清空及重载保留验证。本轮8个源码/测试文件，无子代理。正在重打包，尚未安装，证据.scratch/compiler-clear-history/。
- 清空历史列表版已安装，覆盖上述进行中状态。真实EXE10项验收通过（含ZIP下载和清空后文件保留/重载不恢复），安装前后281模块/11资源一致；旧包.scratch/compiler-clear-history/previous-package。用户实际历史未被自动清空，待用户点击按钮。未跑全仓或九模式厂商重编译。

## 编译文件夹拖放上传（2026-09-17，进行中）
- gui/compiler.js复用addFolder/uploadGroup上传路径；drop同步捕获目录entry，递归读取子目录并循环readEntries直到为空，保留相对路径，一次多文件夹独立任务。仅接受目录，空目录/读错误/单文件>256MiB/任务>2GiB或20000文件提示失败；读取上传期间锁定，不自动编译。
- gui/compiler.html增加整页拖放高亮与提示，原添加按钮保留。tests/compiler_ui_contract.cjs RED→GREEN覆盖多目录、分页、嵌套路径、阻止导航、单文件拒绝；Node语法/契约通过。gui/compiler_smoke.py新增模拟drop事件通过真实WebView/API建立两平台任务验收。4个源码/测试文件，无子代理，正在打包，未安装。证据.scratch/compiler-folder-drop/。
- 拖放上传版已安装，覆盖上述进行中状态。Node契约另覆盖忙时拒绝第二次拖入、读取错误后释放上传锁；实际EXE11项验收通过，含模拟目录drop事件→真实上传API→两任务/子目录内容核验。未做资源管理器鼠标实际拖放，未跑Python套件/九模式厂商编译。安装前后281模块11资源一致；旧包.scratch/compiler-folder-drop/previous-package。用户重开即可使用，原按钮保留。

## Chroma SCAN 扩展TS8～TS15（2026-09-17，进行中）
- 用户明确允许TS8至TS15共8组。program_gen/platforms/chroma/scan_writer.py将_GROUP_TS及变量映射扩展到8～15，gui/scan_conversion.py复用该范围，独立转换和旧原生生成保持一致；超8组报明确中文限制，保留按时序内容去重及按Pattern重设语义。
- tests/test_gui_scan_conversion.py新增3/8/9组公共convert_scan边界，RED→GREEN；转换及native assembly共16项+5子测试通过。用户实际iddq_bridge_1.wgl原报3组错误已复现，修改后转换成功，PAT使用TS8/TS9/TS10，产出3文件。证据.scratch/scan-ts8-15/。
- 当前3个源码/测试文件，正在验证8组厂商PAT语法及重打包，尚未安装。独立语法样例初缺Q边沿，修正样例后继续验证，不扩展其他WGL规则。
- 八组独立样例DEC/PAT厂商编译已通过（gate/results.json），覆盖TS15；真实用户3组文件转换成功。候选包281模块/11资源一致，用户安装版PID29204仍运行，已请求退出等待安装；未跑无关桌面自检或全仓测试。候选.scratch/compiler-feature/package/dist/MCU_Workbench_App。
- 用户确认退出后TS8～TS15修复已安装MCU_Workbench_App，覆盖上述待安装状态；安装后281模块11资源一致，旧包.scratch/scan-ts8-15/previous-package。原WGL未修改，重开后可重试转换。

## SCAN预览标签无效修复（2026-09-17，已安装）
- gui/workbench.js修复两层根因：结果renderKey纳入previewKind；pickPreviewFile仅保留匹配类别的当前文件，否则优先同sourceName同platform，再找该类首文件，无该类显示空提示。点击左侧文件同步类别并刷新高亮。
- tests/test_gui_workbench.cjs真实事件委托路径RED（点击code仍scan.pat）→GREEN；覆盖Pattern/code/timing往返、按钮高亮和第二WGL切换到其对应片段。Node语法及公共/交互契约通过，未跑真实浏览器/Python/厂商编译。
- 仅更新安装版_internal/gui/workbench.js，281模块11资源一致。旧JS.scratch/scan-preview-tabs/workbench.before.js；2个源码/测试文件，无子代理。重开工作台加载新JS，转换结果无需重新生成。


## SCAN 手动筛选管脚与紧凑布局（2026-09-17，进行中）
- gui/scan_conversion.py::read_wgl_pins复用WGLParser的signal解析，不展开向量；manual_pin_orders按每文件原信号顺序过滤，convert_scan(manual_pins=...)复用既有向量/时序/异步时钟筛选。手动与Excel互斥，拒绝空选择、未知/重复管脚、归一化重名及任一文件零管脚。
- gui/scan_workspace.py::pins + server.py POST /api/scan/pins提供已导入WGL管脚并集及各文件列表；start冻结manualPins，按冻结WGL重验，改变选择不自动覆盖旧关联。
- 前端workbench三资产与tests/test_gui_workbench.cjs由manual_pins_ui代理独立修改，主线负责后端/测试/集成。布局取消左右等高、上传区紧凑，左侧管脚选择独立于Excel。
- 转换新测试及HTTP新接口均RED→GREEN；实际用户iddq_bridge_1.wgl 61→16管脚双平台转换及全部Chroma向量宽度检查通过；最小手动筛选DEC/PAT厂商编译通过。证据.scratch/manual-scan-pins/。尚未完成前端集成/打包安装。

- 前端最终实现：左侧输入区下方显示管脚搜索/全选/清空，自适应多列；右侧手动开关与Excel互斥。平台checkbox仅data-platform参与；读取期间关闭手动或改用Excel会取消旧响应，按输入ID/SHA重读，既有勾选保留。
- 本轮共9个源码/测试文件（主线5、前端代理4，无重叠），Python专项23通过+10子测试；Node公共/交互契约及语法通过；最终源码真实WebView2十项通过，含无Excel上传、默认全选、空选择禁用、实际转换、快照、三个预览标签。未跑全仓、S100厂商门禁或硬件；S100双平台转换及向量列测试通过，Chroma DEC/PAT门禁通过。最终候选包构建中。

- 已完成安装，覆盖本节待构建状态：MCU_Workbench_App为最终新版，安装后281模块/11资源与源码一致；新EXE独立compiler自检11项通过。用户窗口未运行，直接备份安装；旧版.scratch/manual-scan-pins/previous-package。未修改源WGL及用户运行资料。代理仅UI四文件，无重叠修改；修复过异步取消及source枚举集成问题，最终所有专项门禁通过。未测量token用量。


## SCAN NRST误删与原始Label复用（2026-09-17，已安装）
- 最新真实任务9b0db96b2f7025b76f7bfbb279339948的CP3 PIN DEC含PD11，VERSION指定NRST PIN=PD11；旧_selected_pins仅WGL端改名NRST而Excel侧仍PD11导致误删。gui/scan_conversion.py统一两端别名后匹配，真实两个WGL18→19列恢复NRST，其余70397/98089行向量列逐行不变；证据.scratch/scan-nrst-fix/result.json。
- 用户追加原始Label功能：复用tools/wgl2chroma的label_marker/label_base，空值默认关闭，标记注释后的向量自动按前缀编号。新增label_options成对输入及标识符校验；S100向量后处理支持任意合法label前缀，避免漏筛选与漏替换TIMING_SET。scan_workspace冻结Label配置并避免不同配置自动刷新旧关联。前端代理仅workbench.html/js及对应cjs测试，主线拥有conversion/workspace/Python测试，无文件重叠。
- 复现测试RED→GREEN；NRST+Label组合最小Chroma DEC/PAT厂商编译通过，验证资料.scratch/scan-label-nrst。尚在前端和真实WGL联合验证，未安装。

- 本轮7个源码/测试文件（主线4、前端代理3无重叠）：Python转换/workspace/native assembly 25通过+14子测试；前端Node公共与交互契约通过；真实WebView2 17项通过（Label双空/单空/非法前缀、实际双平台筛选转换、冻结快照及预览标签）。真实两个WGL配合CP3 Excel+Label输出19列，分别200/300个连续Label，与原注释数量一致；S100带Label行也核对19列。资料.scratch/scan-label-nrst/result.json、ui/report.json。正在构建候选包，用户工作台PID36056仍运行，验证完成后需退出更新；未修改用户Excel/WGL或历史输出。

- 候选已构建并核对281模块/11静态资源，新EXE compiler冒烟11项通过。尚未安装：2026-09-17最后核对安装版PID36056仍在运行，已请求用户保存退出，待答复后将MCU_Workbench_App备份到.scratch/scan-label-nrst/previous-package，再复制.scratch/compiler-feature/package/dist/MCU_Workbench_App并运行verify_package.py。不得停止用户进程，旧错误输出需用户重新转换生成。本轮无全仓测试及S100厂商编译，未测量token用量。

- 用户确认退出后已安装，覆盖本节待安装状态：MCU_Workbench_App更新完成，安装后281模块/11静态资源一致；旧版完整备份.scratch/scan-label-nrst/previous-package。重开后可配置Label并重新转换，PD11按Excel配置保留为NRST；未改原始WGL、Excel及历史输出。


## SCAN配置紧凑布局（2026-09-17，已安装）
- 仅gui/workbench.html/css两界面资产调整：左右输入/配置约0.85:1.15，配置内部Label和Excel/管脚模式并排，平台横排，摘要与启动按钮同行；缩小标题/上传/提示间距。1100px及以下改为纵排，700px以下配置单列。业务JS/后端未改。
- Node工作台契约通过；隔离真实WebView2 20项通过，包含Label/手动管脚实际转换、三预览标签，以及模拟展开Excel详情后的配置高度497.7px、结果顶部687.2px、无水平溢出（该窗口尺寸下）。资料.scratch/scan-compact-layout/ui/report.json；不声称所有窗口尺寸视觉验收。
- 两静态资源已同步安装版，281模块/11资源与源码一致；旧资源.scratch/scan-compact-layout/previous-assets。无需停止用户窗口；重新打开加载新布局。未重建EXE、未跑后端/厂商重复测试，无子代理。


## HEX→Pattern新功能调研（2026-09-17，仅分析）
- 用户要求总结D:/Code/TEMP/HEX_TO_PAT；目录内为03_PatternConvert.zip，仅提取源文件到.scratch/hex-pat-review/source/，未执行原EXE或修改原包。88源码/项目文件、44 C#源，源SHA见inventory.json。
- FBIST Flash目录23主源，SRAM仅PT067/PT100两版（实际通过SWD），SWD Flash16主源（不含ConsoleApp1），另有PAT→SD和sector测试。PT104 FBIST进FBIST/预编程/全擦/写/读，256Byte页、TS1、PA11/PA13/NRST；PT104 SWD Flash读回循环注释、PF5第三管脚、TS2，不能与现SWD默认NRST直接等价；PTXXX主下载块注释不能当通用模板。PT061/064有S100 SD分支但未证明全型号跨平台。
- 建议独立HEX转Pattern入口，三模式+芯片/区域profile；统一HEX地址/校验解析后保留原下载流程，分平台输出；先独立队列/预览/ZIP，后接现资源槽位Link。旧解析存在固定扩展地址、按行补齐/尾字、固定路径/管脚等限制。现SWD底层和Flash产品事实可参考复用，但不是现成任意HEX下载器。
- 报告.scratch/hex-pat-review/接入分析.html。主线分析FBIST/SRAM及架构，Terra只读SWD Flash，主线复核PT104读回注释/PF5及真实PT061_sd文件；无源码修改、未运行编译/原工具/机台测试，未测量token用量。下一步需用户确定首批型号和各模式原工具基准及真实HEX样例；当前未授权具体实现范围，不自动开始实现。

## HEX→Pattern首批实现（2026-09-17，进行中，覆盖前述未授权状态）
- 用户确认首批覆盖全部提供型号，以芯片/版本选择。tools/hex_to_pattern/profiles.json 42版本，38活动下载版本、4模板/读回专项禁用；legacy中44份原C#与原包逐项SHA一致。build_workers.py将活动版本及隔离入口编译为随包携带的NET workers，客户无需安装C#编译器。
- gui/hex_conversion.py负责Intel HEX格式/长度/校验和/重叠地址校验与旧版本输入归一化，调用版本worker并核对文件/向量；当前连续地址、对齐及相对64KiB已核对范围外明确拒绝，不截断地址。gui/hex_workspace.py负责持久任务、串行队列、ZIP/预览及清空列表保留磁盘产物。
- gui/server.py增加/api/hex/*及/hex；gui/hex.html/js提供紧凑型号版本选择、多HEX选择/拖动、任务结果与ZIP。workbench.html/js增加独立入口；desktop阻止转换期间关闭，hex_smoke.py新增真实桌面验收；build_desktop包含新资产及tools资源。
- 专项8项通过（包括38个原转换内核实转）；Node HEX和工作台契约通过。目录代理Terra拥有profiles及其测试，UI代理Luna拥有hex页面及其测试，无重叠；主线负责后端/集成/最终复核。厂商语法及桌面/候选包验收进行中，未安装或硬件验证。

- HEX首批已完成安装，覆盖进行中状态：16个业务/目录/测试文件及44份不改动的原始C#。Python专项13通过（38内核实转），Node HEX/工作台契约通过。Chroma 35份PAT及DEC编译通过0错误0警告；S100 3份SD追加到完整隔离工程全部编译通过0错误22警告。验收脚本初版目录错及删旧PAT引用导致的失败仅在scratch内修正，未改生成向量绕过错误。
- 源码与打包WebView2各9项通过（上传/型号选择/批量实转/预览/原生ZIP保存/清空保留文件/无横向溢出）。安装后284应用模块、13资产、HEX源/目录/内核资源一致。未运行用户旧EXE，未做机台、异机或全仓测试；使用合成HEX，提供的原压缩包内无HEX样例。
- 安装目录MCU_Workbench_App已更新，旧版备份.scratch/hex-feature/previous-package；源码/打包smoke分别ui02/report.json和packaged/report.json，厂商证据gate/compiler.json、gate/s100-compiler.json。第一轮WebView sandbox无法启动，改为授权的隔离原生验收后通过。用户输入、工具原包及旧任务产物未改。相对64KiB连续范围限制已在界面明确。未测量token用量。

## HEX管脚映射与数据校验开关（2026-09-17，进行中）
- gui/hex_conversion.py::configured_profile校验逐列管脚名、去重和读回能力，workspace.start冻结请求pins/verify到每个任务及ZIP metadata。头部管脚映射保持向量列顺序不变；build_workers.py的隔离入口新增verify参数，仅在关闭时跳过原Read_pat，原C#文件不改。原版本无活动读回的两种可下载版本不允许强行开启。
- gui/hex.html/js增加紧凑管脚编辑和读回开关，按版本保留配置草稿；可重新转换完成任务。拖放区覆盖页面高度，保留多HEX拖入。hex_smoke.py改用真实DOM拖放并检查管脚/校验冻结和输出预览。专项RED两失败后GREEN，38版本改名及开关实转检查通过：校验关闭输出仅移除原行，没有改写保留的写入波形。
- 当前9个源码/测试文件及生成内核更新，集成/厂商/真实桌面验证中，尚未安装。测试基目录.scratch/hex-feature/options-*；不重复处理旧S100系统事件。

- HEX管脚/校验/拖放更新已安装，覆盖进行中状态：按所选原C#版本预填默认管脚，逐列编辑，恢复默认按钮仅还原管脚；不同版本各自保留页面配置草稿。两种无活动读回的原版本提示不可开启，不伪造校验能力。默认38份输出与上版逐字节一致（.scratch/hex-options/gate/baseline-check.json），36个可读回版本关闭校验仅省略原有行，全部38版本管脚映射通过。
- 本轮9个源码/测试文件、38个worker及manifest更新；原C#未改，无子代理。Python专项15通过，Node HEX/工作台契约通过；修改管脚+关闭读回的35份Chroma PAT经DEC/PAT编译通过，3份S100 SD随完整隔离工程编译通过，警告保留。证据.scratch/hex-options/gate/compiler.json与s100-compiler.json。未追加全仓或硬件/异机测试。
- 最终打包EXE原生桌面13项通过，含默认管脚、恢复默认、多HEX DOM拖放、校验关闭和任务冻结、真实ZIP保存；报告.scratch/hex-options/packaged/report.json。安装后284模块/13资产及转换内核资源一致。旧包备份.scratch/hex-options/previous-package，用户文件和历史输出未改。未测量token用量。

## 实际HEX与原工具对照（2026-09-17，完成）
- 用户新提供D:/Code/TEMP/HEX_TO_PAT/HSI_TRIM_V01_01.hex并确认PT104，要求其他版本一起测。输入11240字节/3976有效数据，连续0x08000000～0x08000F87，SHA c6ec18e3be03d2b4df031b4e06ead77a0e25a3519d8423050a5d0ffbffce2d96。
- .scratch/hex-real-compare/compare.py直接从原ZIP构建各C#原Main（只重定向目录，SRAM插值等价翻译供旧csc），原工具读取未改HEX，工作台运行默认convert_hex；38可用版本均完成。PT104三版逐字节一致；总31字节一致、2 SRAM仅名称_Sram差异、5实际波形差异。
- FBIST PT064/PT067/PT068：先补齐HEX最后8字节至16导致额外8字节FF读回，新增68行；原算法写补齐、读只按原长度。SWD PT105 Flash/Boot：原算法保留HEX高地址+0x04000000，本例0x0C000000；Python剥离高地址后变0x04000000。causes.py单项恢复及worker直接喂原HEX两组实验，5项全部恢复字节一致。不得把本PT104 HEX结果推成其他芯片实际地址正确性。
- 报告.scratch/hex-real-compare/对比报告.html，明细results.json，原/工作台输出ZIP同目录。只做对照分析，应用源码与安装包未改，上述5版本差异仍存在；后续如要求原工具严格一致，应处理输入归一化，而不是重写C#波形。未做机台/异机/全仓测试，无子代理，未测量token用量。

## HEX输出S100格式（进行中）
- 用户要求Chroma HEX版本也能导出S100 SD。gui/hex_pattern_format.py仅转换已提供引擎PAT语法：保留管脚/向量/数据比对字符/标签/注释，TSn→TIMING_SET G1_n并保留切换位置；STOP→END。RPT超过65535分段，周期总数不变；未知语法报错而非丢弃。实际PAT存在TS1/5/6切换，不能采用原PatToSd工具直接删TS的方式。
- configured_profile增加outputPlatform(chroma/s100/both)，hex_conversion按格式返回文件清单，ZIP及任务冻结沿用现有接口；原生S100版本只输出SD。hex.js/html增加输出格式选择，保留默认管脚和校验开关；SD所需周期/边沿必须由S100工程按原TS设置。
- 新格式RED后GREEN，35个Chroma版本通过向量序列、重复周期和有效时序等价测试。实际用户HEX批量导出、厂商编译、HTTP及原生桌面验证中，尚未安装。证据.scratch/hex-sd。

- HEX S100导出候选已完成，待用户退出更新：7个源码/测试文件修改；专项Python17通过，Node HEX/工作台契约通过；真实HEX对35版PAT/SD向量、总重复周期和有效时序逐段对齐，证据.scratch/hex-sd/gate/real-hex-semantic-check.json。35份SD加入隔离S100完整工程编译通过0错误22警告，s100-result.json及s100.log保留。
- 新PAT解析严格保留read_start等标签，长RPT分段。最初RED及实际源中独立标签/超长RPT暴露后补支持并GREEN；原生验收脚本selector转义错误修正，最终EXE桌面14项通过（.scratch/hex-sd/packaged/report.json），285模块13资产核对通过。未修改C#引擎、HEX归一化或原有S100原生引擎。
- 当前安装版PID10004仍运行，已请求用户保存退出。待确认且实际无该进程后，把MCU_Workbench_App备份到.scratch/hex-sd/previous-package，再复制.scratch/compiler-feature/package/dist/MCU_Workbench_App并运行verify_package.py。不得强制退出用户窗口。时序TSn→G1_n映射只保留引用，实际周期/边沿需S100工程等效配置；未做机台/异机/全仓测试，无子代理，未测量token用量。

- 2026-09-18用户确认退出后，HEX S100导出版本已安装，覆盖上述待更新状态。安装前确认无工作台进程，候选及安装后均核对285模块/13静态资产及HEX内核资源一致。旧包完整备份.scratch/hex-sd/previous-package。重新打开HEX转Pattern可选择Chroma PAT、S100 SD或PAT+SD；原生S100版本仍仅SD。此次只安装已验收候选，不重复运行已通过的厂商及专项测试，用户输入和历史产物未改。

## 程序页统一 Pattern Link（2026-09-18，开发验证中）
- gui/index.html：外部资源统一 Pattern Link，固件 download 槽增加 HEX 结果选择；SCAN/MBIST 行增加程序页关联入口，复用既有三件套装配。
- gui/hex_workspace.py::snapshot 校验所选 run、ZIP 对应输出并冻结字节；gui/swd_workspace.py 复用同 CP/资源名绑定、保存/重载/冻结机制，externalGenerations 独立保存 HEX 副本，不混入 SWD 编辑器历史。HEX 历史清空/重新生成不改变已确认的程序 Link。
- gui/server.py 增加只读 /api/pattern/state 并回挂 session.hex；现有 /api/swd/link 兼容 hexTaskId/hexRun。
- program_gen/core/swd_pattern.py 共用资源 overlay，HEX 限 Firmware download pattern，核对目标管脚。Chroma 来源 SD 在程序装配按用途映射 G1_5→G1_4（擦除）、G1_6→G1_5（编程），不改向量。program_gen/platform_program/s100.py 允许消费既有 G1_2 定义。
- tests/test_hex_link.py 覆盖冻结版本、清空/保存/重载、产物修改、平台缺失、错误槽位、管脚及用途时序映射；前端契约与 desktop_smoke 文案同步。实际 PT104 双平台工程/厂商门禁及打包验收进行中，尚未安装。
- 补充验收：gui/pattern_link_smoke.py 由 desktop_smoke 调用，真实 WebView 验证 HEX 选择/副本冻结/清空历史/查看/解除和 SCAN 程序页入口；源码窗口 7 项通过。SCAN 两个 POST 遵循服务 guard 顺序执行。
- PT104 实际 HSI_TRIM_V01_01.hex 经 fbist-pt104-flash 转换并 Link 至 CP3 Download_Code / Intergration_V01_05；.scratch/pattern-link/gate/programs2 双平台完整生成，PAT 字节只改声明，SD 只改用途对应时序，Chroma DEC/PAT/PLN、S100 全编译均通过并生成 921316 字节 GSW。日志/result.json 同目录 gate 下。
- SWD/HEX 生命周期与 HTTP 集成 21 PASS；HEX/SCAN 装配专项 21 PASS +2 子测试；前端 146/146、工作台契约通过。扩大平台骨架检查出现 5 个失败（含子测试），均为旧注释/排版断言；baseline_check.py 在进程内恢复本轮修改前的 s100.py 时序逻辑，复现完全相同失败，未改旧行为。未跑全仓。候选 EXE 打包验收进行中。
- 最终完成：源码与打包 EXE 完整桌面自检均 47/47（full-source/report.json、packaged-final/report.json，后者 frozen=true）。更新历史自检的 SWD 缓存按钮及位字段定位以匹配现有界面；首次候选包自检缺少工作资料路径与旧定位的失败报告保留为历史，不能作为最终结果。
- 已确认无运行工作台并更新 MCU_Workbench_App，旧安装备份 .scratch/pattern-link/previous-package；安装包再次验证 286 模块、13 资产及 HEX 原始工具资源一致。原启动工作台.cmd 可用。验收说明 .scratch/pattern-link/report.html；未进行硬件上机。

## Pattern Link 顶部统一入口（2026-09-18，待验收安装）
- 用户要求全部 Pattern Link 从关联预览顶部一个按钮进入，按当前 typed 场景分流。gui/index.html 移除资源折叠卡片内各名称按钮及分散 SCAN/Pattern 映射入口，新增顶部 sticky Pattern Link；SCAN/MBIST→SCAN 弹窗、外部槽→同一弹窗选择本行各资源（download 可选 HEX）、无外部槽的 TRIM/VERIFY→原 Pattern 映射。外部关联弹窗仍可进入映射，非 download 隐藏 HEX 工具入口。
- 后端绑定/生成与工具算法未改。tests/test_gui_ui.cjs 先 RED（缺少统一入口）后 146/146 GREEN；gui/desktop_smoke.py 与 pattern_link_smoke.py 更新入口定位，真实窗口与候选包校验进行中。证据 .scratch/link-entry。
- 顶部入口已验收待退出安装：Node146/146（含真实按钮触发 TRIM 映射）、隔离WebView7项（同一顶部按钮进入HEX/SCAN并保存/查看/解除）、候选286模块/13资产一致。源码变动只限 index.html、两份桌面自检定位和test_gui_ui.cjs；未改编译/绑定内核，不重复跑厂商编译。
- 当前安装PID22988仍运行，已请求用户保存退出。退出后确认无进程，将安装目录移至 .scratch/link-entry/previous-package，再复制 .scratch/compiler-feature/package/dist/MCU_Workbench_App 并执行 .scratch/compiler-feature/verify_package.py。不得强制关闭。测试/构建证据 .scratch/link-entry/ui/report.json、final.log、build.log。
- 2026-09-18用户确认退出后，顶部统一 Pattern Link 版本已安装，覆盖上述待更新状态。安装前确认无工作台进程；候选与安装后均核对286模块/13资产及HEX工具资源一致。旧版备份.scratch/link-entry/previous-package，原启动工作台.cmd继续使用。未重复已通过的专项/厂商检查，未改用户输入与历史产物。

## Pattern 资源交互方案（2026-09-18，等待用户选型）
- 用户要求先看方案和示例再加入工作台。正式试改已撤回，安装包核对286模块/13资产仍与源码一致；本轮不更新安装包。
- 独立原型 .scratch/pattern-cards/prototype.html：A右侧资源卡片/B集中关联清单/C资源详情工作区，?variant=A/B/C；FBIST跳表、SWD/HEX/SCAN选择/更换/解除均为内存演示，不请求业务API。页面“查看完整方案”包含分类、工具往返和验收范围。可直接双击HTML，或 python -m http.server 8877 --bind 127.0.0.1 --directory .scratch/pattern-cards。
- 来源盘点：FBIST/PUMP已有真实pattern来源行；Flash compare可追溯NM_pattern；Flash页/UID来自ADDR_MAP多行；外部资源引用坐标不能当成波形配置来源。SWD源变更失效与HEX冻结副本版本须区别呈现。
- 已在浏览器验证HEX选择→确认→卡片显示固件/型号/版本，截图检查布局；原型不运行编译或全仓测试。domain terra只读盘点，无代理文件修改或重叠；未测量token用量。待用户确认方案后才实现生产功能。

## Pattern 卡片 A（2026-09-18，用户选定，实施验证中）
- 用户已选择A并授权加入正式工作台；gui/index.html 改单列资源卡+下方配置，FBIST generated 卡复用真实locations直接跳表，外部卡查询当前Excel绑定及SWD/HEX来源，结果选择器支持分类/搜索/显式更换解除。没有来源的生成项不允许外部Link。
- gui/workbench.js 增加生成工具返回提示，保留原程序/行/资源上下文，返回时核对身份再选择结果；不自动关联。后端pattern_state只读扩展由card_state代理处理，允许文件swd_workspace.py/test_hex_link.py；主线独占前端及前端测试，无重叠。
- 原型仅供设计参考。Node专项先RED（145/147）后148/148；workbench public/interaction契约通过。待真实WebView及打包验证。用户要求只做专项与实际界面验证，不跑全仓。
- A方案已完成并安装：源码/测试共6文件（index.html、workbench.js、swd_workspace.py、pattern_link_smoke.py、test_gui_ui.cjs、test_hex_link.py）。前端148/148；工作台public/interaction契约通过；HEX/SWD/来源联合检查26通过1失败。失败为RealTrimLinkTests中重新构造pattern_links与session.links的DAC output槽不同，baseline.py恢复本轮前pattern_state仍复现同一差异，未改无关来源逻辑。
- 源码真实WebView13项通过（source-report.json）；打包EXE53项通过且frozen=true（packaged/report.json），含FBIST整卡跳表、HEX搜索/冻结/历史清空/更换解除、生成工具往返保留目标与不自动替换、SCAN三件套入口、双平台完整程序计划及母本SHA不变。浏览器实际页面截图确认右侧单列卡片布局。
- 首次源码WebView受启动环境限制失败，提权重试通过；首次候选测试缺外部工作资料路径，核实并仅停止该测试进程，指定MCU_WORKBENCH_WORKSPACE后通过。初次使用不存在的workbench测试文件名已改用test_gui_workbench.cjs。记录失败不作为通过证据。
- 安装前再次确认无MCU_Workbench_App进程，旧包移至.scratch/pattern-cards/previous-package，候选复制至MCU_Workbench_App；安装后286模块13资产校验通过。继续使用原启动工作台.cmd。没有更改转换算法、生成器与编译器，本轮未重跑厂商编译/硬件/异机；按用户选择未跑全仓。代理仅后端2文件无重叠，token未测量。

## A方案入口与存储映射修正（2026-09-18，验证中）
- 用户反馈顶部Pattern Link与卡片重复且占用存储映射位置。index.html删除通用顶部入口及分流函数；普通TRIM/VERIFY在资源区保留明确的编辑Pattern映射按钮，SWD/HEX/SCAN从卡片进入。
- 存储映射从测试配置折叠中提取为Pattern卡片上方独立section，支持尚无映射的普通测试项直接设置；其他测试配置仍在下方。test_gui_ui.cjs RED146/148→GREEN148/148；desktop_smoke.py与pattern_link_smoke.py改用直接卡片并加入布局断言。
- 本轮仅上述4文件，待桌面/候选验证后更新安装；沿用用户指定专项和实际界面范围，不跑全仓。
- 用户补充点击LSI_IWDG资源卡仍进入旧TRIM/VERIFY映射。发现canMapPattern只按原始type=verify判定及openSwdLink无目标时错误回退；改按当前typed kind/专用标记判断，未编译草稿仅允许普通fbist，外部资源缺失不再进入旧映射。新增HEX/SWD/SCAN/MBIST入口回归RED148/149→GREEN149/149。
- 按用户明确的CP1 LSI_IWDG_Test真实卡片验证，目标LSI_IWDG_V01_00正确，HEX/SWD选择器打开且旧弹窗未打开；源码桌面16项通过（lsi-source-report.json）。已打包前一次候选，最终加入LSI专用回归后重建并验收中，尚未替换上轮A安装。
- 最终候选lsi-packaged/report.json：56/56通过、frozen=true；安装前核实无工作台进程，已备份上轮A包至.scratch/pattern-cards/before-storage-fix并安装修正版，286模块/13资产再次一致。覆盖上述待验证/待安装状态。LSI_IWDG资源卡实测进入正确目标选择器；普通Pattern映射只用于普通FBIST。未改存储模型、转换或编译器算法，未跑全仓/机台，未用子代理。

## Pattern Link 对齐与 SWD 步骤关联（2026-09-18，开发中，未安装）
- 用户纠正：FBIST卡片应先选Link，SWD候选应以Pattern名称显示；SWD须关联步骤定义，在生成完整程序时自动生成，不要求预先生成产物。此要求覆盖旧A方案FBIST跳表与SWD结果选择描述。
- index.html新增与原型一致的紧凑选择器；FBIST选择/确认/取消/一次撤销真实WebView通过，编辑源表保留次要入口。SWD选择已保存步骤，程序卡片显示自动生成，目标名预填新建步骤、准确定位编辑来源；workbench.js与swd.js桥接程序上下文。
- 后端swd_workspace.py由独立swd_source_binding代理独占，扩展swdSource定义引用与freeze按需生成；主线独占前端和pattern_link_smoke.py/test_gui_ui.cjs，无文件重叠。兼容既有HEX冻结版本与SWD历史关联。
- 初步Node150/150，工作台与SWD契约通过；新的SWD端到端及厂商门禁待执行。尚未打包安装；当前安装版仍为before-storage-fix之后修正版。证据.scratch/pattern-cards/source-*。
- 本轮7个源码/测试文件：index.html、workbench.js、swd.js、pattern_link_smoke.py、test_gui_ui.cjs、swd_workspace.py、test_swd_source_link.py。SWD source绑定保存会使检查失效；freeze纯内存读取当前已保存步骤/config生成双平台bytes，不创建历史产物；旧HEX/generation绑定兼容，同CP共享冲突双向验证。
- 主线集成22/22通过（source-integration.log）；Node150/150与工作台/SWD交互契约通过。真实WebView来源标题、定位编辑器、确认仅保存步骤、按需双平台bytes以及FBIST选择确认/取消/撤销通过（source-native-report.json）。截图source-visual/{fbist,swd}.png核对布局；首次截图因专用Python没有PIL失败，改用现有Python312截图，后续完整通过，未新增依赖。
- .scratch/pattern-cards/source-gate：CP3 PT104_SWD_ADC1链接不同名称source_adc_steps，无generation历史即可装配；目标PAT/SD与冻结内容字节对齐。Chroma DEC/PAT/PLN与S100全编译通过，日志与result.json保留；非机台验证。
- 候选286模块13资产一致，source-packaged/report.json桌面验收进行中。安装PID4356仍运行，尚未询问退出、未更新安装。按用户范围未跑全仓。代理仅后端两文件，无重叠，审阅修正link检查失效与空ID分支；token未测量。
- 最终source-packaged/report.json：66/66、passed=true、frozen=true，含SWD来源名称/定位编辑/确认仅绑定/按需波形、FBIST确认取消撤销、HEX兼容及SCAN入口。原工作台PID4356已自行退出；候选自检退出后再次确认无工作台进程，旧安装备份.scratch/pattern-cards/before-source-links，已替换MCU_Workbench_App，安装后286模块13资产核对一致。覆盖上述开发/待安装状态。继续使用原启动入口。

## SWD 同组第二行卡片修复（2026-09-18，待打包验收）
- 用户截图CP3 Adc_Test ADC2 FLOW198卡片报引用变化。真实母本adc_repro.py复现：后台target按CP/item/phase/role/names去重，四资源只保留首行197，前端错误按当前行198精确匹配。
- index.html::patternTargetMatches按当前typed链接的CP/item/资源名匹配，不改变后台target ID/绑定/生成；openSwdLink正常和失效绑定入口共用。不会跨CP/item或忽略已删除名称。
- 本轮3文件index.html、test_gui_ui.cjs、pattern_link_smoke.py。Node RED后151/151 GREEN；真实WebView FLOW197/198各四卡全部可打开且目标名正确（adc-native-report.json），原FBIST/HEX/SWD/SCAN验收仍通过。测试初次夹具未设置linkRow导致假失败，修正夹具后通过。
- 尚未安装，候选adc-build.log构建中。未改生成/厂商编译算法，本轮不重跑厂商编译与全仓，沿用用户专项/实际界面范围。无代理，token未测量。
- 最终adc-packaged/report.json：74/74通过、frozen=true，包含ADC FLOW197/198各四资源卡打开、原SWD步骤关联与FBIST/HEX/SCAN回归。候选286模块13资产一致。修复已就绪，待当前工作台退出安装；旧包应备份.scratch/pattern-cards/before-adc-row-fix，不覆盖已有备份。候选仍在.scratch/compiler-feature/package/dist/MCU_Workbench_App。尚未安装。
- 用户确认退出后，ADC同组第二行卡片修复已安装，覆盖上述待安装状态。安装前确认无工作台进程；旧版完整备份.scratch/pattern-cards/before-adc-row-fix；候选与安装后均核对286模块13资产一致。继续使用原启动入口，本轮仅安装已通过74项桌面验收的候选，未重复专项/厂商测试，未改用户数据。
- 交接文档：.Codex/handoffs/2026-09-18-pattern-link-swd-handoff.html，汇总最新安装结论、SWD来源语义、ADC同组行匹配根因、代码入口、验证/备份及建议技能；系统TEMP另存同名副本。当前没有待实施或待安装任务，等待用户下一需求。

## 关联预览执行顺序条移除（2026-09-20，源码完成，待退出同步）
- 用户要求删除截图红框执行顺序按钮条。gui/index.html 移除顺序条、点击高亮处理及专属样式/提示；保留存储映射、Pattern资源和测试配置，后端步骤与程序生成未改。
- tests/test_gui_ui.cjs 更新既有布局检查：有阶段数据时也不显示顺序条，并验证资源与配置保留。RED 150/151 → GREEN 151/151，node tests/test_gui_workbench.cjs public/interaction均通过；未做真实桌面或全仓验证。
- 安装资产是 MCU_Workbench_App/_internal/gui/index.html，可以只备份并同步此HTML，无需重打包。同步前进程检查发现工作台已运行，已中止，安装文件未改；等待用户退出，之后重新检查进程、备份旧HTML、复制gui/index.html并核对SHA256。历史候选构建目录尚未同步，不要以旧候选覆盖本次页面。
- 2026-09-20 用户确认退出后，已完成安装HTML同步，覆盖上述待同步状态。检测到旧进程16636（启动于9月18日、MainWindowHandle=0），未强制停止；仅备份并替换独立HTML资产，文件复制成功。备份 .scratch/before-sequence-removal-20260920-102455.html 与替换前文件哈希一致；安装index.html与源码SHA256均为AC724D486743A89647B7BECA67642D3484A884F4739F39424BE550D6031FB6E5，确认不含link-sequence/highlightLinkStage。重新启动原入口加载新页面；未重复专项测试或运行真实桌面验收。历史候选包仍未同步，不可覆盖当前安装HTML。

## Link 来源名称作为程序引用（2026-09-20，实施中）
- 用户明确要求确认Link后以来源Pattern名为准，程序和Excel同步更新。HEX更新原固件引用格；SWD经用户最新意见改用xlsx内嵌mcu/pattern-links.json，不新增可见工作表或外置sidecar。
- 主线负责gui/swd_workspace.py、Link草稿应用/保存链路及端到端测试tests/test_pattern_link_names.py；link_sheet代理独占core/pattern_links.py、workbook_editor.py、test_pattern_link_sheet.py；swd_names代理独占typed名称投影/WorkbookReader/ProductCompilation/native_target/ADC双平台renderer/specialized_links及test_pattern_link_names_render.py。不得互改文件。
- 验收关注确认后Excel、Link、程序名一致，取消不改，保存重载保持，同CP冲突拒绝，双平台真实编译。当前仅开始RED测试，尚未安装。
- 实现已整合，27个源码/测试文件（不计地图/验收脚本）。已改用xlsx内嵌JSON，未增加可见工作表。adoptSourceName确认路径在gui/pattern_link_selection.py写回固件FLOW.step或patternLinks草稿并重建目标，SwdWorkspace迁移共享绑定/冲突校验；未确认/异常不提交新绑定。旧API与历史绑定保持兼容，新界面显式采用来源名。
- patternLinks经WorkbookEditor.apply、全部现有草稿/保存/预览边界、WorkbookReader/ProductCompilation进入native_target计划投影；ADC/DC/FREQ/OPA/DAC/VIHVIL明确typed Pattern字段及DAC渲染时动态output名同步，不替换成品文本。普通Recipe/协议资源的异名选择明确拒绝，应编辑相应Recipe；不冒充专用SWD名字覆盖。
- 证据.scratch/link-source-names：整合pytest 32通过（integration.log），最后改名/重载/缓存3通过（final-names.log）；前端152/152、workbench public/interaction通过。同草稿targets复用解析缓存，RED2次→GREEN1次。两平台实际新名ADC_Source_V03/Firmware_V03输出及Chroma DEC/PAT/PLN、S100全编译通过（chroma-result.json/s100-result.json）；S100须按启动脚本设S100_HOME=项目toolchains/s100，bcc32 SHA仍791E3C...18CED。
- 中间失败：pytest默认TEMP无权限改为项目内basetemp；源码WebView沙箱窗口无法启动，隔离原生验收之后被新增未保存草稿确认框阻塞（已仅停止本任务测试进程并修正测试确认）；S100第一次目录错误/PRG而非PRJ参数错误/沙箱子进程阻塞，最终正确目录与PRJ在原生环境通过。并发编辑时旧DacTestPlan配新renderer的失败已用新进程消除，不作为通过证据。
- 最终候选构建完成，289模块13资产核对一致；安装包真实桌面验收进行中，尚未替换安装。安装前仍须确认无用户工作台进程并备份；保留之前已删除执行顺序条的改动。源码包含Link确认finally重新renderLinks，恢复卡片可点击。
- 最终完成并安装：.scratch/link-source-names/packaged/report.json 79项真实打包桌面检查通过，passed=true、frozen=true，涵盖HEX名称写回、SWD草稿JSON、取消无修改、再次打开、解除保留名称、FBIST/SCAN及母本字节不变。最终3项名称/保存重载/缓存复验通过；原源窗口中止记录不作为通过证据。
- 确认无工作台进程后，旧MCU_Workbench_App完整移至.scratch/link-source-names/before-name-authority，最终候选已安装；安装后289模块/13资产核对一致。原启动工作台.cmd继续使用。旧Link不会自动改名，重新确认后采用新规则；确认先改草稿，保存/另存Excel才落盘，母本原文件不自动覆盖。
- 普通Recipe/内置协议资源的异名Link明确拒绝（不属于专用SWD名称覆盖）；内部JSON保存名称映射，SWD步骤/HEX冻结内容仍沿用原工作空间存储。未做硬件上机/异机/全仓测试。两代理分工无源文件重叠；DAC动态output最初只读判断有误，主线检查实际renderer后要求修正并加入双平台测试。使用量工具显示当时账户周额度已用74%，不是本任务token统计，未声明节省量。
- 新交接 .Codex/handoffs/2026-09-20-link-source-names.html；当前无待安装任务。

## Link 响应优化与弹窗载入 SWD Excel（2026-09-20，进行中）
- 实测纯 SWD 首次改名13.809秒，相同关联0.040秒；耗时来自改名后WorkbookReader、WorkbookEditor与ProductCompiler重建。主线负责swd_workspace.py、pattern_link_selection.py与名称集成测试；link_import_ui独占index.html/test_gui_ui.cjs/pattern_link_smoke.py。目标为纯名称Link不重算整本且快速预览与完整重算一致；弹窗直接上传步骤Excel并按文件选择Pattern，导入不自动确认。尚未安装。
- 后端实现：Session保留base_compilation；SwdWorkspace按已验证草稿字节缓存预览，名称变化复用明确资源投影，固件只替换DownloadPhase后复用原_firmware呈现。其他内容修改仍走完整编译。pattern_link_selection读取草稿覆盖/行顺序定位HEX原单元格，原WorkbookEditor.apply校验保留。新增时间预算与快速/完整预览相等的差分测试。
- RED首次SWD13.634秒；GREEN实测SWD0.3661秒、HEX0.5994秒（.scratch/link-speed/timings.json）。名称/source/HEX组合13项通过（.scratch/link-speed-final.log），含连续关联、撤销/重做、版本拒绝、保存重载及生成内容。新增修改gui/server.py一行保存base_compilation，界面代理尚在执行；未安装。
- 最终基线缓存缩小为Session.base_firmware_plans（只保留固件阶段计划，不额外保留整份编译）；HEX/缓存2项复验通过（.scratch/link-speed/narrow.log）。本轮7个源码/测试文件：server.py、swd_workspace.py、pattern_link_selection.py、test_pattern_link_names.py，以及前端代理3文件。前端初步153/153，主线审阅发现上传选择器/筛选切换/真实上传smoke需完善，已退回修正，尚未打包。
- 前端主线最终接管并清理代理残留：唯一data-swd-file/input与upload-button；上传使用既有认证api，导入返回importedDocumentId定位新文档，切SWD清选择/搜索，确认期间禁用控件，导入令检查失效但不改程序草稿；SWD文档筛选不影响HEX。真实smoke通过DataTransfer/change测试坏文件再重试、筛选/取消及3秒确认预算。
- 最终Node153/153、workbench公共/交互通过；旧SWD15项兼容、导入/source17项均通过。隔离候选.scratch/link-speed/package/dist/MCU_Workbench_App构建完成，289模块13资产一致；真实桌面验收PID29260运行中。用户安装窗口PID23396仍开着，尚未替换或停止。
- 首次真实包验收已通过文件上传/坏文件重试/筛选/取消以及HEX0.75秒、固件SWD0.85秒，但ADC连续修改3.02秒超3秒预算，整体未通过（packaged/report.json）。保留原预算，增加_draft_bytes_cache：按editor身份+现有fingerprint复用已验证bytes，每次仍ensure_source_current。重复查询打包次数RED2→目标1，磁盘改变须拒绝。最终候选package-final/dist已核验289/13；13项回归与PID36292桌面复验进行中，未安装。
- 最终完成并安装：bytes-green.log最终13项通过；packaged-final/report.json为87项、passed=true/frozen=true，真实HEX1.00秒、固件SWD2.42秒、ADC SWD2.02秒，上传坏文件重试/筛选/取消/母本字节不变均通过。首次packaged报告仍是失败记录，不当通过证据。
- 用户已自行退出工作台；确认无进程后备份原安装至.scratch/link-speed/before-install，将package-final/dist候选安装到根MCU_Workbench_App，安装后289模块13资产一致。原启动入口可用，无待安装事项。未改平台生成算法、未重跑厂商/全仓/机台。新交接.Codex/handoffs/2026-09-20-link-speed-swd-import.html。代理初版3文件由主线接管修正后实际验收，无并发编辑；最终7源码/测试文件。

## 桌面工作簿另存选择位置（2026-09-20，已安装）
- 用户反馈程序页另存只能固定输出，并询问Link关联机制。已解释：名称JSON嵌xlsx，步骤/HEX来源留本机workspace.json按Excel字节SHA关联，工作台另存persist新SHA；单独拷Excel不携带完整来源。
- DesktopBridge.save_workbook通过Windows FileDialog.SAVE选目录/文件名，取消不调用保存；复用Session.save/save_draft的校验与Link指纹持久化，再原子复制完全相同bytes到所选路径，HTTP不增加任意路径写入。已加载源路径可知时禁止另存覆盖源，写入失败保留旧目标。index.html两种另存均调用桌面bridge，浏览器仍用原HTTP路径。
- 本轮5源码/测试文件：desktop.py/index.html/pattern_link_smoke.py/test_gui_save_as.py/test_gui_ui.cjs。9项单测+2子测试通过；Node155项待日志核对。桌面smoke新增指定路径/取消/内嵌JSON/来源指纹检查，通过替代picker返回值验证真实JS桥接，不冒充原生文件对话框交互已自动化。完整保存专项与隔离打包进行中，尚未安装；无代理。

- 保存专项最终14项+8子测试通过（.scratch/save-as/tests-final.log），Node155/155（ui-final.log）。初轮新增UI断言把初始lastSaved误写undefined，已按模型null修正；再次执行全部保存专项通过。桌面打包Python环境无pytest，改用项目常用系统Python运行测试。候选289模块13资产核对通过，原生隔离验收PID35144进行中；尚未安装。

- 桌面最终91项通过（packaged/report.json，passed=true/frozen=true），包含取消/指定路径/JSON/指纹的真实JS桥接。根安装用户进程16524仍运行，已请用户保存退出，未强停或替换。交接.Codex/handoffs/2026-09-20-save-as.html；退出后复查进程，备份至.scratch/save-as/before-install再复制候选并验证。

- 用户确认退出后完成安装：核实旧PID16524为无窗口残留，结束后确认无工作台进程；根安装完整备份至.scratch/save-as/before-install，验收候选已复制到MCU_Workbench_App。安装后289模块13资产核验通过，原启动入口可用，无待安装事项；对应save-as交接已更新。

## AI 助手第一版方案评审（2026-09-21，未实施）
- 用户明确独立窗口、不控制硬件；核心产出SWD配置流程Excel，同时辅助工程问答、检查解释、已有软件功能。候选DeepSeek或Kimi K3；首批PY32F420/PT104/PCD009。完整方案与续接：.Codex/handoffs/2026-09-21-ai-assistant-v1-plan.html。
- 结论：保留旧EncodingDB→Directive→intent→Composer主线，不能把历史失败全归模型。受控M2.7漏OSPEEDR；M3错题含EGR自清/COMP只读位的历史oracle假阴、RTC值错、I2C自纠、DMA编译/资料问题。旧地图15/17未明确模型版本，不直接标M3；没有新在线模型胜负或比例结论。
- 旧项目composer+measure前序99项离线通过；本次主线独立复现负值未拒绝、同字段矛盾合并、raw GPIO绕过保护、RO字段生成W、ADC ready phase2先于ADEN phase10等5项反例。当前生成器WAIT10us两平台RPT=-146，C_L对0位比较，兼容语义必须显式适配。均纯内存/文本，无硬件/付费API/源码或安装变更。
- 方案要求请求绑定资料版本与工程草稿快照；注意swd.js authoring.rows不在MCUSWD.state中，Session.checked共享状态需协调；复用现SWD编辑/保存/导出/Link，支持候选/差异/过期拒绝。DeepSeek与Kimi K3官方要求完整assistant推理字段回传，不能只改旧agent模型名。不要误称MiniMax历史content内think被丢。
- 两位Terra只读审查历史证据与编译正确性，主线负责整体设计/当前工程/官方协议/独立复验，无并发编辑。第三路因线程限制未启动，主线完成。方案中48例×2模型×3次、95%目标均为拟定验收，未运行；下一步先继续讨论其他部分，不开始开发、付费评测或硬件操作。

- 用户最新安排（2026-09-21）：当前仅记下方案，继续讨论其他功能；全部讨论结束后才汇总最终实施文档，用户另开session开发。ai-assistant-v1-plan.html已明确标为讨论稿；技术建议和评测指标不视为全部确认，禁止直接依此启动实施。

- 第五项权限边界已由用户确认：查询/明确要求的检查转换与独立生成直接执行；助手主动建议改工程先差异确认；用户明确指定可撤销修改可直接入草稿。超范围另确认、批次整体撤销、应用前校验基线；不自动覆盖/Link/保存。已记入讨论稿。下一项讨论API配置与运行体验，尚未定案。

- 第六项API配置与运行体验已确认：DeepSeek/Kimi可配置与手选模型，密钥本机安全存储，连接测试含工具调用；切模型仅新任务生效，不静默降级/换服务商；真实阶段、分类错误、有限重试与停止、保留中间候选但不伪成功。已记入讨论稿；下一项讨论会话保存与工程隔离。

- 第七项会话记录与工程隔离已确认：按任务本机保存对话/确认条件/对象/产物版本/未决问题；重开核对当前状态，重启未完成任务不自动重跑；跨工程不混事实、旧候选校验基线、另存保持关联；区分用户确认与AI推测，支持清理但无云同步。下一项讨论资料库、冲突与经验积累。

- 第八项用户明确补充：AI须告知使用者新产品导入需要哪些资料。讨论稿已记要求与建议流程：先区分已有芯片新产品/未支持芯片并识别任务，按需列已有/缺失/待核实/冲突及必需/条件/可选资料，说明用途、替代形式、缺失影响；上传后核实内容，给可做/阻断/最小补料结论。不把资料齐全当完整支持或上机验证。第八项其余规则及此流程细节仍为建议，当前无实施。

- 第九项结果交付已确认：问答/检查/修改/生成按任务给解释入口、可定位问题、差异候选、可编辑另存Excel；展示真实条件和分项验证，修改基于最新草稿并保留手工内容；Excel脱离聊天可用。生成与Link独立，确认Link改草稿、保存后写Excel；失败保留候选和下一步。下一项讨论首版验收与模型实测，指标仍为建议，当前仅设计记录。

## AI 助手 V1 实施文档（2026-09-21，方案交付，未开发）
- 用户已确认第十项分层验收、真实任务模型比较和明确支持范围原则。当前继续指令承接前述“讨论结束后生成实施文档，再另开session实施”。
- .Codex/handoffs/2026-09-21-ai-assistant-v1-plan.html已由讨论稿整合为实施文档，覆盖已确认需求、芯片/产品关系、十环节SWD、复用/必修缺口、新产品资料清单、真实工具和数据契约、窗口/草稿/权限/历史、独立Excel与本机Link区别、模型与验收、文件落点和新session起步指令。前述“非最终实施文档”状态被本节覆盖。
- 95%仍是候选质量目标，48例×2模型×3次为建议规模；确切模型、支持矩阵、短延时/轮询、PDF解析依赖与在线预算需实施阶段锁定。现有requirements仅pandas/openpyxl，不宣称已有PDF/OCR。默认build_desktop输出根安装，需隔离构建。
- 本轮仅更新实施文档与项目地图；无源代码/安装/硬件/付费模型变更。新增Terra只读复核无编辑权，与主线无文件重叠；文档结构/显示校验进行中，不替代程序测试。
- 最终只读复核已整合：chipId/productProfileId/targetPlatform分离；PatternRow逐类适配、混合比较不可擅自拆读、WAIT边界/时基、一次比较非轮询；新增AI来源JSON的版本/语义摘要/缺失降级契约。
- 文档完成：15节、18表、15导航，标签闭合/导航/必要边界文案校验通过；本地浏览器首页、资料表、接手说明显示正常。首次校验因非必要文字标记失配失败，修正检查标记后通过；不属于源码回归。仅更新本文档和地图，接手指令在文档末尾；等待用户另开session实施。

## AI 助手 V1 实施中（2026-09-21，新会话）
- 用户已授权实施，先支持范围、旧核心与确定性修复，再模型和独立窗口；保留安装与用户数据，不接硬件。最新要求最后提供API后直接真实测试，费用不作限制，目前未提供密钥，未调用模型。
- Terra domain_core 独占新增 swd_authoring/ 和 tests/assistant_core/，负责最小迁入及五类已知反例。主线负责 gui/assistant_swd.py、tests/test_assistant_swd.py、支持范围及整合；无编辑重叠。
- 适配首个整字配置→既有Excel导出/重载/向量生成测试已RED→GREEN（1 passed）；尚无平台编译、完整链路、模型或桌面验收。等待时基未核实，暂阻断等待/轮询，不改旧生成器。
- 续接 .Codex/handoffs/2026-09-21-ai-assistant-implementation.html。账户周额度初读剩余11%，非任务token统计。

- 实施进展更新：主线适配10项GREEN，新增真实COMP1/COMP2双平台Directive端到端和CLI拒绝覆盖用例，等待核心迁入完成后整合。tools/assistant_offline.py提供离线独立输出入口；不读写安装和用户workspace。
- 主线审查发现Terra最初手写6字段快照偏离迁入目标且地址错误，已明确退回；该7项toy GREEN不计验收。代理现已撤回简化核心，改为真实composer/intent/EncodingDB及包内JSON迁入，旧回归待核对。
- 账户周额度最新剩余9%，已提醒用户并续接；任务token仍未测量。在线API由用户最后提供后直接测试、费用不限，但现无密钥与在线调用。

## AI 助手实施进度（续，覆盖上文早期状态）
- 阶段A/B完成：真实旧核心和60份原始资料完整迁入，主线接管审查并补访问、越界、冲突、SWD保护、时序等修复；旧toy结果不计。tests/assistant_core + test_assistant_swd + test_swd_generator 共120通过（.scratch/assistant-v1/integration.log）。Chroma DEC/PAT/PLN通过；S100最终原生运行0错误22警告，bcc32.cfg前后字节一致（s100-native.json/log）；s100-compiler记录是早期失败，不能当通过证据。
- 阶段C/D继续：gui/assistant_tasks.py新增独立后台任务、有限工具循环、重复提交去重、取消后拒绝回包、重启中断与独立候选文件。tests/test_assistant_tasks.py先缺模块RED后5通过；目前未接HTTP/UI。资料查询/生成复用EncodingDB和assistant_swd，不具备工程修改或硬件权限。带导入资料的上下文暂拒绝生成，待实现来源核对。
- model_transport Terra仅负责gui/assistant_model.py与tests/test_assistant_model.py；主线负责任务/设置/窗口，无编辑重叠。完整推理消息只在一次运行内回放，不写可见历史。用户要求本阶段完成后统一检查，保留必要TDD专项；当前未做真实API，未修改当前安装与用户workspace。
- 模型/窗口新增落点：assistant_model.py为固定官方端点SSE与完整消息回放；assistant_settings.py为会话密钥/Windows DPAPI；assistant.html/js为独立助手、设置、历史、条件与候选下载；assistant_tasks.py为后台任务/有限工具。server.py新增认证assistant路由且不要求打开程序；desktop.py新增助手单实例窗口/主窗读取桥接/退出取消；workbench入口、index程序快照与swd.js弹窗快照。assistant_smoke.py新增独立原生验收范围，仅用假模型。
- 专项：模型10通过待主线复核重定向/usage边界；任务5、HTTP1、desktop6通过；settings本机DPAPI2通过（受限沙箱加密失败，非降级明文）。尚未统一检查或真实模型。助手生成目前仅独立候选，带导入资料上下文暂阻断；现阶段没有工程修改/应用/撤销工具，不能声称V1完成。原生双窗口验收在隔离.scratch/assistant-v1/native-workspace运行中。
- 本轮统一阶段整合168项通过（phase-c-integration.log）；SWD/workbench前端契约与程序UI155/155通过。DPAPI本机2通过另计。assistant_smoke真实双窗口13项通过（native-stage/report.json，frozen=false），含独立候选送入/整批撤销/过期拒绝。swd_workspace.stage_excel仅内存pending；保存仍走原边界。assistant_tasks.stage校验草稿/知识/文件摘要，workbench应用时再次核对快照及管脚。build_desktop增加隔离路径参数、新UI资源和领域数据，待隔离打包。未安装/真实API/全仓。额度余3%已提示，详细续接已更新。
- 本轮最终阶段结果：隔离候选package/dist已构建；packaged/report.json 13项真实EXE桌面通过、frozen=true；关键UI与领域data/schema共69文件SHA一致。docs/assistant-support.html更新真实边界。没有安装、真实模型、全仓或硬件验收；阶段C/D基础链路完成，但完整V1仍需资料来源对照、受控修改、既有工具、连续历史和在线评测。续接2026-09-21-ai-assistant-implementation.html末节覆盖尚未构建状态。

## AI助手资料对照与受控修改（继续实施）
- 新增gui/assistant_edits.py与test_assistant_edits.py：现有W且step=/的32位字面值，按已验证字段掩码修改，保留其他位/全部其他行/备注/额外列。仅普通RW字段，目标寄存器含特殊/未知访问拒绝；既有完整流程不冒称复验。弹窗草稿优先。11项RED→GREEN，合并tasks19项通过。
- assistant_tasks新增prepare_swd_edit候选/差异及stage，assistant.js显示差异确认，workbench/swd.js应用到真实弹窗或文档草稿并支持整批撤销（待真实桌面整合）；所有应用复核当前快照，禁止范围外改动。尚未改安装。
- material_reconcile Terra仅新增assistant_materials.py/test_assistant_materials.py，负责只读相关寄存器资料对照；主线处理修改候选与应用，无源文件重叠。该阶段完成后统一检查，必要TDD专项持续进行。
- 字段修改真实窗口16项通过（edit-native/report.json，frozen=false）：差异确认、原弹窗只改data、整批撤销及旧候选拒绝。旧package/dist仍为13项版本，不包含本轮修改。MaterialLibrary.state新增完整资料版本；前端仅摘要/版本，HTTP助手start注入后台权威materials，stage核对后台版本。tasks9专项通过，edits11通过；资料代理仍执行，尚未统一整合。本机账户周额度余1%，已提示并续接。

## AI 助手程序检查与会话续接（2026-09-21，源码阶段）
- gui/assistant_workbench.py：提问冻结草稿交给现有Session.check，工程SHA核对并恢复主窗checked凭据；tests/test_assistant_workbench.py覆盖取消、并发、异常与真实母本只读检查。真实检查通过但测试首次因SHA大小写断言失败，已修正测试，待复跑。
- gui/assistant_tasks.py、assistant.js/html：parentId续接，20次追问上限；同模型会话在内存保留完整工具/推理消息，重启或切模型仅注入明确标识的问答摘要；历史不存推理原文，工程/SWD对象切换要求新问题。任务专项12通过（新增2项先RED后GREEN）。
- 上阶段资料对照与编辑等整合206项通过，证据.scratch/assistant-v1/phase-d-integration.log；已有native16项源码验证，旧隔离包13项已落后当前源码，不能当新版验收。资料对照真实发现CFGR1.PPRE1位宽冲突，仍明确阻断相关交付。
- 当前用户已重置额度并要求继续；无需再次请求测试许可，按其先完成阶段再统一验证。安装和用户资料未变，API仍待最终用户提供。新只读Terra acceptance_audit审查剩余验收缺口，不编辑源文件。

- 继续实现：程序检查使用浅复制Session隔离checked，短锁只冻结editor，耗时检查在锁外；真实母本回归4项通过且输入字节不变。前端程序快照改用visibleValue，未保存值回归RED→GREEN，UI156/156。
- assistant_tasks历史清理只删除合法任务ID目录、保留其他文件，清理需用户点按钮确认；会话/HTTP14项通过。真实双窗口history-native/report.json18项通过，frozen=false。
- 新增工作台action候选：assistant_workbench准备当前HEX/SCAN参数或独立程序检查，assistant_tasks.execute需UI确认且防重复/失效；desktop/workbench桥接回原结果页。index/hex/workbench公开当前参数；SCAN.start新增默认true的refresh_associations，助手false以免自动改Link。本段尚待跨模块回归。
- 新Terra provenance_lifecycle负责assistant_swd、swd_workspace、swd.js/html及对应测试，修复PCD009身份与Excel来源失效可见性；主线不编辑其文件。只读acceptance_audit已完成审查；尝试transport_retry因线程上限未启动，由主线处理。

## AI 助手继续实现与整合结果（2026-09-21，覆盖上文待实现状态）
- assistant_workbench复用真实Session.check/generate与HEX/SCAN.start；程序检查凭据隔离，模型只准备操作卡，用户确认后execute启动，当前上下文/输入SHA复核及幂等执行。SCAN助手调用refresh_associations=False，不自动改Link。desktop.assistant_job/workbench.assistantJob返回原结果页。真实HEX/SCAN输出与Chroma完整程序生成通过，后者首次测试因输出根约束、随后Windows过长路径失败，调整测试隔离根至.scratch/ag后通过，不改生产路径规则。
- assistant_model增加连接阶段网络/5xx最多1次可取消退避；响应头/流开始后不重试，401/403/429/协议不重试，ModelConfig repr不含密钥。19项模型专项通过。assistant/test认证路由+设置按钮必须模型调用connection_probe并收到回传才算连接通过，假模型测试通过，未真实API。
- tools/assistant_eval.py及tests/fixtures/assistant-eval-v1.json冻结12例小样本；默认仅列用例，--run+显式提供环境密钥才付费，输出目录必须新建。记录模型、fixtureSHA、请求用量/时间、任务及候选；自动产物约束不是最终质量评分。3项确定性oracle通过。
- 程序快照为visibleValue、完整draft及当前生成目标；hex/workbench增加当前转换设置公开快照。231项跨模块整合通过（phase-e-integration.log），出现1条测试子进程UTF8/GBK解码warning正在修正。Node程序UI156/156，workbench/HEX契约通过。
- native actions-native/report.json记录锁竞争失败：零延迟假模型在HTTP提交仍持guard时调用工具，误报忙。新增公开RED/GREEN用例，后台工具短暂可取消等待锁，锁外执行耗时检查；actions-native-fixed/report.json真实桌面22通过，frozen=false，包括转换确认前不执行、真实HEX产物、连接测试及迟到取消。旧package/dist不代表当前源码。
- provenance_lifecycle Terra已修PCD009身份与工作区Excel来源状态，33专项及SWD契约通过；主线已读源码，追加未保存草稿来源提示和CLI测试编码边界仍由其独占。没有源文件编辑重叠。
- 全仓回归正在隔离.scratch/fw运行（input/golden/toolchains为读取原资料的junction，所有输出到隔离目录；沙箱不授予原workspace写入），日志full-regression.log，退出码full-regression.exit。已见失败行，未结束，不能称全仓通过。native22后准备隔离新版包。安装、用户资料、硬件、真实API均未动。

- 最新隔离EXE已构建完成：.scratch/assistant-v1/package-final/dist/MCU_Workbench_App。packaged-final/report.json实际EXE22项通过(frozen=true)，package-final-assets.json显示78文件与源码SHA一致。没有替换安装。来源生命周期补充含未保存草稿提示和复杂Excel降级，34专项通过；CLI编解码warning已修测试。全仓1606项收集，当前约38%仍运行，已见失败，尚无完整结论。
- 真实DeepSeek已接通：用户提供deepseek-v4-pro密钥并授权直接测试，仅进程内使用，不落盘。live-connection/result.json工具往返通过；live-deepseek-12/report.json首轮12项完成，3产物约束通过、4拒绝无候选、5问答待人工评。人工发现生成/应用混淆及未知状态替代方案超出能力，assistant_tasks补明确工具边界，后续live-deepseek-verified与final重复测试进行中。
- 真实SSE发现usage位于带choices的末chunk，assistant_model以前漏计；公开RED后修复，仅非null usage或空choices进入严格解析，模型20项通过；模型/任务/评测38项通过。第一轮usage缺失不可补造。package-final已落后这两处修正，正在构建独立package-tested；全仓回归仍执行中，采样确认已推进GUI生成，不因日志缓冲误称卡死。
- 在线三轮7类共21任务：9生成/修改产物约束通过、12边界无候选；6个真实Excel经SwdWorkspace保存/导出/重载/编辑失效与逐字节向量回放通过。问答仍有局部不准确（基址/寄存器地址、WAIT单位、自动Link），不宣称整体95%。
- 收紧gui/assistant_tasks.candidate_summary：成功候选交付文字从实际工具结果生成并写入后续会话，避免模型虚称已应用/关联/上机或给原WAIT推断单位；3个公开故障先RED再GREEN，模型/任务/HTTP/评测39项通过。无候选问答仍为模型回答。package-tested EXE22项通过，但晚于其构建又加入该修复；最新package-delivery在构建，live-deepseek-delivery验证最后3个交付用例。
- 新.scratch/assistant-v1/verify-live-artifacts.py为本地验收脚本，不是产品依赖；两批roundtrip-report.json共8文件通过。当前回归进到47%，仍有失败与环境错误；未结束，不能宣称全仓通过。

- 最终package-delivery实际EXE22项通过、78资产一致，14源码及EXE摘要单独记录。48真实样本/121完成请求，另连接2请求；可观测304494 total_tokens（首轮缺失）。docs/assistant-support.html与live-evaluation.html同步；最终39专项+当前用户DPAPI2通过。全仓session72713仍运行有失败，等待完整归因；安装未替换。
- 全仓失败专项分诊：baseline-focused.log重现5失败、8通过、3 subtest通过。baseline-fixture.json只读直接openpyxl确认隔离路径解析到原用户母本，SHA256=2982c3dbe5fd53f50214618ce1bfbf6a6d4eb64393f901a3ae79d9acb7231d3d。Mr_VDDD_DC验证行有6行非旧断言2行；CP1 Vrefint已显式EXPORT、CP2 Recipe为空；C117/C121使用小写bank_en使测试大写替换无效。这5项与历史同名失败一致且由母本/断言不匹配直接解释；没有修改母本或放宽测试。全仓尚未结束，最近只读栈已推进test_pdr_trim_render，日志55%可能缓冲，不认定挂起。

## AI助手本轮收尾（2026-09-22）
- 全仓session72713/PID4580因资源压力主动中止，超过90分钟、日志82%，不是完整结果；full-regression-status.json记录系统空闲约585MB/进程私有4.3GB及中止原因。无全仓后台任务待轮询。
- 停止后单独SWD HTTP/Link/保存/预览/生成兼容性6通过（147.24秒，final-swd-compatibility.log）；最终package-delivery源码摘要未变，EXE22通过/78资产一致。Start_Assistant_Candidate.cmd使用独立trial-workspace，交互密钥未持久保存。
- docs/assistant-support.html、live-evaluation.html与handoff末节已同步：48真实样本，已验收受限链路候选，尚非正式发布；普通问答局部问题、其他全仓失败未全部归因。密钥临时副本已清除，在线进程全部退出，原安装/用户资料不动。
## AI助手发布门禁分批归因（2026-09-22，进行中）
- 用户授权开始第1项回归归因，不调用模型、不改母本、不接硬件。新增.scratch/regression-batches/run.py，本地stdlib顺序runner，每个pytest模块独立进程，collection.txt冻结收集清单，逐模块保存log/JUnit XML/JSON及results.json；600秒单模块上限，超时单列而非当通过。使用原隔离.scratch/fw只读来源junction与新的短临时目录，不清理旧证据。
- 当前runner exec session78537，runner.log显示进度，active.json定位当前模块，complete.json仅完整遍历后写入。没有产品源码改动；保留当前候选包。五项历史母本/断言差异证据沿用baseline-fixture.json，其他失败等待实际模块日志后分类。
- 分批归因证据新增：.scratch/regression-batches/summarize.py 从JUnit遍历所有failure/error子节点（不漏unittest子测试），attribution.json记录逐模块依据，report.html/summary.json为可刷新运行中报告，不代表全仓完成。source-start.json记录585源/测试摘要，input-start.json记录母本摘要。DPAPI沙箱失败已原生2项通过；registry循环导入在旧项目全新进程同样复现，先不改源码以保留首轮一致性。
- 当前分批归因续接：.Codex/handoffs/2026-09-22-regression-attribution.html；归因报告会随results刷新。已定位旧工作区路径、测试替身swd_bindings签名、links漏workbook参数等确定性测试兼容问题；首轮源码保持冻结，尚未修复。gui_flow_new_item单模块600秒超时需拆分，不能把部分PASSED当完整结果。两个Terra仅只读审查导入与links，无编辑重叠。
- 用户最新明确要求第一项回归后继续完成第二项普通问答改进，明天验收试用版。须修地址表述/超范围建议/新芯片承诺，真实模型复测并重建隔离候选；第一项结束不能直接收尾。
- 冻结首轮227模块遍历结束：coverage.json按1607节点为1492通过/41失败/31收集失败/15setup错误/21超时未验证/7跳过；first-pass-integrity.json证明585源测试无改动、母本摘要未变。现进入最小修复，新增tests/test_native_registry_import.py以全新子进程验证两种公开导入顺序与registry单例，先记录import-red.log。原始首轮日志保持不覆盖。
- 首轮后修复15个源/测试文件（repair-files.json；before/留原文）：registered_typed_kinds将baseline依赖延迟到STANDARD_TRIM调用，runtime_declarations补总体注释标题；其余13测试含新fresh-import回归、3旧路径、mock swd_bindings、links workbook参数、大小写故障注入、S100 TAB精确期望、RUN/SETVPOSP datalog契约、UID CP输入、build argv隔离、HTTP当前16表/51警告基准。原始业务Golden/母本和编号算法未改。即将逐模块补验，不宣称已通过。
- 补验发现运行时声明单元测试也固定比较完整注释文本；同步唯一新增总标题，其余声明字节断言保留，现16文件。repair-fast首轮42通过/1失败/1跳过，失败仅该标题快照；fresh registry两种顺序已GREEN。需要复跑，不把首轮快验写成全绿。
- .scratch/regression-batches/rerun.py启动修复补验：12个受影响/集成模块独立进程，再将21个new_item节点分为6/6/6/3四组，repair/保留每组log/XML/命令/hash，900秒上限；原首轮证据不覆盖。repair-fast2为43通过1环境跳过（BCB6 harness）。

- 2026-09-22续：回归修复18源码/测试文件（生产仅registry延迟导入、runtime声明标题）。补充NM_TEST完整日志块注释契约、NMLOOP只计真正执行语句及factory23页分组期望；repair-extra 36 passed/45 subtests，repair-fast2 43 passed/1 skipped。227模块首轮原始证据保留，GUI剩余复测由.scratch/regression-batches/rerun.py进行。未修改Golden/母本/编号/Trim算法。
- 第二项问答修复：assistant_tasks.factual_summary以本轮实际capabilities/lookup_field结果及initial_state错误交付确定性事实，普通其他工作流保留模型解释；lookup_field明确addressRole=register_address。tests/test_assistant_qa.py新增4项故障RED+普通回答保持用例，测试历史契约同步校验真实交付答案。真实模型复测、重新隔离打包尚待完成。
- 在线12例首轮复核发现事实模板未直接解释非法值，已补lookup_field可选value只读位宽检查；capabilities可选topic区分scope/same_chip/new_chip/safety，模型必须传入问题原值。8项问答公开反例与保持用例、任务/模型/HTTP/评测合计47通过。第二轮24个真实任务正在live-qa-final进行；package-trial曾22原生通过但已被此次改进超越，最终包使用package-trial-final，尚待验收，勿混用。
- .scratch/regression-batches/effective.py将原1607节点与修复/原生补验去重合并，输出effective.json/html，不覆盖首轮证据；当前修复后的遗留为领域母本基线26失败、环境3跳过、21个GUI节点拆组复测中，前6已通过。
- 回归阶段最终：16个修复补验分组全部完成，原21个GUI超时节点均通过。effective.json去重后1607节点=1578通过/26历史领域与母本基线失败/3跳过，无收集错误、setup错误或超时残留。input-final.json确认母本字节未变；18个回归源码/测试文件，生产改动仅2处。
- 第二项最终补充：人工复核前轮24任务发现2处轮询解释错误，未将有限自动断言24通过冒称人工全绿。capabilities增加timing主题，factual_summary明确轮询/超时/WAIT未支持，禁止降为单次比较；新公开反例RED→GREEN，锁包48专项通过。190项跨模块通过属于此前整合，集合有重叠。
- 最终包改为package-ready，packaged-ready/report.json真实EXE22通过(frozen=true)、package-ready-assets.json 78资产一致、package-ready-source.json 16输入摘要。live-qa-ready进行两轮6类（12任务）补验；旧package-trial和package-trial-final均不是最终包。试用区Windows当前用户加密API设置已保存并验证重启可读，无明文密钥。
- docs/assistant-trial.html由.scratch/assistant-v1/make-trial-report.py生成，包含启动/验收/隔离工作区/证据/残留；docs/assistant-support.html已移除过期“全仓未完成”结论，指向最新报告。启动脚本须最终指向package-ready。

## 2026-09-22 AI助手试用版交付（覆盖此前所有进行中/旧包状态）
- 两项已完成。唯一最新包package-ready-v2/dist/MCU_Workbench_App，Start_Assistant_Candidate.cmd已指向该包/独立trial-workspace；API仅该试用区DPAPI加密保存并验证重启可读。当前安装、真实workspace/母本字节不变，无硬件。
- EXE原生22项通过(frozen=true)、78资产摘要一致、16输入源码与EXE摘要核对；最后49专项通过（qa-ready-final.log），此前跨模块190通过。最终4真实字段/轮询问答通过（live-qa-lock/review.json），此前ready12为11自动+1人工表格核对通过；原自动格式失败和前轮2处轮询问题留证。字段sem_override_src现在保留未独立核实来源提示。
- 完整回归1607节点=1578通过/26已归因领域与母本基线失败/3跳过，16组补验全部结束，原21 GUI超时节点全通过。不能宣称正式发布门禁全绿；领域争议不擅改母本/Golden/编号/算法。
- 交付docs/assistant-trial.html（启动、验收步骤、准确证据与限制）、docs/assistant-support.html；HTML链接、编码和实际launcher目标已检查。最小接续为.Codex/handoffs/2026-09-22-ai-assistant-trial-delivery.html；旧包/旧进行中结论由本节覆盖。等待用户验收反馈，无自动任务。

## 2026-09-22 试用反馈：PA4 MCO生成失败（修复验证中）
- 原任务trial-workspace/.../assistant/tasks/d1a94c82e2d3a6eb656de5f8ec60b7c2/task.json，PCD009/chroma/reset已选，16次查询耗尽8轮。真实复现pa4-debug/reproduce.py同样8轮失败，trace仅保存工具调用/最终文本，不存推理或密钥。
- 根因：助手未暴露EncodingDB.pin_functions，字段搜索不含IOMUX，模型反复猜AF。另确定性完整MCO配置确实因GPIO.AFRL的AFSEL0..7复位值缺失而阻断；不能按旧Composer的零值假设导出。没有修改资料/复位值或放宽门禁。
- 最小修复3文件：assistant_tasks新增lookup_pin直接复用既有IOMUX、明确查询职责、基于实际编译诊断交付阻断；assistant_swd错误保留具体warnings；test_assistant_pin覆盖真实公共工具和完整PA4请求阻断。2项先RED，整合58项已通过（pa4-debug/green.log）。真实原请求复测after进行中；package-ready-v2尚未包含此次修复，后续需隔离重打包，不覆盖用户运行窗口。

- PA4反馈最终修复：明确INCOMPLETE_COMPILATION后立即结束，不再让模型继续查资料消耗预算；2反例RED→GREEN，停止条件另RED→GREEN，59相关测试通过。原请求真实最终第6轮准确返回GPIO.AFRL AFSEL0..7复位缺失（pa4-debug/final-live.log），无候选；未解决资料缺口，不声称PA4流程已可生成。
- 最新有效包已改为package-pin-query-final，原Start_Assistant_Candidate.cmd已切换，仍使用原隔离trial-workspace保留用户草稿/设置；原运行窗口未关闭。packaged-pin-query/report.json 22项EXE通过；pa4-debug/assets.json 78资产一致、source.json输入/EXE摘要。docs/assistant-trial.html与assistant-support.html明确PA4限制；pa4-debug/diagnosis.html记录原因/修复/证据。报告链接验证通过，生成报告脚本同步新包路径。

## 2026-09-22 用户复位补充闭环（实施中）
- 用户明确确认GPIOA.AFRL地址0x40024020完整reset全0；限定PCD009产品/py32f420/该地址，标记用户工程确认，不改包内GPIO类型数据。
- 主线assistant_tasks新增needs_input、confirm_knowledge用户入口、tasks/reset-confirmations.json持久化、原意图本地重编译；assistant.js表单/server认证路由；assistant_materials按实例读取字段。新test_assistant_knowledge先7项RED（最初temp权限setup错误后用.scratch独立基目录重跑），正在实现。
- Terra reset_domain独占encoding.py/composer.py/assistant_swd.py与新test_assistant_reset_domain.py，负责地址限定reset、结构化缺口与真实来源；主线无编辑重叠。尚未新包/真实调用成功，旧package-pin-query-final仍有效。

- 复位补充闭环完成：本轮12源码/测试文件（8主线+4领域代理），173项整合通过；追加真实字段查询/导入reset一致性反例发现代理仅写来源未更新查询值，主线补字段返回后GREEN。领域代理35项与整合有重叠，不累加。
- 新包package-reset-knowledge/dist/MCU_Workbench_App为唯一最新试用包，launcher已更新；reset-knowledge/native/report.json 25项EXE通过/frozen=true、assets.json 78资产一致、source.json记录源码及EXE摘要。
- 用户全0通过同一confirm_knowledge路径已保存到trial-workspace/outputs/gui_runs/assistant/tasks/reset-confirmations.json；新增成功任务b03fb1845a74af921849371a9e6fdff4，原失败/草稿/安装保留。独立8行Excel与PAT在reset-knowledge/configuration.xlsx及PA4_MCO_HSI8M_DIV128.pat。
- 真实DeepSeek原PA4问题8轮完成，完整7条W值/来源/Excel生命周期及逐字节向量回放通过（reset-knowledge/live）；本地8行含单次HSIRDY检查，隔离.scratch/akr-chroma DEC/PAT/PLN通过，有工具链警告，无硬件。首个外发旧context/materials方案被自动审批拒绝，已改为空context/不发送导入资料后获准测试。
- docs/assistant-trial.html与assistant-support.html、生成脚本已同步；本轮不重跑全仓，之前1578通过/26历史失败/3跳过结论不改变。后续无需再问GPIOA.AFRL值，其他地址/产品不得外推。

- 新增docs/assistant-guide.html：面向用户的实际按钮使用说明，含PA4生成步骤、折叠条件、下载/送入/保存差别、复位补充卡、已有步骤修改和常见问题；按当前assistant.html/js核对。仅文档新增，不改应用/安装。

## 2026-09-22 首页候选送入编辑器误判（修复中）
- 用户新任务c14638fd7f4329edc96c361b8b949311在home生成，context.swd为空；首次打开SWD导致整快照不等误报草稿改变。stage_context两条公开反例先RED。
- assistant_tasks.stage仅忽略page，独立新建且原SWD未加载时允许加载干净目标；实际旧草稿/编辑候选/资料/知识/文件SHA保护保留，返回当前验证快照供主窗二次核验。assistant.js点击先等待编辑器加载，desktop.assistant_context可请求打开SWD。assistant_smoke新增真实首页首次送入/撤销案例。5源测试改动，统一验证/新隔离包待完成，旧包仍在。

- 首页送入修复完成：45相关检查通过；用户实际c14638fd7f4329edc96c361b8b949311八行候选隔离回放成功，原记录不改。stage-fix/native.json首次在助手开窗超时未到送入；相同包新工作区native2.json 27项EXE通过/frozen=true，包含首页首次点击自动加载/送入/撤销及真实编辑后拒绝。
- 最新唯一包package-stage-fix，Start_Assistant_Candidate.cmd已更新；78资产一致/source摘要在stage-fix。docs/assistant-guide/trial/support同步。无真实模型调用、无硬件、无安装覆盖；用户保存旧草稿后重开新版、从历史直接使用现有候选即可。

## 2026-09-22 Kimi接入修复（进行中）
- 实测用户Kimi密钥国际models接口401、国内200仅列kimi-k2.6/kimi-k2.7-code；国内chat K3=404模型或权限不可用，另两模型200。probe/chat-probe证据在.scratch/assistant-v1/kimi-debug，无密钥/推理原文。
- assistant_model新增固定官方国内/国际地区选择与K2思考参数；settings白名单/地区持久化，旧配置保留国际默认；assistant.html/js地区和模型UI，tasks会话身份含地区。test_assistant_kimi 4项先RED后GREEN，40相关测试通过；真实工具往返与隔离包待验证。旧package-stage-fix仍为当前包，未更改现有设置。

- Kimi修复交付：6源测试文件，42项（含DPAPI）通过、27项EXE通过/frozen=true、78资产一致。最新唯一package-kimi，launcher已切换，guide/trial/support追加Kimi设置说明。未改用户设置/密钥，用户重开选Kimi+国内+kimi-k2.6。
- 真实结果：K2.6完整SSE工具往返2请求成功；K2.7-code普通回复成功但工具第二请求429（live.json保留失败，不算全通过）；K3国内404。两个临时探针只发连接测试，无工程数据；密钥经getpass仅留进程内存，源码/日志无sk-匹配。协议官方依据platform.kimi.com的K3/K2.6/K2.7-code quickstart。此次未复测全部生成质量，不作模型排名。

## 2026-09-22 Kimi Code订阅入口（进行中）
- 用户确认Moderato订阅。官方Code接口api.kimi.com/coding/v1、模型k3/k3-256k；旧密钥在Code models和chat均401 invalid_authentication_error，code-probe.json保留，仅测试消息。真实成功待有效密钥。
- assistant_model/settings/js/html与test_assistant_kimi共5源测试修改，独立kimi-code服务商防止与按量平台混淆；真实User-Agent，不伪装其他客户端。3新测试RED→GREEN；43通过+沙箱DPAPI失败，正在原生复验。旧package-kimi尚未替换。

- Kimi Code入口交付：44专项通过（原生DPAPI复验成功）、27 EXE窗口检查通过/frozen=true、78包资产一致；证据kimi-debug/code-{tests.log,native.json,assets.json,source.json}。最新唯一package-kimi-code，试用launcher已切换，保留trial-workspace设置/历史。3说明文档追加订阅与按量区别。
- 用户再次提供相同密钥；国内和国际Code的models/chat均401 invalid_authentication_error，code-probe.json/code-international-probe.json保留；没有真实K3成功证据，也未保存或替换用户密钥。后续需有效订阅密钥在新版设置填写再测试。不接硬件、无新代理，未重跑全仓。

- 用户提供Moonshot国内kimi-k3示例后，按完全相同model/messages、不带effort/tokens/stream的HTTP载荷复测，仍404 Not found the model kimi-k3 or Permission denied；证据kimi-debug/user-example.json与user_example.py（无密钥）。由此排除先前附加参数导致该404；密钥在订阅平台401不能推断其全局失效。未改应用或用户设置。

- 后续新密钥实测：用户给定国内kimi-k3最小示例仍404；国内models200仅返回kimi-k2.6/kimi-k2.7-code，国际models401。证据kimi-debug/new-key-example.json与new-key-models.json，无密钥落盘，未改设置或应用。新密钥在国内鉴权有效但K3仍不可调用，应核查该开放平台账号K3权限，不能称已连接K3。

## 2026-09-22 用户要求实际SWD Pattern抽样验收（进行中）
- .scratch/assistant-v1/pattern-acceptance/run.py从既有用户pattern.xlsx原始副本选5例：DAC001/FFF、OPA先关后开8步、PA4 HSI8M/128、ADC CAP边界。plan.json记录源SHA/原始行/验收目标；不覆盖原Excel。Kimi K2.6真实任务在隔离tasks运行，密钥仅getpass进程内，无工程全量上下文外发。后续需独立语义、Excel往返、编辑器、平台编译及HTML验收报告。

- Pattern抽样验收完成：docs/assistant-pattern-acceptance.html。5源样本实际与用户当前pattern.xlsx八个功能字段一致，源SHA测试前后1e217034a0192389a03236abe6215689f8b6338864d9ef76fb64831df29f26e8不变；历史副本整本不同，source-check明确物理行/额外列差异。
- Kimi首轮DAC最小码要求补时钟，其余4项429，无候选。保存设置无可用密钥，改用此前用户授权DeepSeek密钥getpass内存测试；5任务/26完成请求/311171实测tokens。DAC001 Chroma、DACFFF S100各生成一份3行候选，9项值/时钟/来源/保存重载/向量回放均过；MCO8轮失败（AF0误作func后重复pin字段触发sequence），OPA拒绝但解释错误，CAP正确拒绝，无缩水候选。
- Chroma隔离.scratch/apa-chroma完整DEC/PAT/PLN通过，43诊断；S100编译前工具身份Synaptics非Borland而阻断，未宣称编译通过。真实候选源码窗口首轮启动失败native.json；新工作区native2/report.json4项送入/撤销通过，当前EXE标准packaged/report.json27项通过/frozen=true。测试副本重绑定干净目标context，原任务记录未改。
- 本轮仅验收脚本/报告，无应用源码或安装/用户设置改动，不接硬件、无新代理、不重跑全仓。报告13本地链接有效。整体验收不通过；后续优先pin_config说明/模型重复指令、OPA解释、正确S100工具链与Kimi限流后复验。

## 2026-09-22 简单Pattern失败根因修复（进行中）
- 对照同知识库：回放MCO原最后请求仍INVALID_INTENT，5条最小正确指令立刻得到8条正确写入；证明是工具接口契约/模型规划而非寄存器生成能力缺失。OPA旧核心write_reg存在但助手未开放，CAP旧生成器支持但助手未开放；不能混称全系统不支持。
- assistant_tasks补pin_config完整覆盖/参数默认/禁止重复GPIO字段说明，lookup_pin按实际IOMUX返回可执行指令选项；capabilities明确字段聚合和未开放顺序写/CAP边界。test_assistant_pin公开查询→编译验证先RED后GREEN，42相关测试通过；2源码/测试改动。pattern-diagnosis/live.py使用原题复测OPA及2次MCO，密钥仅隐藏输入，尚未新版包。

- 根因修复完成：2源码/测试文件（assistant_tasks、test_assistant_pin），42专项通过；MCO同原题两次DeepSeek分别5轮/4轮均8步候选，每份14项字段/来源/Excel往返/向量回放通过，Chroma DEC/PAT+PDT两例通过。OPA2轮解释准确拒绝，未新增顺序写/CAP能力。证据pattern-diagnosis/report/review/compiler.json。
- 最新唯一隔离包package-pin-contract，launcher已切换；native/report.json27项EXE通过/frozen=true，78资产一致，source摘要记录。docs/assistant-pattern-diagnosis.html根因报告与3使用文档更新。原用户安装/资料/设置不变，无硬件，无新代理、未全仓复跑。不要把2次MCO成功外推普遍可靠；旧验收失败证据保留。

## 2026-09-22 TK SRAM 采集独立 Excel 样例
- 用户提供 TK_24M_Test S100 PLAN 与 Pattern，确认三个结果按 MAX/MIN/dex 顺序、每个16bit；本轮明确选择先交付独立Excel样例，随后指定目标Chroma，不授权以样例冒充完整程序。
- 新增 outputs/tk-capture-20260922/TK_24M_Chroma_配置样例.xlsx，两页采集配置/结果判定，填入PA4、3结果、16bit、上下限1000..23500/1000..23500/1..85及原流程条件。按连续布局列0x20000F00/F02/F04与@2，显式保留原DAQ映射尚未验证、内置地址高位需核实的边界。目标Chroma时序/PAT资源和Bin映射未补造。
- .scratch/tk-capture-sample/build.mjs 用bundled artifact-tool创建，两个页渲染检查、openpyxl只读重载关键值/类型/十六进制文本通过。xlsx不是FLOW导入格式，无源码改动、编译或硬件测试，无安装/用户原文件修改，无新代理。

## 2026-09-22 普通 KEIL SRAM 结果判定
- core/firmware_test.py 将 RUN_SEQUENCE-SRAM_CAPTURE-JUDGE 与后续连续 JUDGE 行绑定为同一捕获组；firmware_judge.py 增加 SramValueJudgePlan。Chroma firmware_test_renderer 复用注册的 SRAM_CAPTURE adapter 并逐值 JUDGE_VARIABLE，不在结果行之间触发或复位。S100 仍明确拒绝此新增组合。
- gui/recipe_editor.py 说明顺序判定合同与默认 stride=4；tests/test_firmware_sram.py 覆盖三值、边界和 Chroma 生成。实现验证进行中；原安装与用户数据不改。

- 本轮验证完成：.scratch/tk-sram/regression.log 65项通过（隔离旧流程副本仅去掉用户新增三行）；当前母本在内存中修正五格后 ProductCompiler 成功。Chroma DEC/PAT/PLN 全通过，但 sram_capture.pat 缺失，保留 STUB 发布阻断，非上机验收。全仓91通过后原母本非法Recipe阻断，未宣称全绿。
- 独立交付 .scratch/tk-sram/Start_SRAM_Candidate.cmd 与 package/dist/MCU_Workbench_App；原启动器未切换。package-check.json 验证4模块一致；native-retry.json 正常桌面权限下 frozen 原生自检通过，首轮沙箱 WebView 启动失败记录保留。验收说明.html 含五格配置修正、采集资源限制与日志链接。原Excel SHA未变。

## V0.5 异机交付清单（2026-10-08，覆盖此前 V0.5 准备状态）
- GitHub 私有仓库 https://github.com/homoyoung555/MCU_Workbench 已创建；CLI 已登录 homoyoung555，凭据保存在 Windows keyring。主线本地分支 codex/workbench-migration；发布约定为远端 main、标签 v0.5、V0.5 试用 Release。
- 本版编辑/程序生成、SCAN/SWD/HEX、独立 AI 助手保留；gui/server.py::make_server 默认 compiler_enabled=False，/compiler 和全部 /api/compiler/* 返回403；workbench.html/js 禁用入口并拦截脚本导航。内部编译回归仅显式开启，桌面/首页显示 V0.5。
- 新 tests/test_v05_release.py 先11 RED后 GREEN；tests/test_compiler_http.py 显式开启被测内部编译模块，test_gui_desktop.py 保留服务独立性断言并纳入禁用参数。
- .gitignore 排除 .scratch/.test_tmp、私有 Codex 证据与用户设置；仍保留 gui/data、swd_authoring/data/cache 内置知识。源码允许清单756文件；不提交工具链、应用安装包、原工程输入、API、聊天或私有交接记录。
- README.md 为新电脑部署/开发入口说明；requirements-desktop.txt 固定已验证 pywebview/PyInstaller 版本；docs/release-v0.5.html 为试用发布说明。
- .scratch/release-v0.5/deploy 下程序 MCU_Workbench 与资料 MCU_Workbench_WORKSPACE 并列，发布启动器显式定位相邻资料目录。候选从当前源码重建，保留原安装与真实用户资料，不连接硬件。
- artifacts 包为 MCU_Workbench_V0.5_Windows.zip（约37.85MiB）、Data.zip（约33.70MiB）、Source.zip（约2.88MiB）和 SHA256SUMS.txt。Data 含622个 input 文件及1个产品/地址限定复位补充；不迁移密钥、设置、聊天。ZIP CRC/禁止路径/密钥格式检查通过，源码ZIP与暂存文件内容一致（Git换行归一化后）。
- 验证：锁包专项27/22子测试通过，工作台/SWD前端契约通过；frozen EXE助手双窗口原生27/27，关键模块/资源14/14；input原始文件与部署副本622/622 SHA256相同。
- 全仓门禁91通过后因原母本 FLOW row205 Recipe '/' 非法停止，原母本未改；既有26领域/母本基线失败和3环境跳过保留。TK流程缺真实 sram_capture.pat，不得以STUB冒充正式资源。未完成异机或硬件验收。
- 本机发布辅助 .scratch/release-v0.5/package.py、source-selection.json、release-body.txt、各清单/日志，以及 .Codex/handoffs/2026-10-08-v05-publication.html 均为本地证据，不随Git上传。最终是否已推送/发布以 GitHub 仓库和 Release 实际状态核对。
