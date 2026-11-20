# M2 独立验收安全整改记录（M2-INDEPENDENT-REVIEW-REMEDIATION-001）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `708833dd…`（CI run `44792814901` 双矩阵 282 passed——仅证明旧测试范围） |
| 本地基线 | `30429f4`（领先远端 1 提交：docs-only CI 时序补录，已核实并保留；本任务书随整改提交留档） |
| 整改提交 | 见文末（代码/测试与报告分两个本地 commit，**未推送**） |
| 执行日期 | 2026-11-20 |
| 方法 | 每项 RED（可观察错误行为，非 ImportError）→ 最小 GREEN → 全量回归（306 passed，233 基线零删减） |
| approver | **USER_PENDING**（M2 阶段门、推送、M3 启动均待用户决定） |

## R1 — 唯一风控批准被 OMS 强制执行（P0）→ **PASS**

- **RED**：`allow=False` 决策 → 照常 ACKED（创建券商订单）；伪造 allow=True 决策 → ACKED；参数替换（QQQ/sell/5000）→ 全部照发。日志：`independent-remediation/red-tests.log`。
- **GREEN**：
  - `security/approval.py`：`ApprovalSecrets` HMAC-SHA256 密封，运行时铸造、仅与 OMS 装配共享（跨进程分发 UNVERIFIED，如实标注）。
  - `risk/engine.py`：APPROVE 决策在 `limits_snapshot` 内嵌绑定事实（`bound_symbol/bound_side/bound_quantity/decision_expires_at`）+ 对 `intent 全量 payload + symbol + side + quantity + policy_hash + decision_at + expiry` 的 HMAC 密封；决策 TTL 60 秒。
  - `oms/engine.py::submit`：发送前校验 allow/intent_id/policy_hash（OmsEngine 钉扎）/时效/密封重算/三元绑定，任何不符 → **审计 OMS_APPROVAL_REFUSED、零 journal 写入、零发送**。
  - **零契约扩展**：绑定信息放既有 `RiskDecision.limits_snapshot`（dict[str,str]），§2.2 未动；依赖规则保持（oms 不 import risk——密封工具在共享 security）。
- **负例**：allow=False、伪造、intent_id 错配、expired/future、policy 错配、三种参数替换、正例（引擎签发密封照常 ACKED 且 created==1）。

## R2 — Live 在 M2 绝对不可执行（P0）→ **PASS**

- **RED**：LIVE policy + `approval_verifier=None` → 决策 APPROVE（缺失不拒绝）。
- **GREEN**：LIVE 且验签器缺失 → `LIVE_APPROVAL_VERIFIER_MISSING` 硬拒；验签器抛异常 → `APPROVAL_INVALID:VERIFIER_FAULT` fail-closed；LIVE × MOCK_ONLY 不可执行字段存在 → `LIVE_MOCK_ONLY_UNENFORCED` 硬拒。M2 无任何 live broker adapter；`configs/live` dry_run=true 强制（M0 既有）不变。

## R3 — 解锁双因子：对账事实 + 操作人批准（P0）→ **PASS**

- **RED**：timeout→UNKNOWN→recover（查无）→ `operator_unlock("op","approved")` 成功解除（缺陷确认）。
- **GREEN**：解锁前查询 `journal.unresolved_count()`——存在任何非终态/未对账意图 → `OMS_UNLOCK_REFUSED_UNRECONCILED` 审计 + OmsError；全部 RECONCILED/终态才允许清除，并追加 `OMS_UNLOCK_MOCK_ONLY`（订单级对账、positions/cash 证明缺失如实标注）。FakeBroker 无完整持仓/现金账本 → 确证不足时**保持 HALT**，不假装生产恢复条件。KillSwitch 未被复制。

## R4 — Journal 原子事务边界（P1）→ **PASS（含真实缺陷修复）**

- **RED（超出审查预期的真实缺陷）**：崩溃窗口模拟证明 **原子性承诺未兑现**——journal 用 `isolation_level=None`（autocommit），`with conn` 上下文不启动事务，两条 INSERT 各自立即提交；"同事务"注释与实际不符。
- **GREEN**：显式 `BEGIN IMMEDIATE / COMMIT / ROLLBACK` 事务；新增 `record_intent_and_submitting(...)`（意图+SUBMITTING 尝试+崩溃模拟同一事务，先红测试 `test_crash_between_steps_leaves_no_sendable_state` 证明提交前崩溃=零行）；移除无消费者的两步法（record_intent/mark_submitting/set_state——CAS `transition_state` 覆盖全部转换，`WHERE state=expected` 存储层强制）；诚实记录：SQLite 事务与外部 broker 调用**不是**分布式单原子事务（不可能），崩溃窗口语义 = 提交前零行/提交后 SUBMITTING+对账恢复。

## R5 — 成交回报原子处理（P1）→ **PASS**

- **RED**：ACKED + fill 后 journal 仍 ACKED（状态/累计不落盘）。
- **GREEN**：`journal.apply_fill` 单事务：事件去重（INSERT OR IGNORE）→ 状态/数量校验（仅 ACKED/PARTIALLY_FILLED 可成交、UNKNOWN_INTENT/撤单后拒、超量拒）→ 累计 `filled_qty` + 状态跃迁同事务提交。重复事件 0 双计；部分成交持久化为 PARTIALLY_FILLED；无第二套 ledger。

## R6 — Egress fencing TOCTOU（P0 主张收窄为可证明边界）→ **PASS（MOCK_ONLY 边界如实标注）**

- **RED**：确定性阻塞 port（A 校验后阻塞于 port 内，B 提升 epoch，A 继续）→ 整改前 A 的结果被采纳为 ACKED。
- **GREEN**：`egress._assert_still_current` 在 **port 返回后**重校验 fence；被取代写者 → `EGRESS_FENCE_SUPERSEDED_DURING_CALL` 审计 + FenceError → OMS 映射 HALT_NEW_RISK（结果不采纳、不确认成功）。cancel 同样处理。
- **诚实边界（ADR-002-addendum 已含、代码 docstring 记录）**：单次 validate ≠ broker 侧远端 fencing；mock-scope 临界区不证明任意长网络调用期间的互斥——真实 broker 侧 fencing 证据归 Alpaca Paper 专项（BROKER_BEHAVIOR_UNVERIFIED）。未引入 Redis/Kafka/分布式锁；未跨外部 I/O 持有 SQLite 事务。
- **配套**：SQLite 连接新增显式 `check_same_thread` 参数（默认线程锁定；R6 测试显式跨线程模拟飞行窗口），多进程语义不受影响（每进程独立连接）。

## R7 — §6.2 强制字段执行映射（P1）→ **PASS（含 6 项 MOCK_ONLY 如实标注）**

| 字段 | 配置校验 | 执行时验证 |
|---|---|---|
| max_gross_exposure_pct | 必填/有限/正 | ✓ 执行（GROSS_EXPOSURE_EXCEEDED） |
| max_net_exposure_pct | 必填 | ✓ 执行（NET_EXPOSURE_EXCEEDED，本次补齐） |
| max_single_symbol_pct | 必填 | ✓ 执行（SINGLE_SYMBOL_CONCENTRATION，ExposureState 增加 per-symbol 输入，本次补齐） |
| max_single_order_notional_usd | 必填 | ✓ 执行 |
| max_daily_loss_pct / drawdown / 异常订单速率 / 账户快照年龄 / ACK 等待 / allow_margin | 必填 | **MOCK_ONLY 不可执行**（无可信输入源）：逐决策审计 MOCK_ONLY_UNENFORCED 清单；LIVE 决策一律硬拒 |
| require_settled_funds | 必填 | ✓ 执行（INSUFFICIENT_SETTLED_FUNDS） |
| allow_short | 必填 | ✓ 执行（SHORT_NOT_ALLOWED，本次补齐） |
| allowed_symbols | 必填 | ✓ 执行（SYMBOL_NOT_ALLOWED） |
| max_market_bar_age_seconds | 必填 | ✓ 执行（含 **`or` 默认值陷阱修复**：显式 0 不再被默认 120 遮蔽） |
| 解锁条件（recovery_requires） | 必填 | ✓ R3 双因子 + MOCK_ONLY 标注 |

- 缺失/非有限/NaN/float/错账户/无快照 → 全部 fail-closed（tests/risk 19 例保留全绿）。

## 8. 验证与回归

- 全量：**306 passed**（M0 140 + M1 71 + M2 既有 49 + 本整改 24 + 检查器 26——原有 1,080 故障矩阵保留并在密封决策语义下重跑全绿，未重复合并虚报分母；对抗负例在 m2_remediation 独立计分）。
- 门禁：environment/architecture（3 包 0 违规）/scan_secrets（268 files, 0 findings）/verify_live_blocked/smoke_mock/diff --check 全 EXIT=0。
- 证据：`artifacts/evidence/M2/independent-remediation/{red-tests.log, green-tests.log, checks.log, fault_matrix_delta.log}`（red 日志含 21 项先红）。架构补遗见 `architecture-health.md` §D。

## 9. 残余风险与边界

1. R6 端口调用进行中的 epoch 接管 → 结果降级 UNKNOWN/HALT（不被采纳）；真实 broker 侧 fencing 归 Alpaca Paper 专项。
2. R7 六字段 MOCK_ONLY 不可执行（审计可见 + LIVE 硬拒）；真实账户状态输入归后续授权阶段。
3. R3 订单级对账 MOCK_ONLY；positions/cash 证明归后续。
4. ApprovalSecrets 单进程 MOCK_ONLY；跨进程分发 UNVERIFIED。
5. 上游 U-1（VendorFacts 词表）UNRESOLVED / BLOCKED_DATA 维持。

## 10. 状态

**（2026-11-20 第二次更新）`M2_INDEPENDENT_REMEDIATION_VERIFIED / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
整改提交经用户明确授权推送（`708833d..9a69a16`）后，远端 CI **双矩阵实际 PASS 于最终整改 SHA**：run `44806785967`——ubuntu ✓（35s）+ windows ✓（10m3s），URL `https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44806785967`；306 用例（含 24 项安全负例、1,080 实例故障矩阵、双进程争写）双平台实际执行。approver = USER_PENDING；不关闭 M2、不启动 M3。
