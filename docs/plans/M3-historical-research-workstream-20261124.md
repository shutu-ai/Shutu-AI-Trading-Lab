# M3-H — 历史研究并行补证工作流（H0→H3）· 2026-11-24

| 字段 | 值 |
|---|---|
| task_id | `M3-HISTORICAL-RESEARCH-ROADMAP-CORRECTION-20261124-R1`（H0 已由本轮完成） |
| 性质 | 对两份 v2.1 计划的**追加式治理附录**的展开文档；不是 v3、不是新的总规划、不是第四种准入状态 |
| 主从关系 | 本文服从 `AGENTS.md` 与两份 v2.1；M-1～M11 主干、E/S/R 三轨、M9 最终 Holdout、全部阈值**原样不变**（`docs/reviews/M3-historical-research-gap-audit-20261124.md` §1） |
| 根因依据 | `docs/reviews/M3-historical-research-gap-audit-20261124.md` §4-§5 |
| 状态 | **H0=READY_FOR_OPERATOR_REVIEW**；H1/H2/H3 均为 `AUTHORIZATION_PENDING`，任何 Agent 不得在用户签批前启动对应真实动作 |

---

## 0. 双工作流总览（只补证，不重开门）

```text
工作流 A（既有，本轮不动）: M3.5 Forward Engineering
  S8 只读逐周期真实采集 ──(每周期单独签批)──> ≥5 全覆盖真实交易日
  → E=PENDING_FORWARD_WINDOW → (自然积累+真实恢复事件) → E 判定
  状态: REAL_FORWARD_DAYS=1, eligibility=PENDING_FORWARD_WINDOW, M3.5_GATE=USER_PENDING

工作流 B（新增，独立补充）: M3-H Historical Research Readiness
  H0 离线治理(本轮,DONE) → H1 受限只读历史试点(待批) → H2 受限历史回测研究(待批)
  → H3 M4 开工申请(待批,仅提案权)
  与 A 仅在"重叠披露"处相交; 数据/账本/协议/凭证全隔离(§5)
```

两流关系三条铁律：
1. B 永不写 A 的任何状态：`s8-real-pilot` 状态目录、Journal、Receipts、Anchor、`REAL_FORWARD_DAYS`、`eligibility` 判定一律零接触（E14/E15，审计 §2）。
2. A 永不解锁 B 的数据门：T9.9 的 `API_VERIFIED` 范围（当日 IEX 单周期）不得自动升级为历史接口/跨年/SIP/复权/许可证明（任务书 P0-6；E14）。
3. A、B 都不推进 M4/Paper/Live：`M4=NOT_STARTED`、`PAPER_WRITE=NOT_AUTHORIZED`、`LIVE=PROHIBITED`（AGENTS.md 规则 3）。

---

## 1. H0 — 离线架构审计与治理（本轮，已完成）

| 字段 | 内容 |
|---|---|
| 进入条件 | 用户明确下达本任务书（2026-11-24 已发生）；HEAD 与已知公开基线一致（审计 §1 核对通过） |
| 输出工件 | ① 差距审计 `docs/reviews/M3-historical-research-gap-audit-20261124.md`；② 本工作流文档；③ H1 授权草案（未签署）；④ 阻塞登记表；⑤ 两份 v2.1 的日期化追加（治理附录 + 交叉引用） |
| 验收判据 | 任务书 §8 全部硬门逐项留证；两份 v2.1 append-only（`git diff` 仅追加）；静态门 EXIT=0；`REAL_API_CALLS=0` |
| 失败回退 | 任何基线冲突/证据缺失/门不通过 → 停在未提交状态，保留问题报告，不制造 PASS（任务书 §9） |
| 明确禁止 | 联网、券商 API、`collect` 任何形式、凭证读取、购买、push、修改测试/证据/协议/阈值 |
| 人类批准节点 | 审阅本轮四份文档与两处追加；决定是否进入 H1 |
| 下一个任务 ID | `M3-H-H1-LIMITED-ETF-HISTORY-PILOT-<YYYYMMDD>`（待用户批准后由用户下达） |

---

## 2. H1 — 受限 ETF 历史数据只读试点（`AUTHORIZATION_PENDING`）

**用途定义**：为"受限 ETF 日线历史研究"这一**新用途**（区别于全市场 `historical_research_daily`，审计 Q1）获取最小真实历史数据，登记供应商原始事实与数据/许可/质量/PIT 证明。**不产出策略结论。**

| 字段 | 内容 |
|---|---|
| 进入条件（全部满足才可执行） | ① 用户签署授权草案（`docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md` 签名栏，或其逐字等价文本）；② 操作者完成草案 §A 账户/许可核对（本人）；③ `HEAD=origin/main` 且 CI 绿（执行轮重验）；④ 环境无协议/证据变更冲突 |
| 输出工件 | `configs/data_acceptance.yaml` 新增 purpose 行 `historical_research_limited_etf`（阈值先声明，on_fail=RESTRICT_SCOPE，见授权草案 §C 草案文本）；`artifacts/evidence/M3-H/h1/`（原始回执 hash、质量报告、许可核对记录、快照 manifest + `research_admissible` 结果、IEX 深度/CA 实测事实表）；独立快照命名空间 `artifacts/datasets/historical_research/`（§5） |
| 验收判据（客观） | ① 用途行机器校验通过（全部阈值非空、非法词 fail-closed——U-1 词表语义延续）；② 采集请求数 ≤ 授权上限、全部只读 GET、`TRADING_API_HOSTS` 零命中；③ 质量门输出分母/缺失/覆盖率/延迟（零分母报 INCONCLUSIVE）；④ 每行数据带 `received_at_utc` ≠ 历史事件时间的披露字段；⑤ snapshot hash 可重算且 `evaluate_purpose` 给出 ACCEPT 或 RESTRICT_SCOPE 的**有据判定**（不满足即如实 BLOCKED_DATA）；⑥ 前向账本零写入（机器断言：与 `s8-receipts-v2` 链无共享条目）；⑦ `REAL_API_CALLS` 仅限授权草案范围内的只读 GET，`BROKER_ORDERS=0` |
| 失败回退 | IEX 历史深度不足/CA 不可用/许可不符 → 如实登记 UNVERIFIED/BLOCKED，工作流 B 回退 H0 态；登记表更新（R2/R5 行），不降阈值、不改判定顺序（ADR-003 D5 冻结） |
| 明确禁止 | `feed=sip`、付费升级、websocket、`--complete`、>2 标的、分钟线、任何 Trading API 主机/写路径、凭证值进入任何日志/上下文/git、把 H1 数据写入前向账本或合成账本、据 H1 宣称全市场能力 |
| 人类批准节点 | 用户签署 H1 授权（一次性，范围=草案所列）；执行完成后停 `M3-H-H1-GATE=USER_PENDING` 审阅证据 |
| 下一个任务 ID | `M3-H-H2-RESTRICTED-BACKTEST-STUDY-<YYYYMMDD>`（仅当 H1 判定合格后申请） |

**与 T9.9 的证据边界**：H1 的 `API_VERIFIED` 升级范围**仅限** H1 实测的确切端点×参数×日期区间，逐条登记；不得引用 T9.9 为历史能力证明（E14）。

---

## 3. H2 — 受限历史回测研究（`AUTHORIZATION_PENDING`）

**用途定义**：在已准入的 H1 数据上，复用 M3 的**唯一正式回测引擎**（`backtest/engine.py` + `arms.py`，E18）执行透明规则基线研究；上限证据等级=`HIST_OOS_SUPPORTED`（Arch:248），**不声称任何 Alpha**。

| 字段 | 内容 |
|---|---|
| 进入条件 | ① H1 快照 `research_admissible=True` 且用途判定非 BLOCKED；② 用户签批 H2 任务书；③ 新协议文件冻结（新 `protocol_id`，如 `m3-h-restricted-historical-v1`，`data_scope=REAL_HISTORICAL_LIMITED_ETF`，`max_claimable_evidence=HIST_OOS_SUPPORTED`——该天花板值取自 `evidence_state` 枚举的历史证据上限（v2.1 §4.6），并在 H2 协议冻结时纳入其受控词表显式定义）——**不改** `m3-synthetic-engineering-v2` 一字节（协议 v2 审计链延续，ADR-004 附记） |
| 输出工件 | 真实数据协议 + 官方运行账本（新 batch，`experiment_batches` 血缘注册引用合成批次）+ `artifacts/evidence/M3-H/h2/`（B0/B1/B2 ×1/×2/×3、滚动 OOS 折边界、`cohort-overlap-report` 含历史↔前向重叠披露、IEX 偏差披露节）+ 三轨式报告 `docs/reviews/M3-H-h2-{engineering,strategy,real-capital}.md`（沿用统一报告规范，Exec:18） |
| 验收判据（客观） | ① `sample_gate` 在真实 sessions 数上 SATISFIED；② 同 hash 复跑 digest 一致（确定性门）；③ 成本 ×1≥×2≥×3 单调退化与费用账目一致；④ 滚动 OOS 折不重叠 + Purge/Embargo 生效；⑤ 重叠报告逐条披露 SPY/QQQ 在历史/前向/未来 Holdout 三域的同日观测，联合统计不重复计数；⑥ 交易统计按 `min_trades_for_stats` 如实 N_A；⑦ 结论行强制携带 `evidence_state=HIST_OOS_SUPPORTED 或 INCONCLUSIVE/FAILED`，出现更高声称即失败；⑧ `final_holdout_status` 仍 `SEALED_NOT_MATERIALIZED` |
| 失败回退 | 数据质量不符 → 回退 H1 重新准入；统计不显著/样本不足 → 如实 INCONCLUSIVE（工作流 B 允许以 INCONCLUSIVE 收尾——"现金观望是合格结果"，Arch:7） |
| 明确禁止 | 解封 Holdout、声称 FORWARD_SUPPORTED/SUPPORTED、启用 B3–B8 中依赖 M5/M6/M7 组件的臂（若协议未含）、修改成本/阈值、复权口径造假（无 CA 数据时只能 raw+披露，禁止伪造调整价） |
| 人类批准节点 | H2 任务书签批；完成后停 `M3-H-H2-GATE=USER_PENDING` |
| 下一个任务 ID | `M3-H-H3-M4-STARTUP-PROPOSAL-<YYYYMMDD>`（仅当 H2 合格） |

---

## 4. H3 — M4 开工申请（`AUTHORIZATION_PENDING`，仅提案权）

| 字段 | 内容 |
|---|---|
| 进入条件 | H2 出具合格判定（协议 SET 门全过 + 重叠披露完整 + 结论如实）；用户愿意讨论 M4 |
| 输出工件 | 一份 **M4 开工申请提案**（引用 H2 证据），交由用户按 v2.1 M4 任务行（Exec:72-78）独立审批 |
| 验收判据 | 提案仅引用已存在证据；不预设 M4 结果；不构成 M4 授权 |
| 失败回退 | H2 不合格 → 无 H3；工作流 B 终止于 H2 报告 |
| 明确禁止 | 以"历史试点通过"推导 M4 已授权（任务书 §4 T3-B 原文）；触碰 Paper/Live |
| 人类批准节点 | 用户对 M4 的独立签批（与 H1/H2 完全分离） |
| 下一个任务 ID | M4 正式任务书（届时另立） |

---

## 5. T4 — 数据、样本与证据隔离设计（契约级）

### 5.1 命名空间隔离

```text
artifacts/
  datasets/historical_research/        # H1 起的新命名空间（快照 manifest + 分区 content hash）
    snapshot-manifest-<id>.json        # build_snapshot 确定性 manifest（ADR-003 D6）
    partitions/<purpose>/<symbol>/...  # 原始行 + received_at_utc 披露字段
  evidence/M3-H/{h1,h2}/               # H1/H2 证据（回执 hash、质量报告、许可核对、账本+锚）
  state/s8-shadow|s8-real-pilot        # 工作流 A 独占（%LOCALAPPDATA% 真实态目录在外部,本仓库零接触）
```

契约：① `historical_research` 命名空间的任何文件不进入 `s8-receipts-v2`/journal/anchor 的引用集（H1 验收⑥机器断言）；② 工作流 A 的真实状态目录与配置（`configs/forward_observation_s8_real*.yaml`）字节级不动；③ M3 合成实验账本/锚/协议、未来 M9 Holdout 定义（`evaluation_protocol.yaml` `holdout:` 节）零修改。

### 5.2 同标的同日重叠的三域披露

同一（SPY, 2026-11-23, 1Day）观测可能同时存在于：历史快照（若区间覆盖）、前向 cohort（T9.9 已采）、未来 Holdout（若 M9 区间覆盖）。契约：
- 重叠报告按 **日期 × 资产 × 事件 ID × 数据版本** 四元组逐条列出三域成员关系（沿用 `validation/cohorts.py` 五维重叠检测的既有机制）；
- 联合效应/置信度计算中同一观测**只计一次**；任何"独立证据"声称必须附去重说明（Arch:250,300）；
- 机器可验收：H2 验收⑤的 `cohort-overlap-report` 必须包含 2026-11-23（两域已知必然重叠日）的显式条目。

### 5.3 `received_at` ≠ 历史 `available_at` 的回溯 PIT 披露

历史数据在**今天**下载，其 `received_at_utc`=下载时刻；它**不是**该 bar 在历史决策时点的可得时间。契约：
- 历史快照每一行携带 `received_at_utc` 与"回溯 PIT 不确定性"标志；数据行的事件时间戳 `ts_event_utc` 按供应商口径登记；
- `pit_rule: available_at <= decision_at` 在 H2 回测中的解释为**协议声明**：日线研究假定"日线收盘数据于次日开盘前可得"（`available_at_rule` 在新用途行显式声明），并强制披露该假设未经逐日时点验证的限制；
- 禁止伪造任何"历史公告/可得时间"；无 CA/公告时点数据的用途不得运行事件类因子（ADR-003 D1、数据验收 D5 冻结语义）。

### 5.4 协议与快照的独立版本化

H1/H2 的一切新协议、新用途行、新批次**只增不改**：`data_acceptance.yaml` 加行不删行、阈值先声明后执行且失败不降（文件头治理规则，`configs/data_acceptance.yaml:1-8`）；`evaluation_protocol` 新文件新 hash；批次血缘双向引用（新 batch 引用合成批次，合成批次不动，E9 模式）。已封存的 M3 合成账本、M3.5 前向协议保持：旧真实预注册已冻结为 `LEGACY_INVALID_VENDOR_CONTRACT`，现行 schema v3 加载器拒绝旧版协议（`configs/forward_observation_s8_real_v2.yaml:6-19`；加载器互拒测试见 `docs/reviews/M3.5-s8-readonly.md:18`）。

### 5.5 执行与凭证隔离（零券商写能力）

- 历史研究执行复用 `apps/market_gateway` 的 GET-only 守卫客户端与静态平面规则（E17）：`TRADING_API_HOSTS`（`apps/market_gateway/http_client.py:45`）在构造期与每请求双拒，负例已有（`tests/s8_gateway/test_http_guard.py`）——**历史研究不新增任何网络代码路径**，不获得 Paper/Live 写能力；
- 凭证处理与 T9.9 同构：操作者本机值盲注入、采集进程直读 `private/`（git-excluded）、日志/回执/git 仅含布尔事实（E13）；`check_architecture` 的平面禁令（data/gateway 不 import brokers/oms/risk）持续强制；
- `artifacts/poc/M-1/` 的样本仅作 POC 参考，不进入任何研究证据链（ADR-003 D3、v2.1 §4.1 REJECT_DATASET 约束）。

---

## 6. 机器可验收的后续测试清单（H1/H2 执行轮的 RED→GREEN 目标）

| ID | 断言（机器可验） | 阶段 |
|---|---|---|
| T-H1-01 | `historical_research_limited_etf` purpose 行存在、全部阈值字段非空、非法词构造 fail-closed（复用 U-1 词表测试模式） | H1 |
| T-H1-02 | 快照 manifest `verify()=True` 且 `research_admissible` 结果与 `evaluate_purpose` 判定一并落盘 | H1 |
| T-H1-03 | H1 证据引用集与 `s8-receipts-v2` 链条目交集为空（前向账本零污染的机器断言） | H1 |
| T-H1-04 | 历史每一行携带 `received_at_utc` 且 ≠ `ts_event_utc`；缺字段即拒绝入库 | H1 |
| T-H1-05 | 请求审计：总数 ≤ 授权上限、全部 GET、主机白名单外零命中（守卫负例保留） | H1 |
| T-H2-01 | H2 协议文件 hash ≠ `m3-synthetic-engineering-v2` 任何历史 hash；`data_scope/max_claimable_evidence` 如实声明 | H2 |
| T-H2-02 | `sample_gate(真实 sessions)`=SATISFIED 才允许官方运行；否则 `OfficialRunRefused` | H2 |
| T-H2-03 | 滚动 OOS 折边界不重叠；重叠报告含历史↔前向 2026-11-23 显式条目 | H2 |
| T-H2-04 | 成本 ×1≥×2≥×3 单调退化断言在真实数据上成立 | H2 |
| T-H2-05 | 账本链验证 + 外部锚落盘；重开带锚正控 | H2 |
| T-H2-06 | 汇总生成器强制 `evidence_state ∈ {HIST_OOS_SUPPORTED, INCONCLUSIVE, FAILED}` 且 `final_holdout_status=SEALED_NOT_MATERIALIZED`；出现更高声称即测试失败 | H2 |
| T-GAC-01 | Goal Alignment Check 节存在于每次新阶段验收报告（静态检查：标题+核心能力引用非空） | 全部 |

---

## 7. 与 M-1～M11 主干的关系声明

本工作流是**对 M3 真实数据研究范围的补证**：它不重新开关 M3 已关闭的合成工程门（`CLOSED_WITH_SCOPE` 原样，E11）、不改变 M1 数据准入判定（H1 只是**新增一个用途行**并按既有判定顺序评估，ADR-003 D5）、不预支 M3.5 的前向窗口、不解封 M9 Holdout。H2 的正式研究若未来希望计入 v2.1 的 S 轨，届时按统一报告规范另出具对应三轨文件——命名与门槛全部沿用 v2.1 §11.2-11.3，不产生并行权威（Exec:204-210）。
