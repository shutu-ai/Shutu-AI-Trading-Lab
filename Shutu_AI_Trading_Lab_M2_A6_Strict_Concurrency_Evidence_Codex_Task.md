# Shutu AI Trading Lab — M2 A6 严格跨进程同步与恢复证据补强（Codex 任务书）

> Task ID: `M2-A6-STRICT-PROCESS-BARRIER-AND-EVIDENCE-001`  
> 制定日期：2026-11-21  
> 仓库：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> 参考远端主分支：`ca29f9f56cf5e5cb3e1b24be02d1f35d7ab303b4`（执行前必须重新检查）  
> 核心代码成功 CI：run `44891635260`，**实际被测 SHA** `4a327b46337ccc3b7993bb211373c9cc172680c0`，Ubuntu/Windows 成功；`ca29f9f` 是其后的 docs-only 记录提交，不得误称此 CI 对它直接执行过。  
> 当前许可范围：**仅 M2 A6 定向整改与本地验证**；未经用户单独明确授权，不得 push，不得关闭 M2，不得启动 M3。

## 0. 目标与结论边界

A5 已证明双进程可竞争同一个持久 SQLite `claim_send_attempt`，并验证 50 轮中每轮一名成功、五轮强制终止后的基本 UNKNOWN/HALT 行为，代码与 CI 具有价值。但 `send_claim(A)`、`send_claim(B)` 后依次读回结果只证明父进程不等待第一个结果才向第二个进程发命令，**不能证明两 worker 每轮已在共同起跑屏障前 READY**；测试只校验成功数，没有独立断言 `errors=[]`/两次 attempt/最终数据库状态。崩溃测试复用 KillSwitch 对象，尚未证明对象重建后的 HALT 持久性及真实新增风险发送阻断；证据目录和生产变更表述亦存在不一致。

**本任务只填平这些证明缺口。** 禁止为了追求更多测试而重写 OMS、风险引擎、交易执行或引入新消息队列/基础设施。若发现真正的产品缺陷，先保存最小 RED 复现，再修复并 GREEN；不允许隐藏失败、削弱断言或者重命名失败为成功。

本任务**只证明本机同一 SQLite 文件的跨进程 journal 原子 claim 与 mock-only 恢复安全性**；不证明跨主机共识、真实券商幂等、BrokerPort 跨进程端到端唯一入场或 Live 交易安全。

## 1. 硬约束与预检

1. 先阅读 `AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`、`Shutu_AI_Trading_Lab_M2_A5_True_Process_Race_and_M3_Codex_Task.md`、`docs/reviews/M2-a5-independent-closure.md` 以及现有 M2 安全验收证据。
2. 输出 `git status --short`、本地 HEAD、远端 `main` HEAD、A5 CI run 与 `head_sha`，检查未提交内容。禁止 `reset --hard`、`force push`、覆盖先前证据或隐式合并用户工作。
3. `M2_GATE=USER_PENDING`、`M3_START_APPROVAL_PENDING`，`BLOCKED_DATA`、`U-1=UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED` 不变。所有测试仅合成数据 + SQLite + FakeBroker，严禁访问外部市场数据、Alpaca Paper/Live、账户密钥、真实最终 Holdout；研究状态不得提升为真实策略证据。
4. 保留 M2 既有 338 项测试目标、≥100 轮线程 Port 入口检验、≥1,080 故障组合及安全负例。任何 `skip`/`xfail`、放宽断言、改变阈值都须视为阻断项。
5. 不改变原 v2.1 架构责任边界。优先增补已有 `tests/fault_injection/`，不要另建一套交易状态机、SQLite journal 或进程协调基础设施。

## 2. A6-T0 — 差异盘点与 RED 复现

对比 `4a327b4` 和 `ca29f9f`，形成准确的提交-证据矩阵。明确：A5 原报告称“生产代码变更零”，但后续 `4a327b4` 修改 `src/trading_lab/oms/fence.py`，必须在最终复核报告中标为 **A5 首轮零产品代码变更，之后的 CI 稳定化有产品代码变更**，列出动机、回归风险和独立验证。记录 `full_checks.log` 中的采集时 HEAD 与实际代码 SHA 的区别；不静默改写原始日志。

先写故意可失败的验证证明旧测试证据不足：例如仅第一个 worker 执行 claim、第二个迟到的顺序情形可令旧“唯一赢家”断言通过，而新屏障证据必须拒绝这类流程。RED 测试仅用于证明门槛有效，不要求保留长期故意失败用例；保留可重复运行的反面测试。

## 3. A6-T1 — 跨 Windows/Linux 的逐轮双进程 READY/GO 同步屏障（P0）

### 3.1 方案

优先使用 `multiprocessing.get_context('spawn')` 加跨进程 `Barrier(3)` / `Event` / `Queue`（或等价双向 IPC）。必须同时适配 Windows 与 Ubuntu，避免依赖 fork-only 语义。

每轮：

1. 持久化新的合法意图、同一 `client_order_id`（COID）、`SUBMITTING` attempt 与适用 fence epoch；两名**独立 OS PID**拥有对同一个 COID 的 claim 资格。
2. 两名 worker 各自使用独立 SQLite connection；每轮先报告 `READY(round, pid, coid)`，进入相同的同步屏障，并保持等待；父进程确认 `ready_count == 2` 以后才放行这一轮 `GO`。
3. worker 在屏障放行后各自**直接调用生产 `OrderJournal.claim_send_attempt()`**；不得由父进程顺序调用，不得先读第一个成功结果再让第二个尝试。
4. 收集两个实际调用结果、PID、异常类/信息、持久状态、每轮 `READY/GO` 事件记录与本轮超时信息。屏障损坏、任一 worker 未 READY、提前退出、仅有一次调用、超时或 SQLite 错误都为 **FAIL**。
5. 连续 ≥50 个独立 COID、每轮硬断言：`distinct_pids=true`、`ready_count=2`、`attempted_count=2`、`claim_winner_count=1`、`loser_returned_none=true`、`errors=[]`、最终 DB attempt state=`SEND_CLAIMED`，持久 attempt 仅被消费一次。统计胜者分布但**不**要求调度公平。
6. 加入防退化测试：故意缺一名 READY、一个 worker 退出、屏障超时、第二 worker 延迟到达——必须 fail-closed/产生明确失败，而非以 `[True, False]` 当作完整成功。延迟不能靠固定 `sleep` 伪装同步；同步证据须来自 IPC 协议本身。
7. 不强求两个 SQLite `BEGIN IMMEDIATE` 真正同时持锁（SQLite 正确语义本就是串行化）；只要求两个真实进程在同一起跑屏障前 READY，放行后在相同竞争窗口尝试，不再由父进程串行重放。

必须保存完整可核查事件记录（每轮结果、失败、重试、PID、数据库状态）。严禁仅用“50/50 PASS”摘要替代逐轮证明。若使用重试，区分测试流程级重试与 SQLite 竞争重试，保留每次尝试与失败原因；不得以重试掩盖违反单发不变量。

## 4. A6-T2 — crash/restart 与真实风险阻断（P0/P1）

使用独立 OS worker 重演至少五轮：claim 已经事务提交、worker 处于 Port 调用之前的可确认停点，然后父进程 `terminate()`/等价强制异常终止并收集真实退出状态；不得用正常 `sys.exit(0)` 冒充 crash，不得仅以返回 claim 的布尔值推断崩溃发生点。

每轮检查：

- 事务已持久化 `SEND_CLAIMED`；异常终止后新进程无法再次领取同一个 COID；当 FakeBroker “暂时无记录”或查询不确定时，**不得**盲重发、补发替代意图或新增风险。
- 在真正关闭旧持有者/创建新对象后，从相同持久路径重新实例化 `OrderJournal`、`FenceCoordinator`、`KillSwitch`、`OmsEngine`，显式调用 `recover()`；`still_unknown` 包含原意图，`KillSwitch.is_halted()` 为真。
- 再次重新实例化一个独立 KillSwitch（条件允许可置于新进程），证明 HALT 可从持久介质恢复，而不只是旧对象内存标志。
- 在未完成对账/合法人工解锁前，用**具有有效 Schema、风险密封与合法账户绑定**的**新增风险请求**触发已存在的真实 mock/OMS/BrokerEgress 路径，断言其拒绝且 FakeBroker 原始 Port entry 增量为 **0**。仅 `operator_unlock("op", "")` 抛任意异常不足以证明这一点。
- 校验存在具体审计事件、失败原因类型，以及没有替代订单意图；应使用明确异常类型或错误码，不使用 `pytest.raises(Exception)` 作为唯一验收证据。

同时记录此次测试严格覆盖的是 **post-claim/pre-Port** 崩溃，不得冒称发单后 ACK 丢失、真实 broker 侧去重、跨进程 Port E2E 或跨主机分布式 fencing。对已经存在的“发送后 ACK 丢失”故障矩阵只做回归，不伪造扩展覆盖。

## 5. A6-T3 — 证据自洽、架构与测试质量（P1）

检查并补齐（以实际可复现数据为准）：

- `artifacts/evidence/M2/a6-strict-process-proof/`: `baseline.md`、`barrier_50_rounds.jsonl`、`crash_recovery_5_rounds.jsonl`、`checks.log`、`ci-verification.md`（远端未运行时应明确 `CI_REMOTE_PENDING`）、`architecture-health.md`、`evidence-manifest.sha256`；逐条 manifest 绑定文件、测试代码 SHA、数据/环境、执行命令、退出码。日志应作追加或新文件，不覆盖 A5 原件。
- 追查 A5 目录缺失的 `abrupt_crash_recovery_5.log`、`thread_retry_accounting.md`、`ci-verification.md`：如从未留存，不允许补写虚构日志；用新的 A6 测试生成可追溯替代证据，并在审查报告中注明 A5 缺口。
- `docs/reviews/M2-a6-strict-proof-review.md`: 按 **REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEBT** 做架构健康清单；区别初次 A5 提交 `719315c`、CI 修补 `4a327b4`、docs-only `ca29f9f` 与 A6 新 SHA；明确每个 CI run 所实际覆盖的 commit SHA。检查 `fence._read_lock` 对原跨线程验证与锁竞争行为有无回归。
- 验证 README/报告的 `E=PASS_WITH_SCOPE(MOCK_ONLY)` 仅针对已通过的 mock 工程安全门；如果 A6 仍未通过，标记 `A6_INCONCLUSIVE` 或 `A6_REMEDIATION_REQUIRED`，不能扩大到 E2E/真实 Broker。

## 6. A6-T4 — 不可缩减的验证矩阵

至少执行仓库现存等价命令，并存真实退出码与 pytest 汇总：

```bash
python -m pytest -q tests/fault_injection/test_a5_true_process_race.py
python -m pytest -q tests/fault_injection/test_a2_quantitative.py
python -m pytest -q
python scripts/check_environment.py
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
```

另需确证原 ≥1,080 fault matrix 实际通过，若其测试被全量 pytest 覆盖，必须明确对应文件名/用例、计数和断言；不得无证据直接写“1080 次”。保持原 100 轮同 COID 线程 BrokerPort entry 恰为 1 的判据。CI 需确认 Ubuntu、Windows 双矩阵均针对**含 A6 修复的同一代码 SHA**成功。未经用户单独授权不得 push；未推送时只能记 `CI_REMOTE_PENDING`，不能杜撰远端状态。

## 7. STOP 门、交付与后续 M3 边界

### A6 本地验收

要求上述全部 P0 与 P1 证据通过、所有安全/架构/回归门通过、日志可溯源、工作区无无意改动。可报告：

`M2_A6_STRICT_PROCESS_PROOF_LOCAL_PASS / CI_REMOTE_PENDING / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

### A6 远端验收（仅推送被用户**另行**授权后）

Ubuntu、Windows CI 对新代码 SHA 均成功，审查补遗已经记录 CI URL、run id、`head_sha` 与两平台结果，才可报告：

`M2_A6_STRICT_PROCESS_PROOF_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

出现任何屏障/持久化/风险阻断硬断言失败，必须报告 `A6_REMEDIATION_REQUIRED`，不得静默降级测试。**A6 结束立即 STOP，不替用户关闭 M2、不自动开始 M3、不擅自推送。**

### M3 仅登记待批准的范围

如果之后用户**分别明确授权**：`M2_GATE=CLOSED` 与 `M3_START=APPROVED`，再独立启动 v2.1 计划中的 M3：先冻结 `evaluation_protocol.yaml` 与 ADR-004，再实现**合成数据/纯离线回测**的 B0 现金、B1 宽基 ETF 买入持有、B2 透明单规则；B3–B8 只冻结协议与公平预算，不提前开发 AI 策略、Regime、Shadow/Paper、真实供应商或 Live。须覆盖 PIT/未来信息、成本×1/×2/×3、延迟/价差/未成交/公司行动/交收、Walk-Forward + Purge/Embargo、研究试验账本、独立 sealed Holdout 的模拟访问拒绝与污染不可复用。真实最终 Holdout 不得在 M3 解封，`BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED` 维持；`S=N_A/INCONCLUSIVE, R=NOT_STARTED`。M3 结束停在 `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`。

## 8. 给 Codex 的启动指令

请只执行本任务书 A6-T0 至 A6-T4。先核对 HEAD、CI head_sha、现有 A5 代码与证据，再 RED→GREEN 补齐**逐轮双进程 READY/GO 同步屏障、两个真实 attempt、严格错误断言、真实 SQLite 终态、异常终止后新对象持久 HALT、真实新增风险发送零入场**。禁止扩展 OMS/风控架构，禁止真实数据/券商/资金操作，保留 338 项基线测试目标、100 轮线程竞争与 1,080 故障矩阵。完成后提交准确证据和验收报告，并在阶段门停止；未授权不得 push、不得关闭 M2 或启动 M3。
