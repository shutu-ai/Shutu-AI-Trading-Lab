# M2 Residual Safety — T0 基线（2026-11-20）

- 远端审查基线：`9a69a16`（run 44806785967 双矩阵 306 passed——旧测试范围）
- 本地 HEAD：`9f20f23`（领先 1 提交；**已核实 docs-only**：仅 `M2-independent-review-remediation.md` 2 行 CI 补录；保留，未覆盖）
- 工作树：clean（仅本任务书未跟踪，随整改提交留档）
- 回归分母：306 用例（contract+security 140 / no_lookahead 71 / risk 19 / oms 14 / architecture 26 / fault_injection 12 / m2_remediation 24）；故障矩阵 1,080 独立实例（seed=20261120，本轮重跑单列记录，不与旧报告合并计分）

## 责任图与信任边界（T0）

```text
SchemaGate(准入) -> RiskEngine(密封批准, HMAC) -> OmsEngine(校验密封+journal-before-send)
  -> BrokerEgress(fence 前校验 + port 调用 + fence 后重校验) -> FakeBroker
KillSwitch: 全局 HALT 唯一权威（RiskEngine/OMS 入口检查）；AuditLog: 唯一审计链
Journal(SQLite WAL FULL): 意图/尝试/事件唯一事实源
```

## R1–R5 风险点与处置计划

| ID | 风险 | 处置 |
|---|---|---|
| R1 | FenceError/UNKNOWN 仅意图级 HALT，无全局持久 KillSwitch → 新意图可继续发送 | FenceError 与 acknowledged=None 分支统一调用 ks.set()；RED：A 失去 fence 后新密封意图 B 必须 0 发送 |
| R2 | BrokerEgress 仅凭 fence 即发送，无 journal 资格校验 → 可无意图直发 | egress 注入 journal+secrets：coid 必须存在 SUBMITTING 意图 + 匹配 fence_epoch 尝试 + 字段绑定 + HMAC 密封重验；cancel 校验意图存在 |
| R3 | transition_state 仅 CAS 不校验状态机合法性 | journal 内调用 validate_transition，非法转换拒绝且状态/版本不变 |
| R4 | apply_fill 不拒 qty≤0/NaN/Inf/float/非 Decimal | 入口类型与数值校验，拒绝时零事件零状态零误报 |
| R5 | OMS 不比对 intent 账户/环境与自身装配；expected_policy_hash 可缺省 | submit 显式比对；构造器强制非空 policy pin |

## 复用清单

contracts（TradeIntent/RiskDecision）、security（ApprovalSecrets/KillSwitch/AuditLog/canonical）、oms.states（唯一转换表——R3 直接复用）、brokers.port——**零新模块**；修改仅限 oms/journal、oms/egress、oms/engine、security/approval（共享校验 helper）。

## 先红后绿矩阵（新增负例分母，单列计分）

R1×3（fence 丧失后新意图、UNKNOWN 后新意图、崩溃恢复入口）、R2×5（无意图直发、字段替换、重放、journal/审计不可用先拒、合法正例）、R3×4（非法转换拒绝）、R4×6（零/负/NaN/Inf/float/非 Decimal）、R5×3（跨账户、跨环境、缺省 pin）。
