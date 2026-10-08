# V1.3 测试程序生成领域

该领域把母本中的测试流程、运行期结果和非易失字段归属编译成不同测试平台的程序。

## 语言

**Full Pin 转换**：
SCAN转换保留输入WGL中完整管脚的输出方式，不以程序Excel中的PIN DEC筛选管脚，也不要求加载程序Excel。

**PIN DEC 适配**：
依据所选程序Excel的PIN DEC定义统一Pattern管脚名称、移除未定义管脚及其向量列，并按PIN DEC顺序排列管脚与对应向量列。它是独立转换时可选的项目管脚适配，不等同于已完成全部程序资源适配。

**Recipe**：
单个测试函数内部按顺序执行的动作，不表达跨 CP 的数据持久化关系。

**EXPORT**：
捕获当前测试项的结果，经可选的命名格式处理后，保存为本测试程序生命周期内的逐 Site 全局值；它本身不写 OTP 或 UID。
_避免_：写 UID、写 OTP、转十六进制

**RAW**：
不改变数值含义的 EXPORT 格式；无 UID 归属的裸 `EXPORT` 默认使用 RAW。

**BCD16_MV**：
把电压换算为整数毫伏，并将四个十进制数字分别编码到四个 nibble 的 EXPORT 格式。
_避免_：转十六进制

**ADC12_3V3**：
以 3.3 V 为满量程，把测量值换算为 12 bit ADC Code 的 EXPORT 格式。

**UID 归属**：
FLOW 行的测试结果需要成为 UID 字段来源；`UID=yes` 隐含一次 EXPORT，但真正写入 UID 仍由后续 UID 流程完成。

**OTP 归属**：
FLOW 行产生的值需要成为非 UID 持久化页字段来源；它只声明字段归属，不规定当前测试项立即写入芯片。

**持久化目标扇出**：
同一个 EXPORT 值可以同时绑定 UID 与 OTP，也可以绑定多个 OTP 页字段；值只产生和编码一次，各目标页分别装载并提交。

**Verify 默认编码**：
Verify 值写入 UID 或 OTP 时，TS 默认使用 ADC12_3V3，其他 Verify 默认使用 BCD16_MV；显式 EXPORT 格式可以覆盖默认编码。

**默认持久化时机**：
Verify 的 OTP 字段默认由 Trim Data Rewrite 提交，Verify 的 UID 字段默认由 PGM CP ID 提交；Trim 的 OTP 字段默认由 Trim Data Write 提交，字段值是最终 DAC。

**Commit 到 Pattern**：
`COMMIT` 复用 EXPORT 已产生的数据通道，把选定值编码并合入对应 Page Image，同时增量更新目标页面的 Program 与 Read/Compare Pattern；它不运行 Pattern，也不物理写入芯片，真正的 erase/program/read 仍由后续 `PGMOTP` 完成。`COMMIT(item)` 引用此前已 EXPORT 的测试值；显式常量使用真实字段名和完整确定值，例如 `COMMIT(PASS_FLAG=0x65BAFFFF)`，不接受含义不明确的 `XXXX` 占位。Flow 必须保证引用值在 COMMIT 前已经产生。

标准 UID/BakeID item 可使用无参数 `COMMIT`：生成器从解析后的 item 目标取得应更新字段、完整终值和逐 Site 门控条件。例如 `Pgm_Cp1_Bakeid` 自动选择 BakeID Pass Flag、对应完整常量以及 `Read_Cp1_Bakeid` 产生的待补写 Site；母本无需重复填写这些可确定信息。显式字段/常量形式保留给特殊产品或调试覆盖，并接受 preflight 校验。

**CP1 Trim Data 初次提交**：
CP1 的 Memory Wakeup 消费 Final DAC 并拼接运行期 REG；随后 Trimdata Write Read 消费这些已拼接 REG，将其装载到对应 Pattern，物理写入芯片并回读。后者不直接消费 Final DAC，也不负责重新拼接 REG。

**CP1 Trim Data 提交范围**：
Trimdata Write Read 提交 CP1 的 Trim Data 字段；目标页可以包含 UID，因为 UID 页也可能存放 Trim DAC。此节点写入 UID 页中的 Trim 字段，Verify、ID 和 Pass Flag 等字段仍由后续 PGM CP1 ID 补写。

**Set All Final Vposp**：
公开 Recipe Module `SETVPOSP` 管理两个不同状态。**VPOSP Pattern 准备态**表示当前 Pump DAC 已动态写入测试机侧 `set_all_final_vposp` Pattern Memory；它不受 DUT 上下电或退出 FBIST mode 影响。**VPOSP 芯片加载态**表示 RUN 该 Pattern 后，内容已实际加载到芯片寄存器；它只在当前上电和 FBIST 会话内有效，DUT 下电或退出 FBIST mode 后失效。用于 Vposp/Vpose/Vnegp/Vnege 等 Trim/Verify 电气条件时，dirty 调用只建立准备态，clean 调用可 RUN 并建立芯片加载态；用于 NM/OTP Flash Pattern 消费链时只建立准备态，由消费者在进入 FBIST mode 后 RUN 一次，再执行同一会话内的 Flash Pattern。用途必须由上层 typed Plan 显式声明，平台 Adapter 不按 item 名推断。当前 CP 有现场 DAC_FINAL 时直接使用，否则从 Read OTP Map 已恢复的 REG 中按 ADDR_MAP 提取；各 Site 使用自己的值。

**Run Pattern**：
全局共享 Recipe Module `RUN(pattern, span)` 只执行指定 Pattern 的完整范围或命名区段，不读取 DAC、不动态改写 Pattern，也不依赖任何 Typed Kind。Product Compiler 负责证明 Pattern 资源与快照有效，平台 Adapter 只把同一个 Run Pattern Plan 翻译为测试机指令。

**Standard Verify 主体**：
一次 Standard Verify 必须包含 `ENTER` 以及至少一次 `JUDGE`；修改 DAC 后可以再次 `JUDGE`，因此 JUDGE 不是恰好一次。其他 Module 围绕这个主体按 Effective Recipe 编排，不能用一串没有 ENTER/JUDGE 的通用动作冒充 Standard Verify。

**跨测试项 DAC 调整**：
`DAC_ADJ` 可以消费此前测试项已经 `EXPORT` 的稳定结果，并按条件调整另一个目标 DAC，例如 `EXPORT(A)` 后由后续测试项执行 `DAC_ADJ(A<0.4:B-1)`。调整量表示目标 DAC 在其合法实际排序中的档位位移，不是编码整数运算；越过最小档或最大档时保持在对应边界档。结果来源 A、目标 DAC B、条件和调整量都是显式业务事实，不由当前 item 名推断；DAC_ADJ 本身不隐含 COMMIT、SETVPOSP 或再次 JUDGE。

**EXPORT 消费闭包**：
ProductCompiler 在最上层按 CP 汇总全部 EXPORT，并建立 producer→consumer use-def 关系。每个 EXPORT 必须至少存在一个位于其后的明确消费者：OTP 字段、UID 字段或 DAC_ADJ 条件；无消费者、消费者位于生产者之前、跨 CP 直接消费或引用不唯一均为编译错误。同一 EXPORT 允许扇出给多个消费者。DAC_ADJ 消费 EXPORT 的 RAW 物理测量值及单位；OTP/UID 所需编码属于各自持久化消费者，不改变 DAC_ADJ 的条件值语义。

**Trim DAC_FINAL 消费闭包**：
同一道 CP 的 Trim DAC_FINAL 必须按 FLOW 声明的用途分别闭合，不能由任意一次读取笼统满足。`OTP/UID=yes` 要求后序 BUILDMAP/COMMIT 等 Page Image 消费；`PUMP=yes` 要求后序 SETVPOSP 消费；DEPEND/DAC_WRITE 只满足测试条件用途，不能替代持久化。一个 producer 同时声明多种用途时，每种用途都必须存在位于其后的合法 consumer。

**最近判定结果**：
同一 Standard Verify 出现多个 JUDGE 时，EXPORT 捕获它之前最近一次已经完成的 JUDGE 结果；需要保存中间测量时，EXPORT 必须紧跟对应 JUDGE。

**逐 Site Pump 值**：
同一次多 Site 测试中，各 Site 的 Pump Final DAC 可以不同；SETVPOSP 必须使用各 Site 自己的当前值。逐 Site 数据选择和 Pattern 处理由已确认的平台实现承担，生成器只编排 typed 操作与依赖，不假设各 Site Pump 值相同。

**Memory Wakeup**：
其 Typed Kind 是 `FLASH_WINDOW`，主体只有 `NMLOOP`。默认 Recipe 是 SETVPOSP → NMLOOP；若前序测试项已经准备了当前仍有效的 final-vposp 快照，显式 Recipe 可以只有 NMLOOP。NMLOOP 在进入 FBIST mode 后运行这份已准备的 Pattern，再进行 NM 的擦、写、读循环。CP1 `Memory_Wakeup` 在该流程前显式附加 `BUILDMAP`，为后续 Trimdata Write Read 准备完整 Page Image/REG；CP2 `Memory_Wakeup` 只执行 NMLOOP，并消费前序测试项准备的快照。`BUILDMAP` 不是 `FLASH_WINDOW` 主体，也不是 `NMLOOP` 的内部动作。

**Build Map**：
根据 ADDR_MAP 构建当前 CP 的完整 Page Image/Trim Data REG；目标可以位于普通 OTP 页或 UID 页。每个适用于当前 CP 的寄存器先以 `CP Data[31:0]` 的真实 16-bit 默认值建立完整基底，再由当前 CP 已产生的 Trim DAC_FINAL 覆盖对应字段；未覆盖的 Verify、UID、Pass Flag 及保留字段保持 ADDR_MAP 默认值。BUILDMAP 不读取芯片，因此不得把默认值描述为物理旧值。它只产生 REG，不装载 Pattern，也不物理写入芯片。

BUILDMAP 只消费其 FLOW 位置之前已经产生的当前 CP Trim DAC_FINAL。只在后续 CP 才执行的 Trim 与当前建图无关；同 CP 但位于 BUILDMAP 后的 Trim 允许暂时保留 ADDR_MAP 默认值并产生 WARNING，因为真实产品可能必须先提交其他 Trim 才能执行该 Trim。硬约束位于整道 CP 的 producer→consumer use-def 闭包：每个同 CP Trim producer 最终必须在其后被合法 consumer 消费，不能因 BUILDMAP 已经过站而成为悬空结果。

`BUILDMAP` 是可被多个 Typed Kind 组合的共享 Recipe Module，不属于 `FLASH_WINDOW` 或 `NMLOOP` 私有。CP1 `Memory_Wakeup` 显式组合 BUILDMAP，是为了给后续 Trimdata Write Read 提供完整 Page Image/REG；其他测试项只有在其 Effective Recipe 明确声明 BUILDMAP 时才使用该能力。

**NM Loop**：
执行平台规定的 NM 擦除、编程和读取循环，最后退出或下电。NMLOOP 不读取 Final DAC、不修改 Pattern Memory 或构建 REG；它消费前序 SETVPOSP 已准备的快照，并在进入 FBIST mode 后运行 `set_all_final_vposp`，再执行自身的 NM Flash Pattern。

`NMLOOP` 是已批准注册的共享 Recipe Module，不归 `FLASH_WINDOW` 私有；FLASH_WINDOW 是首个调用方，未来其他 Typed Kind 只有在其 Module 准入与状态前置条件明确后才能使用。Registry 只提供 Plan 类型检查和双平台 Adapter 选择，不自动授权任何 Typed Kind。

NMLOOP 直接消费 Product Compiler 沿当前 CP FLOW 维护的同一个 `SetVpospSnapshot`，不建立第二套准备态模型。若调用位置存在任一所需 Pump 未准备或 dirty，编译直接 ERROR；生成器不得自动插入 SETVPOSP、复用旧版本或降级为 WARNING。

NMLOOP 的循环次数、阶段顺序和 Pattern 角色属于平台无关业务计划，Chroma/S100 必须消费同一计划；平台 Adapter 只能翻译 Pattern 执行、Datalog、Power 和 Flow/Bin 语法，不能各自保留不同的历史业务序列。每次重新进入 FBIST mode 后运行一次已准备的 `set_all_final_vposp`，同一 FBIST 会话内后续 Flash Pattern 复用该开窗状态。

NMLOOP 对外只有一个 FLOW 测试结果边界。内部各阶段、循环和 Pattern RUN 不建立独立 Schedule 或 Bin；平台 Adapter 可以生成目标平台所需的内部日志，但任一内部执行失败都必须归并为当前 NMLOOP 测试项失败，并沿用该 FLOW 行的统一失败策略。内部失败不提前中止业务序列，仍须执行完整 canonical 循环及最终 `POWER_OFF`，最后统一判定当前测试项结果；清理动作不得因已有失败而跳过。

CP1 NMLOOP 的标准序列以已确认的 S100 完整流程为准：第一段 FBIST 会话执行 100 次 `bulk erase all → bulk program 00 all`，随后再执行一次 `bulk erase all` 并下电；第二段重新上电进入 FBIST 并再次运行 `set_all_final_vposp`，执行 49 次 PCKB/NCKB erase+program 循环，随后执行 PCKB/NCKB read 阶段、100 次 `bulk erase all → bulk program FF all` 及 `bulk read FF NM`，最后下电。Chroma 的历史 CP1 10/25 次简化序列不再作为业务规范。

第一版 NMLOOP 阶段与 `100/49/100` 次数由 code-owned canonical Profile 拥有，CP1/CP2 执行相同业务序列；Product Compiler 按每个稳定 Pattern 角色所需的操作、数据背景、Program Strategy 与 Coverage，从产品级 Required Flash Pattern Request 中唯一选择完整 logical identity。Pattern 名称只由 `NM_pattern` 的 `Pattern name` 进入该 Required Request，NMLOOP 不保留第二份名称表，也不通过追加/移除 `_sm` 或解析名称片段推导。CP1 的 Erase/Program 角色选择规定的 `NM_PLUS_SM` 资源，CP2 选择 `NM_ONLY` 资源；Bulk Read 对两者都固定选择同一组 NM_ONLY 资源，因为硬件不支持 Bulk Read SM。缺少或存在多个语义相同的 Required Pattern 时直接 ERROR；所有选定 identity 固化进不可变 NmLoopPlan，同一道 CP 的 Chroma/S100 消费同一 Plan。Excel 不新增配置列；只有出现第二个经确认且业务序列不同的真实产品时，才把 Profile 选择提升为产品配置或母本事实。

当前正式母本 `NM_pattern` 已补齐 CP1 所需的 PCKB/NCKB `EVEN_ODD + NM_PLUS_SM` Program identity；Bulk Read PCKB/NCKB/FF继续使用既有NM_ONLY identity，不创建非法 `_sm` Read资源。FLASH_WINDOW只对Erase/Program声明CP1 `_sm`资源，对Read声明共享NM资源。

CP1 `_sm` 与 CP2 非 `_sm` 只共享 NMLOOP 的业务阶段、顺序和次数，不保证底层向量内容相同。Pattern Generator 必须按各自 Flash 模式生成真实向量，禁止把非 `_sm` 文件复制或重命名成 `_sm`；例如现有 bulk erase `_sm` 使用 AXA=1，而非 `_sm` 使用 AXA=0。

**Sector Program**：
以 Flash 配置寄存器 `MODE[3:0]=1101` 对一个 Sector 执行编程的 Program Scope。该值不是串行 FBIST `Cmd[3:0]=1101`；后者仍表示 Read Compare，两者属于不同字段。

Sector 当前仅确认 Program MODE=`1101`，母本/Golden 尚无 Sector geometry、Sector Erase MODE 与寻址规范，因此不进入本阶段可生成能力。已记录的后续设计草案是：Sector Erase 推导为 `PEP0111 → Sector Program1101 Pre SEQ → sector-erase-mode Erase SEQ → Clear0001 → Normal0101`；Sector Program 推导为 `Clear0001 → Normal0101 → Write0110 → one PageData → Sector Program1101 SEQ → Normal0101`；Sector Read 推荐展开为Sector内有序Page Read，而不是发明未知的Sector Read MODE。以上均为待硬件事实确认的假设，不得据此生成正式Pattern。

后续要启用Sector，产品母本至少必须正式提供：`sector erase MODE`、`pages_per_sector`、`sectors_per_bank`或可验证的总数、支持Region/AXA、Sector MODE下RA的编码/步长、Program/Erase RED policy、SEQ等待profile，以及Sector内PCKB/NCKB的跨Page相位规则。建议以结构化 `FLASH_SECTOR` 硬件事实表承载，不写GUI选择；现有BANK/Page大小/program bit/read bit继续复用。缺少任一承重事实时Generator必须返回unsupported/product-definition-missing，禁止从Page/Bulk规则猜测。

**Generator / Future GUI Boundary**：
当前阶段只实现无GUI的Flash Compare Pattern Generator及其平台无关request/result接口。未来GUI覆盖整个项目，Flash Pattern Generation只是其中一个被编排功能；Generator不得依赖GUI控件、会话状态或展示文案，也不把用户选择写回Excel。当前首版可实现范围以已闭合的Page/Bulk为准；未来GUI或其他调用方在Sector产品事实补齐后，才能通过同一headless接口启用Sector。

Required `page epr Random NM` 使用固定64-bit seed `0x5043443030395631`。Generator以`SHA-256("flash-page-random/v1" + seed + counter)`计数流确定性生成一份完整PageData（当前256 Byte），并在该Pattern的全部Page Target间复用；每次产品构建产物必须逐字节一致。seed是显式Plan数据而非Excel字段或系统时钟；未来GUI可允许用户输入其他seed以获得不同但仍可复现的Optional Pattern。

**Bulk Program Strategy / Coverage**：
Bulk Program 有两个正交维度，Generator 不得再把它们绑定成旧 `used` 名称套餐。Strategy 选择 `EVEN_ODD` 或 `ALL_PAGES`：`EVEN_ODD` 使用 `MODE=1110 (bulk program even/odd pages)`，由于本系列最小写入单位为完整 Page，每个 Bank 必须分奇 Page 与偶 Page 两个独立 Program pass；`ALL_PAGES` 使用 `MODE=1111 (bulk program all pages)`，每个 Bank 只需一个 Program pass。Coverage 由 AXA 决定：`AXA=0` 表示 `NM_ONLY`，`AXA=1` 表示 `NM_PLUS_SM`；两种 Strategy 都必须支持两种 Coverage，`ALL_PAGES` 只表示写入策略、绝不暗含 `NM_PLUS_SM`，`_sm` 文件名也不能充当硬件语义来源。

Bulk Program pass 数按产品 Bank 几何计算：`EVEN_ODD = bank_count * 2`，`ALL_PAGES = bank_count`。当前双 Bank产品分别为4次与2次写入；奇偶 pass 必须独立闭合 Program 的 `3→4→5` 流程，不能只切换数据而复用未完成的 latch/SEQ 状态。EVEN_ODD 固定采用 parity-major 顺序：先对所有 Bank 执行 `RA=1` 的奇 Page pass，再对所有 Bank 执行 `RA=0` 的偶 Page pass；当前即 `Bank0 odd → Bank1 odd → Bank0 even → Bank1 even`。ALL_PAGES 不分奇偶，RA 确定性编码为0并按 `Bank0 → Bank1` 执行。

Bulk `EVEN_ODD` 的 PCKB/NCKB 必须保留跨 Page parity 反相，不能复用 Page Scope 的“所有页同相位”规则。选择 PCKB 时，`RA=1` 奇 Page pass 写 PCKB PageData，`RA=0` 偶 Page pass 写 NCKB PageData；选择 NCKB 时相反，奇 Page写 NCKB、偶 Page写 PCKB。每个具体 Page 内部仍按 Excel block chessboard 从该 pass 选定的起始相位展开，但 Page parity 决定整页起始相位。

Bulk `ALL_PAGES` 不分奇偶：无论 Coverage 为 `NM_ONLY` 还是 `NM_PLUS_SM`，选择 PCKB 时所有被覆盖 Page 使用PCKB相位，选择 NCKB 时全部使用NCKB相位。`ALL_PAGES + PCKB/NCKB` 属于合法但低频的自由组合，Generator 必须支持且不得报错；GUI 不把它作为常用默认预设，但也不能隐藏为不可达能力。

Bulk `EVEN_ODD` 的 parity 数据变换只适用于PCKB/NCKB。选择 `00`、`FF` 或自定义完整 PageData 时，奇 Page 与偶 Page pass 写入完全相同的数据，不反相、不旋转、不偏移；Generator 不得把 parity 自动变换推广到非棋盘数据。

每个 Bulk Program pass 只向 Page Latches 写入一份完整 PageData，数据组数仍为 `PAGE_BYTES * 8 / program_bit`；目标 Page 数量不参与数据组计算。随后由 `MODE=1110/1111` 把该 latch 内容应用到当前 pass 选择的奇页、偶页或全部页。每个 pass 独立执行 `Clear Latches → Write one PageData → Program SEQ`，禁止按被覆盖 Page 数重复写 latch 数据。

Bulk Erase 不具有 EVEN_ODD/ALL_PAGES Strategy，只选择 Coverage：`MODE=1011 (bulk erase)`，`AXA=0` 为 `NM_ONLY`、`AXA=1` 为 `NM_PLUS_SM`，RA/CA/PA 确定性编码为0。Pattern 起始公共 `RPT 1000` 后固定增加一拍 `111 RPT 2` settling vector；随后每个 Bank 独立执行一次完整 `Pre-Program → Bulk Erase → Clear Page Latches`（阶段 `1→2→3`），当前双 Bank 固定按 `Bank0 → Bank1` 共执行2次。

Bulk Erase 的 Stage ① Pre-Program 固定采用 ALL_PAGES Program MODE，与任何独立的 Bulk Program 请求 Strategy 无关：先配置 `PEP=0111`，再以 `bulk program all pages=1111` 执行 canonical Pre SEQ，然后才以 `bulk erase=1011` 执行 Erase SEQ。不得用 `EVEN_ODD=1110` 把 Pre-Program 拆成奇偶两次。

Bulk RED policy 固定按操作派生：Bulk Erase 与 Bulk `ALL_PAGES` Program 编码 `RED0_EN=RED1_EN=RED2_EN=RED3_EN=1`；Bulk `EVEN_ODD` Program 与 Bulk Read Compare 编码四个 RED 字段全0。RED 不进入 GUI/API，也不得仅依据 AXA/Coverage 或文件名推导。

Bulk `OPR_SEL` 与共享五阶段语义一致并按阶段派生：Pre-Program=`00(pre)`，Erase=`10(erase)`，Program 的 Clear/Write/SEQ 上下文=`01(program)`，Read Compare=`00(pre/no pulse)`。Clear Page Latches 自身不消费 OPR，保持所属 Erase 或 Program 上下文；Coverage、Bank、DataSpec 均不得覆盖该规则，GUI/API不暴露该字段。

Repair 是独立的单 Bank NM Compare 协议，不是只替换 FBIST Cmd 的 Bulk Read。它与同 Bank Bulk Read 共享 `RA=0`、`AXA/CA/PA=0`、`OPR_SEL=00`、数据背景到 `COMP_MODE/COMP_DATA` 的映射、`COMPARE_NUMBER=0x4000` 与 `comp_data=0x5A`，但 Repair 必须使用 `Cmd=1010`、四个 `REDx_EN=1`、在寄存器配置前写入 Normal MODE；Bank1 还在公共起始等待后增加 `111 RPT 2`，Bank0不增加。Repair Cmd 的命令位前保留独立 write-register `111`，结果旗标后固定为3拍 `1X1`；Bulk Read 的 `Cmd=1101`、`REDx_EN=0` 与 read-close 尾部不得复用到 Repair。

Bulk Read 只支持 NM Region，不具有 Coverage 选择：固定 `AXA=0 (NM_ONLY)`，按 `Bank0 → Bank1` 对各 NM Bank 执行Compare；禁止生成 `NM_PLUS_SM`/AXA1 Bulk Read。SM Region 只能通过明确目标的 Page Read Compare 验证，因此 GUI 在 Bulk Read operation 下不得展示 Coverage/SM 选项，标准测试资源也不能用 `_sm` 名称伪造不存在的 Bulk SM Read 语义。

Bulk Read 使用 Flash 内部 Compare FSM，每个 Bank 只发送一次串行 `Cmd=1101 read_compare_mode`。固定 `READ_MODE=0`、`ADDR_MODE=0`、RA/CA/PA=0；DataSpec 映射为：00→`COMP_MODE=0, COMP_DATA=0x00`，FF→`0,0xFF`，PCKB→`1,0xFF`，NCKB→`1,0x00`。`COMPARE_NUMBER = nm_pages_per_bank * PAGE_BYTES * 8 / read_bit`，所有因子必须从 Excel 产品事实读取并整除/字段宽度校验；当前 `512*256*8/64=16384=0x4000`。Bulk Read 只允许这四类可由内部 FSM 表达的背景，不支持任意 custom PageData；custom Bulk Program 的验证必须拆成Page Read H/L Compare，Generator 不得伪造 custom Bulk Read。

Bulk MODE 生命周期固定。EVEN_ODD Program 的每个奇/偶 Bank pass 执行 `clear page latches=0001 → normal=0101 → write page latches=0110 → one PageData → bulk program even/odd=1110 Program SEQ → normal=0101`；ALL_PAGES Program 的每个 Bank pass 使用相同前半流程，但最终为 `bulk program all pages=1111 Program SEQ → normal=0101`。Bulk Read 每 Bank 按 `Bank/Address/Compare registers → normal=0101 → Cmd=1101 internal compare → comp_flag check` 执行；不得复用Page Read的H/L Compare数据流。

Bulk Read 的结果标志比较由 Excel 产品事实控制：`comp_flag=yes` 时，将 `comp_data` 解析为期望字节并按 MSB→LSB 生成H/L比较位；`comp_flag=no` 时完全省略该段。当前母本为 `yes/0x5A`，对应 `01011010 → L H L H H L H L`；这些值不得硬编码，也不得由数据背景或Pattern名称推导。

Compare Pattern Generator 的 ECC timing 完全由 Excel `ecc` 产品事实控制并跨Page/Bulk共享：`ecc=0` 时不生成任何ECC等待向量；`ecc>0` 时在每个Program数据组和每个Read数据组后插入对应数量的ECC周期，Bulk内部Compare路径也必须在其组节拍计算中体现同一延迟。`ecc` 必须校验为非负整数，不进入GUI/API，双平台Adapter不得各自改写其语义。

**Flash Pattern Generation Request**：
由 GUI 或其他调用方提交的平台无关 Compare Pattern 请求，明确选择 Program Scope、数据背景、目标地址与输出身份。Excel 只提供硬件编码事实；`NM_pattern` 定义产品测试所需的 Required Compare Pattern Set，由标准产品构建统一生成；GUI 只暴露自由验证用的 Optional Compare Pattern，不展示、替换、关闭或改写 Required Pattern，也不因每次 GUI 生成而强制重生成测试资产。标准构建可在产物汇总阶段组合 Required 与 Optional 清单并严格检查输出身份冲突，但两者拥有独立触发入口，`used` 文本不是自由组合接口。

**Flash Compare Pattern Generator**：
只生成 Compare 型 Flash Pattern，承载 Page/Bulk/Sector 的自由组合擦写读验证。它可消费标准构建编译出的 Required Compare Plan，也可消费 GUI/API 提交的 Optional Compare Plan；GUI 路径只生成用户明确请求的 Optional 产物。Capture/Raw Read 不属于该模块。

**Flash Label Generator**：
独立于 Flash Compare Pattern Generator 的固定测试资产模块，完整接管旧生成器 `flash_pattern_label_created()` 的职责，以 `ADDR_MAP` 等产品事实统一生成 UID/OTP/Trim 等测试 Page 所需的 Page Erase、动态 Program/Read labels、UID/CP 派生 Program/Read、独立 CP/Bake masked check（Bake 写入复用当前 CP 普通 ID Program/Read） 与 Page Capture Pattern。其产品级 `FlashLabelGenerationPlan` 只能由 Product Compiler 组合已编译的 `AddrMapCatalog` 与 Flash hardware facts 产生，并以有序 Page 计划集合表达整项产品固定资产；GUI、Renderer、typed kind 和平台 Adapter 都不能自行读取母本、逐页提交请求或构造这些业务事实。`FlashLabelContract` 是 Pattern/Label 完整名称的唯一编译结果：生产端和消费端都只引用其中的具体名称，不得再按 page、register、CP、正反码或平台后缀自行拼接；消费关系允许多个测试项复用同一标签。Capture、动态标签 Compare 和 UID masked check 都属于同一 Page Read 操作的不同数据接收策略；UID Page 的生命周期状态仍归 OTP Page Engine，Generator 只消费已编译的期望值、Mask 与 Capture/Label 布局。CP ID、BakeID 的固定写入值及检查范围是不会随产品母本变化的代码事实，由 Product Compiler 集中选择并写入计划，不从 Excel 读取，也不允许双平台 Renderer 各自维护。Page 擦除、编程和读取的已确认新版规则是生成权威；旧 `flash_pattern_label_created()` 产物只用于核对输出身份、标签、固定值、检查范围与平台语法，不得为了逐字节一致恢复已被新版规则取代的旧行为。独立 legacy 入口 `otp_read_pattern_created()`、`nm_read_pattern_created()` 与 `read_status_mode_created()` 不属于该模块。本模块不向自由组合 GUI 暴露，也不允许 GUI 请求把测试用 Pattern 混入 Optional Compare Plan。

**固定 UID Word 协议**：
2026-08-27确认：制造追溯与ID标签由代码中的固定UID协议维护，不从Excel的描述文字解析，母本无需改列或把fixed改成lable。上层组合ADDR_MAP页面默认值、固定逻辑位布局和完整Word标签；Flash Label Generator与UID消费者引用同一编译计划。CP1/CP2/CP3普通ID Pattern统一八个32-bit范围，Program/Read各自命名；S100范围由st/sp标签表示，不是八个独立文本标记。

| Word | 标签基名 | 高位到低位内容 |
|---:|---|---|
| 0 | lot0 | LOT前4字节 |
| 1 | lot1 | LOT后3字节、SLOT |
| 2 | uid_xy | 原始XY高位、X低8、Y低8、年月 |
| 3 | uid_info | 测试厂、CP版本号、CRC8、PASS字节 |
| 4 | cp_ver | CP1版本、CP2版本、原默认低16bit |
| 5 | cp12_id | CP1/CP2 ID与Bake标记 |
| 6 | cp34_id | CP3/CP4 ID |
| 15 | project | PROJECT反16bit、正16bit |

不改变实际地址、位序、字段编码、CRC输入或算法；Trim/Verify标签、UID Capture与独立ID Check不改。CP3正式Word3低8bit=0x78，Word4低16bit来自上层页面默认（本母本FFFF）；PROJECT正值P的整字为((~P&FFFF)<<16)|(P&FFFF)。Bake LOADMAP整Word设Read=X，防假PASS清理仍按既有阶段规则整Word置全1；正式UID COMMIT装填八个已拼接Word并恢复比较，不再逐小字段写Pattern。

**Page Pattern Target**：
一份 Page Scope Pattern 可以按调用方给定的顺序处理一个或多个 Page，目标表示为有序 `pages[]`；单 Page 是只有一个元素的特例。生成器保持该顺序，不把 Page 集合隐式扩大为整片或 Bulk 操作。每个 Page Target 必须解析为完整地址元组，而不是只保存 RA：AXA 是目标页/地址空间的属性，不能由 Page Program/Erase/Read 操作类型写死。现有普通 NM Page 路径使用 `AXA=0`；`ADDR_MAP` 驱动的 UID、TRIM0、TRIM1 等特殊页三类 Page 操作均使用 `AXA=1`（当前 RA 分别为 `0x1A`、`0x1D`、`0x1E`，CA/PA 在启动时为 0）。

Page Target 支持两种互斥输入：调用方可选择 catalog 中已知的逻辑 Page（例如 UID/TRIM0/TRIM1，由生成器解析 Region 与完整地址元组），也可提交显式 Page Target。两种输入编译成同一种 canonical Page Address；已知 Page 的派生字段默认不允许被调用方局部覆盖，避免形成名称与地址不一致的目标。BANK 先用逻辑编号表达，再由硬件编译层编码；它受 memory Region 及区域几何约束，不是按 Page 名称任意选择。UID/TRIM0/TRIM1 等页属于 SM Region，因此固定为逻辑 `BANK=0`，对应当前双 Bank FLASH_EPR one-hot 编码 `BANK_SEL=01`、`BANK_EN=01`；不得因为其 `AXA=1` 或 Page 名称而改选其他 Bank。

NM Region 的 Page Target 对外使用区域内全局、0-based `page_index`，不要求用户选择 BANK。Generator 从产品母本读取 `total_pages` 与 `bank_count`，先校验 `0 <= page_index < total_pages` 且页面能按 Bank 几何合法分配，再计算 `pages_per_bank = total_pages / bank_count`、`logical_bank = page_index // pages_per_bank`、`RA = page_index % pages_per_bank`，最后把逻辑 Bank 编译成 FLASH_EPR one-hot `BANK_SEL/BANK_EN`。当前母本为 NM 1024 Page、双 Bank，合法编号固定为 `0..1023`、每 Bank 512 Page：Page 511 → Bank 0/RA 511，Page 512 → Bank 1/RA 0，Page 525 → Bank 1/RA 13，Page 1023 → Bank 1/RA 511。GUI 不应让普通 NM Page 请求手填可由几何推导的 BANK/RA。

当前正式母本同时存在一个必须修正/确认的硬件事实冲突：`FLASH_EPR configs` 被现有解析协议解释为 `RA(offset=0,width=8)`，只能表示0..255；但上述已确认geometry要求每Bank 512 Page，RA必须表示0..511并至少为9bit。旧Generator会把超宽RA静默截断，导致Page256与Page0等地址碰撞。新Product Compiler必须在计划阶段拒绝所有超出RA字段宽度的Page Target；在母本确认RA应为9bit或重新确认Bank geometry之前，`page program PCKB/NCKB NM`两项Required Pattern不得正式生成。

本系列产品的最小写入单位是完整 Page，CA/PA 不参与 Page 选择，在 Page Erase/Program/Read 中语义无效。Generator 必须为确定性向量统一编码 `CA=0`、`PA=0`，GUI/API 不暴露这两个字段；Page Program 阶段 ④的数据位置与总量仅由每条 FBIST CMD 的写入位宽、Page 大小和命令次数推进，不通过递增 CA/PA 寻址。

Page 数据组数量不得硬编码，必须读取 Excel 产品事实并校验：`program_group_count = PAGE_BYTES * 8 / program_bit`，`read_group_count = PAGE_BYTES * 8 / read_bit`；`PAGE_BYTES`、`program_bit`、`read_bit` 必须为正数且两次除法都必须整除，否则在生成前报配置错误。当前母本 256 Byte/Page、program bit 32、read bit 64，因此 Stage ④为64个32-bit写入数据组，Page Read 为32个64-bit Compare数据组；这些数值不是跨产品常量。

Page Scope 的冗余阵列选择固定为关闭：Page Erase、Page Program、Page Read 均统一编码 `RED0_EN=RED1_EN=RED2_EN=RED3_EN=0`。这些字段是 Generator 的 Page policy，不进入 GUI/API 请求；如未来产品需要 RED Page 操作，应以新的显式能力/Region 规则扩展，不能让用户在当前 Page 请求中任意翻转。

Page Scope 的 `OPR_SEL` 由阶段固定：Pre-Program 使用 `00(pre)`，Erase 使用 `10(erase)`，Program 的 Clear/Write/Program 上下文使用 `01(program)`，Read Compare 使用 `00(pre/no program pulse)`。Erase 后的 Clear Page Latches 不消费 OPR 语义，可保持 Erase 上下文的 `10`；GUI/API 不暴露 `OPR_SEL`，Generator 必须从 operation stage 派生。

Page MODE 生命周期固定如下。Erase：配置 `PEP=0111`，再以 `program page=1100` 执行 Pre-Program SEQ，随后以 `erase page=1000` 执行 Erase SEQ，再执行 `clear page latches=0001`，最后回到 `normal mode=0101`。Program：`clear page latches=0001 → normal mode=0101 → write page latches=0110 → PageData → program page=1100` 执行 Program SEQ，最后回到 `normal mode=0101`。Read Compare：配置 `normal mode=0101`，只发送一次 `Cmd=1000 read_mode`，随后输出所有 Compare 数据组。MODE 均由 operation stage 派生，不向 GUI/API 暴露。

Page Read 的读配置固定为 Generator policy：`READ_MODE=1`、`ADDR_MODE=0`、`COMP_MODE=0`、`COMP_DATA=00000000`、`COMPARE_NUMBER=0`。该路径不使用 Flash 内部 Compare FSM/固定比较数据；一次 `Cmd=1000` 后，由 Pattern 按 canonical PageData 生成的 H/L 向量逐位比较所有 read groups，因此能支持任意完整页期望值。上述字段不进入 GUI/API。

Page Read 同样以完整 Page 为原子操作。每个 Page 先独立完成 Region/BANK/AXA/RA 配置，再读取整页；只发送一次 `Cmd=1000 read_mode` 启动读取，随后输出 `read_group_count = PAGE_BYTES * 8 / read_bit` 个 Compare 数据组，每组 framing 为 `1bit 1 + 1bit L + read_bit 数据`。Generator 必须验证整除且拒绝不合法的产品几何。当前母本 `PAGE_BYTES=256`、`read_bit=64`，因此是一条 read_mode CMD 后跟 32 组 `1 + L + 64-bit Compare Data`，不是32条 read CMD；16组只覆盖128 Byte，不能代表完整 Page。多 Page Read 严格按 `pages[]` 顺序逐页闭合，不合并成跨页连续读。

Page Program 的写入数据与 Page Read 的期望 Compare 数据复用同一个 canonical `PageData`。第一版同时支持内置背景 `00`、`FF`、`PCKB`、`NCKB`，以及调用方提供的任意完整 Page payload；自定义 payload 长度必须严格等于产品母本的 `PAGE_BYTES`（当前 256 Byte），不接受部分页数据、隐式补齐或截断。GUI/API 以按 Page Word 地址递增排列的 32-bit Word 数值作为数据语义，不要求用户输入地址小端 byte array；文本 `44 33 22 11` 与 Word literal `0x44332211` 等价，均规范化为数值 Word `0x44332211` 并按 `bit31→bit0` 发送/比较。完整 Page 可提交 64 个 Word literal，或 256 个按每四字节一组、MSB→LSB 书写的 byte token。共享 serializer 对 Program/Read 分别按 `program_bit/read_bit` 划分 CMD，CMD 覆盖的 Word 地址区间保持递增，但每个 CMD 内按高地址 32-bit Word 到低地址 32-bit Word发送；平台 Adapter 不得重新解释或重排数据。

跨 Word 顺序已冻结。例如 `Word0=0x44332211`、`Word1=0x88776655`：当 `program_bit=32` 时依次由 CMD0 发送 Word0、CMD1 发送 Word1；当 `read_bit=64` 时同一 CMD 内先比较高地址 Word1，再比较低地址 Word0。该顺序由共享 serializer 生成，Compare 数据必须与 Program 数据使用完全相同的 PageData 解释。

Page PCKB/NCKB 是 block chessboard，不是逐 bit 或逐 Word 棋盘。Generator 从 Excel `chessboard_data` 读取 block 大小与起始值；当前 PCKB=`8 bytes 0`、NCKB=`8 bytes 1`，因此 PCKB 在每个 Page 内按 `8B 00 → 8B FF` 循环，NCKB 为其逐位反相 `8B FF → 8B 00`，周期16 Byte。Page Scope 中相位作用域严格为单个 Page：每进入一个新 Page，PCKB 都从0块重新开始，NCKB都从1块重新开始，不跨 Page 延续；Bulk EVEN_ODD 是明确例外，由 Page parity 选择正相/反相。Program 与 Compare Read 必须从同一生成后的 canonical PageData 序列化。

第一版一份 Page Pattern 只拥有一份共享 `PageData`，按相同规则应用到其有序 `pages[]` 中的每个 Page；Page Target 不允许携带逐页 data override。若不同 Page 需要不同数据，调用方必须拆成不同 Pattern Generation Request/输出 identity，Generator 不在单个 Pattern 内隐式拼接异构 PageData。

当一份 Page Pattern 包含多个 `pages[]` 时，必须按列表顺序逐页闭合完整操作，禁止把同一阶段跨 Page 批处理：Page Erase 对每一页独立执行 `Pre-Program → Erase → Clear Page Latches`（阶段 `1→2→3`），Page Program 对每一页独立执行 `Clear Page Latches → Write Page Latches → Program`（阶段 `3→4→5`），完成当前页后才能进入下一页。

**FBIST Flash EPR Cycle**：
Flash 擦写生成的基础五阶段流程为：① Pre-Program selected memory（先配置 FLASH EPR `MODE=PEP`，再使用目标 Scope 对应的 Program MODE 执行 canonical SEQ：Page=`1100`、Bulk All=`1111`、Sector=`1101`）；② 按 Page/Bulk/Sector Scope 选择相应 Erase MODE 并擦除目标；③ 使用 `clear page latches` MODE 清空 page latches；④ 使用 `write page latches` 流程把数据写入对应 latches，每次 FBIST CMD 的数据位数由产品的 command/program-bit 配置决定；⑤ 按 Page/Bulk/Sector Scope 选择相应 Program MODE，通过 SEQ 把 latch 内容真正写入目标 memory。

Erase Operation 只组合阶段 `1 → 2 → 3`；Program Operation 只组合阶段 `3 → 4 → 5`。阶段 1、2、5 是 SEQ-driven operation，必须执行 canonical SEQ；阶段 3、4 不是 SEQ operation，不得误套 SEQ。现有 `SEQ_1230()` 的硬件序列为 `SEQ=01 → 10 → 10 → 10 → 11 → 00`、对应 `PE=0 → 0 → 1 → 0 → 0 → 0`，阶段按 pre/erase/program 选择 MODE、等待时序和标签策略。新生成器应把这五个阶段建成共享流程原语，再由 Erase/Program 与 Page/Bulk/Sector 组合，避免各模式复制一套擦写流程。

**Load Map**：
消费已经构建或恢复的完整目标页 REG，根据 ADDR_MAP 将全部适用页同时动态装载到对应页面的 Program 与 Read/Compare Pattern；目标页可以包含 UID。它不重新拼接 REG、不读取 Final DAC，也不运行 Pattern。Trimdata 早写 UID 由业务计划只选择本阶段的 Trim 寄存器，并把 PASS ID 设为全 1；Verify 字段及其默认值均不装填，未选择字段的 Pattern Memory 保持原状。普通 Trimdata Read 仍装载全部适用寄存器。

**增量页面装载（COMMIT 内部能力）**：
消费 COMMIT 选定的变化字段及更新后的 REG，只重新装载受影响页面的 Program 与 Read/Compare Pattern；未变化页面沿用此前 LOADMAP 建立的 Pattern 状态。它与 LOADMAP 共用底层字段装载逻辑，但不再作为独立 `RELOADMAP` Recipe 暴露给填写人。

**Check OTP**：
消费已恢复并重新装载到 Pattern 的目标 OTP REG，逐页运行 Read/Compare Pattern，最后退出或下电。它确认捕获数据经 ADDR_MAP 解码和 REG 拼接后仍与芯片内容一致，不执行 erase 或 program，也不准备 final-vposp；进入 FBIST mode 后必须先运行前序 SETVPOSP 已准备的 `set_all_final_vposp`，具体页面集合由调用计划决定。

BakeID 前置 CHECKOTP 的失败 Site 由测试机运行流程自行判 FAIL 并停止后续执行。生成器不额外建立失败 Gate、不再次筛选 Site，也不为该前置检查失败插入 UID 重擦；这不改变 READID 产生的 Bake 待补写 Gate，或实际 PGMOTP 写后回读失败的重擦规则。

**Program OTP**：
消费 Load Map/Commit 已准备的页面 Pattern，逐页执行目标 OTP 页的 erase、program 和 read/check，最后下电。它不准备 final-vposp；进入 FBIST mode 后必须先运行前序 SETVPOSP 已准备的 `set_all_final_vposp`。目标可以是普通数据页或 UID 页；它不解释字段来源或重新装载页面数据。正式 UID/BakeID 写入具有防假 PASS 的失败清理规则：任一 Site 写入后回读失败时，对该失败 Site 再次擦除 UID Page，再按当前 FLOW 的失败策略判退；失败重擦同样必须遵守 Flash Pattern 的 final-vposp 前置规则。该规则同样适用于 CP3 与 BakeID，不再保留按站点或 item 分叉的历史差异。普通 OTP 页不因该规则自动追加失败擦除。Trimdata 早写 UID 时 PASS ID 为全 1，不执行失败 Site 快照与重擦。

**Read OTP Map**：
通过 Capture 读取调用计划选定的 OTP 页面，按 ADDR_MAP 解码捕获数据并恢复对应完整 REG。普通 Trimdata Read 调用它读取当前 CP 适用的普通数据页；UID/BakeID 流程调用同一模块读取 UID Page，不新增 READUIDMAP。Capture、解码和 REG 恢复机制相同；Bake 的恢复字段集合由上层计划明确筛选，未恢复字段仍占用原 Capture 布局位置，不得压缩偏移。Capture 不使用 VPOSP；该动作只建立页面寄存器状态，不隐含 Final DAC 恢复或 Pattern 准备。

`READOTPMAP` 的放置位置由填写人决定，可以位于 Trimdata Read、BakeID 或最后的 Pgm CP ID 等节点。普通跨测试项页面读取按 CP 维护已读取页面集合，每次调用只 Capture 当前计划需要且尚未读取的页面；但同一个 `TRIMDATA_READ` 内每个显式验证段都是独立的运行时验证，必须实际执行自己的 Capture，不受该全 CP 去重影响。若 BakeID 流程已读取 UID Page，后续 UID 消费者可复用该状态；`TRIMDATA_READ` 始终排除 UID Page。所有行为都基于解析后的页面身份和 Typed Kind 契约，不根据测试项名称猜测，也不由生成器自动插入缺失模块。

`READOTPMAP` 支持默认与显式页面选择：无参数时请求当前 CP 的全部适用 OTP 页面；`READOTPMAP(UID)` 只请求 UID Page。两者在执行前都减去本 CP 已读取页面集合，因此先执行 `READOTPMAP(UID)`、后执行无参数 `READOTPMAP` 时，后者只 Capture 其余尚未读取页面。更一般的页面参数格式留到实现时确定。

**Trimdata Read**：
必要主干为 Read OTP Map → Load Map → Set All Final Vposp → Check OTP。四个 Module 必须存在且保持顺序，但可重复，也可在任意位置插入具有 typed plan 且通过状态闭包校验的其他共享 Module；整个测试项仍只有一个 Definition、Schedule、Bin 与失败出口。

**内部页面更新与公开 COMMIT**：
页面字段合入、变化字段跟踪和局部 Pattern 重装载仍是生成器内部必需能力，但不再作为 `UPDATEMAP/RELOADMAP` 两个公开 Recipe 步骤要求填写人组合。公开 `COMMIT` 一次表达“选择值来源 → 合入 Page Image → 增量更新目标 Program/Read Pattern”；内部实现必须继续保留完整页面的其他字段，并只标记实际受影响页面。`COMMIT` 不物理写入。

**Program OTP 提交范围**：
Program OTP 对当前提交节点需要落地的全部目标页执行完整 erase、program 和 read/check，目标页可以包含 UID。页面是否参与由本节点要提交的字段决定，不能按 UID/非 UID 整页排除。

无参数 `PGMOTP` 的默认目标页由当前测试项语境确定：`type=uid` 默认只提交 UID Page；Trim Data 节点默认提交其业务目标页。保留 `PGMOTP(...)` 显式页面形式，以支持未来在单一节点指定或覆盖提交集合，具体参数语法留到实现前讨论；不新增 `PGMUID` 模块。

`type=uid` 统一进入一个 UID Typed Kind，普通 CP ID 默认 Recipe 为 `COMMIT → PGMOTP(UID)`；BakeID 必须显式填写 `READOTPMAP(UID) → LOADMAP(UID) → CHECKOTP(UID) → COMMIT → PGMOTP(UID)`，BUILDUID 也必须显式填写完整链路。显式 Recipe 覆盖默认并接受依赖与顺序预检。无参数 COMMIT 从标准 item 与上层目标计划取得最终 PASS 字段、完整值及待补写 Site 状态；不能绑定固定 CP 编号。Recipe 全展开示例母本属于后续填写参考，不修改当前正式母本。

`BUILDUID` 不属于任何 CP 或 item 的隐式默认动作，凡需要生成制造追溯 UID 的节点都必须在 Recipe 中显式填写。由于显式 Recipe 覆盖整条默认 Recipe，填写 `BUILDUID` 时应同时写出完整后续链路，例如 `BUILDUID → COMMIT → PGMOTP(UID)`；生成器不因出现 BUILDUID 而暗中追加其他模块。

**Trimdata Rewrite**：
当前候选默认 Recipe 为 `COMMIT → PGMOTP`。COMMIT 只处理当站 `type=verify + OTP=yes` 新产生的 EXPORT 值：将已编码测试值合入 REG，并局部刷新相关页的 Program 与 Read/Compare Pattern；当站不存在这类字段时，COMMIT 不产生装载动作。没有新字段时 PGMOTP 是否仍必须执行尚待讨论，不能提前固化。若产品流程还需要重新读取、更新或准备其他状态，填写人可以显式组合相应模块；生成器只校验所填模块的顺序和前置依赖，不因测试项名称隐式补齐其他步骤。

**UID 页协同**：
UID 页可同时承载 Trim DAC、Verify 值、CP/Bake ID 与 Pass Flag；其读取、字段保留、分阶段提交和失败处理必须与 ID/UID 流程共同定义。在该流程完成讨论前，不从 Trim Data 模块单方面决定 UID 页的完整行为。

**ID 检查入口**：
`type=id` 统一进入 ID Typed Kind，`Read_<target>` 默认展开为 `READID`，`Check_<target>` 默认展开为 `CHECKID`。检查目标从完整、可校验的 item 命名协议解析，不要求 Recipe/sub 重复声明；不能用 `"bake" in item` 等模糊字符串判断。无法解析或目标不受支持时在 preflight 报错。

**ID 检查失败策略**：
`type=id` 的 item 前缀同时声明失败处理。`Check_<target>` 对目标 ID 做强制校验，失败按该 FLOW 行的 bin 策略判退；`Read_<target>` 读取目标并产生逐 Site 状态，失败不直接判退，而是供后续对应写入流程决定哪些 Site 需要补写，例如 `Read_CP1_bakeID` 产生 CP1 BakeID 待写状态。生成器必须按完整命名协议解析前缀和目标，不能从任意字符串片段猜测策略。

**UID 提交节点**：
`type=uid` 的 `Pgm_<target>_Read` 测试项共同核心是一次完整的 UID Page 更新与回读闭环：先把当前节点应新增或修改的 UID、ID、Pass Flag 等字段写入 UID Page，再立即回读并检查写入结果。它既不是单独 PGM，也不是单独 Read；生成器应把目标与阶段编译成统一 UID 提交计划，平台层只适配具体 pattern/capture API。

UID Page 的字段合入复用通用 `COMMIT`，不新增 UID 或 BakeID 专用更新模块。BakeID 先通过共享 READOTPMAP/LOADMAP 恢复、装填上道 CP 需要保留的字段并完成防呆检查，再由无参数 COMMIT 只对待补写 Site 把 Pass Flag 更新为标准 item 对应的最终完整值；随后 `PGMOTP(UID)` 完成物理写入与回读。

在 `type=uid` 节点使用无参数 `COMMIT` 时，生成器从标准 item 名解析当前目标，并自动选择相应 ID/Pass Flag 字段、完整终值和 Site 门控，例如 `Pgm_CP1_Bakeid` 自动关联 `Read_Cp1_Bakeid` 的待补写状态。`COMMIT(PASS_FLAG=0x65BAFFFF)` 等显式形式允许特殊产品或调试覆盖；显式参数只改变本次 Page Image/Pattern 字段更新，不改变后续 `PGMOTP` 的物理提交职责。

普通 `Pgm_CPxID_Read` 的无参数 `COMMIT` 只合入当前 CP 新产生或修改的 `UID=yes` EXPORT 值、当前标准 item 对应的 ID/Pass Flag，以及同一 Recipe 中 `BUILDUID` 本次生成的完整追溯字段。前站已经写入的 UID 字段只保留 `READOTPMAP` 恢复值，不从当前程序的全局变量、默认值或同名后站字段重新取值覆盖。

`type=uid` 中 item 带标准 `bakeID` 目标的节点统一归为 BakeID 流程类型。它自动关联同目标 `Read_<target>` 产生的逐 Site 待补写状态，填写人无需在 Recipe 中再次声明条件。`READOTPMAP`、保留字段恢复以及第一次页面防呆检查面向全部有效 Site；只有最终 BakeID Flag 更新与物理提交受待补写状态门控。该关联必须按解析后的标准目标建立，不使用任意 `"bake" in item` 子串碰撞来绑定。

BakeID 节点发生在当前 CP 自身 Trim/Verify 之前时，属于当前 CP 但尚未产生的 UID 字段不进入本次 COMMIT 的有效更新集合；COMMIT 内部的增量装载在 Read/Compare Pattern 中将这些字段设置为 `X/don't care`，本次 PGMOTP 不校验其内容；待当前 CP 正常 UID 提交时再写入真实值并严格回读比较。该规则由字段的起算 CP 与当前 Flow 位置判定，是公共阶段有效性语义，不是 Chroma/S100 平台特例。

2026-08-27 CHECKOTP 复测裁决：用户与领导确认，Bake 前置 CHECKOTP 必须保留，不能按 golden 注释取消。LOADMAP 每次执行都把本阶段不应比较的制造信息（LOTID、Slot、XY、日期、版本、Project 等）设为 Read=X，不能依赖 Pattern 初始值；上道 CP 保留字段仍按恢复值严格比较。上层根据普通 CP ID 完整 identity label 计划补齐遮蔽，已由临时 PASS/后续 PASS 清理覆盖的标签不得重复写。新增遮蔽只改 Read；原有防假 PASS 的 Program 全1规则不变。正式 BUILDUID/COMMIT 以真实字段值恢复 Read 比较。

2026-08-27 BakeID 审阅修正：只恢复上道 CP 需要保留的 Trim/Verify 字段，不恢复整页镜像/保留位；Program/Read 统一使用当前 CP 普通 ID Pattern，独立 Bake Check 只用于 READID。当前 CP 尚未产生的 Trim/Verify 不装填 Program，只在 Read 遮蔽；当前 CP 后续制造/PASS 字段需在共享 Program Pattern 置全 1、Read 置 X，防止提前写入当前站通过标记。正式 UID COMMIT 再恢复其正式值。筛选、完整名称和目标常量只由上层编译计划提供。

2026-08-13 新程序已澄清 BakeID 中间序列：先通过既有 UID Capture/REG 布局恢复上道 CP 需要保留的字段，把前站正常 Pass Flag 仅写入 Program Pattern，并在 Read Pattern 对该 Flag 使用 `X/don't care`；随后运行一次 UID Read/Compare Pattern，检查其他应保留字段。该临时 Flag 不发生物理写入。之后只对 `Read_<target>` 标记为待补写的 Site，把 Flag 改成最终 BakeID 值并执行 UID Page erase/program/read。最终回读失败时仍必须对失败 Site 再次擦除 UID Page，再按 FLOW 失败策略判退；该失败重擦与普通 CP ID、CP3 使用同一条 `PGMOTP(UID)` 规则。

**Build UID**：
2026-08-27：用户已审阅review_v6并确认本节点PASS；UID与ID Kind及READID/CHECKID/BUILDUID Module已注册。PASS指当前实现、定向测试、厂商编译与生成物审阅，不等于完整CP或机台验收。

八个Word全局数组及拼接移位统一使用`uint32_t`，整字常量使用`U`后缀；类型由上层`BuildUidWord.value_type`传给声明和`CommitFieldValue`。S100宏声明早于`stdint.h`，参数沿用golden的`unsigned int*`（`write_pat_temp_long`）及`unsigned int`（固定值），保证到double GB前不经过signed int；普通16-bit Trim的`int*`接口不变。宏名中的long不代表使用long类型。

`BUILDUID` 用于生成最终制造追溯 UID 数据，包括 Lot ID、Wafer Slot、XY 坐标、日期、测试厂、项目/程序版本以及按既定字节序列计算的 CRC 等字段。它只计算上层计划指定的待写Word，不修改 REG、不装载 Pattern，也不物理写入；Pass Flag 由上层UID目标计划确定，作为Word固定基底与制造字段拼接，后续 `COMMIT` 才装填完整Word。最终 UID 节点可组合为 `BUILDUID → COMMIT → PGMOTP(UID)`。

BUILDUID 使用的批次号由测试机自动提供；生成器不另行裁决 Lot ID 与 Wafer ID 的业务来源，不擅自统一或替换各平台既有获取方式。平台负责取得数据，BUILDUID 消费已提供的数据形成追溯字段；迁移时不擅自修正基准中的平台差异；S100现有Slot装填/CRC来源不同及末Site CRC广播等已记录在交接，不能宣称双平台编码等价。

`BUILDUID` 的运行位置决定哪一道 CP 承担最终 UID 构建，不再硬编码为 CP3。生成器应先编译统一的 BuildUidPlan，再由它驱动完整依赖闭包：UID 字段/变量模型、全局变量声明、startup/test_start 的平台数据获取与校验、CRC helper、当前测试项的字段生成，以及 flash pattern 的目标标签/位段绑定。任何一层都不能再以 `CP3` 或 `Pgm_CP3ID_Read` 作为启用条件。将来若 CP4 是最后一道 CP，只需把模块放在 CP4 的目标 UID 节点；实际可写字段、Pass Flag 布局及位宽仍必须来自 ADDR_MAP/UID 目标定义，模块不会凭空扩展物理 UID 布局。代码库中的其他 CP3 条件（例如 PDR、VTE、FREQ）不属于该依赖闭包，不能随本模块重构一并替换。

`BUILDUID` 对程序版本字段采用 ADDR_MAP 驱动：只生成并写入当前物理 UID 布局明确存在的版本字段。即使未来由 CP4 执行 BUILDUID，也不会自动新增 `CP3_VERSION` 或按站点数量扩展字段；新版本字段必须由新产品母本的 ADDR_MAP/UID 目标定义明确提供。

当前 CP 显式使用 `BUILDUID` 时，由上层 BuildUidModulePlan 提供依赖闭包，生成器通过既有 startup/test_start Hook 准备平台数据。读取、缓存和校验时机遵循用户指定的各平台基准：Chroma 在 test_start 取得 XY、按 LOAD_ID_FLAG 获取/补录 Wafer/Lot/Slot，并在 BUILDUID 内再次读取及校验 XY；S100 使用既有系统变量，并在 BUILDUID 中解析 Wafer Slot。不得用“BUILDUID只能消费缓存”改写已验证行为；这些都是测试机运行时取数，不是生成器重读母本。

BUILDUID 原生迁移保持各平台指定基准的字段排列、XY 坐标编码、日期/版本编码、CRC 算法及输入字节顺序不变，只迁移生成结构。Chroma 基准为用户指定的 `temp/Chroma_最新程序/V1.0/` 下已验证 CP3 PLN；S100 暂无上机基准，按当前生成器 `3329e06` 的实现保留，不标为已上机验证。精确路径及文件哈希见 `.Codex/handoffs/2026-08-27-native-generator-remaining-work.md`。若双平台存在实质差异，须单独列出具体差异核对，不擅自统一或修改编码规则。

startup/test_start 数据获取、LOAD_ID_FLAG 缓存及触发逻辑按上述各平台基准保留；Chroma 已由用户确认现场验证，S100 的现场状态未知。原生迁移不重新设计换片刷新机制，也不新增检测或重读策略。

Chroma 的 BUILDUID 启动数据准备保留既有人工补录入口：自动获取不到合法 Wafer ID 时允许操作员补录 Wafer/Lot 信息；补录并校验合法后继续，补录后仍不合法则中止。不能在原生迁移时删除该交互并直接中止，也不据此向其他平台新增未约定的交互。

`BUILDUID` 不是产品级唯一动作：特殊流程可以在 CP2 提前构建并写入 UID，CP3 仍再次生成本 CP 所需的 UID 数据。唯一性只在单个 CP 内约束为最多一个使用点；不同 CP 可以各自使用一次，并分别生成该 CP 所需的全局变量、startup/test_start 数据准备和 BuildUidPlan。跨 CP 的字段覆盖或保留关系仍由各节点的 ADDR_MAP、COMMIT 与提交顺序决定。

每次执行 `BUILDUID` 都重新生成并覆盖 ADDR_MAP 中归属于 BUILDUID 的完整追溯字段集合，而不是只补当前 CP 的增量字段。后站使用本次程序开始时重新取得并缓存的 Wafer/Lot/Slot/XY，加上当前日期、厂别和版本重新计算全部追溯字段与 CRC；同一 UID Page 内不属于 BUILDUID 的 Trim、Verify、ID/Pass Flag 等字段仍由 READOTPMAP 保留或由各自模块更新。

**VPOSP 刷新决策**：
是否需要当前 final-vposp 由填写人在 Recipe 中以 SETVPOSP 显式声明；SETVPOSP 根据 Pattern 快照的逐 Pump dirty 状态准备或刷新所需字段。Trim/Verify 用途允许 clean 调用直接 RUN；NM/OTP Flash 用途只准备，由消费者在 enter FBIST mode 后运行已准备的快照。任何可能修改 Pump 的 typed operation 都必须只使对应 Pump 字段失效；未知的条件式修改按可能修改处理，不能由 renderer 根据 item 名推断。

**按需恢复 DAC**：
从已恢复 REG 中提取某个后续动作实际需要的 Final DAC。它不是 Trimdata Read 的默认组成部分；DAC Write 在当前 CP 没有对应 Trim 时自行执行该恢复，在已有当前 CP Trim 时直接使用现场 Final DAC。

**DAC_WRITE**：
Verify 测量前，把已有或指定的逐 Site DAC 值动态写入当前逻辑测试项的 Trim DAC Pattern，并执行该 Pattern 一次。Pattern、动态字段 label、位宽、SWD pin 与 RUN 资源全部由上层 FBIST Pattern Plan/catalog 固化；Module/Adapter 不读取母本、Pattern 文本或全局状态。`ENTER(ROLE=TRIM)` 必须使用 Pattern Sheet 的 `trim mode` 角色（例如 Mr_VDDD_DC 使用 `enter_mr_vddd_dc`），不得退回同 item 的 verify mode Pattern。当前 CP 已产生的 DAC_FINAL 必须位于消费者之前；否则只能消费此前 READOTPMAP 已恢复的 ADDR_MAP Page Image/REG 位段；显式二进制参数作为固定值覆盖。CP1 Mr_VDDD_DC 直接消费前序现场 DAC_FINAL，CP2 Mr_VDDD_DC 从已恢复的 `REG_PMU_TRIM2[7:4]` 取得当前值；二者结构不得混同。缺少前序生产者/恢复、多个无法证明一致的物理恢复候选、Pattern 动态字段缺失或位宽不一致均阻断生成。

**DAC_FINAL**：
Trim 搜索完成后的最终 DAC 值，也是 Trim 项被 UID 收集时的数据来源。

**产品程序计划**：
整本母本经过一次完整语义编译后得到的产品级计划。它统一解析共享的 ADDR_MAP、Pattern、字段来源和跨 CP 关系，并包含各道 CP 相互独立的 CP 程序计划。Chroma、S100、LAB 与 Production 都消费同一份产品程序计划，不重新解释母本业务语义。

**CP 程序计划**：
产品程序计划中一道 CP 的完整程序语义，包括该 CP 的有序测试项、Recipe、跨测试项状态、程序依赖以及调度关系。它是独立输出和执行的程序单位，但共享信息及跨 CP 关系由产品程序计划统一编译，不由各 CP 重复扫描母本。

**渲染计划**：
产品程序计划针对一个明确平台和生成模式形成的物理产物计划。平台与 LAB/Production 属于渲染目标，不属于共享 CP 业务语义；Chroma/S100 的物理段落顺序、最终文件清单、输出路径和原子替换范围在渲染计划中确定。CP 程序计划只声明平台无关的资源需求，不包含 `.pln/.pat/.dec` 或 `.prg/.sd/.hed/.tim/.prj` 等最终文件布局。

**程序依赖闭包**：
整本母本统一分析后，为每道 CP 根据实际测试项及其 Recipe 推导出的最小完整依赖集合，包括运行时变量、startup 数据、helper、Pattern 和其他程序资源。同一道 CP 内对依赖去重并检查缺失来源、类型、位宽和语义冲突；未被该 CP 使用的模块依赖不生成。不同 CP 是独立程序，不共享运行时全局变量；跨 CP 数据只能通过 OTP/UID、ADDR_MAP 恢复或明确的外部输入传递。

**OTP 页引擎**：
管理 OTP/UID Page 的完整 Page Image、REG 来源、字段保留与修改、dirty page、Program/Read Pattern 准备、Capture 去重以及物理提交和 UID 失败 Site 重擦。`BUILDMAP/READOTPMAP/LOADMAP/COMMIT/CHECKOTP/PGMOTP` 共享该页面状态；它不决定 Pump DAC，也不暗中准备或执行 SETVPOSP。

`BUILDMAP` 根据 ADDR_MAP 定义的页面布局及其有效当前值/默认值来源建立完整 Page Image；`READOTPMAP` 根据芯片物理回读内容建立完整 Page Image。`COMMIT` 只在已有完整 Page Image 上派生新版本，不负责创建页面，也不允许在回读字段缺失时用 ADDR_MAP 默认值静默补齐。`LOADMAP` 或 `COMMIT` 产生的 Program/Read Pattern 必须绑定准确的 Page Image 版本，`CHECKOTP/PGMOTP` 不得消费旧版本 Pattern。

**Compare Mask**：
某一次 `CHECKOTP` 或写后回读判断所使用的临时比较视图。`X/don't care` 只改变当前消费者是否比较某字段，不改变完整 Page Image，也不修改可复用的基础 Read Pattern；测试项结束后该视图自然失效，不依赖“先改 Pattern、后恢复 Pattern”的隐藏状态。

**页面状态去重**：
`READOTPMAP` 是否执行物理 Capture 取决于当前物理页面状态是否已知，而不是只判断同名模块是否出现过。首次 Capture 建立已知状态；后续读取在状态仍已知时复用当前 Page Image。`COMMIT` 只改变计划镜像，不改变芯片；`PGMOTP` 成功后把已提交版本确立为新的已知物理状态。若中间动作可能改变页面但最终内容未知，则该页失效，后续 `READOTPMAP` 必须重新 Capture。普通 `RUN(pattern)` 默认不修改 OTP；会修改 OTP 的 Pattern 必须显式声明受影响页面，否则母本预检报错。

Page Image 不按每个 Site 复制完整状态。普通流程共享一份面向全部有效 Site 的基础 Page Image；只有 Bake 最终补写使用受对应 Gate 控制的字段/Site 差异层。这样保留 Bake 的选择性写入语义，同时避免建立没有业务必要的通用逐 Site 页面状态机。

**平台符号表**：
CP 程序计划先以语义身份描述运行值和所需资源，平台渲染计划再为每个语义变量唯一分配 Chroma/S100 具体标识符。全局声明、Startup、Helper 和测试项代码必须共同引用同一个 SymbolRef；业务 Adapter/Writer 不得从 FLOW item 重新猜测或自行拼接 `REG_...` 等变量名。母本预检/渲染规划统一检查缺失来源、重名、类型/位宽/作用域冲突及跨 CP 非法引用。测试机固定 API 标识符只能作为明确注册的平台常量存在。

中央全局变量生成 Module 按已编译声明顺序输出；连续相同 C 类型的变量采用 DAC_FINAL 既有格式合并声明，每行最多四个变量，类型变化或到达四个时换行。业务 Module 不自行控制该物理排版。

**COMMIT 合并边界**：
语义计划按 Recipe 顺序保留每一次 `COMMIT`，并为其派生的 Page Image 记录独立版本和字段来源。只有当中间版本没有被 `CHECKOTP`、`PGMOTP`、读取目标 Pattern 的 `RUN` 或其他已声明消费者观察时，平台渲染器才可把连续字段 RMW 与 Pattern 刷新合并。连续写同一字段按顺序以后值为准；若前值从未被消费，母本预检给出 WARNING，不静默吞掉可能的填写错误。

**生成器与测试机运行边界**：
生成器负责产出业务语义正确、依赖完整且符合目标平台语法/编译约束的测试程序，并生成模块明确规定的内部动作，例如 UID 写后失败 Site 重擦。普通失败发生后的 Site 激活状态、Flow 是否继续、结果累计和 Bin 处理由测试机运行机制负责；生成器不另建跨页面事务、回滚或通用失败传播状态机。

**测试值生命周期**：
普通测试主体产生的结果默认只在当前测试项内有效。`EXPORT`（可带简单数据处理）把该结果提升为可供同一 CP 后续测试项消费的语义值，并由平台符号表生成所需全局声明。`UID/OTP` 列只声明持久化目的地，不承担变量存储；带这些目的地的 Typed 测试项默认 Recipe 包含所需 EXPORT，显式覆盖 Recipe 后若缺少后续必需的值生产者，母本预检报错。`DAC_FINAL`、READOTPMAP 恢复字段、BUILDUID 输出等模块明确的长期值无需重复 EXPORT；同一 EXPORT 值可以同时扇出到 OTP 与 UID 字段。

**测试业务动作计划**：
共享 Product Compiler 的输出粒度停在测试业务动作，而不是平台语句或通用底层指令。Trim、OTP、OS 等 Typed Test Plan 明确算法、参数、Limit、Datalog 身份、Recipe 和依赖；Chroma/S100 Adapter 再通过各自可复用的 Pattern、测量、Datalog、Site Gate、符号、REG RMW、OTP E/P/R、Relay/Power 语句生成器翻译为测试机源码。Adapter 不重新读取母本或决定业务，最终源码必须进入目标平台编译验证。

**程序贡献**：
测试类型 Adapter 和 Recipe 模块 Renderer 返回的结构化渲染输入，包括符号、Lifecycle Hook、Helper/Macro、测试函数、Flow 节点及 Pattern/资源需求。业务模块不得持有最终文件句柄、修改工作目录、临时复制资源或写正式输出路径。平台 Program Assembler 统一合并和冲突检查贡献、排序 Helper 与 FLOW 测试项、生成 Booking/Flow 和最终 Manifest，并映射到平台文件；完整请求只在 staging 产物通过平台编译后由 Publisher 原子发布。

**Pattern 资源身份**：
Pattern 先以标准逻辑身份及内容/参数定义进入程序依赖闭包，再由平台映射扩展名和物理路径。多个完全一致的请求只生成或复制一次；同一逻辑名或平台文件名对应不同来源、内容、参数或用途时阻断并报告冲突，禁止后写覆盖。最终 Manifest 在物化前由 Program Contributions 推导，不通过扫描已有输出目录猜测；未被计划引用的历史或临时资源不进入正式产物。`NM_pattern`、普通 `pattern` 和 ADDR_MAP 动态 Pattern 都遵守该规则，业务依赖来自 Catalog 属性而不是文件名片段。

**Program Skeleton 与 Lifecycle Hook**：
每个平台拥有始终生成的必要程序骨架，例如 Chroma 的 `START_UP/test_start/TEST_PRO/test_end/RELEASE` 及 S100 对应结构；即使没有可选业务依赖也不能裁掉。Product/Feature 依赖只向骨架预定义 Hook 提交结构化动作，例如 BUILDUID 向 `TEST_START` 贡献 Wafer/Lot/Slot 获取，不能创建、删除或绕过必要 Hook。Assembler 对贡献去重、冲突检查并按依赖排序；POWER、SRAM 等继续作为可复用 Helper，不用其函数名冒充 Lifecycle。

**Test Definition 与 Schedule Entry**：
测试函数定义和 Flow 调度是两个引用同一标准测试身份的计划对象。Definition 拥有主体、Effective Recipe、依赖、Datalog 点及明确变体；Schedule Entry 拥有 FLOW 顺序、启用状态、条件、HW/SW Bin 和调用变体。灰色/comment-out 行仍生成定义与资源，但调度保持禁用；连续 `CP+item+type` 组只生成一个定义和调度身份，sub 形成多个 Datalog 点。`OTP_READ` 为定义但不调度，`NM_Data_Read` 为定义并调度；Booking、Bin 和平台 Flow 名统一引用该身份，禁止分别拼接。

Effective Recipe 的测试主体不得使用没有业务含义的通用 `TEST/BODY` 占位来继续隐藏 type/writer 分派。公开主体动作必须表达实际职责，例如开短路测试、测量、Trim 搜索、扫描、运行明确 Pattern 或判断；正式 V1.3 当前 13 个原始 FLOW type 及其细分 Typed Kind 必须逐类依据母本与双平台现有逻辑确定主体动作和默认 Recipe。

**OS 平台范围**：
Chroma 的 OS 测试包含普通 IO Pin、TP Pin 和电源轨 OS；S100 明确只执行普通 IO Pin 与 TP Pin，不执行电源轨 OS。该差异由已注册的平台 OS Profile 在渲染规划前明确解析，不能由 S100 Adapter 静默丢弃共享动作。进入安全 OS 电气状态及测试后的 Relay/Power/Pin 恢复属于 OS 主体的不可省略内部安全行为，不要求填写人用 Recipe 分别拼接。

Typed Kind `OS` 的默认 Effective Recipe 为单一 `OS_TEST`。该主体内部完成平台 Profile 选择、Force/Measure/Compare/Datalog 和安全清理，不另拆公开 `JUDGE`；FLOW relay 以及 Hbin/Sbin 失败路径属于 Test/Schedule Plan。未来新增 OS 能力通过扩展 OsTestPlan 与平台 Profile 接入，不改变当前填写方式。

**PDR Trim**：
`Pdr_Trim` 虽然原始 `type=trim`，但它通过特殊 DAC 顺序和数字状态转换点选择 `PDR_DAC_FINAL`，随后在另一电压条件下验证最终状态，不属于按模拟/频率 target 搜索的通用 Trim。它独立编译为 Typed Kind `PDR_TRIM`，默认 Recipe 为深模块 `PDR_TRIM`；Pattern、VPOSP、Power、Datalog 等作为该模块明确依赖，不在通用 Trim 中堆叠 PDR 分支。

**Standard Trim**：
电压、电流、频率 target 驱动的普通 Trim 统一属于 Typed Kind `STANDARD_TRIM`，测量族只是计划参数。默认 Effective Recipe 为 `ENTER-TRIM-JUDGE`：ENTER 解析模式 Pattern；TRIM 负责 DAC 搜索域/变体及逐点 Set DAC、可选 PE、测量并产出 DAC_FINAL；JUDGE 负责最终 DAC 测量、Limit 和 Datalog。`DEPEND/DAC_ADJ` 可选，显式 Recipe 只按模块契约校验而不受固定组合白名单限制。`DAC_ADJ` 是共享 Recipe Module，不归 Standard Trim 私有。`OTP/UID/PUMP` 仅声明 DAC_FINAL 后续用途，不暗加 COMMIT、PGMOTP 或 SETVPOSP。

`DEPEND`、`DAC_WRITE`、`SETVPOSP` 共用同一 DAC 来源解析规则：在当前 FLOW 位置已经由当前 CP 产生的 DAC_FINAL 优先，否则使用已建立 ADDR_MAP Page Image/REG 中恢复的值；位于后续 Flow 的生产者不可提前消费。无来源时报 ERROR；多个物理恢复候选必须能证明一致或在运行时校验一致，禁止任选其一。`DEPEND` 内部调用目标 item 的 Set DAC Helper，填写人不提供恢复参数。

**FBIST Verify**：
原始 `type=verify` 是混合容器；普通非 PDR/BOR 的 `mode=fbist` 行统一属于 Typed Kind `STANDARD_VERIFY`，不按执行特性组合继续拆分。它完全遵循 Effective Recipe，并由公开 Recipe Module 组合行为。没有 UID/OTP 持久化目的地时默认 Recipe 为 `ENTER-JUDGE`，任一 `UID=yes` 或 `OTP=yes` 时默认为 `ENTER-JUDGE-EXPORT`。JUDGE 自身完成最终 Force/Measure、Limit 和 Datalog；`DAC_WRITE` 是显式可选模块并复用统一 DAC 来源解析器。`PE=erase/program` 作为 JudgePlan 的测量条件，其 NM Pattern 自动声明 VPOSP 前置依赖，不重复成为 Recipe 参数。

**STANDARD_VERIFY 可编排 Module 集（暂定）**：
当前 `STANDARD_VERIFY` 可使用的公开编排词汇为 `ENTER/JUDGE/RUN/EXPORT/DAC_WRITE/COMMIT/DAC_ADJ/SETVPOSP`。这是 Module 合同集合，不是 Verify 子类型枚举，也不排除其他 Typed Kind 拥有其专属 Module；平台 Adapter 只翻译已经编译完成的 Module Plan，不从 item 名或母本反推行为。`ENTER/JUDGE` 复用公共合同，其余 Module 也按共享能力设计，不能绑定某个 Typed Kind 的私有状态。

**DAC Adjust**：
公开 Recipe Module `DAC_ADJ` 消费已解析的当前 DAC 值、调整条件、步进/顺序域与写回目标，产出调整后的 DAC 值。它同时服务 Standard Trim 的后处理和 Verify 的 VT Shift，因此不得依赖 Trim 搜索过程、TrimSpec 私有状态或 item 名称。调整 Pump DAC 后，所有依赖旧值的 VPOSP Pattern 快照必须标记失效；后续若要执行新值对应的 Pattern，必须显式调用 `SETVPOSP`。

动作型 FLOW 使用 `type=adjust, mode=/`，对应 Typed Kind `DAC_ADJUST`。它不是 Verify，不要求 ENTER/JUDGE；必须填写显式 Recipe，第一版严格使用单输入、单目标的 `DAC_ADJ-SETVPOSP-COMMIT`，不隐式 RUN、JUDGE 或 PGMOTP。`DAC_ADJ(A<0.4:VPOSE+2)-SETVPOSP-COMMIT` 表示按 Site 消费同 CP 前序 A 的 RAW EXPORT、沿 VPOSE 合法实际码序加两档并边界饱和、使 VPOSP 快照失效、由本次 dirty SETVPOSP prepare-only，最后让裸 COMMIT 自动把同一 change-set 合入当前 CP 唯一的非 UID Trim 字段并刷新 Program/Read Pattern。目标 DAC 来源遵循统一规则：当前 CP 前序现场 DAC_FINAL 优先，否则必须从已经 READOTPMAP 的 ADDR_MAP REG 恢复；两者均不可用时编译失败。节点12已实现上层 Action Plan、双平台 native assembly 并注册；未来多条件、多目标在上层规则与冲突/原子策略处扩展，不改变单条 `DAC_ADJ` Module 的接口。

**PE Window**：
Verify/Trim 测量中可选的 NM Pattern 开窗条件，由 FLOW 的 `PE` 字段声明为 ERASE、PROGRAM 或空。它属于 Judge Plan 的 typed 测量条件：测量前执行 Pattern 的前半区段、测量后执行后半区段；不是独立 Recipe Module，也不形成新的 Typed Kind。

**PDR Verify**：
`Pdr_Verify` 独立为 Typed Kind `PDR_VERIFY`，默认 Recipe 为深模块 `PDR_VERIFY`。该主体完成 FBIST/PDR 模式进入、PDR_MAX 正常状态检查、PDR_MIN 复位状态检查、两次结果合并、退出和安全清理，并显式声明 DAC、Pattern 与 Power 依赖；不得再通过 item 子串进入普通 JUDGE。正式 V1.3 当前没有 BOR Verify，未来如需支持必须另建 `BOR_VERIFY`，不能复用 PDR 判定。

**Firmware Function Test**：
正式母本中同一 item 由一行 `mode=hex` 下载和一组 `mode=keil` 功能步骤组成的测试项，Typed Kind 为 `FIRMWARE_FUNCTION_TEST`。母本不填写组合Recipe：`mode=hex` 行的Recipe留空，mode本身隐式确定共享业务Module `DOWNLOAD_CODE`；承载KEIL阶段的行填写该阶段Recipe，当前正式功能组均填写 `RUN_SEQUENCE-JUDGE`。Product Compiler按FLOW顺序把同一item的这些行组成有序 `phases[]`，所以该组的有效行为仍是先下载、再执行KEIL阶段，但不存在Recipe跨行继承。`DOWNLOAD_CODE`负责运行已有下载Pattern；`RUN_SEQUENCE`只运行程序并执行进入、触发、等待与Force等动作，`JUDGE`负责最终测量或数字比较。整组只有一个 Definition、Schedule 和 Bin 出口，但下载与功能序列各自保持独立完整上下电会话；Site执行仍由测试机保证，生成器不加运行时Gate。内部计划不写死两行，给未来重复下载、多段运行和等待/检查保留扩展点；复杂阶段选择参数语法在真实需求出现时再定义。`VERIFY_HEX`/`VERIFY_KEIL` 只是待替换的旧执行阶段分类，不是目标业务Kind；KEIL模式测试仍须按真实结果合同分类。

**Firmware Download Pattern**：
由生成器外部流程根据真实固件和下载协议分别提供的Chroma/S100测试机Pattern；`DOWNLOAD_CODE` 只按FLOW `step`中的逻辑资源名绑定并运行，不读取 `.hex`、不把固件转换为PAT/SD。两平台目标资源必须进入产品资源闭包；真实资源缺失时，生成器为目标平台生成带明确标记的最小可编译空向量，并将该资源状态记为 `STUB`，同时诊断所属测试项、平台和逻辑资源名。`STUB` 只用于生成工程的结构与编译验证，不计入真实原生覆盖；任何残留 `STUB` 都必须使生产发布/验收的资源完整性门禁失败。Adapter不得静默跳过资源，已知旧占位资源也按 `STUB` 处理；测试机工程能够编译不代表固件可下载。未来若要支持 `.hex → Pattern`，必须另建具有地址、协议和向量编码事实的Firmware Pattern Generator，不扩张DOWNLOAD_CODE职责。

没有同 item Keil 阶段的独立 `mode=hex` 项属于 Typed Kind `CODE_DOWNLOAD`；其Recipe同样留空，由 `mode=hex` 隐式确定单一有效Module `DOWNLOAD_CODE`，并与 Firmware Function Test 复用同一个下载模块，不复制实现。正式CP3 `Download_Code` 保持独立Definition/Schedule/Bin，不与后序KEIL项合并；生成器不据此建立跨测试项固件依赖。

**Firmware Run Test**：
没有同item下载阶段、且全部业务行为可由通用有序KEIL动作表达的测试项，Typed Kind为 `FIRMWARE_RUN_TEST`。当前正式CP3 `Power_Test`、`RCC_Test`、`RTC_Test` 的每条KEIL数据行均显式填写Recipe `RUN_SEQUENCE-JUDGE`：RUN_SEQUENCE把该行编译为进入、触发、等待、Force及资源生命周期等typed actions，紧随其后的JUDGE按该行强类型结果合同完成标量测量或数字比较；具体动作继续以该行FLOW `step` 为唯一来源，但Native step不再包含结果token `T`。生成器不检查此前是否执行过 `DOWNLOAD_CODE`，也不匹配固件身份。Product Compiler必须完整解析并校验step文本，产出保留row/sub provenance的有序 `KeilPhase[]`；双平台Adapter只翻译这些phase，不得重新解析原始step，也不得把同名Module跨行合并。同item默认只建立一次完整上电会话，但组内必须按FLOW行序执行每行的完整Recipe，即 `RUN(row1)→JUDGE(row1)→RUN(row2)→JUDGE(row2)`，不能先执行全部RUN再在组末判定；只有typed actions中的显式 `RP` 才按其位置重新建立会话。正式 `Power_Test` 三行因此共享Definition、Schedule、Bin和一次上电，却分别在stop0、stop1、standby状态建立后立即测流。需要每行完全独立会话时应拆成不同item或填写明确RP。Power的F动作编译为电源轨 `SupplyForceAction`，标量JUDGE消费已建立的Force lease而不再次Force；该lease由下一条同rail SupplyForce替换，最终由会话cleanup/POWER_OFF释放，不能在sub间把VCC4设0或隐式掉电。Power测流不构成独立Typed Kind。RCC/RTC的外灌时钟由RUN_SEQUENCE建立，并在该行JUDGE之后由phase cleanup释放。分类依据是动作词汇能否完整表达业务且不存在独立状态机或专属资源合同，不按item名称列白名单。像PVD这种依赖迟滞状态和专有多点协议的测试仍使用独立深主体，即使其mode同样为keil。

**KEIL 电平触发时序**：
共享 `RUN_SEQUENCE` action联合中的 `[HL]+` token编译为 `LevelSequenceAction(pin, levels, segment_duration)`；未在token后显式填写宽度时，每个H/L段统一默认 **5ms**，例如 `HL` 表示H 5ms后L 5ms。紧随其后的 `<n><ns|us|ms>` 是每段宽度的显式覆盖并继续有效，正式 `LSI_IWDG_Test` 迁移后的 `PA11:HLHL-500uS-W100` 必须保持500us/段，不能被5ms默认覆盖。裸整数发码、动态X发码、W/F/FS/RP及Pin选择都不属于该时长合同。缺省或显式时长均由Product Compiler固化进typed action，Chroma/S100 Adapter不得保留5ms/1ms的平台默认差异；mode=hex中另有同名Legacy helper的行为不因本合同被顺带改写。

**Native `T` 淘汰与 JUDGE 边界**：
Legacy KEIL step中的终止token `T` 同时隐式选择电压/电流/频率测量、数字比较、SRAM Capture和部分清理，形成第二套结果分派。目标Native语法彻底移除 `T`：`RUN_SEQUENCE`只产出结果之前的typed actions；标量与数字结果由显式 `JUDGE` 完成，普通SRAM结果使用 `SRAM_CAPTURE(...)-JUDGE`，ADC数值使用Capture Module后接 `ADC_JUDGE`，深Recipe则由主体内部结果合同负责。Native step出现 `T` 必须编译失败，不能静默忽略；Legacy迁移器按旧T的实际分支删除T并补写正确Recipe。当前正式母本没有KEIL SRAM Capture实例；10组CP1/CP2 HEX+KEIL功能项以及CP3 Power/RCC/RTC的KEIL阶段均迁为 `RUN_SEQUENCE-JUDGE`。其中固件功能组和RCC/RTC使用 `DigitalCompareJudgePlan`，Power使用 `ScalarMeasurementJudgePlan(CURRENT)`；原数字比较伪单位 `UNIT=pat` 同步改为 `/`，JUDGE由typed meas pin与target合同选择分支。由F等动作建立的资源必须拥有显式lease生命周期，不能重新藏进JUDGE或T：RCC/RTC外灌时钟在该行JUDGE后释放，Power电源rail Force则由下一同rail Force替换或在session末释放。DC/VIH-VIL/FREQ/ADC/OPA/DAC等显式深Recipe的SWD行若step只有旧T，迁移为 `/`且不额外追加JUDGE，因为其主体已经拥有判定；PVD的 `HL-222-15-X` 是必要进入模板，原样保留。

**Power_Test sub边界复位**：
三条sub共用一次上电，但每次从当前sub切换到下一sub时必须且只执行一次DUT reset。Product Compiler根据相邻 `KeilPhase` 保留的sub provenance，在sub值发生变化的边界插入平台无关的 `DutResetAction`，执行顺序固定为 `RUN(current)→JUDGE(current)→DUT_RESET→RUN(next)`；相邻行仍属于同一sub时不复位。首个sub依靠组级上电初始化，不额外插入边界复位；最后一个sub完成JUDGE后直接进入组级cleanup/POWER_OFF，不再执行无后继目标的复位。该动作只重整DUT，不重新上下电，也不释放Power测流持续使用的电源轨Force lease；Chroma与S100 Adapter必须产生等价的NRST复位行为。DUT reset属于phase orchestration合同，不能重新藏回 `T`、`JUDGE` 或平台私有尾处理。
`DutResetAction` 的物理合同统一为 **NRST拉低5ms → 拉高5ms → 结束保持高/释放**。Chroma与S100必须按该合同生成等价资源，不复用正式Chroma Legacy `reset_pattern` 的高1ms→低1ms最终保持低尾处理，也不照搬外层 `temp/UID` 参考程序中低50ms→高50ms→X的非正式S100资源。缺失真实可生成reset资源时必须阻断，不能用可发布STUB掩盖。

**固件下载与执行责任边界**：
`DOWNLOAD_CODE` 只生成下载动作，`RUN_SEQUENCE` 及各KEIL深主体只生成程序执行动作。同一测试项内，生成器按FLOW行顺序组合HEX隐式下载阶段与KEIL显式Recipe阶段；位于不同测试项时，生成器不建立、跟踪或校验当前固件状态，不检查前序下载，不匹配固件身份或版本，也不创建编译期前置闭包、运行时Gate或逐Site跳过逻辑。应下载哪份固件、KEIL项执行哪份程序以及跨测试项顺序是否正确，均由母本填写人和测试流程负责确认；Site是否执行仍由测试机保证。
_避免_：Current Firmware、Firmware Image Preparation、固件版本匹配、下载成功Gate、生成器逐Site固件状态

**Flash 条件与开窗引擎**：
管理 Pump DAC 来源、`set_all_final_vposp` Pattern 逐字段快照及 NM/OTP Flash Pattern 的开窗前置条件。Flash 用途的 `SETVPOSP` 只准备或刷新对应 catalog 字段；`NMLOOP` 等 Flash Pattern 消费者在 enter FBIST mode 后运行已准备的 Pattern 一次，并在同一 FBIST 会话内复用。它不管理 OTP Page Image 或 COMMIT 字段。

**Flash 开窗测试项**：
以 `NMLOOP` 为主体的测试项，默认 Effective Recipe 为 `SETVPOSP-NMLOOP`。SETVPOSP 准备 final-vposp 字段；NMLOOP 消费该快照，在 enter FBIST mode 后运行 `set_all_final_vposp`，再执行 NM 擦写读循环。显式 `NMLOOP` Recipe 合法，但必须在其 FLOW 位置存在由前序测试项准备且未被 Pump 修改失效的快照。

该测试项的标准 Typed Kind 名称为 `FLASH_WINDOW`；`Memory_Wakeup` 仅是现有母本中的历史 item 名，不再作为编译器业务分类名。

`SETVPOSP` 以调用位置的有效 Pump 值维护逐字段 VPOSP Pattern 快照。该快照可以跨测试项复用：首次或部分 Pump 失效时只改写对应 catalog 字段；版本未变时保持现有 Pattern Memory。Trim/Verify 用途保留 clean 快照 RUN；NMLOOP、CHECKOTP、PGMOTP、UID 失败重擦及其他 NM/OTP Flash Pattern 消费者使用 prepare-only 用途，并在 enter FBIST mode 后运行已准备的 final-vposp Pattern 一次。

VPOSP Pattern 准备态属于测试机 Pattern Memory，可跨测试项、DUT `POWER_OFF` 及 FBIST mode 退出/重进复用；只有对应 Pump DAC 可能改变、Pattern 被覆盖或重新生成、或者测试程序重新初始化 Pattern Memory 时才失效。VPOSP 芯片加载态属于 DUT 寄存器状态，不能跨 `POWER_OFF` 或退出 FBIST mode 复用；每次重新上电并进入 FBIST mode 后，Flash Pattern 消费者都必须重新 RUN 已准备的 `set_all_final_vposp`。

需要 VPOSP 的 Pattern 范围以母本 `NM_pattern` Sheet 的 `Pattern name` 列为唯一权威名单。编译器按标准化后的完整 Pattern 身份匹配，不根据 item、CP 或 Pattern 名中的 `nm/erase/read` 等片段猜测。`ADDR_MAP` 继续只负责页面和字段布局，不重复维护该 Pattern 名单。

**Site Scope**：
Recipe 模块默认对当前全部有效 Site 执行，填写人不在 Recipe 中配置 Site 参数。只有 Bake 业务在最终补写阶段使用对应 `Read_<target>` 产生的 Gate：Bake 的 READOTPMAP、LOADMAP、CHECKOTP 仍面向全部有效 Site，最终 COMMIT/PGMOTP 才面向待补写 Site。正式 UID/BakeID 的 PGMOTP 写后回读失败仍对失败 Site 执行统一重擦；PASS ID 全 1 的 Trimdata 早写除外；这是 PGMOTP 的内部失败清理，不属于 Bake Gate。

**Typed 测试项种类**：
根据测试项的业务职责识别出的明确测试族。同一个 FLOW `type` 可以对应不同的 Typed 测试项种类，例如测量 Shmoo、COMMIT Shmoo；普通 UID 与 BakeID 则共用一个 UID Kind，以上层目标计划和 Recipe 区分。允许留空的普通测试项，其默认 Recipe 按 Typed 测试项种类确定，不能只根据原始 `type` 字符串选择；`FIRMWARE_FUNCTION_TEST`、`ADC_TEST` 等compound Kind由多个phase各自的有效Recipe组成，不要求再注册一个会覆盖phase的组级默认Recipe。

**Effective Recipe**：
一个可执行测试项或compound phase进入程序计划前得到的唯一完整Recipe。其来源只能是三种互斥方式之一：① Excel显式Recipe；② 该Typed Kind明确允许留空并注册的默认Recipe；③ 编译器声明的封闭式intrinsic phase规则。当前唯一的intrinsic phase是 `mode=hex`：编译器构造 `DownloadPhase`并固定其有效Module为`DOWNLOAD_CODE`，该行Recipe必须留空；`mode=keil`没有默认值，Recipe必须显式填写。普通Kind只有在声明“允许留空”时才必须提供默认Recipe；compound Kind可完全由phase Recipe组成而没有组级默认。显式Recipe完整覆盖普通Kind默认值，但不得覆盖intrinsic phase；因此HEX行Recipe非空、KEIL行Recipe为空、或其他不允许留空的Kind缺Recipe都必须编译失败。Effective Recipe必须包含对应测试项或phase的主体动作，不能只描述主体前后的附加步骤。平台Adapter只消费已经补全和校验的Effective Recipe/phase plan，不处理空Recipe，也不自行补充业务Module。新架构要求母本存在Recipe列；缺少该列的旧母本不属于新生成器支持范围，继续使用独立保留的历史生成器。

**FLOW Type**：
填写层用于提供基础列Schema、ENTER等模块默认解析上下文及Typed Kind分类事实的测试族标识；它不是平台writer分支，也不直接产生测试机代码。Recipe是否允许留空及如何补全由上面的Effective Recipe来源规则决定，不能一概由原始type补全；`mode=hex`的`DownloadPhase`按mode识别，`mode=keil`要求显式Recipe。`SHMOO`是Recipe执行修饰而不是type，扫描项仍填写其真实基础type。

**OTP 页面流程预设**：
`data`、`read`、`write` 是面向填写人的三个常用 FLOW type 预设，而不是平台执行分支：默认 Recipe 分别为 `LOADMAP-PGMOTP`、`READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP`、`COMMIT-PGMOTP`。它们保留团队熟悉的填写方式并允许 Recipe 留空；显式 Recipe 仍可完整覆盖，最终职责只由 Effective Recipe 及模块契约决定。

**Trimdata Write**：
以 PGMOTP 为物理擦写回读主体的页面写入测试族；COMMIT-PGMOTP 与 LOADMAP-PGMOTP 共用 TRIMDATA_WRITE，前者合入字段增量，后者装载已有完整页面。`data` 只保留为 LOADMAP-PGMOTP 填写预设，不是独立 Typed Kind。

**UID Trim 早写**：
UID 页存在当前 CP 前序已产生的 Trim 数据时，允许随 LOADMAP-PGMOTP 早写；只有 Verify 数据时不早写 UID。早写仍以完整页为单位，对应 PASS ID 字段明确使用 `0xFFFFFFFF` 并同步 Program/Read Compare 期望值，避免仅写 Trim DAC 就产生假 PASS；实际通过标记留到后续正式 ID 写入阶段。早写 LOADMAP 不装填 UID Verify 值，也不额外装填 Verify 默认值；只装填本阶段 Trim 寄存器与全 1 PASS ID。

**Trimdata Read**：
Typed Kind `TRIMDATA_READ`，以共享 Recipe Module `READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP` 形成一个读取验证闭环，并只有一个 Definition、Schedule、Bin 与测试结果边界。它拥有 Module 准入、有序依赖、共同 Page Scope、状态版本与资源闭包，但不拥有这四个 Module 的实现；`READOTPMAP`、`LOADMAP`、`CHECKOTP` 必须与既有 `SETVPOSP` 一样注册为可被其他 Typed Kind 复用的共享 Recipe Module。四个必要 Module 必须存在并满足 `READOTPMAP < LOADMAP < SETVPOSP < CHECKOTP`，但不要求连续相邻；其他共享 Module 可以插入任意位置，只要其 typed 输入、输出、失效效果和结果边界不破坏闭包。必要 Module 允许重复，每个 `CHECKOTP` 都必须绑定它之前最新且完整的 Page Image、LOADMAP Pattern 与 VPOSP 准备版本。生成器把 `CHECKOTP` 的运行时结果接入该测试项的统一失败出口；真实上机时是否失败及测试机如何处理失败 Site 不属于生成器领域。
该 Typed Kind 不绑定 CP2/CP3 或任何固定 CP 编号；当前产品只在 CP2/CP3 使用属于母本数据事实。未来 CP4、CP5、CP6 等只要具有合法的非 UID Trimdata Page、产品事实和完整 Effective Recipe，均使用同一个 `TRIMDATA_READ`。
FLOW `type=read` 直接分类为 `TRIMDATA_READ`，不检查 item 是否命名为 `Trimdata_Read`；item 只提供测试项身份与显示名称，不参与业务路由。未来出现不同读取业务时必须增加新的 FLOW type 或明确分类事实，不得让 `read` 根据 item 名分叉。
_避免_：READ、Trim Data Reader、四个独立测试项

**Trimdata Read 验证段**：
`TRIMDATA_READ` 内从一次 `READOTPMAP` 到闭合它的一次 `CHECKOTP` 的有序 Module 区段。同一验证段内的 `READOTPMAP`、`LOADMAP` 与 `CHECKOTP` 必须绑定完全相同且顺序一致的 Page 集合；不同验证段可以绑定不同 Page 集合。页面只需在段首 `READOTPMAP(...)` 显式填写一次，后续无参数 `LOADMAP/CHECKOTP` 自动沿用；段首也无参数时使用 Product Compiler 根据当前产品确定的默认 Trimdata Page 集合。后续 Module 若重复填写页面，必须与段首完全一致。读取但未在同段完整验证的 Page 属于编译错误，平台 Adapter 不解析继承或推导页面。
同一个 `TRIMDATA_READ` 内每个显式验证段的 `READOTPMAP` 都必须实际执行，即使此前验证段读取过相同 Page，也不得被全 CP captured-page 去重静默消除。该规则不改变 CP 之间的状态隔离，也不顺带修改 UID/BakeID 等其他 Typed Kind 自己的跨测试项复用或去重语义。
每个验证段固定使用两次独立 DUT/FBIST 会话：第一次 `POWER_ON → enter FBIST → READOTPMAP capture → POWER_OFF`；随后在 DUT 断电时执行测试机侧 `LOADMAP → SETVPOSP prepare-only`；第二次 `POWER_ON → enter FBIST → RUN 已准备的 set_all_final_vposp → CHECKOTP → POWER_OFF`。该会话划分属于平台无关业务计划，Chroma/S100 Adapter 不得自行合并会话或省略重新加载 VPOSP。

**Load Map**：
共享 Recipe Module `LOADMAP` 把同一版本的完整 Page Image 同时投影到该页面的 Program Pattern 与 Read/Compare Pattern Memory，并以一个原子准备结果发布；它不运行 Pattern、不修改 DUT。只准备 Read/Compare Pattern 属于不完整状态，因为后续 `COMMIT/PGMOTP` 需要以同一 Program Pattern 基底做字段增量更新。
_避免_：只装载检查 Pattern、由 COMMIT 猜测 Program Pattern 基底

**Trimdata Read 与 UID Page**：
UID Page 的读—改—写生命周期归 UID/BakeID Typed Kind 所有；BakeID 为判断芯片是否已经过前一道 CP 而更新 UID Page 时，必须先读取并保留上道 CP 需要的字段，再合入 BakeID 后写回；不捕获或恢复整页原始镜像及保留位。`TRIMDATA_READ` 的默认及显式验证段均不读取、装载、检查或要求 UID Page 状态，两种 Typed Kind 之间不存在直接数据依赖。UID/BakeID 产生的页面或符号状态留在 CP 级运行时状态中；只有后续某个 Module 明确需要其中字段时，才由通用来源解析器证明完整 UID/BakeID 闭环已经结束且状态未失效，不得由 `TRIMDATA_READ` 自动补读 UID。

**候选 Page Image**：
`TRIMDATA_READ` 内部由 `READOTPMAP` 首次读取形成、尚未完成独立回读验证的页面内容。它只允许被同一 `TRIMDATA_READ` 内部的 `LOADMAP` 与 `CHECKOTP` 使用，不向后续测试项发布。

**可信 Page Image**：
生成计划中的数据可用性事实，表示 `TRIMDATA_READ` 已在运行路径上为候选 Page Image 编排后序 `CHECKOTP`，因此后续测试项只会排在该验证动作之后。它不表示生成器知道真实上机结果；运行时通过、失败及逐 Site 状态仍由测试机执行语义决定。
_避免_：编译期已验证页面、生成器知道 CHECKOTP 结果

**UID 写入流程预设**：
`uid` 是 UID Page 写入测试项的 FLOW type，默认 Recipe 为 `COMMIT-PGMOTP(UID)`。BakeID 补写与 BUILDUID 完整生成仍使用显式 Recipe；普通 UID 和 BUILDUID 面向全部有效 Site，Bake 仅在最终 COMMIT/PGMOTP 使用对应 Read Gate，该 UID/BakeID 业务的失败 Site 重擦属于模块内部清理，不自动用于 PASS ID 全 1 的 Trimdata 早写。

BakeID 对 UID Page 的操作不是局部字段盲写：它拥有上道 CP 所需字段的读取、保留、BakeID 合入与写回闭环，不要求整页原始内容保持不变，并在流程结束后把当前页面或符号状态留在 CP 级运行时状态中。`TRIMDATA_READ` 不消费该状态，也不重复读取 UID Page；其他后续 Module 只有在明确需要其中字段时才通过通用来源解析器消费。

**ID Item 协议（暂定）**：
`type=id` 的标准 item 使用完整 `Check_<target>` 或 `Read_<target>` 身份；Recipe 留空时分别展开为 `CHECKID` 与 `READID`。前者把目标检查结果交给当前 Flow/Bin，后者产生后续 Bake 补写 Gate；target 从完整 item 协议取得，不要求重复填写，`READID` 不等于恢复 UID 字段的 `READOTPMAP`。

**NM Main 测试主体**：
`type=main` 以共享业务模块 `NM_TEST` 承担 NM 测试主体，封装上电、进入 FBIST、加载已准备的 VPOSP、业务 Pattern 序列及清理。当前变化通过一个模式参数表达，不向 Excel 暴露底层上下电、FBIST/VPOSP RUN 或循环块，也不新增通用编排语言。
用户明确 Golden PgmCKBB 前置的重复擦写由已有 `FLASH_WINDOW` 承担，本轮 MAIN 不重复实现该能力，也不据此新增循环接口；Disturb 已确认的连续两次 Program 不因此取消。

**NM_TEST 模式**：
不填参数的 `NM_TEST` 默认采用 `normal`，正常生成并执行既定读回；`NM_TEST(repair)` 仍生成 MAIN 主体中的 Read 调用及对应日志，但逐行添加 C 风格 `//` 注释使其不执行，不删除或省略这些代码。其余擦除、编程次数、会话和准备/清理行为不因该参数改变；repair 表示为后续 VT 的 Repair 路径准备测试背景，不在 MAIN 执行 Repair/Capture，不把 Read Pattern 比较位改成 X。实际 Repair、冗余状态和写回能力本轮仍暂不实现。

**MAIN 操作范围**：
MAIN 的全部 item（包括 Disturb 与 Initialization）的擦除、编程和读取均限定为 `NM_ONLY`，不擦写 SM。该范围不改变 FLASH_WINDOW 已确认的 NM+SM 行为。

**MAIN Initialization**：
将 NM 恢复为擦除态的 MAIN 测试项，不是只读检查；normal 模式的业务顺序为上电、进入 FBIST、加载已准备的 VPOSP、擦除 NM、全片读 FF 检查、下电。

**MAIN Disturb（基础序列）**：
以每个数据背景连续两次完整 Program Pattern 调用施加扰动、随后读回检查的 MAIN 测试项，两次编程之间不擦除。`Disturb_FF` 为擦除 → Program FF ×2 → Read FF；`Disturb_CKB_CKBB` 为擦除 → Program PCKB ×2 → Read PCKB → 擦除 → Program NCKB ×2 → Read NCKB；次数指完整 Pattern 调用次数，不是内部编程脉冲数。
上述为 normal 模式基础序列，repair 模式仅将各 Read 调用及对应日志保留为 `//` 注释代码。最新指定程序只用于说明流程可变化；用户已明确本轮暂不实现 Repair、冗余状态及后续写回链路，不以完整复制该程序为验收目标。

**普通 VT 测试**：
在给定 VTE/VTP 条件下，通过所选 Read Pattern 判定的测试主体，对应 `VT_TEST` 的 normal 行为；默认读取 NM，也可显式选择 OTP 页面。当前范围仅包含普通 VT；Repair 模式只是后续方向，不包含实际修复、冗余状态捕获或写回。

`type=VT` 的空 Recipe 由上层补为无参数 `VT_TEST`；显式 Recipe 仍只接受一个测试主体，不开放重试参数或 Repair。测试会话不加载 MAIN 的 VPOSP；进入 Pattern 及所选 Read 由上层绑定已有资产，平台只翻译 plan。

**VT / MARGIN 读取目标**：
Recipe 支持 `VT(OTP-trim0)` / `MARGIN(OTP-trim0)`，页面名按现有 Flash Label Plan 绑定，例如 `fbist_page_read_trim0`；`trim1` 等已有且有 Read Pattern 的页面同理，不允许裸 `OTP`、未知页面或任意文件路径。简写归一到既有 `VT_TEST` / `MARGIN_TEST`，旧名也支持同一参数。空 Recipe、无参数或显式 `(NM)` 保持原 NM 背景选择。

`trim0` 只是示例，不是页面白名单；`VT(OTP-uid)` / `MARGIN(OTP-uid)` 同样支持。UID按既有 `FlashLabelContract.uid_variant(cp)` 映射绑定生成Plan中的UID Read，与当前CP的LOADMAP/PGMOTP使用同一资源，例如CP2对应 `fbist_page_read_cp2_id`，不凭空创建 `fbist_page_read_uid`。缺少页面、CP变体或Read资源时仍明确报错。

OTP Read 直接复用前序测试已装载的 Compare Pattern 数据，不重新执行 LOADMAP、不读取芯片后重建期望值、不擦写。调用方须保证前序已为目标页面准备正确 Compare 数据且未被其他步骤覆盖；当前扩展只验证页面资源绑定，不新增跨项装载状态追踪。只更换 Read Pattern，VT 电压/重读/判定与 MARGIN 八轮二分/只收数据/抽测 Gate 均不变；FLOW item 命名协议保持既有规则。

**VT 读回复判**：
普通 VTE 首次 Read 失败的 Site 再重读一次，普通 VTP 只 Read 一次、不重试。这是普通 VT 的固定业务差异，不增加 Excel 重试参数。

**VT 电压来源**：
普通及 Bake VT 的 VTE/VTP 电压以 Excel `VERSION` 中对应 CP 的配置为准，由上层 ProductCompiler 固化进不可变 VT plan。Golden 仅作为流程核对证据，不用其电压常量覆盖母本；下游不读取母本或 Golden。

**Bake VT Gate 绑定**：
Bake VT 使用前序 Read Bake ID 已产生的逐 Site Gate，由上层将现有 READID plan 的 `gate_symbol` 与 `gate_semantic_identity` 绑定进 VT plan。VT 只消费同一变量及 `ID_GATE` 资源身份，不重复声明或初始化，不另造标志，也不从 Golden 名称或 CP 编号自行推导变量名。

Gate 覆盖完整上下电会话；启用的 Bake VT 必须在同 CP 中具有唯一前序且启用的 Read Bake ID，编译期拒绝缺失、歧义或禁用的生产者。

**Margin 测试结果**：
每个 Site 的带单位裕量测量值，仅用于记录，不按该数值判定 PASS/FAIL；搜索中的 Read PASS/FAIL 只用于确定搜索方向，不能作为该项的筛选结果。结果默认只在当前测试项内有效，后续测试项需要用它判断或调整 DAC 时必须显式 `EXPORT`，普通 VT Verify 独立完成其自身的电性判定。

整个 MARGIN 项只收数据，包括 enter/read 的比较结果都不用于本项判退。不备份/恢复本项判定；数值日志不填搜索端点作为上下限。0 V、−1 V等边界值由用户直接在Log中观察，不转成PASS/FAIL分类；平台框架放行仅表示本项不筛选，不表示电性合格。

Margin Export 与任何 FLOW type 都不存在隐式依赖；只有 Recipe 明确声明输入的具体消费者才要求前序 Export。普通 VT 测试独立执行，不因 `type=VT` 自动读取 Margin，420 的 `Vt_Shift_Test` 属于显式消费两个 Margin Result 的特例。

**Margin 搜索范围**：
当前产品各 CP 的普通及 Bake Margin 使用统一参数：VTE 从 0 V 向 −1.0 V 搜索，VTP 从 0.2 V 向 1.0 V 搜索，均二分8轮，不增加母本配置。搜索范围仅限定测量区间，不是 PASS/FAIL 判定限值。

**Margin 边界记录**：
逐 Site 完成规定轮数的搜索后，若全 FAIL，记录起始端（VTE 0 V、VTP 0.2 V）；若全 PASS，记录终止端（VTE −1.0 V、VTP 1.0 V）；两种结果均出现时，保留最终收敛区间中点。端点值用于标识搜索未找到翻转边界，不表示已测得精确阈值，也不据此判退。

**Margin 抽测使能**：
正式 Margin 由既有晶圆坐标抽测条件决定是否执行，Bake Margin 还须满足已有 BakeID Gate；不改变抽测范围或绕过门控。参考程序 CP1/CP3 的强制开启仅用于临时收集数据，不属于正式测试规则。

**系统辅助测试项**：
不要求填写在 Excel FLOW 中、但由生成器产品规则加入 CP 程序计划的固定测试项。它与 Excel 测试项一样具有 Typed 测试项种类、默认 Effective Recipe、程序依赖和明确的调度属性，不允许继续作为 main 或 writer 末尾的隐藏动作。当前 `OTP_READ` 为生成但不调度的系统辅助测试项，`NM_Data_Read` 为生成并调度的系统辅助测试项。

**母本预检**：
在正式生成测试程序前，对母本执行与正式生成完全相同的读取、标准化和业务语义编译，并展示诊断结果；它本身不生成平台程序，也不另行实现 Recipe 或业务规则。只有能够证明继续生成必然错误或存在明确风险的诊断属于 ERROR 并阻断相关生成；无法证明必错的可疑情况属于 WARNING，默认展开等说明属于 INFO。

**FLOW 测试项组**：
同一道 CP 中连续且具有相同 `item + type` 的 FLOW 行组成一个测试项组；每个具体数据行仍由 `CP + item + type + sub` 唯一标识。组内 `sub` 表示数据点或结果身份，共享一个 Typed 测试项种类、一个 Effective Recipe 和该测试族规定的共同配置；测试函数与 Flow 调度只生成一次，Datalog 可继续使用 `item + sub`。同一 `CP + item + type` 不允许拆成多个不连续组。

**DC 测试族**：
当前数值DC族统一为 Typed Kind `DC_PARAMETRIC_TEST`，默认 Effective Recipe为深模块 `DC_TEST`。它表达两个互补sub组成的SWD DC Pin参数测量，共享Pin拓扑、Force/Measure/Judge、安全进入、Datalog与清理合同；平台无关Plan使用判别联合 `LeakagePlan | VolVohPlan | RpdRpuPlan`，分别保留奇偶Pin交叉漏电、分组输出电压和上下拉电流算法，不使用可空字段袋或Adapter中的item名称分支。上层必须根据完整测试项组的sub角色、Force量纲、测量UNIT与限值形状唯一编译并校验variant；无法唯一确定时阻断。三个variant的两个sub均在同一次完整上电会话中按母本顺序执行；每个sub必须在下一个sub开始前撤销自身Force，组末统一执行其余安全清理并下电。`DC_TEST` 的平台无关Plan必须显式包含SWD配置Pattern动作：`LeakagePlan`在整组测量前执行一次共享配置，`VolVohPlan`与`RpdRpuPlan`在每个sub测量前执行该sub对应配置。该动作只配置MCU测试状态，不下载或改写固件；Native双平台Adapter必须等价实现。DC SWD Pattern与Firmware Download Pattern遵守相同资源闭包：缺失时生成带 `STUB` 标记的最小可编译空向量并输出精确诊断，允许结构/编译验证，但不计入真实覆盖，且生产发布/验收门禁必须因任何残留 `STUB` 失败。Pin拓扑由PlatformProgramFacts统一投影：Leakage及普通DC分组均排除NRST/TP，Leakage按声明顺序奇偶交叉，普通DC组每组最多8根且尽量均衡。第一版不开放内部Recipe拼接点，未来真实前后动作可在深模块外组合。

`DC_VIHVIL_Test` 不属于上述三种 DC Scan，独立为 Typed Kind `DC_VIH_VIL`，默认 Effective Recipe 为深模块 `VIH_VIL_TEST`。该Kind与Recipe不绑定传输协议；第一版Native同时支持两种已知格式，上层按FLOW mode编译并校验强类型 `SwdVihVilPlan | KeilVihVilPlan`，Adapter只消费已选定的Plan variant，不另设SWD/KEIL业务Kind或Recipe。其输入阈值扫描、结果判定、Datalog 与安全清理属于该主体内部职责，不通过通用 DC strategy 或 item 名称分支实现。当前Legacy母本 `FLOW!189` 仍是单行 `type=verify, mode=swd, step=T`，本轮未修改xlsx；Product Compiler只把该迁移输入收敛为不含T的typed plan。整个SWD测试项共用一次完整会话，顺序固定为上电、一次SWD配置Pattern、依次执行LL/HH/HL/LH四组驱动与捕获、恢复Pin状态、下电。五个SWD配置/捕获Pattern属于外部资源，缺失或命中旧空占位时生成显式STUB：保证工程可编译，但不计真实覆盖并阻断生产发布/验收。VILVIH_ODD/EVEN由PlatformProgramFacts按Pad名数字奇偶一次编译并排除SWD/CLK/NRST/TP；历史命名保持ODD=偶数Pad、EVEN=奇数Pad。`KeilVihVilPlan`由两个互补variant组成；二者共享一个Definition、Schedule和Bin，但各自执行完整的45%/55%驱动、33%/67%比较阈值上电、typed KEIL入口actions、算法生成判定Pattern、恢复及下电会话。生成器不校验它们所需固件是否已下载；S100 Legacy未在两个variant间完整下电的差异已由Native关闭。

**FREQ 测试族**：
正式母本的 `Clock_check_Test`、`Hse_Test` 与 `PLL_Test` 分别编译为独立 Typed Kind `FREQ_TEST` 实例，默认 Effective Recipe 为深模块 `FREQ_TEST`；三者各自拥有一个Definition、Schedule和Bin，具体14个档位由同名FREQ sheet分组提供，不把档位继续展开到FLOW。FREQ sheet每一行都是完整配置case，而非只替换测量限值：上层以完整 `source + mul + div` 唯一编译配置Pattern identity，由 `source × mul ÷ div` 推导target并结合该行限值；需要HSE/LSE等外部输入时钟时，必须先建立外部时钟，再运行该case唯一配置Pattern，随后执行TMU测量/判定并撤销该case外部时钟。Pattern不能只按source复用，例如 `HSI8×6` 与 `HSI8×9` 必须绑定不同资源。外部配置Pattern沿用统一STUB合同。默认同一FREQ item的全部case共用一次完整上电会话；FREQ sheet已有 `step` 列中的typed `RP` 表示在当前case开始前结束上一会话并重新上下电，其余step动作保持原有顺序由上层一次解析。当前最新人工参考要求在 `Clock_check_Test/HSI16` case填写 `RP`，从而形成HSI8独立会话与HSI16/24/48共享会话；HSE及PLL不写RP。Adapter不得按item名称、source或Pattern字符串补上下电例外。

上述FREQ合同已于2026-08-30落地：正式母本`Clock_check_Test/HSI16`已填写`RP`，Product Compiler生成3个Plan/14个case，双平台Native Assembly/Renderer及Typed Kind Registry已闭合。HSE32的IOMUX角色解析为PD0，Adapter严格按“外部时钟→配置Pattern→TMU→撤销时钟”执行。14个配置资源当前均为显式STUB，只可用于结构/厂商语法验证，不能视为真实覆盖或发布输入。

**ADC 测试族**：
同一CP内连续的 `Adc_Test/ADC1` 与 `Adc_Test/ADC2` 两行合并为一个 Typed Kind `ADC_TEST`，共享一个Definition、Schedule和Bin；`ADC_TEST` 只表示业务种类和每phase固定的Power、Force、安全清理外壳，不再注册或默认使用同名深Recipe。平台无关Plan使用按母本顺序排列的 `AdcPhase[]`，每个phase由对应ADC sheet分组提供完整通道配置并保存自己的显式Effective Recipe：第一版只接受SWD数值路径 `SWD_CAPTURE-ADC_JUDGE`、KEIL SRAM数值路径 `RUN_SEQUENCE-SRAM_CAPTURE(...)-ADC_JUDGE`、KEIL数字比较路径 `RUN_SEQUENCE-JUDGE`。ADC1与ADC2各自执行一次完整的上电、通道Force、phase Recipe、安全清理及下电会话，二者不共享电源状态；未来新增ADC3时增加phase，不增加Typed Kind或拆分结果边界。每个phase必须保存从CH0到最大CH的完整固定 `CaptureSlot[]`，所有slot均按固定bit偏移解包，不得因封装未引出而压缩；已引出的外部Pin执行PPMU Force并判定，显式 `INT_*` 内部源不Force但可判定，未引出的外部Pin只占capture位置且不Force、不判定、不生成Datalog，限值取对应ADC sheet行。`ADC_TEST` 不绑定SWD协议，AdcPhase按其FLOW mode校验Recipe与协议variant一致；不得再通过 `UNIT/cap_cfg` 或Adapter item分支选择路径。

**JUDGE 与 ADC_JUDGE 边界**：
共享 Recipe Module `JUDGE` 的目标合同使用判别联合，而不是继续增加互相无关的可空字段：`ScalarMeasurementJudgePlan` 保留现有单值电压、电流、频率判限；`DigitalCompareJudgePlan` 只表达显式比较Pin和期望数字状态，不把“必须使用比较Pattern”固化为业务语义；`CapturedValuesJudgePlan` 消费前序Capture Module产生的普通有序数值并逐项执行Limit与Datalog。DigitalCompare由Adapter依据已占用的测试机资源选择等价实现：Pattern Engine空闲时运行生成的比较Pattern；Chroma低频外灌占用Pattern Engine时，保持时钟到判定完成并以PPMU 0uA逐Pin测压比较H/L，随后phase cleanup释放时钟。该选择是平台资源翻译，不改变typed期望。ADC KEIL数字比较从FLOW `meas pin`取得以`+`分隔的比较Pin，从 `target`取得H/L状态；第一版严格要求两个Pin和两个H/L字符一一对应，母本不填写Pattern名或执行策略。数字比较所需的ADC输入Force仍来自ADC sheet并属于AdcPhase测试条件，不塞进JUDGE。普通 `SRAM_CAPTURE` 结果使用 `SRAM_CAPTURE(...)-JUDGE`，不新增 `CAPTURE_JUDGE` Module；若Capture产生N个结果，FLOW测试项组只有一行时将该行Limit应用到全部N个结果并生成`sub_0..sub_N-1`身份，恰有N行时按顺序逐行绑定各自`sub/low/high`，其他行数均编译失败。Captured Values的FLOW `low_range(%)`/`high_range(%)`在该分支中是直接绝对上下限，不套用target或百分比公式；编译后统一命名为`low_limit/high_limit`，避免把旧列名中的`%`传播到领域合同。JUDGE分支由前序typed输出和当前测试Kind决定，不按UNIT字符串分派。ADC Capture解码、固定槽位数组、通道选择及ADC专用Limit计算属于独立 `ADC_JUDGE`；它只消费已经由 `SWD_CAPTURE` 或 `SRAM_CAPTURE` 产生并解码的数值，不负责捕获或Force。因而ADC_TEST内部三种已知phase链分别为SWD数值路径 `SWD_CAPTURE-ADC_JUDGE`、KEIL SRAM数值路径 `RUN_SEQUENCE-SRAM_CAPTURE-ADC_JUDGE`、KEIL数字比较路径 `RUN_SEQUENCE-JUDGE`。现有Native JUDGE已实现标量与数字比较Plan；普通Captured Values分支仍须等真实母本case明确续行合同后再接入。旧writer中的 `JUDGE_PAT`/UNIT=pat及UNIT=cap均不算共享Module能力。

**ADC Capture 数值宽度**：
每个ADC通道固定占用并完整拼接16个Capture bit，不再另设只截取低12位的解码分支；ADC期望值和上下限仍按12-bit码域 `0..4095`（换算分母4096）计算。当前协议事实要求高4位恒为0，因此完整16-bit拼接与12-bit数值相同；若高位异常为1，不得静默mask，而应让原始值进入 `ADC_JUDGE` 并自然触发越限，以暴露Capture资源、位序或固件输出错误。双平台必须使用相同的16-bit槽位和位序合同；S100 Legacy当前只拼15位属于Adapter实现缺口。未来若高位被定义为状态或元数据，必须新增显式Capture编码variant，不能改变本合同的含义。

**SRAM Capture Module**：
`SRAM_CAPTURE` 是读取并拆分SRAM结果缓冲区的共享Recipe Module；基地址和数据布局由该Module参数拥有，不再以FLOW `UNIT=cap`触发。目标Native母本删除 `cap_cfg` 列，而不是保留空值；`UNIT=cap`也不是合法Native单位。普通Capture结果若无物理单位则 `UNIT=/`，若固件值代表mV、uA、Hz等则填写真实Datalog单位；UNIT不参与Capture或JUDGE分支选择。第一版Recipe语法为 `SRAM_CAPTURE(<base>,<count>x<width>[@<stride>])`，例如旧 `SRAM-0X3000-48-16` 直接表达为 `SRAM_CAPTURE(0x3000,3x16)`，旧 `SRAM-0X3000-256-32` 表达为 `SRAM_CAPTURE(0x3000,8x32)`；不再让填写人用“总bit÷位宽”间接表示元素数。`stride`单位为byte，省略时沿用当前SRAM读取ABI的4-byte步长，紧凑16-bit数组等非默认布局才显式写 `@2`。第一版只支持等宽元素序列，并固定采用无需母本额外填写的逻辑读取ABI：第i个元素字节地址为 `A=base+i×stride`，从little-endian byte stream的A位置起组装无符号值并取低`width`位。Adapter必须通过对齐READ32、按`(A&3)×8`移位，并在字段跨32-bit边界时再读下一字拼接；不得依赖非对齐word read，也不得自行选择字节序、符号扩展或其他位域。因此16-bit `@2`的相邻元素分别来自同一对齐word的低/高16位，ADC默认`@4`行为不变。当前双平台SRAM Capture Pattern只动态改写地址低16位，高位窗口固化在资源中，所以第一版`base`是该Pattern窗口内的16-bit byte offset并校验完整读取范围不越过`0xFFFF`；完整32-bit绝对地址需新的Pattern资源合同。编译器同时校验`count>0`、`1<=width<=32`和`stride>0`。未来出现大端、有符号或非低位字段的真实布局时再增加显式参数/variant，不能从UNIT或测试项名称猜测。目标Plan展开为基地址、元素数量、有效宽度和步长，并产出有序typed values；它不拥有Limit、Datalog或PASS/FAIL，普通结果交给共享 `JUDGE`，ADC结果交给 `ADC_JUDGE`。ADC SRAM路径写作 `RUN_SEQUENCE-SRAM_CAPTURE(0x3000,22x16)-ADC_JUDGE`，其中元素数量必须与对应AdcPhase的完整CaptureSlot数量一致，否则编译失败；`width=16` 将逻辑低16位完整交给ADC_JUDGE，不会遮蔽ADC值内部的bit12..15。Legacy迁移器在所有旧Capture行完成迁移前可以只读旧 `cap_cfg` 列并转换为Module参数；Native编译器不得消费该列，完成全量迁移后从母本物理删除。

**SWD Capture Module**：
`SWD_CAPTURE` 是配置SWD测试状态并取得Capture数值的共享Recipe Module。对ADC phase，它顺序拥有配置Pattern、平台Capture/DAQ建立、Capture Pattern运行、原始bit读取、按固定CaptureSlot解包以及Capture/DAQ撤销；Power、ADC输入Force和phase末安全清理仍由 `ADC_TEST` 外壳拥有，Limit、逐通道Datalog和PASS/FAIL由后续 `ADC_JUDGE` 拥有。其Typed Plan显式绑定 `CONFIG_PATTERN` 与 `CAPTURE_PATTERN` 两个逻辑资源角色、Capture Pin以及输出槽位合同；母本不重复填写平台文件名。Chroma与S100现有不同的PAT/SD命名和Capture API由资源目录及Adapter映射，不构成业务Recipe差异，也不得在Adapter中按item字符串推导。缺失或已知占位的外部Pattern沿用统一STUB合同。ADC SWD phase的Recipe固定为 `SWD_CAPTURE-ADC_JUDGE`。

**ADC RUN_SEQUENCE 终止动作**：
ADC遵守全局Native无T合同：`RUN_SEQUENCE` 只执行进入码、触发、等待、显式RP等结果产生前的准备动作；KEIL SRAM路径由紧随其后的 `SRAM_CAPTURE`读取结果，KEIL数字比较路径由紧随其后的 `JUDGE`执行比较。Legacy ADC迁移器删除旧T并输出明确迁移诊断，Native ADC step出现T直接编译失败。Legacy writer虽允许FLOW `step` 以 `X` 切出判定后的suffix，但现有正式及历史母本未发现ADC使用该能力；第一版Native ADC只接受结果产生前的actions，发现非空suffix必须明确报错，不静默删除、提前或塞入清理。未来出现真实后置动作案例时，再以Recipe末尾第二个 `RUN_SEQUENCE` occurrence表达，不预先实现 `BEFORE/AFTER` 参数；该suffix限制是ADC专属，不能自动扩大到其他Typed Kind。

**OPA 测试族**：
`OPA_TEST` 是独立业务Typed Kind及深Recipe，但不绑定传输协议；第一版同时支持SWD与KEIL的OPA sheet驱动扫档。两种variant共享IOMUX拓扑、一次完整上电会话、有序OPA case、输入Force、输出电压Limit/Datalog和安全清理合同；SWD case以外部配置Pattern建立模式，KEIL case以OPA sheet对应的step actions建立模式。整张OPA sheet的case默认共用一次上电；当前case的step显式包含typed `RP` 时，必须先完成上一会话清理与下电，再重新执行完整会话前导，而不是只发裸 `POWER_OFF/POWER_ON`：SWD重新建立电源、Relay/PPMU并再次运行 `OPA_GPIO_INIT`，KEIL重新建立电源、Relay/PPMU并再次执行FLOW公共进入actions，随后才运行当前case配置、Force、测量与判定。是否使用OPA sheet只由显式Recipe选择，不能根据工作簿是否存在全局OPA sheet猜测，也不新增 `use_sheet` 布尔列：`Recipe=OPA_TEST` 明确表示消费OPA sheet；缺表、缺case或KEIL case缺step均编译失败。

上述OPA sheet路径已于2026-08-30落地并注册。正式CP3 SWD项迁为显式`OPA_TEST`，11个case及IOMUX/bonding后的OPA2三组由上层固化，双平台Adapter不重读母本。当前12个SWD初始化/配置Pattern均为显式STUB，只可用于结构与厂商语法验证，不能视为真实覆盖或发布输入；direct KEIL仍按下一段通用固件合同处理。

不使用OPA sheet的KEIL OPA属于 `FIRMWARE_RUN_TEST`，显式Recipe为 `RUN_SEQUENCE-JUDGE`，编译器不得读取OPA sheet。`RUN_SEQUENCE`在FLOW step的 `F` 位置消费 `FV/FI=<force_pin>:<voltage>` 并产生 `ForceVoltageAction`；共享标量 `JUDGE`从 `meas pin`、`UNIT=V`及FLOW Limit取得另一管脚的电压判定合同，并在被测Pin使用0uA量测偏置，不能把输入刺激误当成测量偏置。测试会话在判定后及异常路径撤销输入Force、测量PPMU与Relay，再安全下电；Native显式JUDGE路径移除Legacy结果token `T`，避免重复判定。旧 `FV/FI=OPA` 只供迁移器识别并补写 `Recipe=OPA_TEST`，不作为Native隐藏分派开关；`RUN_SEQUENCE-JUDGE`若仍填写该哨兵、缺F或缺有效Force pair均编译失败。该direct路径不另建 `OPA_DIRECT`、`FORCE` Module或OPA专属Plan。

**DAC 测试族**：
`DAC_TEST` 是独立业务Typed Kind及深Recipe，不绑定SWD或KEIL协议；`Recipe=DAC_TEST` 明确表示消费DAC sheet并执行有序模式/码点扫描。SWD variant以外部GPIO初始化、模式配置与码值Pattern驱动DAC，KEIL variant以FLOW公共进入动作和DAC sheet逐点step驱动固件；两者共享DAC输出Pin拓扑、逐点0uA偏置测压、上层已计算的绝对Limit、Datalog和安全清理合同。整张DAC sheet的码点默认共用一次上电；当前码点的step显式包含typed `RP` 时，必须先完成上一会话清理与下电，再重新执行完整会话前导：SWD重新建立电源、Relay/PPMU并再次运行 `DAC_GPIO_INIT`，KEIL重新建立电源、Relay/PPMU并再次执行FLOW公共进入actions，随后才设置当前模式/码点并测量判定。`DAC_TEST` 不得复用现有 `DAC_WRITE`：后者写入FBIST/Trim DAC字段，不执行DAC输出电压扫点。

上述DAC sheet路径已于2026-08-30落地并注册。正式CP3 SWD项有33个点，IOMUX/bonding后只测PA7；20个唯一初始化/配置/码值资源当前均为显式STUB，只可用于结构与厂商语法验证。direct KEIL仍按下一段通用固件合同处理。

不使用DAC sheet的KEIL DAC属于 `FIRMWARE_RUN_TEST`，显式Recipe为 `RUN_SEQUENCE-JUDGE`；`RUN_SEQUENCE`只执行固件设置DAC输出所需动作，标量 `JUDGE`在FLOW `meas pin`指定的DAC输出Pin上以0uA偏置测量电压并使用 `UNIT=V`及FLOW Limit判定。该路径不读取DAC sheet、不生成码点循环，也不新增 `DAC_DIRECT` Module；Native显式JUDGE路径移除Legacy结果token `T`。是否消费DAC sheet只由Recipe决定，不能按全局sheet存在性或item名称猜测；旧 `FV/FI=DAC` 哨兵只供迁移器补写 `Recipe=DAC_TEST`，不得成为Native隐藏开关。DAC_TEST缺表/case/KEIL step，以及direct路径缺测量Pin、有效电压Limit或仍残留DAC哨兵时均编译失败。

**PVD 测试族**：
正式 `Pvd_Test` 编译为独立 Typed Kind `PVD_TEST`，默认 Effective Recipe 为同名深模块 `PVD_TEST`；它执行KEIL程序但不下载固件，所需程序是否已正确下载由母本填写人确认。上层Plan将FLOW进入模板 `HL-222-15-X` 与PVD sheet的case step编译为每个case的进入动作，并预先推导四个有序电压点及对应双Pin数字期望；Adapter不得重新解释原始step或计算迟滞公式。有效case 1..7各自执行一次完整的上电、进入码、四点状态机和下电会话；同一case的四点必须连续供电，保持先下降后上升所需的迟滞状态，不能拆成通用 `RUN_SEQUENCE-JUDGE` 或在点间重上电。进入模板中的 `HL` 复用共享 `LevelSequenceAction`，因未显式填写宽度而得到每段5ms的KEIL默认值；PVD不得另造专属时长字段。整个item仍只有一个Definition、Schedule与Bin，四点数字比较可复用生成比较Pattern的共享能力，但状态机和循环边界属于PVD_TEST主体。

**Shmoo 执行方式**：
以有序一维 `STEP` 序列重复执行部分 Effective Recipe 的执行修饰方式，而不是独立的测试业务种类、FLOW type或Recipe Module。扫描测试项填写真实基础 `type`；当前测量扫描使用 `type=verify`，由该 type 决定基础 Typed Kind。某个支持扫描的业务 Module 通过显式 `SHMOO=STEP` 参数声明自己消费当前扫描点，例如 `ENTER(SHMOO=STEP)-JUDGE` 或 `LOADMAP-DAC_WRITE(SHMOO=STEP)-COMMIT-PGMOTP`。带该参数的 Module及其后的全部 Module是扫描相关后缀；第一版一条 Recipe 只允许一个 SHMOO 参数，不支持二维扫描、多个扫描参数或循环后的额外后缀。第一版暂定只有 `ENTER` 与 `DAC_WRITE` 可携带该参数；二者必须绑定唯一动态字段并在编译期校验STEP位宽，其他Module可以进入逐点执行但不能消费扫描值。

每个SHMOO点均执行一次独立完整上下电会话，因此不能再笼统规定参数前的Module全部只执行一次。编译器按状态生命周期闭合每点前导：只产生测试机侧、跨DUT上下电仍有效状态的准备Module（例如 `LOADMAP`）在循环外执行一次；建立循环后缀所需DUT状态且声明为可安全重放的前置Module（例如 `ENTER`）在每次重新上电后重跑，但不消费本点STEP。因而 `ENTER-DAC_WRITE(SHMOO=STEP)-JUDGE` 的每个点均按“上电→ENTER→DAC_WRITE(当前点)→JUDGE→清理→下电”执行，而循环前的LOADMAP不重复。不得任意重放COMMIT、PGMOTP等有持久副作用的前置Module；若循环后缀依赖某个跨下电失效、又未声明安全重放的前置状态，Recipe编译失败。该重放是Typed dependency/lifetime闭包，不是Adapter按Module名称补动作。

具体点集以 FLOW `step` 列为唯一来源：单行范围可展开连续点，多行离散值形成携带各自 `sub/target/limits` 的点集；Recipe 不重复填写字面范围。第一版暂定 Pattern及其他业务资源仍按原 `item` 绑定；含 `SHMOO=STEP` 的测试项只在生成的测试项名称上固定追加 `_Shmoo`，不新增 SOURCE/名称列，也不靠后缀反推资源。没有 SHMOO 的同名不同 Recipe不自动生成 `_1/_2`，须使用不同 item，否则按名称歧义报错。SHMOO只控制循环、STEP注入、逐点身份、会话重建及扫描恢复，不产生或覆盖判定；每点及整个测试项的PASS/FAIL完全由逐点业务 Module中的 `JUDGE(PF=...)`、`PGMOTP` 等合同决定。`SHMOO=STEP` 仅临时覆盖扫描 Module的正常数据来源；完成全部点或进入异常清理时必须恢复该调用位置原本的值并同步相关Pattern Memory，不能把最后一个STEP泄漏给后续测试。`ENTER`通常恢复catalog默认值，`DAC_WRITE`恢复其正常DAC_FINAL/ADDR_MAP等来源，而不是统一恢复静态默认。第一版所有SHMOO点（含FBIST与非FBIST）不跨点复用DUT状态；这有意改变当前旧FBIST Shmoo全点共用一次会话的行为并增加测试时间。后续只有在明确状态生命周期和性能收益后，才重新裁决会话复用。测试项进入什么模式、使用什么 Pattern及每点执行测量、Page Image字段更新或物理写入，由基础 Typed Kind及闭合后的逐点计划决定。现有正式母本的 `type=shmoo`、编译器独立 `SHMOO` Kind及显式 SHMOO Module构想仅为待迁移兼容/历史形态，不是目标领域模型。

2026-08-30实现状态：正式4条旧Shmoo行已迁为`type=verify`并用`ENTER(SHMOO=STEP)`显式消费STEP；CP1范围0–7保留`PF=NO`记录语义，CP2离散0/3/7保留各自sub/target/绝对limit与`PF=YES`判定。扫描作为`StandardVerifyPlan`执行修饰进入原生注册路径，不存在新的SHMOO Typed Kind或Recipe Module。每点独立上下电，ENTER与DAC_WRITE两种消费者均通过测试；Pattern Memory在每点后恢复，DAC_WRITE恢复不重跑业务Pattern。正式母本SHA256为`EC90D9FF5D20CF96DB0A6CE78DCE961676AF77F36CE289BF8F64B8C714289003`，native registry对206/206条FLOW已有注册覆盖；覆盖不等于机台验收或正式入口发布。

**Redundancy State**：
420 自修复流程在一道 CP 内按 Site 保存的冗余资源状态。第一版证据形状为 2 个 Bank、每 Bank 4 个 Slot；每个 Slot 至少包含 `available/status`、sticky `busy` 与 9-bit NM page。状态由 `test_start` 初始化，多个 Repair 测试项持续累积，提交后不清零；它不是 VT 测试结果，也不是 ADDR_MAP Page Image。该术语当前仅记录调研事实，本轮重构不实现或公开该模型。

**Repair Profile**：
一次自修复针对的 NM 数据背景，420 已出现 `ALLF`、`ALL0`、`CKBD` 与 `ICKBD`。Profile 精确绑定各 Bank Repair Pattern，但不决定 VT/VTP 电气条件；电气条件和目标 NM 内容必须由前序模块提供。

**REPAIR**：
420 调研中推导出的候选 Recipe 业务模块，而不是本轮已批准接口。候选职责是消费当前有效的 VT/NM 条件、VPOSP 资源和 `RedundancyState`，执行 Repair/Capture 并原子更新状态；具体程序形态、名称和参数均未定。本轮不在 Module Registry 注册 `REPAIR`，不生成占位实现。

**BUILDREDUNDANCY**：
420 调研中推导出的候选构建职责，而不是本轮已批准接口。若未来程序形态确认，它可把 Redundancy 状态转成 ADDR_MAP 字段绑定，并复用 `COMMIT/PGMOTP`；本轮不注册该模块、不新增专用 Sheet 或 writer。

**Redundancy Commit Point**：
FLOW 中由填写人显式放置的 `BUILDREDUNDANCY-COMMIT-PGMOTP` 测试项。420 的 `Slave_Rdy_Log_FF/00/Ckb/Disturb/Disturb_FF/iCkb` 是其历史实现；它们的位置说明提交可以批量覆盖一个或多个前序 Repair，生成器不得自动把提交插在每次 Repair 后。

**Redundancy Resource Catalog**：
仅在产品使用 `REPAIR` 时需要的资源声明，至少包含 Profile×Bank Repair Pattern、Bank 初始化 Pattern、Busy/Page Capture Pattern、Capture 位序与宽度、Slot 到 ADDR_MAP 字段映射及重复页抑制策略。Product Compiler 用它建立完整依赖闭包并做 preflight；平台 Adapter 只翻译已解析资源，不按 `repair/redudancy` 文件名片段猜测。旧程序拼写 `redudancy` 仅作为兼容资源别名。

**VT Shift Consumer（420 特例）**：
显式消费 `Vte_Ckb_Margin_Shift` 与 `Vtp_Ckb_Margin_Shift` Export 的 VPOSP 调整动作。它按阈值和 DAC 顺序表通过共享 `DAC_ADJ` 更新 `VPOSP_DAC_FINAL`，再由现有 ADDR_MAP/COMMIT/SETVPOSP/PGMOTP 能力刷新后续资源。它是 Redundancy 前的产品校准策略，不属于普通 `type=VT`，也不属于 `REPAIR` 内部职责。

**动态 PUMP 调整**：
已确认存在、但本轮暂不实现的跨测试项业务能力。真实场景可能同时消费多个 `EXPORT` 结果并原子调整多个 Pump，例如 VTP/VTE 条件同时满足时 VPOSP 加若干档、VPOSE 减若干档；这属于多输入、多输出规则决策，不是多维 Shmoo。调整后应使旧 VPOSP Pattern 快照失效，并由通用 `COMMIT-SETVPOSP-PGMOTP` 完成物理落点与写入；420 的阈值、环形 DAC 顺序和双 Margin 只是一种策略。具体规则优先级、冲突/累加、档位顺序和母本填写格式等待用户提供复杂案例后再定，本轮不注册公开模块或占位实现。
