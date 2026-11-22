# M3.5 执行授权记录（Authorization Record）

> Task ID: `M3.5-SHADOW-FORWARD-ENGINEERING-001`
> 记录日期: 2026-11-22
> 记录人: Codex 执行代理（Claude Code 会话，本仓库工作区）
> 性质: 本文件是对**用户人工签批**的忠实记录，不是签批本身；签批是用户在授权对话中的明确选择。

## 1. 签批前核验（第一道强制门，任务书 §0.1）

执行开始前对仓库做了授权记录检索，结论：**签批前仓库内不存在任何授权记录**。

- `git status --short` / `git rev-parse HEAD` / `git rev-parse origin/main`：本地 = 远端 = `e1301c5ebd5eff7c307ec500849b8d8fd83c9525`（含 docs-only `0b84ec4`、`e1301c5` 补录；受测代码 SHA 仍为 `906bf6f`）。
- 全仓库检索 `M3_GATE=CLOSED_WITH_SCOPE`、`M3.5_START=APPROVED`：除任务书自身文本外无匹配。
- 权威记录一致为待签状态：
  - `docs/reviews/M3-engineering.md`（`M3_GATE=USER_PENDING；push/M3 关闭/M3.5/M4 需用户分别签批`）
  - `docs/reviews/M3-r2-independent-closure.md`
  - `artifacts/evidence/M3/r2/verification.log`（`M3_GATE stays USER_PENDING`）
  - `artifacts/evidence/M3/r2/remote-ci.md`
- 任务书自身（`Shutu_AI_Trading_Lab_M3_5_Shadow_Forward_Codex_Task.md` 头部）声明：本文件不是启动授权，`M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`。

## 2. 用户签批（原话与记录路径）

- **签批时间**: 2026-11-22（执行会话内，紧接着上述核验报告之后）
- **签批方式**: 用户在授权对话中对核验问题作出明确选择。问题原文完整列出两项待签批项：

  > 仓库内未找到 M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY) 与 M3.5_START=APPROVED 的任何签批记录，任务书要求两项齐全才能执行 S0–S7。您是否现在明确签批？

  用户选择（原话）：

  > **两项均批准，执行 S0–S7**

- **签批内容**（据此记录）:
  1. `M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` — **APPROVED**
  2. `M3.5_START=APPROVED`
- **记录路径**: 本文件（`artifacts/evidence/M3.5/authorization.md`），源记录为该授权对话本身。

## 3. 批准范围（边界）

- **批准执行**: 任务书 S0–S7，仅离线、合成、无真实事件源的 Shadow 前向工程夹具（`SYNTHETIC_REPLAY`）。
- **不批准 / 明确禁止**（无需再次确认即持续生效）:
  - 真实行情 API、数据订阅、任何券商/市场数据凭证读取；
  - Alpaca Paper/Live 连接与任何 BrokerEgress 写调用；
  - M4 及之后任何阶段的启动；S8（真实 Shadow / Paper）未获单独授权；
  - 推送（push）——push 需单独授权；本阶段默认仅本地 commit；
  - 将合成回放计为真实前向交易日；`S=INCONCLUSIVE`、`BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED`、`R=NOT_STARTED` 状态保持。
- **停止条件**: 完成离线范围后停止在 `M3.5_GATE=USER_PENDING`。

## 4. M3 关闭范围的澄清

`M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 的语义按任务书记录为：M3 在**合成工程证据范围**内关闭（受测代码 `906bf6f`，CI run 44998829308 双矩阵 572 passed，见 `artifacts/evidence/M3/r2/remote-ci.md`）。该关闭不解除 `BLOCKED_DATA(全市场历史研究)`、不解除 `M1 U-1 UNRESOLVED`、不宣称任何真实 OOS/Alpha 证据，不改变 M3 旧账本/旧 Hash/旧协议的不可变性。
