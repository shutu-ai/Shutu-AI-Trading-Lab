# ADR-002 补编: M2 OMS / 风控 / 单写者出口实现决策

| 字段 | 值 |
|---|---|
| 状态 | ACCEPTED（M2 范围内，MOCK_ONLY） |
| 日期 | 2026-11-20 |
| 阶段 | M2（独立风控与 OMS 崩溃一致性） |
| 编号说明 | 计划为 M3/M6/M11 预留 ADR-004/005/006，本补编挂靠 ADR-002（隔离边界）以避免编号冲突 |
| 范围 | 合成数据 + 本地 Fake Broker；真实 Alpaca 一切行为 `BROKER_BEHAVIOR_UNVERIFIED` |

## 决策

### D1 — Journal: SQLite WAL + synchronous=FULL（标准库，零新依赖）

订单意图/尝试/事件持久化用 SQLite（`sqlite3` 标准库），WAL 模式 +
`synchronous=FULL`：每次提交 fsync WAL，进程崩溃不丢已提交事务（SQLite
承诺），断电场景由 WAL 全同步语义覆盖到"已提交即持久"。选型对比：
- 二进制 append-only JSONL + 每行 fsync：可实现但需自证 atomic-append 与
  tail-torn 处理，工程量大于收益 → 拒绝。
- 任何服务型存储（Postgres/Redis）：任务书明令禁止的中间件 → 拒绝。
- 内存"持久化"：fail-closed 要求禁止 → 拒绝。
事务边界：意图 PREPARED 写入 + SUBMITTING 尝试记录在**同一事务**提交后才
允许调用出口；出口调用成功后回执另起事务落盘。崩溃恢复以 Journal 为唯一
事实源。

### D2 — 风控前置且独立：决策以数据形式传给 OMS

`RiskEngine.evaluate(intent) -> APPROVE / REJECT / HALT_NEW_RISK`（结构化
原因码 + Decimal 金额）。OMS 只消费 `RiskDecision` 契约（§2.2），**不 import
risk 包**；risk 包不 import oms/brokers（架构检查器强制）。检查顺序冻结：
Kill Switch → 授权/签批有效性 → 账户/环境/标的/价格 → 额度/预算/新鲜度 →
审计可用性。任何一级失败即终态，短路且审计。

### D3 — 生产者身份：不可伪造的内部对象绑定（MOCK_ONLY 标注）

`risk.TrustedProducer` 由受信运行时入口构造（私有构造签名 + 运行时随机
token 比对），测试/外部 JSON 无法伪造成合法生产者。跨进程的真实身份传递
**本阶段未实现**，全局标注 `MOCK_ONLY/UNVERIFIED`；不得宣称完整生产隔离。

### D4 — 单写者出口：SQLite 原子 epoch + 租约 fencing

`(environment, account_id)` 的 fencing epoch 存 SQLite（事务内 `UPDATE ...
SET epoch = epoch + 1` 原子递增），租约带过期时间。所有 broker 写经唯一
`BrokerEgress`：先校验本地 fence（epoch/租约/账户绑定），无效即拒绝且不出
口。双实例争用由 SQLite 事务串行化保证（同机跨进程真实并发测试证明）。
FakeBroker 不认识 epoch——**核心保证在出口，不在 mock 的 valid_fences**。
单宿主多进程为当前边界；多宿主分布式 fencing 无消费者，不做。

### D5 — UNKNOWN 语义：可证明事实 vs 不确定事实

- 出口调用**前**写 `SUBMITTING`（同事务含完整意图）→ 出口调用**后**才可能
  出现"券商已收到但结果未知"。凡响应丢失/`get_order=None`/404/429/5xx/超时
  → 状态 `UNKNOWN` + `HALT_NEW_RISK` + 审计，**绝不自动重发/换 coid/替代
  意图/清除 UNKNOWN**；恢复必须先对账（reconcile）+ 操作人解锁。
- 重试仅当存在**可证明未送达**（如出口在校验阶段即拒绝、连接未建立）——
  FakeBroker 注入的"未到达"类故障属此类；其余默认无该保证。
- ACK/成交回报按 broker event id 幂等去重，重复/乱序不双计。

### D6 — 恢复（recovery）：对账解锁

进程重启 → 读 Journal 未终态意图 → 取新 fencing epoch → `HALT_NEW_RISK`
冻结新增风险 → 对 FakeBroker 对账（`get_order` + 本地状态比对）→ 一致的
标记 `RECONCILED` → 操作人显式解锁（Kill Switch clear 语义）才恢复新增
风险。审计/Journal 打不开 → fail-closed 停止，不降级运行。

### D7 — 合成数据边界

M1 BLOCKED_DATA 不变：M2 全部使用显式标注 `synthetic-engineering-fixture`
的数据与标的（测试符号如 `TEST_SYMBOL_A`），真实研究准入路径在 risk 层继续
拒绝（无授权签批/无已确认许可）。`engineering_mode` 一类全局开关**不存在**
——合成性由数据来源标注与测试作用域保证，不进生产配置。

## 已知限制（诚实记录）

1. `MOCK_ONLY/UNVERIFIED`：FakeBroker 去重/行为不证明真实 Alpaca 幂等、
   撤单、429/5xx、查单可见性——Paper 实测需用户另行授权的专项阶段。
2. 生产者跨进程身份、多宿主 fencing：未实现（无消费者，不预建）。
3. WAL FULL 覆盖进程崩溃与掉电（SQLite 语义）；存储介质级损坏不在 M2 威胁
   模型（单机可信盘），备份/恢复演练归后续常驻服务阶段。
