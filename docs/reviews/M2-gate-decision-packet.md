# M2 阶段门审批决定包（待审批，非批准记录）

> **性质**：本文是供用户审批 M2 阶段门的决策包。`approver` 为 USER_PENDING——Agent 不得代签。
> **Task ID**: `M2-FINAL-GATE-AND-M3-GATED-20261121-001`

## 仓库与 CI 信息

| 字段 | 值 |
|---|---|
| 仓库 | `shutu-ai/Shutu-AI-Trading-Lab` |
| 远端 main | `1988cab264e6f76ee280eb245e3ce16378be9ba2` |
| 最终 A7 已验证代码 SHA | `379bd72b19a6ee416e48444c4e4bab6e1eb8f120` |
| CI Run | [`44912904901`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44912904901) |
| CI 结果 | Ubuntu ✓（42s）+ Windows ✓（6m12s），各 347 passed |
| 本地 HEAD | `1988cab`（=远端，无未推送提交） |
| 工作树 | clean |

## 测试分母

| 类别 | 数量 |
|---|---|
| M0 安全回归（contract+security） | 140 |
| M1 no_lookahead | 71 |
| M2 risk 引擎 | 19 |
| M2 OMS 核心 | 14 |
| M2 架构检查器 | 26 |
| M2 故障注入 | 29（含 12 原始矩阵 + 4 竞争 + 2 A2 + 2 A5 + 2 A6 + 7 A7） |
| M2 A7 定向证明 | 48（含 A7 新增 + 既有 m2_remediation 迁移） |
| **合计** | **347** |
| 故障矩阵（独立分母） | **1,080** 实例 × 9 类，0 violations，seed=20261120 |

## 主要 E/S/R 字段

| 字段 | 值 |
|---|---|
| E | **PASS_WITH_SCOPE(MOCK_ONLY)** |
| S | N_A |
| evidence_state | NOT_EVALUATED |
| R | NOT_STARTED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |

## 已具备证明摘要

- Journal-before-send（写盘失败=零发送）：事务层验证 + 120 no_journal 实例
- 原子 Send Claim：100 轮线程 Barrier + 50 轮双进程 + BEGIN IMMEDIATE CAS
- UNKNOWN 不盲重发：380 实例（ack_lost + timeout + hostile resend）
- 审批密封：HMAC + TTL + 绑定校验（伪造/替换/过期 → 0 发送）
- KillSwitch：持久 HALT + 恢复解锁双因子
- 跨进程 fencing：50 轮双真实 OS 进程 BEGIN IMMEDIATE 仲裁
- 恢复对账 + 操作人解锁双因子：5 轮 crash 后显式 recover + 零未决解锁
- 3 平面架构边界 0 违规：data/risk/oms/brokers 各自禁用方向已验证
- 347 用例在 Ubuntu + Windows CI 双平台通过（多轮验证）

## 未具备证明

- 真实 Alpaca 幂等/撤单/查单可见性：BROKER_BEHAVIOR_UNVERIFIED
- 真实账户/持仓/现金对账：MOCK_ONLY
- 跨宿主故障一致性：单宿主
- 全市场研究数据：BLOCKED_DATA（U-1 UNRESOLVED + 无供应商凭证）
- 真实策略收益：无

## 剩余限制

- R6 TOCTOU 窗口（port 调用中 epoch 接管→HALT）：已缩小但未完全消除
- R7 六字段 MOCK_ONLY：逐决策审计 + LIVE 硬拒
- R3 订单级对账 MOCK_ONLY：positions/cash 账本归 Paper/实盘阶段
- ApprovalSecrets 跨进程分发：UNVERIFIED

## 审计说明

- A5 原报告"零产品代码变更"需修正：后续 `4a327b4` 修改了 `fence.py`（read lock），属产品代码变更
- A2 日志曾被重生成（格式修复）；A5 `process_concurrent_50.log` 为覆盖式写入；这些不是伪造数据但非原始首次运行日志
- manifest 仅覆盖 evidence 目录文件，不覆盖 src/ 代码——代码完整性由 Git SHA 保证
- 历史 A2/A5/A6 日志不得在未来轮次覆盖——本轮及后续测试输出路径已隔离

## 待用户审批原文

以下为建议的审批语句。**仅当用户真正发出相同含义的审批后，才可在新的授权任务中写入已签批事实。**

> 我批准 M2_GATE=CLOSED，范围 E=PASS_WITH_SCOPE(MOCK_ONLY)，保留 BLOCKED_DATA、U-1 UNRESOLVED、BROKER_BEHAVIOR_UNVERIFIED、S=N_A、R=NOT_STARTED；不授权 M3 启动和任何真实券商交易。
