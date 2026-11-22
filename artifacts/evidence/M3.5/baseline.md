# M3.5 架构基线与盘点（S0）— Architecture Baseline

> Task ID: `M3.5-SHADOW-FORWARD-ENGINEERING-001` · 2026-11-22 · 执行前基线冻结
> 代码基线: 本地 = 远端 `main` = `e1301c5`；M3-R2 受测代码 SHA `906bf6f`（CI run 44998829308，双矩阵 572 passed，`artifacts/evidence/M3/r2/remote-ci.md`）。
> 授权: 见 `authorization.md`（2026-11-22 用户签批两项）。
> 状态标注: `M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`（仅合成工程范围）/ `M3.5_GATE` 执行结束时 = `USER_PENDING` / `S=INCONCLUSIVE` / `R=NOT_STARTED` / `BLOCKED_DATA(全市场历史研究)` 不变 / `M1 U-1 UNRESOLVED` 不变 / `BROKER_BEHAVIOR_UNVERIFIED` 不变。

## 0. 不变量（本阶段不可破坏）

1. **M3 身份不可扰动**：`research-code-identity-v1` 的身份范围是 `src/trading_lab/{backtest,contracts,security,validation}` + `src/trading_lab/__init__.py` + runner `scripts/run_m3_r2_baselines.py`。M3-R2 官方批次 `m3-r2-batch-1` 的 `code_hash=af7ff10c…`（git_commit `4ae119f`）已由账本锚封存。**本阶段不向这四个包添加/修改任何文件**，因此重算 M3 身份仍得 `af7ff10c…`；旧账本、旧锚、旧协议（`8afb5207…`）、历史预算一律不动。
2. **唯一权威**：`ExperimentLedger`（研究批次账本+预算）、`BacktestEngine`（历史模拟成交）、`MarketCalendar`（时间/日历）、`security.canonical`（规范化）、`AuditLog`（追加式审计链）、OMS/KillSwitch（券商写路径停机）各只有一个正式实现，M3.5 不复制、不并行、不重构。
3. **范围**：仅离线 `SYNTHETIC_REPLAY`。无真实行情 API、无 Alpaca Paper/Live、无 BrokerEgress 写调用（静态检查 + 运行时监视器负例双重证明）。

## 1. 七分类盘点

| 分类 | 对象 | 说明 |
|---|---|---|
| **REUSE** | `security.canonical`（`canonical_json_bytes`/`canonical_digest`/`sha256_hex`） | 全部哈希/摘要唯一来源，daemon 直接导入 |
| **REUSE** | `security.audit.AuditLog` | 前向事件日志（journal）的骨干：追加式 JSONL + hash 链 + `.head` 尾截断检测 + `verify()`。**不新建日志原语**。 daemon journal 的"已评分"持久记录 = 链中 `SCORED` 条目，跨重启恰好一次由此保证 |
| **REUSE** | `validation.cohorts`（`CohortSpec`/`ForwardCohort`/`check_overlaps`） | 前向 cohort 语义（`prediction_locked_at < observation_available_at`、评分后污染标记）。任务书 S2.3 指出其内存一次性标记不证明跨重启恰好一次——持久化由 journal 的 `SCORED` 链条目承担（见 S2 设计），`ForwardCohort` 用于 cohort 声明与重叠披露 |
| **REUSE** | `data.calendar.MarketCalendar`（含 `is_available` PIT 门） | 时区/交易日历/早收市判定；合成回放使用**预注册合成假日表**，不推断真实开市时间；真实日历数据属 S8 另行授权 |
| **REUSE** | `contracts`（`MarketBar` 等 pydantic 契约） | 事件 envelope 字段语义（tz-aware、`ts_available >= ts_event` 等）与 daemon envelope 校验对齐 |
| **REUSE** | B2 冻结规则定义与参数 | `B2_single_rule` MA(2,4)（`m3-r2-batch-1` 于 Train/Validation 预算化选择冻结，见 `experiment-summary.json` `b2_params_frozen=[2,4]`）；前向预测使用同一冻结定义（daemon 内增量决策函数 + 与 `backtest.arms` 决策等价性回归测试绑定，防漂移） |
| **REUSE** | M0/M2 KillSwitch 的**隔离语义** | KillSwitch 是券商写路径（OMS/risk，`Environment ∈ {PAPER, LIVE}`）的停机机制。daemon 无券商写路径，禁止借用 `PAPER`/`LIVE` 标签冒充环境；daemon 以自身 SUSPENDED 状态 + 审计实现"新预测停机"，真实 KillSwitch/Paper 接线属 S8 另行授权 |
| **REUSE** | `research-code-identity-v1` 的**方案模式** | LF 规范化、排序清单、canonical JSON、git 字段记录不入哈希——按同一纪律新建 `forward-daemon-identity-v1`（见 ADD），父身份显式链接 `af7ff10c…` |
| **REUSE** | M2 故障注入测试模式 | 子进程 `os._exit` 真进程崩溃、双进程竞争模式沿用 `tests/fault_injection` 既有手法 |
| **MODIFY** | `scripts/check_architecture.py` | 扩展 `apps/trading_daemon` 包规则：禁 `trading_lab.brokers`、禁网络模块（socket/ssl/urllib/http/requests/websockets/alpaca…）、禁 artifacts/poc 片段导入；为检查器规则新增 ≥2 拒绝 + ≥2 合法用例。**唯一架构检查器不变** |
| **MODIFY** | `pyproject.toml` pytest 配置 | `pythonpath` 增加 `"."` 使测试可导入 `apps.trading_daemon`（不影响 M3 身份范围） |
| **ADD** | `apps/trading_daemon/` | 前向 daemon 应用层（新职责，见 §2），不入 `src/trading_lab` 四身份包 |
| **ADD** | `configs/forward_observation.yaml` | 前向预注册（来源授权开关、B2 冻结、事件契约、TTL、市场钟、S5 状态机、真实窗口资格规则）；纳入 daemon 身份哈希 |
| **ADD** | `scripts/run_m35_shadow_replay.py` | 官方确定性回放 runner（记录身份、驱动合成夹具、写证据日志/状态 JSON） |
| **ADD** | `tests/forward_smoke/` | 时间锁、幂等、重启/崩溃、断网、无券商写、负例、身份、资格状态机测试 |
| **ADD** | `artifacts/evidence/M3.5/`、`docs/reviews/M3.5-*.md` | 授权记录、证据与三轨报告 |
| **REPLACE** | （无） | 不替换任何既有机制 |
| **REMOVE** | （无） | 本阶段无遗弃代码删除项；不触碰安全控制 |
| **POC-ISOLATE** | `artifacts/poc/`、M-1 candidates | daemon 与测试一律不导入 POC；检查器规则强制（`artifacts`/`poc` 片段在 daemon 导入路径 = 违规） |
| **DEPENDENCIES** | （零新增） | 无新依赖/框架/后台服务。现有依赖（pydantic、pyyaml、pytest）+ stdlib 足够。SQLite 也不新增使用（journal 复用 AuditLog JSONL，无 OMS fence 的 SQLite——见 §2 取舍） |

## 2. 新增持久事件记录的职责与理由（任务书 S0.3/S1 强制解释）

**新增物**: `apps/trading_daemon/journal.py` 的 ForwardJournal——以 `AuditLog` 为骨干的前向状态机日志。

**为什么不能直接用既有机制**:
- `ExperimentLedger` 是研究批次账本：预算计数、arm 结果注册、批次语义。前向运行是**操作事件流**（锁预测/收观察/评分/拒绝/挂起），消费者是 daemon 恢复逻辑与资格状态机，不是预算统计。任务书明令禁止复制其预算语义；直接塞入会把两种生命周期焊死。其锚文件模式（`ledger-anchor.json`）被 mirror 为 journal 锚（`journal-anchor.json`），共享的是"外部锚防尾截断"模式而非代码。
- 裸 `AuditLog` 缺少：事件→槽位状态机推导（重建 slots/scored/duplicates）、事件 ID 幂等索引、锚文件。ForwardJournal 只做这一层，且**复用**（而非复制）AuditLog 的链/头/verify。

**为什么不用 `oms.fence.FenceCoordinator` 做单写者锁**: FenceCoordinator 绑定 `Environment ∈ {PAPER, LIVE}`。daemon 是 `SYNTHETIC_REPLAY`，借用 `PAPER` 会伪造 `account_environment`（S4 字段诚实性），违反环境语义。新增 `session.py` 的最小租约锁文件（owner/pid/租约到期；未到期持锁 → 拒绝启动；到期 → 审计后接管；双进程竞争负例覆盖）。这是进程排他原语，不是第二 OMS/风控。

**为什么 B2 前向决策在 daemon 内重实现为纯函数而不复用 `backtest.arms._run_ma_cross`**: `_run_ma_cross` 与 `BacktestEngine.submit()` 耦合（历史模拟成交语义：延迟、下一开盘成交、部分成交）。前向锁定的职责是"当时可得收盘上的增量敞口决策"，无成交模拟。两者以**决策等价性测试**绑定（同一合成序列上，daemon 的 above-state 翻转点 = 回测 arm 的提交点序列），漂移即红。这保持"一个职责一个正式实现"：历史模拟归 backtest，前向锁定决策归 daemon。

## 3. 模块依赖图（新增部分）

```
scripts/run_m35_shadow_replay.py ──► apps/trading_daemon.{driver,identity,report,eligibility}
apps/trading_daemon.engine ──► apps/trading_daemon.{envelope,rule,journal,session,clock}
apps/trading_daemon.journal ──► trading_lab.security.audit (AuditLog)
apps/trading_daemon.{envelope,rule,journal,engine} ──► trading_lab.security.canonical
apps/trading_daemon.clock ──► trading_lab.data.calendar (MarketCalendar)
apps/trading_daemon ──► trading_lab.contracts（枚举/字段语义; 无 brokers/oms/risk 导入）
scripts/run_m35_shadow_replay.py ──► trading_lab.backtest.arms（合成夹具生成——工程夹具层，非 daemon 核心）
禁止: apps/trading_daemon → trading_lab.brokers / oms / risk / 任何网络模块 / artifacts/poc
```

## 4. 消费者

- `apps/trading_daemon` 核心消费者: `scripts/run_m35_shadow_replay.py`（官方 runner）、`tests/forward_smoke/`。无其他生产消费者（S8 真实 Shadow 获授权后将是下一个消费者，届时需另行评审）。
- `configs/forward_observation.yaml` 消费者: daemon 身份构建器与 runner。
- journal 消费者: daemon engine（重建状态）、资格状态机、独立审计核查（`verify()` 可独立调用）。

## 5. A6 ready 握手 CI flake 观察项

历史: M3-R2 attempt1 ubuntu 失败于既有 M2 A6 进程竞争 flake（571/572），已记录于 `docs/reviews/M3-engineering.md`。本阶段处置: 保留历史失败 run 记录，不重构无关生产代码；若本阶段回归中 A6 重现，按任务书 S0.5 用确定性 READY 同步小范围 RED→GREEN 并单独报告，50 轮有效竞争数量不得减少。当前基线回归结果见 `verification.log`。

## 6. 已知边界（如实声明）

- 静态架构检查无法捕获计算性动态导入/exec——与 M1/M2 同一边界，由检查器 docstring 声明。
- journal 锚的可信度 = 锚文件自身存储（与 M3 账本锚同一 documented boundary，ADR-002 单机威胁模型）。
- `AuditLog.append` 的时间戳为壁钟（真实接收事实）；合成回放的决策内容不依赖壁钟（确定性回放钟），回放等价性比较的是逻辑摘要（决策/摘要/状态迁移），不是壁钟字面值。
