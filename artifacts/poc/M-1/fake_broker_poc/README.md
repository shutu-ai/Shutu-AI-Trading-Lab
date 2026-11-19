# M-1 Fake Broker Contract POC

必测项（授权任务书 + v2.1 架构 §6.1 / §9 M-1 E-Gate）的契约级实现与测试。
运行：`python -m pytest -v`（20 个用例，Python 3.13，仅标准库 + pytest）。

## 覆盖的四个必测场景

| 场景 | 测试文件 | 关键断言 |
|---|---|---|
| 正常订单流 | `test_01_normal_flow.py` | PREPARED→SUBMITTING→ACK→FILLED；broker 恰好收到 1 次提交；事件按 broker event_id 去重；WAL+synchronous=FULL 落库断言；确定性 client_order_id；重复 intent 拒绝；负数量在 intent 校验层拒绝 |
| 未知订单状态 | `test_02_unknown_state.py` | 响应丢失（before_ack_drop）→ 先对账（按 client_order_id 查单）→ 采纳 broker 真相 → **0 次重发**；conn_refused（可证明未达）→ 安全终止 CANCELED；transient 5xx → REJECTED 且 broker 无订单；UNKNOWN 未解决 → HALT_NEW_RISK，仅操作者显式解锁 |
| 崩溃恢复 | `test_03_crash_recovery.py` | 先持久化后外发（crash_before_send 后 journal 已有 intent）；恢复 = 新 OMS 实例 + 新 fencing epoch + 对账；崩溃前发送窗口由恢复补发**恰好一次**；崩溃后发送窗口采纳不重发；部分成交+崩溃恢复后补齐；broker 侧状态文件持久化使对账有意义 |
| 双执行者冲突 | `test_04_dual_executor_fencing.py` | fencing epoch 单调递增；过期租约失效；旧 epoch 写入被网关拒绝（broker 侧 valid_fences）；冻结执行者唤醒后 0 双写；新 epoch 接管后成为唯一写者 |
| （附加）环境隔离 | `test_05_env_isolation.py` | Paper 执行者无法写 Live 命名空间（env/account 不匹配即拒）；Paper 配置含 live 工件被扫描拒绝；adapter 命名空间不可变、无布尔升级路径 |

## 设计决策（记录供 M2 评审）

1. **崩溃模型**：注入异常（`CrashBeforeSend` / `CrashAfterSend`）替代子进程 kill。
   崩溃一致性主张落在 SQLite 已提交事务上（WAL + synchronous=FULL 在打开时断言），
   恢复 = 同一 journal 文件 + 全新实例。子进程级 kill 属 M2 故障注入范围。
2. **恢复语义**：UNKNOWN 永不盲目重发。broker 查单（client_order_id）→ 有单采纳；
   broker 确认无单且崩溃点在发送前 → 新 epoch 下补发**一次**（broker 侧 client_order_id
   幂等仍是第二道防线）；不可证明 → HALT_NEW_RISK。
3. **网关拒绝 ≠ 未知**：fencing 网关在 broker 之前拒绝 → 可证明未达 → 安全 CANCELED。
4. **已知限制**：对账要求 broker 可达；broker 不可达时保持 HALT（未在 POC 中构造网络层故障，
   M2 需补）；FakeBroker 的成交价格是固定常数（本 POC 只关心状态机，不关心价格正确性）。

## 结论

- 本 POC 证明的是**本地契约**（持久化顺序、状态机、fencing、对账语义）。
- **不证明**真实 Alpaca 的订单语义（超时后查单是否返回、幂等窗口、部分成交回报格式等）——
  这需要 Alpaca Paper 实测（本环境无密钥，标注 `BROKER_BEHAVIOR_UNVERIFIED`）。
- 该契约是 ADR-001 中「alpaca-py + minimal OMS」方案的自研部分工作量预估基础：
  核心协议约 500 行 + 20 个契约用例，M2 再扩展到 ≥1000 次故障组合与子进程级注入。
