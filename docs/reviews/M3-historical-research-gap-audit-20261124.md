# M3-H — 真实历史数据研究目标偏移根因复盘审计（2026-11-24）

| 字段 | 值 |
|---|---|
| task_id | `M3-HISTORICAL-RESEARCH-ROADMAP-CORRECTION-20261124-R1` |
| 日期 | 2026-11-24 |
| 性质 | **DOCS / OFFLINE AUDIT ONLY**（`REAL_API_CALLS=0` / `BROKER_ORDERS=0` / 零联网 / 零付费 / 零凭证读取） |
| 基线 | `HEAD=999b9ba8a958cb2b668f5403320e9501ce838b84 = refs/remotes/origin/main`（未 fetch，仅核对既有远端引用） |
| 上游权威 | `AGENTS.md`、两份 v2.1 计划（本轮只追加，不改写） |
| 结论 | 目标偏移**存在且可定位**：真实前向采集持续推进的同时，真实历史数据研究因**用途分级缺口 + 阻塞治理缺位**停留在笼统 `BLOCKED_DATA`；纠偏路线见 `docs/plans/M3-historical-research-workstream-20261124.md`（H0→H3） |
| 关联工件 | 阻塞登记表 `docs/reviews/M3-historical-data-blocker-register-20261124.md`；H1 授权草案 `docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md` |

**不变量（本轮已核对、零修改）**：`M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`（`docs/reviews/M3-engineering.md:73-87`）、`M3.5_GATE=USER_PENDING`（`docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md:61`）、`REAL_FORWARD_DAYS=1`（T9.9:57）、`S=INCONCLUSIVE`、`R=NOT_STARTED`、`M4=NOT_STARTED`、`PAPER_WRITE=NOT_AUTHORIZED`、`BLOCKED_DATA(全市场研究)`（`artifacts/evidence/M1/data-vendors.md:50`）。T9.9 一次真实只读采集仅作**工程数据路径实证**，不构成历史接口/全市场完整性/历史 PIT/策略有效性的任何证明（其范围限定声明 `API_VERIFIED=…仅升级该接口范围` 见 `docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md:55-56`；前向整窗性质与统计盈利的免责见 :64-68）。

---

## 1. 执行前基线核对（任务书 §1）

| 项 | 实际值 | 处置 |
|---|---|---|
| HEAD | `999b9ba8a958cb2b668f5403320e9501ce838b84` | 与任务书记载的"最近已知公开基线"一致；无冲突，准许写入 |
| origin/main | 同一 SHA（本地既有远端引用；按任务书未 fetch） | 一致 |
| 脏跟踪文件 ×3 | `artifacts/evidence/M2/a5-true-process-race/process_concurrent_50.log`、`a6-strict-process-proof/barrier_50_rounds.jsonl`、`final-send-claim/a2-quantitative-close/process_50_rounds.log`（合计 154 增/154 删行替换：process_concurrent_50.log 104 行、另两文件各 102 行，`git diff --stat`） | **保护，不读取正文、不暂存、不回滚**。成因有仓库先例：A2/A5/A6 测试按设计在每次运行时以新 PID 重写自身日志（`docs/reviews/M3-r2-independent-closure.md:105-106`、`docs/reviews/M3-engineering.md:49-53`）——属其他工作流的本地测试运行痕迹 |
| 未跟踪文件 ×5 | `M35-S8-T9-10-Forward-Window-Readiness-20261124.md`、`Shutu_AI_Trading_Lab_M35_S8_T9_9_First_Real_ReadOnly_Once_Codex_Task.md`、`p1.png`、`p3.png`（**他工作流文件，仅记录文件名，未读取内容**）；本任务书 `Shutu_AI_Trading_Lab_M3_Historical_Research_Correction_Codex_Task_20261124.md`（本任务范围，末尾随文档一并显式提交） | 前四项**保护**，绝不 `git add` |
| 脱敏风险提示 | 脏/未跟踪文件名均为测试日志、任务书、PNG 截图，**无凭证类文件名**；`private/`、`.env`、`*credentials*` 全程未打开、未 grep、未列出内容 | 无需处置 |
| `git add -A` | 未使用（全程逐文件显式指定） | 符合任务书 P0-3 |

---

## 2. 证据定位表（本轮全部结论的唯一出处索引）

| # | 断言 | 证据位置 |
|---|---|---|
| E1 | M1 判定层级词表 DOCUMENTED/API_VERIFIED/UNVERIFIED/BLOCKED_ACCESS；三家供应商均 BLOCKED_ACCESS，零 API_VERIFIED 行 | `artifacts/evidence/M1/data-vendors.md:4,18,31,44,70` |
| E2 | Alpaca Basic（$0）：实时仅 IEX、SIP 历史延迟 15 分钟、历史 bar 自 2016 起、200 req/min、无逐事件发布时点保证 | `data-vendors.md:40-44` |
| E3 | Alpaca 企业行为 API 存在但 Basic 免费档是否包含 = UNVERIFIED；退市/标的映射 UNVERIFIED；许可条款 UNVERIFIED | `data-vendors.md:38-41` |
| E4 | 按用途判定：全市场日线策略研究=BLOCKED_DATA；历史成分/退市研究=BLOCKED_DATA；企业行为可重算研究=BLOCKED_DATA；日线管道工程验证=ACCEPT(仅工程)；工程监控=ACCEPT(仅工程)；分钟线=RESTRICT_SCOPE；事件/公告时点=RESTRICT_SCOPE | `data-vendors.md:46-56` |
| E5 | `configs/data_acceptance.yaml` 仅有 4 个 purpose：`pipeline_poc`、`engineering_monitoring`、`historical_research_daily`（全市场，requires_history_membership/delisting/corporate_actions 全 true，on_fail=BLOCKED_DATA）、`event_research`；**不存在"受限 ETF 历史研究"用途行** | `configs/data_acceptance.yaml:11-70`（全市场行 :42-55） |
| E6 | M1 工程结论：本地工程缺陷为零、E=PASS_WITH_SCOPE(工程子集)；数据准入按冻结必需用途=BLOCKED_DATA；二者不得合并为"完整数据供应准入 PASS" | `docs/reviews/M1-engineering.md:13,45,47` |
| E7 | M1 策略轨：S=N_A，策略证据自 M3 起，不得以数据准入或工程 PASS 充当策略证据 | `docs/reviews/M1-strategy.md:13,19` |
| E8 | M3-R1 合成闭环：协议冻结（v1.1 hash `48dee861…`）、B0–B2 ×1/×2/×3 官方 9 runs、cohort 五维重叠检测、封存 Holdout 状态机、append-only 账本；E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)，522 tests REMOTE_VERIFIED | `docs/reviews/M3-engineering.md:8,14,35-40,44` |
| E9 | M3-R2 补强：协议 v2（`8afb5207…`）、24 文件研究代码身份 `af7ff10c…`、min_bars=100 样本门 fail-closed、账本验链+外部锚、572 tests；20-bar r1 批次降级 SYNTHETIC_SMOKE_ONLY_LEGACY | `docs/reviews/M3-engineering.md:62-69`；`docs/reviews/M3-r2-independent-closure.md:8-10,46-62` |
| E10 | M3 合成官方结果：B0=0.0000 / B1=+0.0105 / B2=+0.0031（×1 成本，120 根合成）；正净值是合成上升漂移的形状产物，`max_claimable_evidence=ENGINEERING_ONLY`，`statistical_alpha` 门 NOT_SETTABLE→恒 INCONCLUSIVE | `docs/reviews/M3-strategy.md:55-61`；`configs/evaluation_protocol.yaml:29-30,67-75` |
| E11 | M3 关闭签批（2026-11-22）：`M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`，不解除 BLOCKED_DATA、不解除 M1 U-1 语义、不宣称真实 OOS/Alpha | `docs/reviews/M3-engineering.md:73-87` |
| E12 | U-1（VendorFacts 非法枚举 fail-open）已按 S8-T1 以封闭词表修复（fail-closed），`BLOCKED_DATA` 不因此解除 | `docs/reviews/M3.5-s8-readonly.md:16`；`docs/reviews/M3.5-s8-operator-gate-reconciliation-t9-7.md`（授权链） |
| E13 | M3.5 S8 只读真实行情授权链：`S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE`（2026-11-22）→ T9.8 直连受限试点例外（2026-11-23）→ B-only 注入核验 → 首次 `collect --once`（2026-11-23 批示，范围 SHA `1751341`/协议 v2/IEX 只读/SPY+QQQ/一次/无 `--complete`） | `docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md:9-18` |
| E14 | T9.9 采集事实：ranged `GET /v2/stocks/{SPY,QQQ}/bars?timeframe=1Day`（feed=iex, adjustment=raw，窗口=当日 ET 午夜→接收时刻）；events=2、quality_rejects=0、回执 2 条；`API_VERIFIED=ALPACA_IEX_RANGED_DAILY_BARS_SCOPE`（仅该接口×该日）；`REAL_FORWARD_DAYS=1`；`eligibility=PENDING_FORWARD_WINDOW`；后续每周期须另行批准 | `docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md:33-41,53-62,74-78` |
| E15 | S8 真实预注册 v3（`m35-s8-real-shadow-readonly-v2`）：feed=iex、plan=basic_free、`broker_credentials=FORBIDDEN`、`vendor_capability_claims_accepted=false`、license scope=`personal_engineering_shadow_only`；窗口起点=会话 ET 午夜（当日），**不含历史回溯区间** | `configs/forward_observation_s8_real_v2.yaml:20-60` |
| E16 | S8 供应商事实分层：IEX 为单一交易所聚合（非 SIP，样本偏 IEX 成交）= DOCUMENTED；Paper Only 账户 IEX 资格=DOCUMENTED（以账户界面与当期条款为准）；全部未 API_VERIFIED（升级只能来自真实到达数据的 receipt 链） | `artifacts/evidence/M3.5/s8/source-license-and-feed.md:7-16,28-32` |
| E17 | 前向工程基座（复用候选）：只读守卫客户端（交易主机双拒）、质量门、回执链；运行时守卫+静态平面规则+预注册加载器三层只读证明 | `docs/reviews/M3.5-s8-readonly.md:15`；`apps/market_gateway/http_client.py:45`（TRADING_API_HOSTS 守卫）及 `tests/s8_gateway/test_http_guard.py` |
| E18 | 研究层正式实现（H2 唯一引擎）：`backtest/engine.py`（Decimal 全链、T+2 交收、守恒）、`backtest/arms.py`（B0/B1/B2 + sample_gate/trade_stats_gate 结果强制）、`validation/protocol.py`（fail-closed 加载器、`sample_gate` :299、`trade_stats_gate` :319）、`validation/cohorts.py`（五维重叠）、`validation/holdout.py`（研究角色读/聚合/差分/探测全拒 :86-110）、`validation/ledger.py`（预算 fail-closed :425-431、锚 :506-525）、`validation/code_identity.py`（24 文件身份） | 上述符号行号来自本轮代码图核验；测试 `tests/backtest/`、`tests/validation/` |
| E19 | M9 Holdout：`SEALED_NOT_MATERIALIZED`、唯一候选选择规则已预注册、`max_unlocks=1`；真实数据 BLOCKED_DATA 期间不物质化 | `configs/evaluation_protocol.yaml:218-246` |
| E20 | v2.1 规划要求原始出处：三轨定义 `Codex_Execution_Plan_v2.1.md:18`；M3 任务行 :56-62；M3.5 :64-70；M4 :72-78；供应商矩阵七字段 `Architecture_and_Codex_Plan_v2.1.md:230-241`；`RESEARCH_SCOPE_LIMITED` 语义 :241；滚动 OOS 仅 HIST_OOS_SUPPORTED :248；前向 cohort 先锁后观察 :250,299；三轴正交 :304-318 | 两份 v2.1 |
| E21 | T9.9 报告成文时 `PUSH=NOT_AUTHORIZED`（:61）；其后该报告经提交 `999b9ba`（"docs(M3.5-S8 T9.9): first real read-only once observed — API_VERIFIED scope upgrade"）存在于 origin/main —— 推送是报告成文之后的独立 Git 事实 | `git log`；`docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md:61` |
| E22 | 静态门脚本均为离线实现（stdlib AST 架构检查 / 本地配置与状态扫描 / 全树密钥正则扫描），本轮实测结果见 §6 | `scripts/check_architecture.py:1-25`、`scripts/verify_live_blocked.py:1-13`、`scripts/scan_secrets.py:1-14` |

---

## 3. T1 — 现状断言矩阵（对照原始产品目标）

原始目标（`Architecture_and_Codex_Plan_v2.1.md:15-17`）：AI 自动研究、严格验证、Champion–Challenger、Paper/Live 隔离；P0→P4 路线（:32-38）；"工程通过 ≠ 策略有效 ≠ 真实资金盈利"（:7）。

| 能力 | 规划要求 | 已实现/实测（真实） | 仅合成工程验证 | 数据阻塞或权限阻塞 | 下一行动 | 需谁审批 |
|---|---|---|---|---|---|---|
| 原始/复权历史数据 | 原始+调整价、企业行为正确处理（Arch:224；Exec M1 :40） | **无已准入研究数据集**；唯一真实数据=T9.9 当日 IEX raw 日线 ×2 标的 ×1 日，属前向账本非研究集（E14） | `actions.adjust_series` 复权重算+asof 约束（ADR-003 D3） | 全市场=BLOCKED_DATA（E4）；Alpaca Basic 历史 2016+=DOCUMENTED、IEX 深度/CA 包含=UNVERIFIED（E2,E3）；Sharadar 1998+=DOCUMENTED 但无订阅（E1） | **H1 试点**：实测 IEX 深度/CA → 冻结窗口与快照（工作流 B） | 用户签批 H1 |
| 历史 PIT 可得性 | event_at/published_at/available_at 分离（Arch:237） | 无真实历史 PIT 事实 | `is_available` 门、UNKNOWN_AVAILABILITY 显式降级、未来记录 100% 阻断（M1-eng:36-37） | Sharadar 仅日级 EOD 粒度（E1）；Alpaca bars 无公告时点 → 事件类因子必须拒绝/降级 | H1 限价格/规则类（无需公告时点）；事件级数据另列阻塞 R4 | H1 用户；事件数据另议 |
| 历史证券池/退市 | universe_asof 可重建任意历史日期池（Arch:234） | 无真实成分数据 | `membership.universe_asof` 区间化+重用检测（ADR-003 D2） | 唯一可行源 Sharadar 无订阅（E4） | H1 不需要（2 只存续 ETF）；H2 维持 BLOCKED | Sharadar 购买决策=用户（阻塞 R1） |
| 回测成交/成本模型 | 延迟/价差/未成交/复权/交收模型（Exec M3 :58） | 无真实数据运行 | 引擎守恒/PIT/确定性 SET 门 + B0–B2 ×1/×2/×3（E8,E10） | IEX 单所成交价 vs 全市场可比性 UNVERIFIED（E16） | H2 复用唯一正式引擎 + IEX 偏差强制披露 | 用户签批 H2 |
| Walk-Forward / OOS | 滚动 OOS、Purge/Embargo（Arch:248-252） | 无真实数据运行 | 滚动 walk-forward 不重叠 OOS、五维重叠检测（E8） | 同上 | H2 真实滚动 OOS（受限标的） | H2 用户 |
| 独立最终 Holdout | M9 单次解封、四态判定（Arch:249,293-302） | 未物质化：`SEALED_NOT_MATERIALIZED`（E19） | 四态 verdict+污染标记机制（E8） | 真实数据缺 | **不动**；H1/H2 不得触碰 Holdout 定义 | M9 届时独立治理 |
| 真实前向 Shadow | ≥5 全覆盖真实交易日+断连/重复恢复（Exec M3.5 :68） | **1 个全覆盖真实交易日**（SPY/QQQ，2026-11-23，IEX；API_VERIFIED 限该接口该日）（E14） | S0–S7 合成回放 686 tests（`docs/reviews/M3.5-engineering.md:10`） | 后续每周期须单独批准（T9.9:76-77）；未满 5 日=PENDING_FORWARD_WINDOW | 工作流 A 继续（逐周期批准），本轮不执行 | 用户逐周期 |
| AI 自动研究/策略对抗 | M4 研究工厂、B6/B7 等预算对照（Exec M4 :72-78） | 未启动：`M4=NOT_STARTED`（E14 状态块） | — | 前置=真实历史研究合格（H2） | 仅当 H2 合格后由 H3 提出申请 | M4 另行签批 |

---

## 4. T1 — 五个必答问题

### Q1 M1 `BLOCKED_DATA` 到底阻塞了什么具体用途？

阻塞的是**三个具体用途**：全市场日线策略研究、历史成分/退市映射研究、企业行为可重算研究（E4，判据=历史成分+退市+企业行为+PIT+许可五个维度不满足或未实测，`configs/data_acceptance.yaml:42-55`）。它**从来不是**"所有 SPY/QQQ 历史研究都不能启动"的同义词——同一张表里 `pipeline_poc` 与 `engineering_monitoring` 就是 ACCEPT（仅工程用途，`data-vendors.md:53-54`）。

但仓库存在一个**分类学缺口**：`data_acceptance.yaml` 只有"工程两用途 + 全市场研究 + 事件研究"四行（E5），**不存在"受限 ETF 日线历史研究"这一用途**。于是任何"拿真实历史数据做研究"的诉求在现有词表里只能落进 `historical_research_daily`（全市场）→ BLOCKED_DATA，或者 `pipeline_poc`（禁止入证据链）——中间档缺失，把"未申请、未实测"呈现成"整体不可研究"。这是本轮纠偏的第一根因。

### Q2 M3 `CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 证明了什么、不能证明什么？

**证明的**（全部以合成数据为界，E8-E10）：冻结协议机器（受控变更→新 hash、运行时不可变）、回测引擎守恒/PIT/确定性、B0–B2 实验夹具与成本 ×1/×2/×3、cohort 五维重叠检测、封存 Holdout 状态机、append-only 账本+外部锚、样本门 fail-closed、24 文件研究代码身份。

**不能证明的**：任何真实市场行为（微观结构、公司行动不确定性、容量/流动性）、任何统计优势（`statistical_alpha` 门 NOT_SETTABLE→恒 INCONCLUSIVE，E10）、真实 PIT、真实成本、IEX 单所成交可比性。M3 关闭记录自身即写明"不解除 BLOCKED_DATA、不宣称任何真实 OOS/Alpha 证据"（E11）。

**历史研究需要的独立补充证明**：(a) 一份已准入的真实历史数据集（snapshot manifest + `research_admissible` + 用途级 `evaluate_purpose` 判定，ADR-003 D8）；(b) 真实数据范围的**新协议版本**（新 hash，不改动 `m3-synthetic-engineering-v2`）；(c) 该协议下的官方真实数据运行（min_bars=100 对日线自然满足）；(d) IEX 单交易所偏差的强制披露。这四项正是 H1/H2 的验收对象。

### Q3 为什么真实前向工程持续推进，历史研究却没有独立排期、授权申请与阻塞责任？

事实链：前向工作流每一轮都有**具体任务书+具体签批**（S8 只读 2026-11-22 签批；T9.7 操作者门消歧；T9.8 直连受限试点例外 2026-11-23 批示；T9.9 首次 `collect --once` 2026-11-23"授权自动执行"，E13）——授权粒度细到"一次采集、两个标的、一个接口"。而历史研究**从未有过对应的授权申请文书**：`BLOCKED_DATA` 被当作一个没有内部结构的单一大门，阻塞项没有按用途登记 owner_role/解除条件/review_trigger（本轮建立的登记表是第一份），也没有任何任务书提出过"申请一个受限历史试点"。叠加阶段门纪律（每轮停在人工门、不自动扩权），理性执行者自然把精力投向**唯一有授权通路**的前向工作流。结论：这是治理结构缺陷（用途分级+阻塞登记+申请文书缺失），不是执行纪律失败，更不是技术不可行。

### Q4 设计缺陷、资源/许可限制、未执行的工作各是哪些？

- **实际设计/治理缺陷**：①用途分级两极化（E5，缺中间档）；②阻塞无登记、无解除条件、无复查触发器；③缺少 Goal Alignment Check（各阶段验收只报 E/S/R 工程事实，无"核心业务目标能力是否推进"的对齐报告，E20）；④历史研究与前向工作流没有并行补证的排期与依赖定义。
- **资源/许可证限制（如实，不夸大）**：①全市场历史需要 Sharadar 订阅（付费，价格 UNVERIFIED，E1）；②Alpaca Basic 历史 bar 深度"自 2016 起"仅为 DOCUMENTED，IEX feed 的实际历史深度、CA 端点在免费档的包含性、个人研究许可全文均 UNVERIFIED（E2,E3,E16）；③IEX 单所数据对策略研究的代表性限制是**数据属性**，不是缺陷（E16）。
- **单纯未执行的工作**：①本轮的 H0 审计与纠偏文档；②H1 受限试点授权草案；③`data_acceptance.yaml` 新增受限历史用途行（属 H1 执行轮）；④双工作流排期。**不得把"未授权/未执行"描述成"技术不可行"**：受限 ETF 历史获取在 DOCUMENTED 层面就存在免费通路（Alpaca Basic 2016+，E2），只是从未实测、从未申请。

### Q5 为什么不能通过改 S/E 状态或把真实行情回填成"前向数据"来补研究缺口？

1. **状态语义**：S=INCONCLUSIVE 是"证据不足以支持结论"的如实判定（`statistical_alpha` 门恒 INCONCLUSIVE，E10）；改写它不产生任何证据。`PENDING_FORWARD_WINDOW` 的机器判定依赖"journal↔receipt 链交叉绑定的真实交易日覆盖"（`docs/reviews/M3.5-s8-readonly.md:19`），回填数据不具备真实到达链。
2. **前向的定义**：前向证据=预测在观察前锁定（Exec M3.5 :66"先锁预测再观察"；Arch:299"先产生并锁定预测、后接收真实价格"）。历史回填的 `received_at`=今天 ≠ 历史决策时点的 `available_at`，永远无法证明"当时可知"（ADR-003 D1）。
3. **协议冻结范围**：S8 v2 预注册窗口起点=会话 ET 午夜（当日），回溯区间不在冻结范围内（E15）；改动即新协议版本+新授权，不存在"在位扩展"。
4. **独立性污染**：把回填数据冒充前向样本会同时污染 M3.5 前向 cohort 独立性与未来 M9 最终 Holdout 的重叠披露义务（Arch:250,300：重叠必须逐条披露，不得重复计数）——这正是任务书 T4 要以隔离设计堵死的地方。

---

## 5. 结论与优先级（P0/P1/P2）

| 级别 | 结论 | 对应产出 |
|---|---|---|
| **P0-1** | 受限 ETF 历史研究（H1）必须成为**独立用途、独立工作流、独立授权节点**，与全市场研究（H2）解耦；本轮已完成分级设计与授权草案，执行仍待批 | 工作流文档 §H1；授权草案（`AUTHORIZATION_PENDING`） |
| **P0-2** | 阻塞治理必须按用途登记（owner/解除条件/复查触发器），"记录阻塞"≠"解决阻塞" | 阻塞登记表（本轮新增） |
| **P0-3** | M3.5 前向账本、S8 冻结协议、M9 Holdout 定义、全部历史证据**零改动**是纠偏的前置约束（已在 §1 与工作流文档中固化为禁止条款） | 工作流文档 §隔离设计 |
| **P1-1** | 用户批准 H1 后：新增用途行 → 最小只读历史试点 → 供应商原始事实+许可/质量/PIT 证据落盘（不写前向账本） | H1 任务（`M3-H-H1-*`，待批） |
| **P1-2** | H1 数据合格后：真实数据版协议（新 hash）→ H2 复用唯一正式回测引擎跑 B0/B1/B2 ×1/×2/×3 + 滚动 OOS + 基准比较 | H2 任务（待批） |
| **P2-1** | 事件级/公告时点数据源评估（Databento 等）与分钟线：保持 RESTRICT_SCOPE，另行授权与可能付费 | 阻塞 R3/R4 |
| **P2-2** | 全市场研究（Sharadar 订阅）解锁决策：纯用户成本/许可决策，Agent 不得代办 | 阻塞 R1 |
| **P2-3** | 每次阶段验收附 Goal Alignment Check（对齐报告，非第四准入状态） | 治理附录 A3-H.4 |

---

## 6. 本轮静态门实测（离线）

| 门 | 命令 | 结果 |
|---|---|---|
| git diff --check | `git diff --check` | **干净**（两份 v2.1 diff 纯追加：+19/−0 与 +48/−0，零删除） |
| 架构边界 | `python scripts/check_architecture.py` | **EXIT=0**：5 packages / 48 files / 0 violations |
| Paper 纯度 | `python scripts/verify_live_blocked.py` | **EXIT=0**：paper runtime contains no live artifacts — PASS |
| 密钥扫描 | `python scripts/scan_secrets.py` | **EXIT=0**：588 tracked files / 0 findings |
| 全量 pytest | **NOT_RUN** —— 本轮为 docs-only 且工作区存在其他工作流未提交的 A2/A5/A6 自再生日志变更；按既有测试设计，运行套件会再次重写这三个证据文件（E9/R2 披露先例），造成归属混淆。不适用原因如实记录 | NOT_RUN |

## 7. T9.9 `PUSH=NOT_AUTHORIZED` 历史语境（不改写声明）

T9.9 报告状态块中 `PUSH=NOT_AUTHORIZED`（E21）是**报告成文时点（2026-11-23）**的如实状态，原文保持原样、本轮零改动。其后该报告经提交 `999b9ba` 进入 origin/main——这是报告之后的独立 Git 事实（`git log` 可查）。本审计仅引用 Git 状态说明先后关系，**不推断、不评价该推送的授权记录**（授权属操作者本地行为，不在仓库可见范围）。

## 8. 验收附页（任务书 §8 硬门逐项）

- [x] 已核对 HEAD/origin/main（一致 `999b9ba`）、脏工作区（3 个他工作流日志，保护未触碰）、未跟踪文件（4 个保护 + 本任务书随本轮提交）；未打开 `private/`/`.env`/凭证。
- [x] 全部结论带文件/行号证据（§2 表 E1–E22）；规划/合成实测/真实 API 实测/未验证四级区分贯穿（§3 矩阵列、E1–E16）。
- [x] H1/H2 两用途独立成篇（工作流 §2/§3、授权草案）；H1 未继承 H2 全市场缺口（用途行 `requires_history_membership/delisting=false` 草案）；无凭证实测/许可验证，H1 全程 `AUTHORIZATION_PENDING`，无任何 ACCEPT 伪造。
- [x] M3 工程存在（E8-E10）但真实历史策略研究无任何统计优势声称；E/S/R 与 BLOCKED_DATA 未升级（§1 不变量核对）。
- [x] M3.5 S8 协议/状态目录/回执/journal/anchor/历史证据零修改（本轮仅 docs）；`REAL_FORWARD_DAYS=1` 引用 T9.9 事实（E14），未升级。
- [x] 双工作流各有授权门/后续任务/验收判据/失败路径（工作流 §1–§4）；H1/H2/H3 均不构成 M4/Paper/Live 授权（§0 三条铁律）。
- [x] PIT/重叠/Holdout 污染风险明确并有机器可验收测试清单 T-H1-01…T-GAC-01（工作流 §5.2/§5.3/§6）。
- [x] append-only：两份 v2.1 原有章节零删除零改写（`git diff --numstat` +19/−0、+48/−0）。
- [x] `git diff --check` 干净；三个静态门 EXIT=0（§6）；pytest NOT_RUN 原因如实（§6）。
- [x] 零联网/零采集/零券商写/零付费/零权限状态变更：`REAL_API_CALLS=0` / `BROKER_ORDERS=0` / `M4=NOT_STARTED`。
- [x] Operator Decision Card 见审计随附最终报告（会话输出），一页以内。
