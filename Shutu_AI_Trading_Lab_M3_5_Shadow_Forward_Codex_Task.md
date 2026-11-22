# Shutu AI Trading Lab — M3.5 最小 Shadow 前向工程验证（Codex 执行任务书）

> Task ID：`M3.5-SHADOW-FORWARD-ENGINEERING-001`  
> 编制依据：`AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md` 中 M3.5 与 §4.3–4.5。  
> M3-R2 受测代码：`906bf6f96e7c6e9541d4fe111e14012998314f50`，远端 CI run [`44998829308`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44998829308)：Ubuntu、Windows 各 `572 passed`。  
> 编制时远端 `main`：`e1301c5ebd5eff7c307ec500849b8d8fd83c9525`（含后续报告/证据提交）；本地可能不同，以执行时实查为准。  
> **本文件不是启动授权**。当前 `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`；用户没有在任务书生成行为中自动签批。  
> 当前不可提升状态：`S=INCONCLUSIVE`、`R=NOT_STARTED`、`BLOCKED_DATA(全市场历史研究)`、`M1 U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`SEALED_NOT_MATERIALIZED`。

## 0. 执行授权及 STOP/GO（第一道强制门）

1. **只在用户另行明确签批 `M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 且 `M3.5_START=APPROVED` 后执行 S0–S7**。先找到并核实人工授权的日期、原话、记录路径、批准范围；不得从报告结论或任务书文本自行推断授权。缺失任何一项立即 `STOP: AUTHORIZATION_PENDING`，不能创建新业务代码。Codex 不替用户签批。
2. 先运行 `git status --short`、`git rev-parse HEAD`、`git rev-parse origin/main`、`git log -n 8 --oneline`；审查尚未上推的 docs-only 补录及用户其他改动，不覆盖、不 reset --hard、不 force push；提交和 push 授权分别处理。**默认只允许本地 commit，不得 push。**
3. 执行时保留 M3-R2 全部已有测试与原始审计工件。不得在 M3.5 任意覆盖 `artifacts/evidence/M3/r1/`、`M3/r2/`、原 `experiment-ledger.jsonl`、`ledger-anchor.json`，或重新标定旧批次为真实 OOS。
4. **当前默认执行范围仅为离线、合成、无真实事件源的 Shadow 前向工程夹具**：不得读取真实券商/市场数据凭证、购买订阅、调用外部行情 API、连接 Alpaca Paper/Live、真实资金或发送任何经纪订单。不得加载真实最终 Holdout。
5. 任何后续真实行情采集、Shadow 实时观察、Alpaca Paper 写接口，均需要**单独明确授权**。M3.5 开工授权不等于数据订阅/真实行情/Alpaca Paper 授权。仅在另行授权后可执行 S8；未授权时 S8 只能保留任务计划，不得调用网络接口。
6. 若发现前序 M2/M3 的真实安全缺陷，只做隔离复现和阻断报告，先停门请用户决定整改范围；禁止在 M3.5 悄悄重构 OMS/Risk/数据准入。不得用 `skip`、`xfail`、调低阈值获得绿色。

## 1. 目标、非目标及明确的证据分层

**阶段目标**：使一条**冻结的透明规则策略**在真实时间流到来时具备“先锁定预测、后等待事实、最后一次性评分”的可重复工程能力；运行中可安全重启、检测重复/乱序事件、保留前向 cohort 和可审计的观测记录。优先 SHADOW（不发券商单）；Paper 仅为另行授权的可选专项。

证据严格分层：

| 模式 | 来源 | 能证明什么 | 禁止宣称 |
|---|---|---|---|
| `SYNTHETIC_REPLAY` | 人工合成或既有离线 fixture | 机制、持久性、时钟、数据/事件隔离、崩溃回放 | 真实前向观察、真实五交易日、真实策略有效性、`FORWARD_SUPPORTED` |
| `SHADOW_REAL_OBSERVED` | 合法授权、可证明在当时到达的真实行情事件 | 前向采集/时间锁定/稳定性（完整真实窗口后） | Alpaca Paper 成交、真实资金绩效、未经统计验证的 Alpha |
| `ALPACA_PAPER` | 另行授权的真实 Paper API | 受实测范围内的 Paper 响应、重复事件、账户/订单对账 | LIVE 执行可靠性、真实市场成交质量、真实投资收益 |

不新建 AI 策略工厂、不开展 M4 沙箱、不实现 B3–B8 运行代码、不建立 Champion–Challenger、不启动 Live，不把合成五日数据伪称“观察了五个交易日”。

## 2. S0：执行前证据门、架构盘点、基线冻结

1. 明确核对上述批准记录与远端 `906bf6f` CI；docs-only `0b84ec4`、`e1301c5` 等以实际 SHA 为准，和受测 SHA 区分。新增任务书、运行证据不得覆盖旧审计链。
2. 检查并**优先复用**：`validation.protocol` / `cohorts.ForwardCohort` / `ledger.ExperimentLedger` / `code_identity`，`backtest` 的 B2 已冻结规则和执行成本纯函数，`data` PIT / snapshot、`security.canonical`/AuditLog、M0/M2 KillSwitch 与真实券商写权限隔离。对比每个模块的消费者、身份/hash、持久化契约和缺口。
3. 提交 `artifacts/evidence/M3.5/architecture-baseline.md`：`REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES` 七分类，以及**唯一权威职责和唯一消费者**。不得复制 M3 的研究账本、回测计算引擎、时间模型，也不得建立第二 OMS 或第二风控系统。任何新增持久事件记录必须解释为何无法直接使用已有机制。
4. 冻结一个透明 B2 规则版本及其参数和**完整执行代码身份**（不仅 runner Hash）；其训练/选择只来自已有合法开发集/合成 fixture，不得用未来前向结果反向优化。M3.5 新代码属于新的代码身份范围，应建立 M3.5 版本化身份并与 M3 `af7ff10c…` 清晰关联，**不得悄悄改写 M3 r1/r2 旧 Hash、旧账本、旧协议或历史预算**。
5. 将 A6 ready 握手 CI flake 作为**观察项**：保留历史失败 run、分类原因。若阶段正常回归未重复出现，不重构无关生产代码；若重现，用确定性 READY 同步与严格错误传播做小范围 RED→GREEN，原 50 轮有效竞争数量不得减少，单独报告。

## 3. S1：最小离线 Shadow 驱动（不连接券商）

交付 `apps/trading_daemon/` 下最小 SHADOW 运行入口，复用现有回测纯计算与契约，不把回测脚本当生产实时执行器直接拼接：

- 显式 `--mode synthetic-replay` 或等价只读配置；默认拒绝任何未授权真实数据端点/券商凭证；导入路径上没有 BrokerPort 写调用。先完成离线测试；不创建未使用的 Alpaca Adapter、消息总线、通用 plugin 框架。
- 接受已标明来源、`event_id`、`ts_event`、`ts_available`、`received_at`、`source`、`dataset_hash` 的事件；研究决策只能在事件实际可得后发生，`ts_available <= decision_at`，不得使用未来修订价、后来公布的企业行为或退出名单。时间戳必须含时区，DST 与早收市按权威交易日历配置/假设显式处理，严禁凭合成 fixture 推断真实开市时间。
- 将“生成预测”“锁定预测”“后来接收结果”“评分”设计为可区分的状态与审计事件。必须**先持久锁定 prediction 的时间和 Hash，然后才能消费 observation**；不能在评分时回填 prediction 时间、偷偷改参数或补造历史。重复 event_id 幂等，乱序/同一事件不同 payload/未来时戳/缺失源标记 => 拒绝或安全挂起、审计，不得静默修复成好看的结果。
- 允许现金/NO_TRADE，任何 Shadow 订单只是虚拟账本中的不具外部副作用的内部意向；**严禁 BrokerEgress.submit/cancel 与真实 API 网络**。可以用 FakeBroker 做专门集成负例，但 FakeBroker 的 ACK 不计作 Shadow 真实执行证据。
- 明确单写者持久化与幂等恢复：启动前先验链/身份/旧状态并处理未决结果；审计/存储不可用时 fail-closed，不返回“成功锁定”。使用已有权威事件日志/账本优先；如确需独立 Forward 事件存储，禁止复制 ExperimentLedger 的预算统计语义，明确读写消费者、最小实现与可追溯迁移理由。

## 4. S2：前向时间锁和独立 cohort

1. 在真实事件到来**之前**冻结预测与 cohort ID。前向 cohort 的`prediction_locked_at < observation_available_at`，以**真实到达记录**而非自行填写的时间作为生产有效性依据；replay 模式标 `SYNTHETIC_REPLAY` 且全程不可升级为真实。每次生成新的 cohort 不得重复利用已评分区间进行选股/调参。
2. 独立记录 cohort 与历史滚动 OOS、合成/未物化 Final Holdout 的日期、资产、事件 ID、标签区间交叉情况，重叠如实披露并降级独立性，不得同一事件既用于选策略又宣称独立前向验证。
3. 使用 M3 的 `check_overlaps`、`ForwardCohort` 与 PIT 时间边界；注意 `ForwardCohort.score()` 的**内存一次性标记不足以证明跨重启恰好一次**，正式持久化必须另有可靠的“已评分”记录及重放拒绝测试。
4. 结果可重放：同数据、锁定策略/代码 Hash、协议 Hash、事件序列、seed，得到等价输出/审计摘要；不能依赖当前壁钟去重演历史真实观察，真实事件入库前必须记下 ingest 时间和证据。

## 5. S3：重启、异常事件、断网和权限负例

以下均需 RED（旧行为若已有安全性则标 ALREADY_SAFE）→ 最小 GREEN → 可复现日志：

- 崩溃时刻：预测生成后未持久化、预测锁定后未评分、结果入库后评分前、评分后再启动；确保没有事后锁定/重复评分/丢失预算事实。
- 重复事件、相同 ID 不同内容、乱序事件、延迟公告、晚到回填、未来可得时间、超出 TTL、空/损坏事件、Snapshot 缺失、账户/环境混用、非法市场时钟、账本尾截断/锚不符/陈旧锁，全部拒绝或保守挂起。
- 至少一次模拟断网、一次真正子进程 `os._exit` 异常退出、一次重复事件恢复、双进程写者冲突；审计与链校验均要复核，不能用 mock 自带去重掩盖重复。
- 注入 BrokerPort 写调用监视器：SHADOW/REPLAY 路径调用次数始终 0；即便环境中出现 Alpaca LIVE/PAPER 凭证，也不得从该路径读取或触发连接。
- 断言 `M1 U-1` 非法 `VendorFacts` 能力字段不能被 Shadow 数据适配/准入旁路冒充真实研究通过；原始 M1 `BLOCKED_DATA` 保留。若需修 U-1，另立明确审批的独立数据任务，不在本任务暗修。

## 6. S4：监控与证据模型（不做华丽看板）

最小结构化字段：`mode`、`source_authorization_status`、`source_evidence_level`、`cohort_id`、`event_id`、`strategy_hash`、`code_hash`、`protocol_hash`、`dataset_hash`、`prediction_lock_digest`、`event_ts`、`available_at`、`received_at`、`decision_at`、`score_at`、`replay_count`、`duplicate_count`、`gap_count`、`clock_skew`、`recovery_status`、`account_environment`、`no_broker_writes`；明确分母和异常数。

监控故障必须暴露，不能因 0 样本宣称 100% 完成。允许输出最小 CLI JSON/Markdown 状态报告；本任务不构建大屏、前端、短信/邮件服务或复杂 Agent 编排。

## 7. S5：真实前向窗口的资格规则（写代码和测试，默认不执行真实采集）

在预注册配置中把证据分为以下机器状态：

- `OFFLINE_HARNESS_PASS_WITH_SCOPE`：合成回放、幂等、时间锁、负例通过；**只证明测试夹具**。
- `BLOCKED_ENV` / `BLOCKED_DATA`：缺合法行情访问/可靠时钟/准入许可/数据质量；不能伪称正在累计真实窗口。
- `PENDING_FORWARD_WINDOW` + `forward_window_status=ACCUMULATING`：**已经合法取得真实到达的前向行情，采集正常，但不足预注册的真实时长/事件数**。这不是 E=PASS。
- `PASS`（M3.5 完整前向 E-Gate）：真实前向观察覆盖**至少 5 个实际可观察的美国证券市场交易日**（或 v2.1 允许的事前注册等效事件窗），不是合成 5 天；每个 cohort 有真正到达时间与预测先于事实的证据；含至少一次断网/重启与重复事件恢复；0 未经批准的 Paper 订单、0 重复 Paper 订单（若并未授权 Paper 则应写 `PAPER_NOT_RUN`，不能虚报 Paper PASS）；全程回放/身份/成本/数据质量审计成功。

不得提前宣布真实窗口完成，不得通过修改预注册日数、人工注入未来行情或伪造接收时间补足进度。`S=INCONCLUSIVE` 在缺有效前向统计证据时持续成立；五日的工程稳定性不代表 Alpha 成立。

## 8. S6：架构完整性与质量硬门

- 维持唯一的 `ExperimentLedger`、回测引擎、代码身份/规范化 Hash 与数据 PIT/许可准入；前向 event store 仅承载不可替代的新职责；不得复制 OMS/KillSwitch/SchemaGate/策略状态机。删除遗弃/重复抽象而不删安全控制。
- 现有 `scripts/check_architecture.py` 是唯一架构检查器，必须扩展 `trading_daemon` 的禁止网络/券商写依赖及 M-1 POC 导入扫描，并为检查器规则增加至少 2 个拒绝和 2 个合法导入用例，防止包路径绕过。
- 除非确有运行消费者与干净环境必要性，不新增依赖、框架或后台微服务；如确需新增，记录许可证、替代方案、Windows + Ubuntu 可安装性、功能代价。
- 最终 `artifacts/evidence/M3.5/architecture-health.md` 包括：`REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES`、唯一消费者、模块依赖图、无调用代码与旧兼容层、风险分层和可复现检查命令。

## 9. S7：验证、输出与强制停止

使用干净 Python 3.13 环境（build isolation 保持开启）；保留现有 572 个 M3-R2 基线测试及 M2 1,080 故障矩阵，不得删除/跳过/弱化：

```powershell
python -m venv .venv-m35-review
.\.venv-m35-review\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-m35-review\Scripts\python.exe scripts/check_environment.py
.\.venv-m35-review\Scripts\python.exe -m pytest -q
.\.venv-m35-review\Scripts\python.exe -m pytest -q tests/fault_injection/test_fault_matrix.py
.\.venv-m35-review\Scripts\python.exe scripts/check_architecture.py
.\.venv-m35-review\Scripts\python.exe scripts/scan_secrets.py
.\.venv-m35-review\Scripts\python.exe scripts/verify_live_blocked.py
.\.venv-m35-review\Scripts\python.exe scripts/smoke_mock.py
git diff --check
git status --short
```

保存每个命令真实 EXIT CODE、环境、代码 SHA、测试总数及每组负例、合成/真实范围；不得把已通过的旧 CI 当作新代码的 CI。推送需单独用户授权，双平台远端 CI 成功后才能写 `REMOTE_VERIFIED`。

交付路径（按消费者实际必要性创建，不建空壳文件）：

```text
apps/trading_daemon/                   # 仅最小 SHADOW / offline-replay 入口
configs/forward_observation.yaml       # 版本化前向预注册与来源权限开关
tests/forward_smoke/                   # 时间锁、幂等、重启、无券商写、负例
artifacts/evidence/M3.5/
  baseline.md
  architecture-health.md
  negative-tests.log
  replay-verification.log
  forward-observation-status.json       # 真实窗口未执行时为 BLOCKED_ENV / NOT_STARTED
  verification.log
  remote-ci.md                          # 未推送标 CI_REMOTE_PENDING
docs/reviews/M3.5-engineering.md
docs/reviews/M3.5-strategy.md
docs/reviews/M3.5-real-capital.md
```

**完成默认离线范围后必须 STOP**：

`M3.5_OFFLINE_HARNESS_LOCAL_PASS / E=PASS_WITH_SCOPE(SYNTHETIC_REPLAY_ONLY) / REAL_FORWARD=NOT_STARTED_OR_BLOCKED_ENV / S=INCONCLUSIVE / R=NOT_STARTED / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M3.5_GATE=USER_PENDING`

如果后续获单独推送授权且双平台 CI 成功，可写 `M3.5_OFFLINE_HARNESS_REMOTE_VERIFIED`，但**不得升级**成完整真实前向 E=PASS。不得代签 M3.5，不得自动启动 M4/M5/M6，不得推动 LIVE。

## 10. S8：未来真实 Shadow / Alpaca Paper（**本次禁止执行，须再次授权**）

只有用户另行批准 **行情来源/凭证/许可范围/观测账户/网络连接方式** 才可实现真实市场事件接入并开启前向计时。真实源须记录公告/事件可得时间与到达时间、订阅权限、来源质量、重连缺口，独立校验来源与未来泄漏；M1 历史全市场 `BLOCKED_DATA` 和 U-1 不因 Shadow 工程 PASS 自动解除。必须事前锁定五日（或等效窗口）协议，不允许事后改变。

Alpaca **Paper 写入**再独立审批：需要权限最小化的 Paper-only 凭证、API 真实幂等/查单/回报/持仓/现金对账、真实网络故障与重复订单证据。任何 Paper 实测不能推断 LIVE，`BROKER_BEHAVIOR_UNVERIFIED` 只能按真实已验证的具体范围缩小。未经 Paper 专项批准不得添加写连接或发单。

## 11. Codex 启动提示词（获签批后使用）

> 已有用户对 `M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 与 `M3.5_START=APPROVED` 的两项明确授权，先在仓库核实授权记录；若缺失立即 STOP。请读取本 MD、`AGENTS.md` 和两份 v2.1 计划，按 S0–S7 执行。只做离线 `SYNTHETIC_REPLAY` 的 Shadow 前向工程夹具：先锁预测再接事实，事件幂等、断网/崩溃恢复、审计链、独立 cohort、PIT 防泄漏。复用 M3 代码身份、协议、账本和 M2 安全契约，不复制 OMS/回测引擎，不改 M3 r1/r2 证据。保留原 572 项测试、M2 1,080 故障矩阵，新增先 RED 后 GREEN、完整回归、架构健康和三轨报告。绝不访问真实数据 API 或真实券商，绝不启动 S8/M4，未经授权不 push，完成停止在 M3.5 人工门。若未获得 M3 与 M3.5 的正式批准，只输出 `AUTHORIZATION_PENDING` 并停止。

---

**验收哲学**：M3.5 的成功首先是“预测真正先于观察、故障后仍可追溯”的前向证据纪律；不是让合成收益看起来漂亮，也不是让 FakeBroker 给出更多绿色 ACK。
