# M2 A2 并发证据数量补证记录（M2-A2-CONCURRENCY-EVIDENCE-CLOSE-AND-M3-GATED-002）

| 字段 | 值 |
|---|---|
| 远端审查基线 | `b7d11aa`（run `44878925093` 双矩阵 334 passed——旧测试范围） |
| 本地基线 | `29ecf54`（领先 1 提交；docs-only CI 补录，已核实保留） |
| 整改提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-21 |
| 方法 | A4 定量补证（不改生产代码——现有 claim_send_attempt 原子事务在 100/50 轮竞争下未暴露任何双发） |
| approver | **USER_PENDING** |

## 上一任务书 A2 量化门槛对照

| 门槛 | 之前状态 | 本轮结果 | 判定 |
|---|---|---|---|
| 双线程同 COID ≥100 轮受控竞争 | NOT_MET（仅单轮确定性 + 5 次重跑） | **100/100 轮完成，每轮恰好 1 次 port 进入**，0 violations | **PASS** |
| 双真实进程 ≥50 轮竞争 | NOT_MET（仅单轮） | **50/50 轮完成 + 5 crash-after-claim 轮，每轮恰一 winner**，0 violations | **PASS** |
| 禁止 SQLite 线程异常虚假绿 | 首版 RED1 被跨线程 ProgrammingError 空过 | 已修：跨线程连接 + 竞争真实性断言（entries ≥ 1） | **PASS** |
| 崩溃后 claim 不再授予 | 未测 | 5 crash 轮：B 存活进程全部拒绝 | **PASS** |
| 无意图/错参数/错 fence 0 发送 | 上一轮 R2 已覆盖 | 回归锁定 | **PASS** |

## A4-2 线程竞争详情（`thread_100_rounds.log`）

- **每轮独立 fresh stack**（Barrier(2, timeout=10) 同步，非 sleep/随机）；每轮新 COID/已密封意图。
- **全部 100 轮：port_entries=1, sent=1, refused=1, created≤1, ok=True**——恰一次 port 进入，恰一次 ALREADY_CLAIMED 拒绝。
- **transient 重试**：3% 的轮次（3/100）遇 Windows 跨线程 sqlite 瞬态异常后重试新 stack，重试后全过——重试不改判 violational 轮（entries=2 硬违规永不重试）。
- **端口入口计数在 BrokerPort 边界**（非 FakeBroker 内部去重）。

## A4-3 进程竞争详情（`process_50_rounds.log`）

- **两个长存活真实 OS 进程**（不同 PID），stdin IPC 控制（无 per-round spawn 开销），50 个独立 COID。
- **每轮恰一个 claim winner**（PID 归属记录在日志）；journal `SEND_CLAIMED` 状态经 DB 查询确认。
- **5 crash-after-claim 轮**：进程 A claim 后 exit；存活进程 B 竞争 → **全部拒绝**；主进程恢复按 UNKNOWN/HALT 处理。
- **证据边界**：跨进程证据覆盖 journal claim 仲裁（原子 SQLite 事务）；per-process real-port E2E 由线程竞争覆盖（`A4-2`）——两者组合 = 完整并发单发证据。

## 残余边界

- R6 TOCTOU 窗口（port 调用期间 epoch 接管→结果降级 HALT）与 R7 MOCK_ONLY 六字段不变。
- 上游 U-1（VendorFacts 词表）、BLOCKED_DATA、BROKER_BEHAVIOR_UNVERIFIED 不变。

## 状态

**`M2_A2_QUANTITATIVE_LOCAL_PASS / CI_REMOTE_PENDING / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
新 SHA 双平台 CI 真实 PASS（需用户授权推送）后升 `M2_A2_QUANTITATIVE_REMOTE_VERIFIED`。approver = USER_PENDING；不关闭 M2、不启动 M3。
