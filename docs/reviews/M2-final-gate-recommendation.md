# M2 最终工程阶段门关闭建议（仅建议，非批准记录）

> **Task ID**: `M2-FINAL-GATE-AND-M3-GATED-20261121-001` A 阶段
> **性质**：本文是 Codex 基于全量验证结果生成的**关闭建议**，不是批准记录。M2 正式关闭须由用户明确签批 `M2_GATE=CLOSED`。
> **日期**：2026-11-21

## 1. 结论建议

| 维度 | 建议值 | 范围限定 |
|---|---|---|
| **E** | **PASS_WITH_SCOPE(MOCK_ONLY)** | 仅本地合成数据 + FakeBroker 工程安全验证；真实 Alpaca 幂等/撤单/查单 `BROKER_BEHAVIOR_UNVERIFIED` |
| **S** | **N_A** / NOT_EVALUATED | 合成交易不产生 Alpha/OOS 统计证据 |
| **R** | **NOT_STARTED** | 无真实账户、无资金、无券商凭证 |
| **数据** | **BLOCKED_DATA(全市场研究)** | M1 U-1 UNRESOLVED + 供应商订阅/凭证缺失 |

## 2. 已具备的证明（全部由自动化测试锁定，经双平台 CI 验证）

| 安全不变量 | 验证方式 | 覆盖分母 |
|---|---|---|
| journal-before-send（写盘失败=零发送） | `test_intent_persisted_before_send` + no_journal × 120 实例 | 121 |
| 原子 Send Claim（并发恰好一人成功） | Barrier(2) × 100 轮线程 + 两进程 × 50 轮（spawn ctx） | 150 |
| UNKNOWN 不盲重发/不换 coid/不替代意图 | ack_lost × 260 + unknown_then_resend × 120 实例 | 380 |
| 陈旧执行者 0 接受写入 | stale_writer × 140 + fencing CAS + per-racer connection | 141 |
| 审批密封（伪造/替换/过期 → 0 发送） | HMAC seal + TTL + 绑定校验 × 24 安全负例 | 24 |
| KillSwitch 持久 HALT + 恢复解锁 | `test_kill_switch.py` + crash 轮 | 10 |
| 恢复对账 + 操作人解锁双因子 | `test_recovery_reconciles_unknown_and_requires_unlock` × 5 crash 轮 | 5 |
| Risk vs OMS 双层防线 | RISK_DENY + OMS_DENY_PREAPPROVED（无条件执行） | 2 |
| 架构边界（3 平面 0 违规） | `check_architecture.py` EXIT=0 | 全部 18 文件 |
| 安全负例（Schema/密钥/隔离/PIT） | tests/security × 140 + no_lookahead × 71 | 211 |
| 1,080 故障矩阵 | `test_fault_matrix.py` 种子=20261120，0 violations | 1,080 |
| 跨进程 journal claim 仲裁 | `test_a5_true_process_race.py` 双真实 OS 进程 Barrier × 50 | 50 |
| Abrupt crash + persistent HALT + new-risk block | `test_a6_strict_process_proof.py` × 5 | 5 |

## 3. 未具备的证明（不因 M2 通过而改变）

| 缺失项 | 归属阶段 | 现状 |
|---|---|---|
| 真实 Alpaca 幂等/撤单/查单可见性 | Paper 专项（用户授权后） | `BROKER_BEHAVIOR_UNVERIFIED` |
| 真实账户/持仓/现金对账 | M2+（需 Paper 凭证） | MOCK_ONLY |
| 跨宿主故障一致性 | M2+ Live 准备 | 单宿主 MOCK_ONLY |
| 全市场研究数据许可/PIT/质量 | M1 BLOCKED_DATA（U-1 + 订阅） | BLOCKED_DATA |
| 真实策略收益/OOS 统计 | M3+（需合格数据） | 无 |
| R6 TOCTOU 窗口（port 调用中 epoch 接管→HALT） | Paper 专项验证 | 已缩小但未完全消除 |
| R7 六字段 MOCK_ONLY 不可执行（daily loss/drawdown/rate/snapshot/ack-wait/margin） | Paper 专项 + 真实账户数据 | 逐决策审计 + LIVE 硬拒 |
| R3 订单级对账 MOCK_ONLY（无 positions/cash 账本） | Paper/实盘阶段 | 生产恢复需完整对账 |
| ApprovalSecrets 跨进程分发 | 真实部署阶段 | 单进程 MOCK_ONLY |

## 4. 准确区分

| 项 | 说明 |
|---|---|
| A7-T1 有条件 OMS 提交 | A7-T1 的 crash 恢复后 OMS 仍在 HALT 状态（自动），测试用 `if new_decision.allow` 有条件调用——这是**正确的**（HALT 下 OMS 拒绝），但 A7-T2 的无条件 OMS 拒绝测试（预批准决策 + HALT → submit → HALT_NEW_RISK）是更严格的独立证明 |
| A7-T1 未独立证明第二次 claim 和第三个 KillSwitch | 本轮 A6 已补充：二次 claim 拒绝 + 新 KillSwitch 对象持久 HALT 确认（A6-T2） |
| 历史 A2/A5/A6 日志曾被重生成 | A2 日志被重生成（格式修复）；A5 日志曾覆盖 `process_concurrent_50.log`（同一文件覆盖式写入）；A6 日志为新文件。这些不是伪造数据，但确实不是原始首次运行日志 |
| manifest 非全库完整性证明 | SHA-256 manifest 仅覆盖 evidence 目录文件，不覆盖 src/ 或测试代码——代码完整性由 Git commit SHA 保证 |

## 5. 残余风险与 M3 阻断分析

| 残余风险 | 是否阻断 M3 合成数据离线工程 | 是否阻断真实全市场研究/实盘 |
|---|---|---|
| 真实 Alpaca 幂等 UNVERIFIED | **否** | **是** |
| U-1 VendorFacts 词表 | **否** | **是** |
| Sharadar/Polygon/Alpaca 供应商凭证 | **否** | **是** |
| R6 TOCTOU 窗口 | **否**（FakeBroker 单宿主范围） | **是**（跨宿主场景） |
| R7 六字段 MOCK_ONLY | **否**（合成 fixture 不使用真实账户状态） | **是** |

**结论**：上述残余风险不阻断 M3 的 SYNTHETIC_ENGINEERING_ONLY 模式。但继续阻断真实全市场研究、Paper/Live 实盘及任何真实资金操作。

## 6. 建议审批语句（候选文本，非授权）

> 我批准 M2_GATE=CLOSED，范围 E=PASS_WITH_SCOPE(MOCK_ONLY)，保留 BLOCKED_DATA、U-1 UNRESOLVED、BROKER_BEHAVIOR_UNVERIFIED、S=N_A、R=NOT_STARTED；不授权 M3 启动和任何真实券商交易。

## 7. 审批后流程

用户发出上述含义的明确审批后，Codex 才可在新的授权任务中写入已签批事实（附来源/时间/范围），并启动 M3 的 B0 双授权检查与 B1 协议冻结。
