# M3.5-S8 执行授权核验记录（Authorization Check Record）

> Task ID: `M3.5-S8-READONLY-MARKET-DATA-GATE-20261122-001`
> 记录日期: 2026-11-22
> 记录人: Codex 执行代理（Claude Code 会话，本仓库工作区）
> 性质: 本文件是对**用户人工签批**的忠实记录，不是签批本身；签批原文见 §2（源记录为执行会话中用户发出的批准文本）。

## 1. 签批前核验（T0 硬门，审批草案 §3）

执行开始前的仓库状态核验（全部为执行会话实查）：

- `git status --short`：仅 4 个未跟踪 docs（`M3_5_S8_ReadOnly_Data_and_Paper_Approval.md` 审批草案、`M3_5_Shadow_Forward_Codex_Task.md`、`M3_R1_Independent_Review_20261121.md`、`M3_R2_Research_Evidence_Integrity_Codex_Task.md`），无代码漂移。
- `git rev-parse HEAD` = `git rev-parse origin/main` = `d85d1051525c33eeb5727f53afa8a8572b779513`（docs-only 后续提交；受测代码基线 `de39b40`/`a06e0dc`，CI run 45006808270 双矩阵 686 passed）。
- 审批草案文件（repo 内 `Shutu_AI_Trading_Lab_M3_5_S8_ReadOnly_Data_and_Paper_Approval.md`）头部明确声明其自身**不是签批**，仅为待签草案。
- 原始 M3.5 S0–S7 授权（`artifacts/evidence/M3.5/authorization.md`）明确 S8 需**单独授权**，不继承。

## 2. 用户签批（原话）

签批时间 2026-11-22，方式：用户在执行会话中直接发出以下批准文本（**逐字记录**，即本阶段的授权源记录）：

> **Shutu AI Trading Lab — M3.5 S8 阶段审批**
>
> 批准启动 **M3.5-S8 真实行情只读 Shadow 验证**，范围限定如下：
>
> 1. 首选 Alpaca 免费 Basic/IEX 行情，初期不超过 3 个美国股票或 ETF 标的，仅进行真实行情接收、预测锁定、后续结果观察和工程证据记录。
> 2. 批准对 M1 U-1 `VendorFacts` 非法枚举值误放行缺陷进行最小修复，并补充正反测试，但不解除全市场历史研究 `BLOCKED_DATA`。
> 3. Codex 负责开发只读行情适配和数据质量验证；Alpaca 账户注册、许可确认及密钥安全配置由我本人完成。未具备合法数据访问条件时停止真实连接。
> 4. 保持既有 M3.5 Synthetic Replay 能力和 686 项回归；真实前向预注册另起版本，不覆盖 M3/M3.5 既有协议和证据。
> 5. 至少观察 5 个真实美股交易日，并验证断线、重启、重复事件和时间可得性。观察不足不得申报完整 E-Gate PASS。
> 6. **暂不批准 Alpaca Paper 写操作**，禁止任何模拟订单或真实资金订单；禁止自动购买付费行情、解封最终 Holdout、启动 M4 或未经授权推送。
>
> 工程完成后提交独立验收报告、源码及证据，停止在 M3.5 人工阶段门。
>
> 审批范围：`S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE`
>
> 保持：`PAPER_WRITE=NOT_AUTHORIZED / R=NOT_STARTED / S=INCONCLUSIVE / BROKER_BEHAVIOR_UNVERIFIED`。

## 3. 批准范围（边界，据此执行）

- **批准执行**：S8 只读真实行情 Shadow 工程 — 只读行情适配器 + 数据质量验证 + U-1 最小修复（正反测试）+ 真实前向预注册（**另起新版本**）+ 工程证据。
- **批准但未执行（需用户先完成前置）**：真实行情采集本身 — Alpaca 账户注册、许可确认、密钥安全注入由账户所有者（用户）完成；本机当前无 `APCA_*` 凭证，真实采集处于 `BLOCKED_ENV`，采集器在凭证注入并显式传入操作者授权标记前**拒绝任何真实连接**。
- **持续禁止（无需再次确认）**：
  - Alpaca Paper 写操作（`PAPER_WRITE=NOT_AUTHORIZED`）— 本阶段无任何 broker 适配器/写路径；
  - 自动购买付费行情（SIP/付费计划在预注册加载器即被拒绝）；
  - 解封最终 Holdout、启动 M4、解除全市场历史 `BLOCKED_DATA`、解除 `M1 U-1` 封闭词表语义；
  - 未经单独授权的 push；
  - 将合成/自测事实计为真实前向交易日。
- **停止条件**：S8 工程完成后停止在 `M3.5_GATE=USER_PENDING`，提交三轨验收报告与证据。

## 4. 与审批草案的关系

repo 内草案文件（§0–§10）是本签批的编制依据之一；**用户签批文本（§2）与草案不一致时以签批文本为准**。签批文本相对草案的要点差异：签批文本为总括性批准（未逐字采用草案 §1 建议文本），并将断线/重启/重复事件/时间可得性的工程验证与"观察不足不得申报完整 E-Gate PASS"列为明确条件（草案 §6 同义）。
