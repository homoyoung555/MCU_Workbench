---
status: accepted
---

# TRIMDATA_READ 使用共享页面 Module 组成可扩展验证闭环

FLOW `type=read` 统一分类为不绑定 CP 编号或 item 名称的 Typed Kind `TRIMDATA_READ`。它必须包含满足 `READOTPMAP < LOADMAP < SETVPOSP < CHECKOTP` 的有序主干，但 Module 不要求连续、允许重复，也允许插入其他通过 typed effect 与状态版本校验的共享 Module；`READOTPMAP`、`LOADMAP`、`CHECKOTP` 与既有 `SETVPOSP` 均在 Recipe Module registry 注册，Typed Kind 只拥有编排、Page Scope、状态/资源闭包及单一 Definition/Schedule/Bin 边界。

每个 `READOTPMAP → CHECKOTP` 验证段共享同一有序非 UID Page 集合，页面只需在段首填写，后续 Module 沿用；每个显式验证段必须实际执行，不受全 CP captured-page 去重影响。验证段以两个独立 DUT/FBIST 会话执行：先 capture 并下电，再由 `LOADMAP` 原子准备同一 Page Image 版本的 Program 与 Read/Compare Pattern、由 `SETVPOSP` prepare-only，最后重新上电进入 FBIST、加载 VPOSP、执行 `CHECKOTP` 并下电。UID Page 生命周期继续由 UID/BakeID Typed Kind 所有，`TRIMDATA_READ` 不读取、要求或消费 UID Page 状态；生成器只保证运行路径和统一失败出口，不预知真实上机结果或建模逐 Site 失败。

首个实现以正式 CP2 `Trimdata_Read` 闭合 Chroma/S100 native assembly，再以 CP3 证明无 CP2 硬编码并串行通过 CRAFT/YT5100；本节点不切换正式生成入口、不发布 outputs。`READOTPMAP` 的 Capture/REG 恢复语义保持当前实现，不在本节点重新设计整页读取算法。

实现状态（2026-08-26）：Product Compiler、三个新增共享 Module、双平台 Adapter、typed-kind assembly 与 registry 已闭合；正式 CP2/CP3 的双平台资源图均可构建。GenerationService 切换、正式 outputs 发布和真实 CRAFT/YT5100 串行编译/上机尚未执行。
