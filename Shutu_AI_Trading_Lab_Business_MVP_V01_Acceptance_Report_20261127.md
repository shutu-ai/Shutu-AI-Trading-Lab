# Shutu AI Trading Lab — Business MVP V0.1 验收报告

**任务：** `BUSINESS-MVP-V01-VERTICAL-SLICE-20261127-R1`（B 线业务 MVP，操作者 2026-11-27 一次性批准）
**结论建议：** `BUSINESS_MVP_OFFLINE = PASS_WITH_SCOPE (SYNTHETIC_OFFLINE_ONLY)`
**性质：** 产品集成演示通过。**不是**策略有效性、**不是**正式阶段验收、**不构成** M4–M7 任何正式阶段的启动或关闭。

## 1. 基线与代码位置

| 项 | 值 |
|---|---|
| 基线 SHA | `dee96b2`（d30a784 + H1B 提交，已推送；经文档"更近共同基线"条款核验） |
| 分支 | `feat/business-mvp-v01`（worktree `.claude/worktrees/business-mvp-v01`，本地提交，未推送未合并） |
| 主入口 | `scripts/run_business_mvp.py` |
| 业务包 | `src/trading_lab/business/`（config/types/fixtures/series/features/information/analyzers/info_fixtures/regime/strategies/router/decision/mockexec/replay/report，15 文件） |
| 契约增量 | **无 §2.2 契约改动**（`contracts/` 包字节与基线一致）。信息模型 `InformationEvent`/`InformationAssessment` + 4 个枚举放在 `src/trading_lab/business/models.py`（业务包内部研究对象，复用 contracts 公开类型别名）。首版曾写入 `contracts/events.py`，M3-R2 冻结证据的代码身份测试（`IDENTITY_PACKAGES` 含 contracts）如实报警后迁移——M3-R2 证据身份保持可复算 |
| 配置 | `configs/business_mvp_demo.yaml`（固定先验）、`configs/business_mvp_protocol.yaml`（演示协议 `business-mvp-demo-v1`，与冻结 M3 协议隔离） |
| 架构门扩展 | `scripts/check_architecture.py` 注册 `trading_lab.business` 平面（禁网络/daemon/gateway 导入 + 全部受限平面禁止导入 business）；守卫测试 `tests/architecture/test_business_plane_rules.py` |
| 测试 | `tests/business/`（fixtures/series/features/information/analyzers/regime/strategies/router/replay/information_models 10 文件 204 用例） |

## 1.1 最终回归（本分支 HEAD，2026-11-27 实测）

```
1335 passed in 565.21s (0:09:25) — exit 0，0 failed
```

## 2. 真实运行命令与样例输出

```bash
python scripts/run_business_mvp.py --mode replay --fixture demo --output-dir <run-dir>
```

实测（Windows，worktree venv，Python 3.13）：

```
[business-mvp-v0.1] run complete
  run_id      : bizmvp-56d28bcd0737335b
  run_digest  : fa19a8c0d08eea109faeac32688a28d664a9a5d74926039f169e2508a0cbbe73
  summary     : <run-dir>/summary.json
  report      : <run-dir>/report.html
  labels      : SYNTHETIC_OFFLINE_ONLY · AI_PROVIDER=MOCK/RULE · EXECUTION_BACKEND=FAKE_BROKER/MOCK_ONLY
  honesty     : BUSINESS_DEMO_ONLY — not strategy effectiveness, not formal stage acceptance
```

一次运行产出：`summary.json`、`pipeline_sessions.jsonl`（特征/状态/信息/候选/决策流水）、`pipeline_executions.jsonl`（Mock 执行）、`fixture_info_events.jsonl`、自包含 `report.html`（无外链、无脚本，浏览器直接打开）。`--mode/--fixture` 非 replay/demo 值 fail-closed（exit 2）。

确定性：同 fixture/config/seed/protocol 重跑 summary.json 逐字节一致（`test_two_runs_identical_digests` 强制）；run digest 为全输出的 canonical digest，墙钟不进入任何工件。

## 3. 八类验收（§4）

| # | 场景 | 结果 | 证据 |
|---|---|---|---|
| 1 | 趋势/震荡/高波动回放 | **PASS** | 7 个 (状态,策略) 对：TREND_UP→ma_cross_trend、HIGH_VOL→high_vol_defensive、RANGE→mean_reversion 等；420 session 完整流水 |
| 2 | 信息事件 | **PASS** | RULE+MOCK_LLM 双分析器评估；future-only 事件全程未被评估（PIT 强制）；1 条 loader 拒绝（缺 available_at）+1 条重复去重；注入文本不改 RULE 判定、注入回显被证据指针检查拒绝（UNKNOWN）；过期事件按 valid_until 停止消费 |
| 3 | 双标的与缺数据 | **PASS** | QQQ 缺口窗口：QQQ=UNKNOWN/STALE_DATA 而 SPY=OK（逐 symbol 独立）；fixture 测试证明缺口移除后 SPY 特征逐字节不变 |
| 4 | 正常模拟执行 | **PASS** | 真 SchemaGate→RiskEngine(APPROVE)→OMS(journal-first/fence)→FakeBroker ACKED→FILLED @ fixture 次开盘价（整股）；ledger 守恒 Δ=0.00 |
| 5 | 风险拒绝与重放 | **PASS** | 超限(ORDER_NOTIONAL_EXCEEDED)、池外(SYMBOL_NOT_ALLOWED)、未审查 producer(BUILD_NOT_REVIEWED)、重复意图重放保护、kill-switch HALT→授权解除、ack-lost→UNKNOWN→recover 对账→operator unlock |
| 6 | 绩效及解释 | **PASS** | 唯一正式 BacktestEngine：候选 net +39.41% / maxDD 12.34% / 11 fills / 费用 11.00 vs B0 0%、B1 −1.96%、B2 +11.02%（同引擎同成本口径）；样本门 SATISFIED(420≥100)；Alpha=INCONCLUSIVE（演示协议 NOT_SETTABLE）；合成数字不构成真实声明 |
| 7 | 可复现与隔离 | **PASS** | 双跑 digest 一致（测试强制）；M2/M3/S8 工件未动（evidence 文件曾因全量测试写日志被运行时覆盖，已 git 恢复并核实 diff 为零）；无真实 API/资金/订单；Holdout 未读取 |
| 8 | 跨平台回归 | **PASS** | 全量 pytest 本分支实测 **1335 passed / 0 failed**（exit 0；基线 dee96b2 为 1076 passed；含架构/秘密/Paper 静态门 0 违规、M3-R2 identity 一致性测试绿）；CI 未运行（不推送无触发） |

## 4. 已有模块复用（不重复建设）

- **契约**：MarketBar/MarketSnapshot/RegimeAssessment/StrategySignal/TargetPortfolio/TradeIntent/RiskDecision 直接复用；仅按文档授权追加信息契约
- **回测**：唯一 `BacktestEngine` + B0/B1/B2 语义（`_run_ma_cross` 直接调用正式实现）；演示协议与冻结 M3 协议 id 隔离
- **安全/风控/执行**：`SchemaGate`（信号+组合双门）、`RiskEngine`、`OmsEngine`（journal-first/fencing/幂等/HALT/对账/operator unlock）、`FakeBroker` 全部原样装配（`mockexec.py` 仅装配，无第二账本/风控引擎）
- **数据**：`SyntheticDataset`、`canonical_digest`、`EvaluationProtocol` 冻结机制复用
- **参考**：OMS 装配范式取自 `tests/fault_injection` + `scripts/smoke_mock.py`

## 5. 集成期修复（阻塞性，已修）

1. **换手上限封死建仓**：0.60 上限使全仓进入(Δ=1.0)永久被拒 → 语义修正为"首仓豁免 + 仅风险增加的换手受上限"（退出/减仓永不封顶），测试同步更新
2. **候选回放未推进引擎时钟**：缺 `engine.run_to(asof)` → 全程对空账本定尺、净值恒 0 → 循环内推进（arms 同款模式）
3. **现金目标不平仓**：只遍历 allocation → 持仓永不卖出 → 并入已持有标的、缺省权重 0
4. **Mock 场景时钟错位**：场景在窗口末执行 → 意图 INTENT_EXPIRED（风控正确拒绝，反向证明时序门有效）→ 场景拨回决策时刻
5. **`equity_curve` 事后回溯 vs 次开盘可得**：正式助手在延迟可得 fixture 上结构性失败（引擎拒绝无标记估值，正确 fail-closed）→ 不改正式平面；回放循环中记录曲线，参考组合排除不可估值 stamp 并披露
6. **契约增量触碰 M3-R2 冻结身份**：信息契约最初写入 `contracts/`，M3-R2 identity 回归测试红（`build_code_identity` 范围含 contracts，冻结 code_hash 失配）→ 迁移至 `business/models.py`、`contracts/` 恢复基线字节、identity 测试恢复绿；信息模型若未来升级为跨平面契约须走正式契约变更流程

## 6. 边界、技术债与未完成项

**本轮明确未授权且未做**：真实 Alpaca API、外部付费 LLM、真实 Paper/Live 订单、Holdout 解封、推送/合并。`PAPER` 枚举复用已全程标注 `EXECUTION_BACKEND=FAKE_BROKER / broker_behavior=MOCK_ONLY`。

**登记技术债（非阻塞）**：
- TD-1 `contracts/__init__.py` 再导出已补；后续信息契约演进需走正式契约变更流程
- TD-2 全量回放 ~2-3 分钟（audit 每事件两次文件写入 × ~5400 事件，Windows 文件延迟主导）；如需提速应优化 AuditLog 批量落盘（安全平面改动，另行评审）
- TD-3 候选策略均为 SPY 单标的暴露，QQQ 仅作数据独立性验证；多标的分配是 V0.2+ 工作
- TD-4 虚拟绩效 tracker 的 rank 归一在候选数少时区分度有限；正式化需按 M4/M6 预算机制重做
- TD-5 B2 参考 arm 曲线排除首个可得性前 stamp（已披露）；与 M3 即时可得口径的差异记录于代码注释

**依赖 A 线（H1B/H1C）**：真实历史快照接口（`load_bars_jsonl` 已就位但真实格式接线未做，属 H1C 后工作）；`S=INCONCLUSIVE`、`R=NOT_STARTED` 不变；`H1_REAL_HISTORY_API=NOT_AUTHORIZED`。

## 7. 出口状态

```
BUSINESS_MVP_OFFLINE = PASS_WITH_SCOPE(SYNTHETIC_OFFLINE_ONLY)
H1_REAL_HISTORY_API  = NOT_AUTHORIZED
S = INCONCLUSIVE / R = NOT_STARTED（正式阶段证据不变）
PAPER_WRITE = NOT_AUTHORIZED / LIVE = PROHIBITED / FINAL_HOLDOUT = SEALED_NOT_MATERIALIZED
M4–M7 正式阶段：未启动、未关闭；本 MVP 通过不产生任何阶段信用
```

STOP — 等待操作者审阅本报告后决定真实数据接入与后续阶段。
