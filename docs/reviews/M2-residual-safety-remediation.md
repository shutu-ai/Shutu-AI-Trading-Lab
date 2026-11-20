# M2 残余安全不变量整改记录（M2-RESIDUAL-SAFETY-GATE-001）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `9a69a16`（run `44806785967` 双矩阵 306 passed——旧测试范围） |
| 本地基线 | `9f20f23`（领先 1 提交；**已核实 docs-only**：仅整改报告 2 行 CI 状态更新；保留未覆盖） |
| 整改提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-20 |
| 方法 | R1–R5 全部 RED（14 项先红，日志 `red-tests.log`）→ 最小 GREEN → 全量回归 330 passed |
| approver | **USER_PENDING**（推送、M2 关闭、M3 启动均待用户决定） |

## R1 — 全局持久 HALT（P0）→ **PASS**

- **RED**：A 失去 fence（仅意图级 HALT_NEW_RISK，KillSwitch 未触发）后，新的合法密封意图 B 照常 ACKED（创建订单）；`acknowledged=None` 分支同样不触发全局 HALT。
- **GREEN**：`oms/engine.py` FenceError 分支与 acknowledged=None 分支统一调用 `KillSwitch.set()`（账户级全局持久 HALT）+ `OMS_FENCE_LOSS_GLOBAL_HALT`/`OMS_UNKNOWN_HALT` 审计；后续任何密封意图被 OMS 入口拒绝（0 发送）。恢复路径维持：对账 + 操作人解锁，无自动解除。
- **边界**：订单级 HALT 不再被误当账户级 HALT；UNKNOWN 永不盲重发语义不变。

## R2 — Egress 必须有 journal 持久授权意图（P0）→ **PASS**

- **RED**：有效 fence 直接调公开 `egress.submit`（无 journal 意图）→ FakeBroker 创建订单；合法提交后重放 egress → 第二次创建（原 1→2）。
- **GREEN**：egress 构造要求 journal + ApprovalSecrets（缺省装配=全拒，fail-closed by absence）；每次写前执行 `check_send_eligibility`：coid 存在 SUBMITTING 意图、env/account/symbol/side/quantity 精确匹配、存在**本 fence epoch** 的 SUBMITTING 尝试、批准密封自 journal 事实重验（`build_send_binding`/`seal_is_valid` 共享构造器——引擎/OMS/出口一处定义）。任何不符 → `EGRESS_SEND_REFUSED_NO_INTENT` 审计 + EgressRefusalError，port 未被触碰。journal 不可用 → 拒绝（JOURNAL_UNAVAILABLE）。cancel 同样要求持久意图存在。**发送资格由 journal SUBMITTING 尝试行构成（先于出口存在），资格消耗后重放 = 状态不再是 SUBMITTING = 拒绝；无第二次到达。** 正例链路恰好一单。无第二审批引擎、无新中间件；oms→security 方向合法。

## R3 — CAS 同时约束状态机（P1）→ **PASS**

- **RED**：`transition_state("ACKED","NEW_INTENT")`、UNKNOWN→SUBMITTING、FILLED→ACKED、ACKED→RECONCILED、未知状态 → 全部落库成功（存储层未强制状态机）。
- **GREEN**：`transition_state` 入口调用 `states.validate_transition(expected, target)`（唯一转换表复用，无第二套），非法 → JournalError 且状态/版本不变；合法转换与 CAS 并发失败行为保留。

## R4 — 成交数量严格正有限 Decimal（P1）→ **PASS**

- **RED**：`qty=0/-5/-Infinity/NaN/5.0(int-float)/5/True` 全部被接受（负数成交会减少累计）。
- **GREEN**：`apply_fill` 入口拒绝 bool/float/非 Decimal 类型与 ≤0/非有限值（`INVALID_FILL_TYPE/VALUE`）——零事件、零状态、零误报；合法部分/足量/重复/超额语义不变。

## R5 — OMS 本地绑定与政策 pin 强制（P1）→ **PASS**

- **RED**：交叉账户意图（同密封装配）被接受发送；`expected_policy_hash=""` 缺省构造被允许。
- **GREEN**：构造器强制非空 policy pin 与 approval_secrets（缺省即 OmsError）；submit 显式比对 `intent.environment/account_id` 与 OMS 装配（`OMS_ENVIRONMENT_MISMATCH`/`OMS_ACCOUNT_MISMATCH` → REJECTED 零发送）。正常 Paper 正例保留；Live 继续硬拒（R2 语义不变），永不接真实 broker。

## 验证

| 项 | 结果 |
|---|---|
| 回归 | 330 passed（306 原样 + 24 新增，单列计分）；分项 140/71/19/14/26/12/48 |
| 故障矩阵 | 1,080 独立实例（seed=20261120）在**新不变量**下重跑 0 violations（`fault_matrix_residual.log`，独立于旧报告计分） |
| 门禁 | environment/architecture（3 包 0 违规）/scan_secrets（0 findings）/verify_live_blocked/smoke_mock/diff --check 全 EXIT=0（`checks.log`） |
| CI | **CI_REMOTE_PENDING**（本任务无推送授权） |

## 残余边界（不因本轮视为解决）

1. R1 全局 HALT 解除仍只走 恢复对账+操作人解锁（设计如此，无自动解除）。
2. R2 资格校验为单 journal 读（多进程由 SQLite 事务串行化）；真实 broker 侧 fencing 归 Paper 专项。
3. egress 密封重验与 OMS 校验为纵深防御两层，共享 `build_send_binding` 唯一构造器（无重复逻辑）。
4. 上游 U-1、BROKER_BEHAVIOR_UNVERIFIED、BLOCKED_DATA 全部不变。

## 状态

**（2026-11-20 第二次更新）`M2_RESIDUAL_SAFETY_REMOTE_VERIFIED / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
整改提交经用户明确授权推送（`9a69a16..fc9c3d4`）后，远端 CI **双矩阵实际 PASS 于最终整改 SHA**：run `44823606397`——ubuntu ✓（34s）+ windows ✓（6m33s），URL `https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44823606397`；330 用例（含 24 项残余安全负例、1,080 实例故障矩阵、双进程争写）双平台实际执行。approver = USER_PENDING；不关闭 M2、不启动 M3。
