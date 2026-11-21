# Shutu AI Trading Lab — M3-R1 独立验收整改与回归闭环 Codex 任务书

> Task ID: `M3-R1-RESTORE-M2-PROOF-AND-COMPLETE-SYNTHETIC-RESEARCH-20261121-001`
> 编制：2026-11-21
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`
> 远端审查基线：`3505799f844c0a8cfa410df269b6afdd907f38f0`
> 远端 Actions：<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44929797426>
> **实际 CI 为 Ubuntu 343 passed / Windows 343 passed**，而不是提交汇报中的 347。CI 绿不代表 M3 完成。
> 已有仓库审批记录：`docs/reviews/M2-gate-closure-record.md` 记录 `M2_GATE=CLOSED`、`M3_START=APPROVED`，授权范围 `SYNTHETIC_ENGINEERING_ONLY`。执行前须按 AGENTS.md 核对该审批的可信来源与适用范围；本文件不能代替新签批。**M3_GATE=USER_PENDING**；不授权 M3.5、M4、真实数据、Alpaca Paper/Live、资金或自动 push。

## 0. 本轮独立审查的已证实事实与裁决

1. `3505799` 的远端双平台 CI 成功，但原始 CI Job 日志为 `343 passed`（比 `f27892d` 的 347 净少 4 项）。
2. 在 `3505799`，`tests/fault_injection/test_a7_targeted_proof.py` 相对 `f27892d` 删除 151 行、增加 54 行。5 轮成功 claim-holder 子进程 `os._exit(37)` 后 `recover()` 自动 HALT 的参数化验证被删除，替换成顺序 claim 再 claim 等更弱验证。这是**测试覆盖退化**，并非已证明生产代码存在新安全缺陷。
3. `configs/evaluation_protocol.yaml` 已存在，但没有完整可执行的协议 hash/freeze、数据分割、Holdout 封存/污染、独立测试阈值、可审核两套预算等治理能力；不能因文件标题写“frozen”而视为冻结完成。
4. `src/trading_lab/backtest/engine.py` 仅定义轻量 `Bar` 和 `BacktestAccount`（42行）；`buy()` 未执行资金不足检查，数量/价格缺乏严格正值和类型约束，`equity()` 对缺失价格默认为零，尚无可复算的离线事件驱动执行模型。
5. `src/trading_lab/validation/` 只有 `__init__.py`；仓库树未见 `tests/backtest/` 或 `tests/validation/`、M3 三轨报告及 ADR-004。现有 `scripts/check_architecture.py` 只扫描旧 3 包（18 文件），没有审查新研究包。
6. 本轮审查结论：`M3_IMPLEMENTATION_INCOMPLETE / M2_SAFETY_REGRESSION_REQUIRED / M3_GATE=USER_PENDING`。**禁止将旧 M2 Gate 改写为未批准；应恢复持续回归覆盖、标注最新代码的工程验收风险，并报告实际证据。**

## 1. 硬性执行边界

- 先读 `AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md` §4.2/§4.3/§4.5/M3、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md` M3、`docs/reviews/M2-gate-closure-record.md`、现有数据契约与已有 M2/A7 测试。
- 先审计工作树、`git rev-parse HEAD`、`origin/main`、提交链 `f27892d → 5c020b0 → 3505799` 和 CI；禁止 `reset --hard`、force push、直接覆盖旧证据、未授权推送。
- 只允许合成数据 + 纯离线工程验证。保持 `BLOCKED_DATA(全市场研究)`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`R=NOT_STARTED`。不得访问任何真实供应商 API、Alpaca Paper/Live、真实账户/密钥、资金、真实最终 Holdout；不能把合成结果作为真实 OOS/Alpha 证据。
- 保留唯一 OMS/Risk/Broker 和 M1 数据准入权威，不引入第二套交易执行器、订单持久化、Schema Gate、事件总线或无消费者框架；优先复用 `contracts.MarketBar`、数据层 snapshot/PIT/actions/membership/calendar、`security.canonical`。若确有必要新增本地类型，须列出为什么无法复用。
- 整改遵循 `RED → minimal GREEN → independent verification`，绝不可用 skip、xfail、宽泛 except、无效断言来掩盖旧测试退化；失败即如实保留，不用重试洗掉安全违例。
- 修改和提交仅在已核实的 M3 本地开发批准范围内；`git push` 需要独立授权。阶段结束强制 STOP，不自动关闭 M3/启动 M3.5/M4。

## 2. 任务顺序与硬门

### R1-T0 — 源码/证据基线审计（先于所有代码修改）

- 输出 `artifacts/evidence/M3/r1/baseline.md`：SHA、CI Run、各平台真实 `343 passed`、旧基线 `347 passed`、现有文件/缺口、各测试的 collection ID 变化、M3 依赖图。
- 查看 `git diff f27892d..3505799 -- tests/fault_injection/test_a7_targeted_proof.py`；先证明删除的 crash/重启测试与数目，列每项断言的保留/删除情况。
- 列 `REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES`，每项新增代码注明唯一使用者。把 M2 旧审计结论与 M3 新分支上的持续回归证据分开，禁止借用旧 CI 冒充当前 SHA 通过。

### R1-T1 — P0：恢复 M2 A7 不可退化的安全回归（第一 STOP/GO 门）

- 从**已验证 Git 版本** `379bd72` 或 `f27892d` 中恢复 A7 真正的 claim-holder crash 测试（`@pytest.mark.parametrize` ×5）：子进程自己原子领取 claim → 持久 `SEND_CLAIMED` → `os._exit(37)`；父进程只做测试编排；fresh Journal/KillSwitch/OMS 调 `recover()` → `still_unknown`、自动 HALT，重建对象确认持久；不盲重发/不替代意图/新增风险零 Port。
- 保留新的一次性 claim 测试若其断言具有独立价值，但不得以其替代五轮 crash 证明。单独覆盖 HALT 前合法预批准、HALT 后**无条件** `oms.submit()` 拒绝；不要从 `created_orders` 一项冒充真实端口入口计数。
- `pytest --collect-only` 明确列出恢复的五个参数化实例和所有既有关键测试；旧 347 项验收意图不得删除或弱化，新增测试独立计数。正常期望本轮测试数不少于旧 347，且有实际新增的 M3 测试。若实现导致其他测试变更，逐项说明增删理由，不只比较总数量。
- 在 `artifacts/evidence/M3/r1/` 保存 RED/恢复 GREEN 与实际错误类别、PID、exit code、HALT/UNKNOWN 持久状态，运行生成证据不得覆盖 A2/A5/A6/A7 旧路径。
- **此门未通过，停止其它 M3 工作。**

### R1-T2 — 协议注册、哈希冻结和审计硬门

- 以 `configs/evaluation_protocol.yaml` 为权威配置，创建可验证的 schema/解析器/规范化序列化和 `protocol_hash`；更改任意受控字段导致新版本和新 hash，禁止运行时静默改变阈值。复用 `security.canonical` 而非第二套 canonical。
- **首先完成** ADR-004 与协议规则再跑正式实验；明确 `dataset_hash`、`code_hash`、seed、固定数值容差、时间/可用性边界、成本模型和验证状态。
- 补完整协议所要求的目标效应阈值、最小独立样本/事件、错误率或置信区间、多重比较、最大试验/查询次数、失败/重试全计费、实际经济成本和研究费用。在依据不足时必须 `PROTOCOL_INCOMPLETE/INCONCLUSIVE`，不能为取得 PASS 采用“100% 最大回撤”之类无约束阈值冒充有效风险筛选。
- B0–B8 逐臂沿用 v2.1 §4.3 原定义。M3 只实现 B0–B2；B3–B8 登记定义与公平对照预算规则，但不新建 Regime/AI/Champion/Portfolio 空壳。等试验预算和等美元预算须独立定义；不能仅设置两个 `true` 就认为公平。
- M9 一次性最终 Holdout 的**候选选择规则**现在预注册；真实数据未就绪时仅登记 `SEALED_NOT_MATERIALIZED`，不伪造样本 ID/hash，不提前选 M8 冠军。

### R1-T3 — 可信的最小离线回测内核

- 检查当前 `backtest.engine.Bar` 是否与既有 `contracts.MarketBar` 重复；优先复用或做极薄且有唯一职责的纯计算投影，不能重写 M1 数据语义。
- 先写 RED：负数/零价格与数量、float 混入、资金不足买入、超持仓卖出、缺失权益价格、无效时间戳/重复 bar、可用与已交收现金错误、现金/股数/费用不守恒。不能允许负现金/凭空新增股份/隐式将缺失价格当零。
- Decimal 全链守恒；实现可审计事件序列及 `cash_available/cash_unsettled/positions/fees/equity`；模拟 T+N 交收按协议假设执行，不能在研究规则中暗含真实券商保证。
- 严格未来信息隔离：`available_at <= decision_at`；收盘形成的信号不得以已知同一收盘成交；执行价应来自决策后可达报价，包含 order delay、bid/ask spread、commission、slippage、impact、volume cap、partial/unfilled/cancel、split/dividend/delist/ticker reuse、可得时间与美国市场日历/DST。
- 先以固定 seed + 同协议 hash + 同数据 hash + 同代码 hash 验证数值与输出 digest 复现；全部缺失源数据 fail closed，不使用系统时间或未显式随机源。

### R1-T4 — B0/B1/B2 透明合成基线

- B0：现金/若有现金利息则按冻结协议计息；B1：宽基 ETF 合成价格、分红和成本的买入持有；B2：预定义的单一简单透明策略（例如均线趋势），只在 Train/Validation 选参数和冻结版本；三臂共享同快照、成本、资金与时间语义。
- 每个实验登记全量成功/失败/重试、交易/未成交、持仓现金与费用；输出 net return、最大回撤、尾部损失、换手、成本×1/2/3、有效观测数、日历跨度、失败数、候选选择理由。
- 盈利/亏损/零交易、市场跳空、全额不成交、费用超过收益、分红拆股、现金交收等合成 fixture 逐类断言。**不要**将合成基线 PASS 标为真实 `HIST_OOS_SUPPORTED` 或声称赚钱。

### R1-T5 — Walk-Forward、Purge/Embargo、Holdout 与实验账本

- 建立不可重叠的 Train/Validation/rolling historical OOS/sealed-final/forward cohort 边界，按日期、symbol、事件 ID、标签区间和 `available_at` 检测重叠；跨界标签执行 Purge/Embargo，生成可审计 overlap 报告。禁止未来复权/未来成分股/未来公司行动/未来收益/反向时间等泄漏。
- 合成 Sealed Holdout fixture 具角色权限：研究角色的直接读取、统计聚合、查询差分及重复探测均拒绝且写审计；一次合法解封及 `polluted_for_future_selection=true`，二次解封与再次选冠军一律拒绝；`PASS/FAILED/INCONCLUSIVE/INVALIDATED` 全部测试。不能把纯 Python 权限模拟冒充 OS 级沙箱，该能力归 M4。
- 全试验账本包含 code/protocol/data hash、预算、seed、事件 ID、成功/失败/拒绝/取消/重试、费用与时点；预算溢出 fail closed，计数不可因重跑/删除失败而减少。

### R1-T6 — 新包架构检查器与负例

- **只扩展既有** `scripts/check_architecture.py`：从当前 3 包扩到包含 `trading_lab.backtest`、`trading_lab.validation` 的 5 包或实际等价范围；禁止研究包导入 `oms/risk/brokers`、POC、直接 Broker 网络或密钥载入；允许经契约读取已准入数据但不准写交易生产层。
- 添加 `tests/architecture` 的自检负例，覆盖绝对/相对/常量动态导入、包名相似前缀误判；静态检查不能覆盖任意动态代码和运行时网络，另以最小运行时能力负例测试并如实标注剩余限制。
- 新依赖必须逐项说明许可、消费者、跨 Windows/Ubuntu 安装和拒绝替代方案；优先无新依赖。不得复制 M1 data acceptance、OMS 或 Risk。

### R1-T7 — 双平台实测、证据及最终三轨报告（人工阶段门）

新建并保存完整工件：

```text
docs/adr/ADR-004-evaluation.md
src/trading_lab/backtest/
src/trading_lab/validation/
configs/evaluation_protocol.yaml
tests/backtest/
tests/validation/
artifacts/evidence/M3/r1/baseline.md
artifacts/evidence/M3/r1/security-regression.md
artifacts/evidence/M3/r1/protocol-freeze.md
artifacts/evidence/M3/r1/verification.log
artifacts/evidence/M3/r1/negative-tests.log
artifacts/evidence/M3/r1/experiment-ledger.jsonl
artifacts/evidence/M3/r1/cohort-overlap-report.md
artifacts/evidence/M3/r1/architecture-health.md
docs/reviews/M3-engineering.md
docs/reviews/M3-strategy.md
docs/reviews/M3-real-capital.md
```

在本地真实运行并记录退出码：

```bash
python -m pytest -q
python -m pytest -q tests/backtest tests/validation
python scripts/check_environment.py
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
# 另按仓库已有故障矩阵入口执行 1,080 个独立实例，不与 pytest 用例数相加
git diff --check
```

- 记录 Windows/Linux Python 3.13、环境、完整分母、RED→GREEN、失败重试次数、最新 HEAD SHA、protocol/dataset/code hash、真实 CI run URL。**只有用户另行授权 push 后**才能根据该实际推送 SHA 的 Ubuntu+Windows CI 声称 `REMOTE_VERIFIED`。工作树及证据状态须如实报告。
- 通过要求：旧 M2 347 项的关键测试身份与安全断言保留；五轮 crash proof 恢复；原 1,080 故障矩阵零安全违例；M3 负例覆盖且实际运行；B0/B1/B2 和协议/封存/可得时间均具可重算证据；检查器扫描新研究包；不修改任何 Live/Paper 边界。
- `E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 只能在**所有** M3 工程硬门通过后报告；否则 `E=REMEDIATION_REQUIRED/INCONCLUSIVE`。保持 `S=N_A/INCONCLUSIVE`、`evidence_state=NOT_EVALUATED`、`R=NOT_STARTED`、`deployment_state=NOT_DEPLOYED`、`BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED`。没有真实可用数据就不声称 Alpha/HIST_OOS_SUPPORTED。
- **停止：** `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`；不得自动签批、push、启动 M3.5/M4 或真实 Paper/Live。

## 3. 当前轮次的建议 Codex 启动指令

> 阅读此任务书、`AGENTS.md` 和两份 v2.1 计划。在已批准的 M3 合成离线工程范围内，仅执行 M3-R1 的 T0–T7。首先核实 3505799 上 CI 343（不是 347）并恢复 f27892d 已有的 5 轮 A7 claim-holder crash/自动 HALT 回归，然后再补齐 M3 协议冻结、回测可信度、B0/B1/B2 与验证负例。不得删弱任何历史安全断言；故障矩阵 1,080 单列；未授权不 push、不启 M3.5、不开真实数据/Broker/资金。提交本地变更、逐项证据与三轨报告后停止，等待用户验收。
