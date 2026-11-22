# M3-R2 T2 — 协议 v2 变更、样本门与预算治理（R2-P1-1 修复）

- 协议文件: `configs/evaluation_protocol.yaml`（唯一权威）
- 加载器: `src/trading_lab/validation/protocol.py`（唯一 sanctioned loader；
  新增 `experiment_batches` 受控节 + `sample_gate` / `trade_stats_gate` API）
- 测试: `tests/validation/test_sample_gate.py`（12 项）；既有 25 项协议测试全数保留

## 1. 协议版本审计链（v1.0 → v1.1 → v2）

| 版本 | protocol_hash | 变更 | 消耗状态 |
|---|---|---|---|
| v1.0 | `9158028541dc0fc7bc6f96b5291d1bee2f43277e055d962ef13f23b684b6e587` | T2 初冻结 | 未被任何官方实验消耗（r1 evidence 留痕） |
| v1.1 | `48dee8613dd727b3fce04230851c75062c9a6e85e634709d8bab09df1cf6ed83` | per-arm 1→3（×1/×2/×3） | **r1 官方 9 trials + 4 queries 全部绑定此 hash**（账本可验） |
| **v2（现行）** | `8afb5207819bcd51ee66072f95d85355ed91b0e73d52e8ed24cc3fcd1ed43901` | ① `protocol_id`→`m3-synthetic-engineering-v2`、`protocol_version`→2；② 新增受控节 `experiment_batches`（r1 legacy 注册 + r2 官方批次声明）；③ description 声明样本门强制语义 | r2 官方 9 trials + 4 queries 绑定此 hash（账本可验） |

变更规则遵循 v2.1：任何受控字段变更 → 新 hash = 新版本；**旧阈值零改动**
（`min_bars: 100`、`min_trades_for_stats: 10`、预算结构 3/3/3 全部保持）。
协议探针测试（9 节受控变更→新 hash）在 v2 上全部照常通过。

**一处既有测试断言更新**（目的保留、随协议变更走）：`test_protocol.py:35` 的
`protocol_id` 断言 v1→v2（该测试的目的"加载成功并绑定 hash"不变；v1 值已在
r1 证据与本文件留痕）。

## 2. 样本门：20 根冒烟 vs 100 根正式的语义对齐

| 数据 | 地位 | 样本门 |
|---|---|---|
| r1 官方 20-bar 数据集（`441980e3…`，账本 13 条） | `SYNTHETIC_SMOKE_ONLY_LEGACY`（v2 批次注册表登记，含消耗预算与账本锚） | `INSUFFICIENT_SAMPLE`（20 < 100）——**永不构成 min_bars PASS**，数据与账本零改动 |
| r2 官方 120-bar 数据集（`803b11b4…`，公式化纯 Decimal 合成） | `OFFICIAL_SYNTHETIC_ENFORCE_SAMPLE_GATE` | `SATISFIED`（120 ≥ 100） |

机制性防线（RED→GREEN）：
- `protocol.sample_gate(n_bars)` 返回 `SampleGateVerdict`（satisfied/verdict/role）；
  99/100/101 边界专测；**计数对象是数据集 session 数（独立 bar），不是权益曲线点**
  （20 根 → 21 个曲线点仍判 INSUFFICIENT，专测钉住两者不得混淆）。
- `run_m3_r2_baselines.official_sample_gate()` 在出具任何工程结论**之前**执行；
  不足门槛抛 `OfficialRunRefused`（官方运行器 exit 2），冒烟数据只能进冒烟证据。
- `ArmResult` 每个结果强制携带 `sample_bars` / `sample_gate_verdict` /
  `trade_stats_status`——结果层不可能"忘记"报告样本地位。
- 诚实 N/A：`trade_stats_gate` 按 `min_trades_for_stats=10` 判定；B0（0 笔）、
  B1（1 笔）→ `N_A_INSUFFICIENT_TRADES`（如实不可计算，**不**判"工程无效"，
  evidence_class 不变）；B2 官方 20 笔 → `OK`。0 收益的 B0 如实报 0.0000。

## 3. 预算治理（不清账、不换名、不绕过）

| 项 | r1 batch（v1.1） | r2 batch（v2） |
|---|---|---|
| 账本文件 | `artifacts/evidence/M3/r1/experiment-ledger.jsonl`（**13 条，只读历史，git 零改动**） | `artifacts/evidence/M3/r2/experiment-ledger.jsonl`（14 条新文件） |
| per-arm 消耗 | 3/3/3 + 4 queries | 3/3/3 + 4 queries（本批次全新预算） |
| 登记 | v2 `experiment_batches.m3-r1-batch-1`（含 dataset/protocol/code hash + 消耗数字 + verdict=INSUFFICIENT_SAMPLE_SMOKE_ONLY） | `m3-r2-batch-1`（`dataset_bars_min: 100`、`OFFICIAL_…`） |
| 血缘 | — | r2 账本首条 `BATCH_INIT` 显式引用 legacy 批次（hash、消耗、**r1 账本外部锚**：13 条 + head `741a9c72…` + tail `f91aef3b…`） |

- 旧 9 trials 未被清除、未改名、未被冒充为 r2 运行；家族累计消耗 9+9=18 trials、
  4+4=8 queries 在两本账本 + 本文件 + v2 注册表中三方可对账。
- 全局 `max_total_trials: 100` 结构保持；每个批次的账本按协议上限独立 fail-closed
  执行（跨批次累计视角以注册表披露，避免"清文件即清预算"）。
- r2 官方运行器对已存在账本**拒绝重跑**（需新协议版本 + 新账本文件）——预算
  不可通过重放脚本刷新。
- 即使样本门 SATISFIED，本批次结果仍为 `SYNTHETIC_ENGINEERING_ONLY`：
  合成上升趋势决定 B1/B2 正净值（数据形状产物），不构成 Alpha / HIST_OOS_SUPPORTED /
  真实数据准入依据；statistical_alpha 门恒 INCONCLUSIVE 不变。

## 4. 官方运行结果（batch m3-r2-batch-1，seed 42）

| 臂 | ×1 | ×2 | ×3 | fills | trade stats | 样本门 |
|---|---|---|---|---|---|---|
| B0_cash | 0.0000 | 0.0000 | 0.0000 | 0 | N_A | SATISFIED |
| B1_buy_hold | +0.0105 | +0.0105 | +0.0104 | 1 | N_A | SATISFIED |
| B2_single_rule (MA 2,4) | +0.0031 | +0.0012 | −0.0006 | 20 | OK | SATISFIED |

- 成本 ×1→×3 单调退化且费用账目一致（B2 ×3 为负 = 费用吃尽毛收益的诚实展示）。
- 0 failures / 0 retries；9 trials + 4 queries 全入账；cohort 披露 independent=True。
- ledger 链验证 14 entries；外部锚落盘 `ledger-anchor.json`。
