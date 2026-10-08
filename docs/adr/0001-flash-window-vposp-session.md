# ADR 0001：FLASH_WINDOW 使用 Pattern 准备态与 FBIST 会话加载态

- 状态：Accepted
- 日期：2026-08-25

## 背景

`set_all_final_vposp` 既会被动态改写到测试机 Pattern Memory，也会在 FBIST mode 内被 RUN 以把值加载到 DUT 寄存器。两种动作的失效条件不同；旧实现把它们混成一次 SETVPOSP 调用，并让 Memory Wakeup 的平台 writer 各自维护 NM 循环。

## 决策

`FLASH_WINDOW` 是 `type=wake` 的 native Typed Kind，主体只有共享 Recipe Module `NMLOOP`。`SETVPOSP` 通过 typed purpose 区分电气条件应用与 Flash prepare-only：

- Pattern 准备态跨 DUT 上下电和 FBIST 退出保留，Pump DAC 改变时变 dirty。
- 芯片加载态只在当前上电和 FBIST 会话有效。
- NMLOOP 每次 enter FBIST 后 RUN 一次已准备的 `set_all_final_vposp`，同一会话复用该加载态。
- CP1、CP2 共用 `100/49/100` 业务序列；CP1 的全部 NM Pattern 使用显式 `_sm` identity，CP2 全部使用显式非 `_sm` identity。
- `BUILDMAP` 是共享模块，不属于 NMLOOP；CP1 Memory_Wakeup 显式组合它，CP2 不组合。

## 后果

Chroma/S100 Adapter 只翻译同一个 immutable Plan，不能各自修改循环或 Pattern identity。当前 Flash Pattern Generator 尚未生成全部 CP1 `_sm` 资源，因此 native 资源闭包会明确失败；补齐真实 SM 向量是后续发布门槛，禁止复制或重命名非 `_sm` 文件。
