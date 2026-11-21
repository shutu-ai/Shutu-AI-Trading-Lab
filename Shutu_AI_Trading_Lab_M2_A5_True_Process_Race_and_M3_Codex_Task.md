# Shutu AI Trading Lab — M2 A5 真正跨进程竞争补证与 M3 正式执行（双阶段门 Codex 任务）

> Task ID: `M2-A5-TRUE-PROCESS-RACE-AND-M3-GATED-001`  
> 编制：2026-11-21  
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
> 独立审查远端 SHA：`1c6d7b722f38dc44881386cbb6a594984a8c1211`  
> 已核实 CI：<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44885002933>（Ubuntu + Windows SUCCESS，336 passed）  
> **当前授权边界：仅 A5 证据修正可作为下一次整改任务提出；M2 关闭与 M3 执行必须分别获得用户明确批准。未经授权禁止自动推送。**

## 0. 任务原因、目标与证据边界

原 A2 任务要求：双线程同 COID ≥100 轮、**双真实 OS 进程同时竞争同一 COID ≥50 轮**，崩溃后绝不盲重发。已有证据：

- `tests/fault_injection/test_a2_quantitative.py::test_thread_100_rounds_barrier_race`：100 轮 Barrier 双线程真实 Broker Port 入口计数；远端 CI 通过，提交日志 100 次 `port_entries=1`，可以保留为通过证据。
- `test_process_50_rounds_long_lived_workers`：使用两个不同 PID，却依次执行 `res_a = worker_a.race(...)`（同步等待结果）再执行 `res_b = worker_b.race(...)`。**这只是跨进程顺序重放测试，不是跨进程同步竞争。** 50 轮均 A 获胜，无法作为并发竞争的充分证据。
- 5 轮 `claim_exit` 使用 `sys.exit(0)`，属于正常进程退出验证；不等于异常崩溃/强制终止。日志中“恢复 UNKNOWN/HALT”的结论不能单凭后继 claim 被拒绝证明；应补充显式恢复调用及持久 HALT 断言。
- 日志的线程 `retries=0` 与部分总结中“Windows 3% 瞬态”不一致。需区分不同运行环境，并以原始可复现日志为准；不得把不完整的失败尝试隐藏在最终成功轮数里。
- `1c6d7b7` 的双平台 CI 证明现有测试通过；**不能证明现有测试没有覆盖到的真实双进程并发场景**。

**A5 目标**：只纠正上述验收证据缺口；优先不改产品代码。若真实并发测试发现可复现安全故障，先 RED 再最小 GREEN；禁止为了完成任务再造第二套发送状态机。

## 1. 不可跨越的约束

1. 先阅读 `AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`、当前 M2 报告与此任务书。
2. 开始前记录本地 HEAD、远端 main SHA、工作树状态，核查未推送的 `0ebae0d`（用户报告为 CI docs-only 补录，**不能凭报告直接认定已存在**）；保留已有改动，不允许 `reset --hard`、`force push` 或覆盖旧证据。
3. 真实 Broker 网络、Alpaca Paper/Live 凭证、资金操作、供应商注册/购买、真实 Holdout 访问均禁止；只使用合成数据、FakeBroker、离线 Python/SQLite。
4. 保留 M1 `BLOCKED_DATA`、VendorFacts `U-1=UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`；M2 本次只可达到 `E=PASS_WITH_SCOPE(MOCK_ONLY)`，不能宣称跨宿主生产级单发或真实 Alpaca 幂等。
5. 任何阶段门须由用户明确签批；CI 绿或生成 MD 不等于 `M2_GATE=CLOSED`、`M3_START=APPROVED`；未经单独授权不得推送。

---

# A 段 — M2 A5 定向补证（本轮任务；完成后**强制 STOP**）

## A5-T0 基线与审查

- 盘点 `OrderJournal.claim_send_attempt()`、`_transaction()`（`BEGIN IMMEDIATE`、`SEND_CLAIMED` 单次消耗）、`BrokerEgress.submit()`、`recover()`、`KillSwitch`、`tests/fault_injection/test_a2_quantitative.py`。
- 先记录上述顺序调用的问题与正确的预期；不能把 `50×[True,False]` 顺序重放称作真正的两个进程同时竞争。
- 保留原 100 双线程测试与 50 顺序重放测试，可以重命名后者或修改为真正并发，保证计数解释一致；不删既有 336 项验收目的和所有安全不变量。

## A5-T1 双真实进程**同步**竞争 ≥50 轮（核心硬门）

要求用 Windows/Linux 都兼容的跨进程同步：例如 `multiprocessing.get_context('spawn')` 创建两名长期存活 worker + 共享 `Barrier`/`Event`，或具双向 READY/GO 交互的 IPC（父进程必须先向两者发开始指令，**不可在等到 A 结果后才向 B 发指令**）。

1. 每轮创建新的合法 `TradeIntent` / 已密封决策 / SQLite `SUBMITTING` intent + attempt，保证两名真实 OS 进程都有资格对**同一个 COID**争夺 claim。
2. 两个 worker 均完成 `READY`，由共同同步点放行后各自调用 **真实 `OrderJournal.claim_send_attempt()`**；成功者在 SQLite 中完成 `SEND_CLAIMED` 持久提交。
3. 父进程分别收集两个 PID、两者到达竞争门的确认、返回值、错误类型、事务状态和 SQLite 持久最终状态；每轮要求 `two_distinct_pids=true`、`ready_count=2`、`attempted_count=2`、`winner_count=1`、`SEND_CLAIMED=true`、`errors=[]`。
4. 50 个独立 COID、50 轮均满足；超时、worker 提前异常退出、Barrier 失效、只有一个 worker 实际尝试，视为无效/失败，不能做 PASS。禁止仅用 `sleep` 和调度时间猜测竞争成立；也不能以两个 PID 的存在代替同步证明。
5. 若验证跨进程 Port 调用次数，必须提供真正进程外可汇总的 Port-entry 证据；否则明确写“证明跨进程 journal claim 仲裁，不证明跨进程 BrokerPort E2E”。
6. 不强制两个 PID 必须各胜多少轮（调度不保证公平），但要统计获胜者分布、每轮屏障证据，并排除“始终让 A 先完全执行、B 再开始”的原测试缺陷。

## A5-T2 异常终止及持久恢复 ≥5 轮

- 真正让领取 claim 的 worker 在 DB commit 后、Port 调用前**非正常终止**（如独立 worker 内 `os._exit(nonzero)`、由父进程定点 `terminate` 等），记录非零/信号终止、持久 `SEND_CLAIMED` 和每轮具体 COID。
- 另一个仍存活的进程不得再次拿到该 claim；无 Port 意外发送/重复调用。
- 重建 OMS/Journal/Fence/KillSwitch 后明确调用 `recover()`，假定 FakeBroker 查询“查无”仍必须 `still_unknown` 包含该意图且全局持久 HALT。审计记录存在，人工未解锁前任何新增风险发送为 0。
- 不得把进程正常 `sys.exit(0)` 或没有运行 `recover()` 的测试描述为“异常崩溃与恢复已验收”。

## A5-T3 线程测试、重试与证据质量

- 原 ≥100 轮 Barrier 双线程验证保持，每轮真实 Port Entry ≤1 且恰一个成功；不依赖 FakeBroker 内部去重隐藏重复调用。
- 记录**每次尝试**（包括重试）及其原因、真实 `port_entries`。出现 ≥2 entries 立即硬失败，永不通过新栈重试洗掉；普通瞬态失败可依清楚的预声明策略处理，但不能把 3% 失败写成“0 失败”。
- 报告必须区分本地 Windows、Ubuntu CI 运行日志与历史存档的差异。CI 运行时产生的证据应通过可访问 artifact 或测试 stdout 提供，不要将本地先前记录冒充远端最新记录。

## A5-T4 验证、安全与架构健康

执行现有仓库实际等价命令并保存真实退出码：

```bash
python -m pytest -q tests/fault_injection/test_a2_quantitative.py
python -m pytest -q
python scripts/check_environment.py
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
```

- 保留既有 336 测试的测试目标（数量可因新用例增加），以及原 1,080 故障矩阵；不降低检查数量、不得 skip/xfail 弱化安全负例。
- 若新用例明确发现产品缺陷，先提交可复现 RED，后最小 GREEN；否则**不改** `src/trading_lab/oms/`、`risk/`、`brokers/`。
- `artifacts/evidence/M2/a5-true-process-race/` 内保存：`baseline.md`、`process_concurrent_50.log`、`abrupt_crash_recovery_5.log`、`thread_retry_accounting.md`、`full_checks.log`、`architecture-health.md`、`ci-verification.md`；记录分母、PID、SHA、每轮真实尝试、失败及重试原因。
- 新增 `docs/reviews/M2-a5-independent-closure.md`，明确顺序重放测试与同步竞争测试的区别，七分类架构健康表（REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEBT）。不得改写旧日志。
- 质量门：零重复 OMS、零兼容层堆积、零新消息队列/数据库/依赖；尽量只改测试。CI Ubuntu+Windows 必须在**最新推送 SHA**真实 PASS（推送要另获用户授权）。

### A5 验收状态和强制停止门

- 本地实际验证通过：`M2_A5_TRUE_PROCESS_RACE_LOCAL_PASS / CI_REMOTE_PENDING / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
- 新 SHA 的 Ubuntu 与 Windows CI 均 PASS：`M2_A5_TRUE_PROCESS_RACE_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
- 失败或证据不充分：`M2_A5_REMEDIATION_REQUIRED` 或 `M2_A5_INCONCLUSIVE`，不得自动关闭 M2。
- **A5 完成后立刻 STOP，不能自行将 `M2_GATE` 设为 CLOSED 或开始下面 B 段；需要用户分别明确审批 M2 关闭和 M3 启动。**

---

# B 段 — M3 透明规则基线、现实回测与冻结研究协议（仅在**另行明确授权**后执行）

> 唯一权威：`docs/plans/` 两份 v2.1 的 M3、Architecture §4.3 B0–B8。M3 只做合成/离线工程验证；不做 M3.5 真前向、不做 M4 AI 沙箱、不做 M6 Champion–Challenger、不接真实数据供应商及经纪商。

## B0. 前置双审批与版本核验

必须获得并核对**来自用户的两项独立授权**：`M2_GATE=CLOSED` 及 `M3_START=APPROVED`。记录审批来源/时间/范围（绝不伪造用户签名）。核对当前 HEAD、远端 main、CI 和未推送 docs-only 补录提交；未授权则 STOP。本文件的存在不是授权。

数据与券商边界：
- `BLOCKED_DATA(全市场研究)` 不变，U-1（VendorFacts 非法枚举值 fail-open）尚需独立整改和供应商 API/许可真实核验；不能把合成数据认定为真实研究准入。
- `BROKER_BEHAVIOR_UNVERIFIED` 不变；不调用 Alpaca Paper/Live、不得使用账户凭证、不得真实资金/订单操作。
- 数据模式严格 `SYNTHETIC_ENGINEERING_ONLY`，不能声称 Alpha 或真实 OOS 支持；`S=N_A/INCONCLUSIVE`、`R=NOT_STARTED`。

## B1. 预注册协议先于正式实验（第一 M3 子门）

落地：`configs/evaluation_protocol.yaml`、`docs/adr/ADR-004-evaluation.md`；独立 `protocol_hash`（复用 `security.canonical`）及版本化工件；记录 git SHA、seed、冻结数据 hash、成本模型和阈值。

必须明确：
- Train/Validation/历史滚动 OOS/独立最终 Sealed Holdout/未来 Forward cohort 的角色、日期/资产/事件去重、重叠披露、Walk-Forward、Purge/Embargo；何种操作属于数据泄漏。
- 投资可执行时点及 PIT 门：`available_at <= decision_at`；订单执行延迟、价差、滑点、冲击、未成交/部分成交、成交量上限、佣金/费用、退市、分红、拆股、可用与已交收现金；成本 ×1/×2/×3。
- 预声明主要指标（净收益、回撤、尾损、风险匹配效用、换手、费用）、独立样本下限、效应阈值、置信/误报控制和多重比较；若无法给出有根据的数值必须 `PROTOCOL_INCOMPLETE/INCONCLUSIVE`，不能为取得 PASS 事后降低。
- B0–B8 的冻结定义与统一数据、预算、成本口径；AI vs 规则的两套公平预算：等候选/试验次数（失败与重试算入）、等美元研究成本（LLM/计算/数据/人工分项）。不可同等时标 `NOT_COMPARABLE`。
- M9 最终 Holdout 一次性解封规则、`PASS/FAILED/INCONCLUSIVE/INVALIDATED` 机器判定、污染日志和唯一候选**事前选择规则**。M3 不冻结具体冠军 `strategy_hash`；须到 M8 结束、M9 解封前按已冻规则锁定。

## B2. 架构与复用清单

先输出依赖图与 `REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES`。优先复用 `contracts` 中的 `MarketBar`/`MarketSnapshot`/`ExperimentRecord`/`FinalHoldoutResult`、M1 数据层 `snapshot/PIT/membership/actions/calendar`、`security.canonical`、`AGENTS.md` 与已有 `check_architecture.py`。

建议最小目录：

```text
src/trading_lab/backtest/       # 纯计算的研究模拟
src/trading_lab/validation/     # 协议/数据分区/试验账本/封存门
configs/evaluation_protocol.yaml
docs/adr/ADR-004-evaluation.md
tests/backtest/
tests/validation/
artifacts/evidence/M3/
docs/reviews/M3-engineering.md
docs/reviews/M3-strategy.md
docs/reviews/M3-real-capital.md
```

严格禁止 backtest/validation 导入 `oms`/`risk`/`brokers` 或任何 POC、网络 API/券商凭证；扩展**现有** `scripts/check_architecture.py`，而非增加第二个检查器；禁止第二套 Schema Gate、通用 ETL/插件系统、冗余适配层或另一套 Live 风控/OMS。

## B3. 最小可重算纯离线回测引擎

- Decimal 现金/股数/成交/分红/费用/权益守恒；清楚区分可用现金、已交收现金、未交收现金和模拟订单，不调用 `BrokerPort`。
- 信号只能使用当时已知数据（包括历史成分/退市及公告）、不能使用未来复权因子；价格来自信号发生后按协议实际可成交的报价时间，拒绝“同日收盘后已知信号在该日收盘成交”。
- 合成负例涵盖时间泄漏、盘后回填、拆股、分红、退市、ticker 重用、成交延迟、缺流动性、未成交、部分成交、保守滑点和交收。
- 所有随机性有注入 seed；同 `protocol_hash + dataset_hash + code hash + seed` ⇒ 可复现结果与预声明数值容差。外部时间、系统随机状态不能影响研究结果。

## B4. 透明基线与预算公平

- 在协议中冻结 B0–B8 定义（以 Architecture v2.1 §4.3 为准）。
- **本阶段只实际实现** B0 现金、B1 宽基 ETF 买入持有、B2 透明单规则及合成夹具。B3–B8 只冻结试验臂定义、预期输入和研究预算，不创建无消费者的 Regime/AI/Champion/Portfolio 空框架。
- 全实验账本必须记录所有尝试，包括失败、拒绝、取消、重复试验和重试，防止幸存者偏差与 AI 隐性搜索优势。

## B5. Walk-Forward、Purge/Embargo 与最终 Holdout

- 时间滚动/扩展窗，按可得信息严格切分，标签跨界 purge、embargo，禁止重叠日期/资产/事件被当作多份独立证据；同时生成可审计 `cohort_overlap_report`。
- 没有合规真实数据时，真实最终 Holdout 标注 `SEALED_NOT_MATERIALIZED`，仅用**合成** sealed fixture 演示访问拒绝、一次性解封、污染后的不可重用及 `PASS/FAILED/INCONCLUSIVE/INVALIDATED` 四种判定。不得谎报已密封真实数据。
- 对研究角色模拟直接读取、聚合统计、间接查询与二次试探的负例，审计拒绝与污染；OS 级权限隔离的缺口归 M4，不把纯 Python 检查冒充进程级沙箱。

## B6. M3 Engineering Gate 与代码质量

- Protocol 不可静默编辑，阈值缺失和预算超额 fail-closed；合成结果不能被提升至真实策略证据；未来价格和多次选择/解封 100% 拦截。
- 全量保留 M0–M2 的安全测试、双线程 100/双进程 50 的真实量化验证、1,080 故障矩阵；不准 skip/xfail 规避；新增测试应先 RED 后 GREEN。
- 新包纳入现有架构依赖门，运行 Ruff（如项目已有配置则沿用；若新增工具需说明许可证/用途）、pytest、密钥扫描、Paper/Live 纯度检查。额外依赖的成本、跨平台性和用途需逐一证明。
- 输出 `artifacts/evidence/M3/architecture-health.md`：唯一职责、复用与删除、冗余扫描、依赖方向、不可变契约复用、POC 隔离、复杂度必要性及待偿还债务。
- 完整证据：`protocol-freeze.md`、`verification.log`、`negative-tests.log`、`cohort-overlap-report.md`、实验账本；Ubuntu/Windows CI 需推送后新 SHA 双矩阵全绿。
- 三轨报告：`E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 仅工程证据成立；`S=N_A/INCONCLUSIVE`（不可称真实 OOS/SUPPORTED）；`R=NOT_STARTED`，`BLOCKED_DATA` 和 `BROKER_BEHAVIOR_UNVERIFIED` 不变。

**M3 完成后**：`M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`，必须停止；不可自动启动 M3.5、M4、真实 Shadow/Paper 或 Live。

---

## 3. 本轮可交给 Codex 的启动提示词（仅 A5）

请阅读 `Shutu_AI_Trading_Lab_M2_A5_True_Process_Race_and_M3_Codex_Task.md`、`AGENTS.md` 和两份 v2.1 计划。

**本轮只执行 A5-T0～A5-T4**：补上 M2 的真实跨进程同步竞争 ≥50 轮和异常崩溃恢复 ≥5 轮。原测试先等待 A 完成再调用 B，属于顺序重放，不能算并发。使用 Windows/Linux 兼容的可证明两进程同步屏障，保存 PID/READY/GO/claim/持久状态证据。优先只修改测试与报告；产品代码如无新 RED 缺陷不得改动。执行 336 基线、100 轮线程竞争、1,080 故障矩阵、所有安全与架构门。未经用户授权不得 push；**完成即停止，不能擅自签批 M2 或启动 M3**。

## 4. 未来 M3 启动提示词（仅在用户分别明确批准后）

用户已明确签批 `M2_GATE=CLOSED` 与 `M3_START=APPROVED` 后，先核验签批、远端 CI 和本地 SHA，再执行本文件 **B0–B6**。仅合成数据、离线回测工程验证；先冻结评估协议，再开展 B0–B2 可执行实验，B3–B8 只登记协议，禁止提前堆叠后续阶段代码。不得访问真实供应商和券商，保持 BLOCKED_DATA、BROKER_BEHAVIOR_UNVERIFIED、S 不提升和 R 不启动。结束停在 M3 人工阶段门，禁止自动 push。
