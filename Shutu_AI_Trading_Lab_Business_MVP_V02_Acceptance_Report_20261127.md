# Shutu AI Trading Lab — Business MVP V0.2 验收报告

**任务：** `BUSINESS-MVP-V02-REAL-HISTORY-20261127-R1`（真实历史研究闭环 + 连续 Mock 执行）
**基线：** `feat/business-mvp-v01` @ `9e4846c`（已推送、PR #1 已建、合并待操作者批准）
**分支：** `feat/business-mvp-v02`（本地提交，未推送）
**结论建议：** `V02_OFFLINE_INTEGRATION = PASS_WITH_SCOPE`；`H1_REAL_HISTORY_API/AUTH = NOT_AUTHORIZED`（A2 全程零真实网络，live fail-closed 已验证）

## 1. 交付内容

| 工作流 | 交付 | 状态 |
|---|---|---|
| A1 | NYSE 日历供给 v2（补 2025-01-09 Carter 国葬 + 2026-01-19 MLK；v1 字节保留、hash 分立；全区间 3683 天独立校验；v2 hash `bd06be2f…`）| ✅ 17+12 测试绿 |
| A2 | 受限历史采集入口 `scripts/collect_historical_snapshot.py`（复用 `HistoricalBarsClient`/`GuardedGetClient`/`VersionedMarketCalendar`；probe 假 transport 端到端 2262 bars/标的、分页/预算30/非200即停/两阶段提交/重算 hash/逐标的缺失分母；**live 模式 fail-closed**：无 `H1_REAL_API_AUTHORIZED=SIGNED` 拒绝且不回显凭证）| ✅ 35 测试绿，零真实网络 |
| B1 | `business/snapshot_source.py`：快照 → `MarketBar`/`SeriesStore`，分区 hash 重算、行数核对、越界/乱序/来源错标必拒；负例齐全 | ✅ 47 测试绿 |
| B2 | SPY/QQQ 双标的候选（V2）：逐 symbol 独立趋势/均值回归/防御/现金；QQQ 不再只是独立性测试标的；权重守恒由构造强制（>1 拒绝）；QQQ 数据缺失 → 该腿 0 + 理由，绝不静默持有 | ✅ 82 测试绿 |
| B3 | `business/continuous.py` 连续 Mock 执行：一个持久虚构账户逐 session 走真实 SchemaGate→RiskEngine→OMS→FakeBroker；coid 含会话序号天然幂等；拒绝如实记录不补发；与回测账本分离标注 | ✅ 9 测试绿 + demo 420 cycles 实测 |
| B4 | 本地信息输入 `--info-file`（JSONL/JSON/CSV）；无信息时 `NO_INFORMATION` 如实记录，不合成新闻 | ✅ 实测 USER_FILE_EVENTS 路径 |
| B5 | 报告扩展：数据源/admission/许可披露、连续账本逐周期流水（`continuous_cycles.jsonl`）、双曲线独立标识、`NO_TRADE`/拒单原因 | ✅ |

## 2. 实测命令与样例

```bash
# demo（合成）模式 — 完整连续链路
python scripts/run_business_mvp.py --mode replay --fixture demo --output-dir <dir>

# 历史快照模式（同一 CLI；本例为 probe 合成快照，真实 API 待签批）
python scripts/collect_historical_snapshot.py --symbol SPY --symbol QQQ --output-dir <c> --transport probe
python scripts/run_business_mvp.py --mode historical-replay --snapshot-dir <c>/historical_research --output-dir <dir>
```

- demo 实测：420 sessions，run_digest `1e5d3d8b…`；连续账户 420 cycles（46 成交 / 31 NO_TRADE / 122 风控拒绝如实记录：INSUFFICIENT_SETTLED_FUNDS 133 + ORDER_NOTIONAL_EXCEEDED 12——拒绝理由均为真实风控语义），ledger 守恒 Δ=0.00。
- 历史模式（probe 快照，2024 窗口 252 sessions）实测 digest `de38d032…`；**同输入同命令重跑字节级一致**（确定性成立）。
- 全量窗口（2017–2025，2262 sessions）：见 §3 实测记录。
- admission 如实标注：`research_admitted=False`，blockers = LICENSE_NOT_VERIFIED / PIT_ASSUMED_NOT_VERIFIED / ADMISSION_NOT_RELEASED——探索级使用，不入正式研究。

## 3. 验收观察（§4 对照，全量实测）

| 观察 | 结果 | 证据 |
|---|---|---|
| 一条命令完整链路 | ✅ | demo 模式 `replay`（420 cycles）与快照模式 `historical-replay`（252/2262 sessions）同一 CLI 实测通过；同输入同命令重跑**字节级一致** |
| 双标的独立 + 负例必拒 | ✅ | per-symbol store 独立计算；hash/行数/越界/来源错标负例必拒（47 测试）；无未来信息 |
| 多周期持仓经真实风控/OMS/FakeBroker | ✅ | demo 420 cycles（46 成交/31 NO_TRADE/122 拒绝）；全量 2262 cycles（55 成交/31 NO_TRADE/1249 拒绝，INSUFFICIENT_SETTLED_FUNDS/ORDER_NOTIONAL_EXCEEDED 均真实风控语义）；连续账本守恒 Δ=0.00；重复回放受 OMS 幂等守卫；**真实 broker 未验证（MOCK_ONLY）** |
| 授权前合成替代 | ✅ | probe 快照全程 FAKE_TRANSPORT 标注；`research_admitted=False` + LICENSE/PIT/ADMISSION 三 blocker 如实；探测数据上的绩效数字（net −41.04% 等）**是合成 fixture 数字，无任何市场含义**，验收对象是管线正确性（守恒/时序/流水） |
| 定向回归 + 一次全量 | ✅ | 定向 698 passed；全量见 §7（独立 worktree 内执行，M2/M3/S8 工件零提交污染） |

**B0/B1/B2 与候选同引擎同成本口径**（全量 probe 数据）：B0 0%、B1 −1.45%、B2 −10.84%、候选回放 −41.04%（100 fills；合成 fixture 数字，仅验证管线）。

## 4. 集成期修复（阻塞项，已修）

1. **风控卖出语义**（risk/engine.py 定向修复）：`evaluate` 增加可选 `side` 参数——SELL 释放资金，settled-funds 预检（BUY 可负担性检查）不适用；其余全部检查不变；`side=None`（全部 M2 调用方）行为逐字节不变；决策密封绑定用显式 side 优先于符号推导。M2 全套回归绿。
2. **OMS 意图幂等**（oms/engine.py）：重复 intent_id/coid 在 journal 写入前受控 `REJECTED` + 审计（此前为裸 sqlite IntegrityError）——B3"重启/重复回放可核查"的直接依赖，更严格。
3. **连续账户卖出记账**：FakeBroker 本身 side 无关，mock ledger 按 side 记账；卖出整股数以实际持仓为上限（决策价/次开盘价差异防走空）。
4. **质量词汇表**：`PIT_ASSUMED_NEXT_OPEN` 入册（H1 假设可得性语义；admission 层承载披露，特征层零影响）。

## 5. 技术债（非阻塞）

- TD-6 连续账户 40k 规模下现金约束产生较高买入拒绝率（如实记录；资金规模为 demo 先验）
- TD-7 `command`（含 output-dir 路径）参与 run_digest——同路径重跑才字节一致（V0.1 语义延续）
- TD-8 历史模式逐周期 OMS 使 2262-session 全量运行耗时数分钟（audit 双写主导，同 TD-2）
- TD-9 真实信息源/LLM 接入（V0.3，需独立许可与预算）；快照 `research_admitted=True` 路径需操作者签批后激活
- TD-10 B2 mean_reversion 的 regime 门为组合级标签（两标的共用 RANGE 判定），per-symbol regime 是后续精细化项

## 6. 边界与状态

```
V01_PR_CI   = PR #1 已建，CI 随 PR 触发（合并待操作者）
V01_MERGE   = USER_PENDING
H1_REAL_HISTORY_API/AUTH = NOT_AUTHORIZED（A2 live 全程拒绝验证；探测/全量下载需签署修订 H1 §7 + A2 许可核对）
H1_CALENDAR_SUPPLY_VERSION = v2（bd06be2f…；v1 证据保留；LICENSE_UNVERIFIED 沿袭）
H1_DATA_ADMISSION = 未启动正式准入（快照均 EXPLORATORY）
V02_OFFLINE_INTEGRATION = PASS_WITH_SCOPE
V02_REAL_HISTORY_REPLAY = 待操作者签批真实数据后激活
CONTINUOUS_MOCK_EXECUTION = PASS（MOCK_ONLY；真实 broker 未验证）
S=INCONCLUSIVE / R=NOT_STARTED；PAPER_WRITE=NOT_AUTHORIZED；LIVE=PROHIBITED；HOLDOUT=SEALED
M4–M7 未启动未关闭；H2 正式研究需独立冻结协议批准
```

STOP — 等待操作者审阅。
