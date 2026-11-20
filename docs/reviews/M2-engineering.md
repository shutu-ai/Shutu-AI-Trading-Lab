# M2 — 工程验收报告（engineering）

| 字段 | 值 |
|---|---|
| stage_id | M2（独立风控与 OMS 崩溃一致性，P0） |
| commit | `b3a3feed109c7ad5a9ad9febc647d38f1162d749`（实现）；门记录 `d0d81b6`；三轨提交见后续 SHA |
| code_hash | git tree at `b3a3fee` |
| protocol_hash | NOT_APPLICABLE（M3 冻结） |
| environment | Windows 11 Pro，Python 3.13.15（`.venv`），离线；FakeBroker 零网络（smoke 扫描证明）；故障注入种子 `20261120` |
| test_commands | 见 §3（全部本地 EXIT=0）；远端 CI = **CI_REMOTE_PENDING**（未获推送授权） |
| evidence_paths | `artifacts/evidence/M2/{verification.log, fault_matrix_report.txt, architecture-health.md, upstream-data-risks.md}` |
| findings | 本地工程缺陷 0（TDD 红→绿）；上游 M1 缺陷 1 项确认并登记（VendorFacts 非法字面量，未修——需单独授权）；真实 Alpaca 行为 BROKER_BEHAVIOR_UNVERIFIED 不变 |
| status | **E = PASS_WITH_SCOPE (MOCK_ONLY)**；全市场研究数据 BLOCKED_DATA 不变 |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |
| next_gate | M2 阶段门人工复核；推送需另行授权；M3 不得自动启动 |
| approver | USER_PENDING |

## 1. T0–T7 交付对照

| 任务 | 交付 |
|---|---|
| T0 盘点/ADR/红绿计划 | ADR-002-addendum-m2（编号避开 M3/M6/M11 预留）；architecture-health 基线 A 节；冻结指标 ≥1,000 |
| T1 独立风控 | `risk/`：policy（§6.2 全字段必填、Decimal、float 拒绝）、engine（冻结检查序→APPROVE/REJECT/HALT_NEW_RISK+结构化原因码+审计）、producer（不可伪造对象绑定，MOCK_ONLY 如实标注）；复用 KillSwitch/SchemaGate 语义不重写 |
| T2 唯一 OMS | `oms/`：SQLite WAL FULL journal（意图+SUBMITTING 同事务先于发送，写盘失败=零发送）、合法转换表状态机、journal-before-send、UNKNOWN→HALT_NEW_RISK→恢复对账→操作人解锁；回报按 broker_event_id 幂等去重 |
| T3 单写者出口 | SQLite 原子 epoch + 租约 fencing（跨进程事务串行化）；唯一 BrokerEgress 先验 fence 后调 port；FakeBroker 不认识 epoch——保证在出口不在 mock；真实双进程争写测试（50 次跨进程获取，epoch 全唯一，陈旧 token 100% 拒绝） |
| T4 故障注入 | **1,080 独立实例**（9 类，seed=20261120，`fault_matrix_report.txt`）：0 重复建单、0 盲重发、0 陈旧写入、0 无意图发送、UNKNOWN 永不清除；核心不变量按实例断言（created_by_intent ≤ 1 不靠 mock 去重掩盖） |
| T5 架构硬门 | 3 平面规则（data/risk/oms 禁兄弟平面、oms→brokers 唯一豁免、包内导入豁免、包边界匹配）+ 26 自测；brokers 平面零网络导入（smoke 扫描）；零新增依赖（SQLite=标准库）；POC 零导入 |
| T6 上游风险 | **确认 M1 缺陷**：VendorFacts 枚举字段接受非法字面量并静默放行（合成复现：P1/P2 均 ACCEPT）；按任务书只登记不修（`upstream-data-risks.md`），列为真实研究数据解封的前置阻断项 |
| T7 CI/证据 | 本地全门禁 EXIT=0（verification.log）；远端 CI_REMOTE_PENDING；证据全部新建于 artifacts/evidence/M2/（不覆盖历史） |

## 2. 安全不变量断言（全部由自动化测试锁定）

| 不变量 | 测试 |
|---|---|
| INV-1 journal-before-send（写盘失败=零发送） | `test_intent_persisted_before_send`、no_journal × 120 实例 |
| INV-2 UNKNOWN 不盲重发/不换 coid/不替代意图/不清除 | `test_unknown_faults_never_resend`、unknown_then_resend_attempt × 120、ack_lost/timeout × 260 |
| INV-3 陈旧执行者 0 接受写入 | stale_writer × 140、`test_stale_token_refused_at_egress`、多进程争写（陈旧 token 全拒） |
| INV-4 回报幂等（重复不双计） | `test_duplicate_fill_ignored`、duplicate_fill × 110 |
| INV-5 恢复先对账+操作人解锁 | `test_recovery_*`、late_recovery × 110 |
| 风控越权/非法信号 100% 拒绝 | tests/risk 19 例（含 kill switch、审计不可用、越权生产者、错账户/环境/标的、过期、超额） |

## 3. 实际运行命令与退出码（HEAD `b3a3fee`）

```text
python -m pytest -q            EXIT=0（282 passed；分项 140/71/19/14/26/12）
scripts/check_environment.py   EXIT=0（3.13.15）
scripts/check_architecture.py  EXIT=0（3 包 18 文件 0 违规）
scripts/scan_secrets.py        EXIT=0（238 files, 0 findings）
scripts/verify_live_blocked.py EXIT=0
scripts/smoke_mock.py          EXIT=0（含 M2 语义：brokers 平面零网络导入扫描）
scripts/… fault matrix         EXIT=0（1,080 instances, 0 violations, seed=20261120）
git diff --check               干净
```

## 4. 诚实边界（不冒充）

1. **MOCK_ONLY**：FakeBroker 的去重/行为不证明真实 Alpaca 幂等/撤单/429/5xx/查单可见性；`BROKER_BEHAVIOR_UNVERIFIED` 保持。
2. **生产者身份**：单进程内不可伪造；跨进程传递未实现——MOCK_ONLY/UNVERIFIED，不宣称完整生产隔离。
3. **多进程**：真实双进程争写已实现并通过；首次运行曾出现 1 次未复现瞬态失败（连后续 5 次全绿），如实记录。
4. **静态检查边界**：变量化动态导入/exec 不可检（检查器 docstring 记录），归进程隔离阶段。
5. **BLOCKED_DATA**：全市场研究准入不因 M2 通过而改变；上游 M1 缺陷（U-1）为解封前置阻断项。
