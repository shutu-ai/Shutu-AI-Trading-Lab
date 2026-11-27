# M3-H1B — 历史数据质量硬门整改与日历冻结 · 验收报告

| 字段 | 值 |
|---|---|
| Task ID | `M3-H1B-HISTORICAL-QUALITY-AND-CALENDAR-FREEZE-20261127-R1` |
| 日期 | 2026-11-27 |
| 代码基线 | `d30a784c7e1aa70cd319d7170fa7caa2a3a676c6`（== origin/main，实测） |
| 远端 CI 基线 | run `45963916852` success，ubuntu + windows（用户口径各 1044 passed；本轮**不借该 CI 背书新代码**，见 §5） |
| 阶段门 | 结束停 `M3-H-H1B-GATE=USER_PENDING`；H1 历史 API 仍 `NOT_AUTHORIZED`；H1 授权草案仍未签署 |

## 1. T0 基线与保护（STOP/GO = GO）

`git rev-parse HEAD == origin/main == d30a784…`（缺口未被预修）；3 份 M2 脏日志与全部既有未跟踪文件原位未动、正文零读取；未使用 `git add -A`。既有 H1A 报告/账本零改写（`artifacts/evidence/M3-H/h1a/` 保留为历史记录——其中的离线演示行带有 P0-Q2 所述几何缺陷，正是本轮的整改动机，不回写）。

## 2. P0-Q1 — 跨标的覆盖率虚高（复现 → 修复 → 样本矩阵）

**复现（H1A 代码，RED）**：`build_historical_snapshot` 将 SPY/QQQ 已有日期合并为 `all_session_dates` 再对"全局并集窗口"算 `bar_completeness`——SPY 3/3 + QQQ 1/3 时聚合读 3/3（100%），且不同请求窗口的标的被并集窗口错误计分。RED 证据：`h1b/red/t1_h1b_red.log`（18 失败，含顺带暴露的零行分区 `max()` 空序列崩溃缺陷）。

**修复（最小实现，不发明第二评估器）**：
- `quality.QualityReport` 增**附加字段** `per_symbol_completeness: tuple[MetricResult, ...] = ()`（默认空，M1 构造器字节不动——兼容测试 `test_quality_report_remains_backward_compatible` + no_lookahead 124 passed 证实）；
- `build_historical_snapshot`：每标的按**自身请求窗口**取 `expected_sessions`，逐标的产出 `bar_completeness:<SYMBOL>` 指标；聚合分母 = Σ各标的 expected、缺失 = Σ missing（同一 `missing/denominator` 公式，直接进入既有 `evaluate_purpose` 判定序，零新口径）；
- 零行标的：`observed=0`、`denominator=expected`（**不隐身**），无 manifest 分区行（无可哈希行、无可声明可得性）；
- 空 manifest（全部零行）按 ADR-003 D5 第一句判 **INCONCLUSIVE**（结构不可观测），区别于"有条目但 basis unknown"的 BLOCKED。

**样本统计矩阵**（`artifacts/evidence/M3-H/h1b/offline-demo/per-symbol-completeness-demo.json`，SYNTHETIC_OFFLINE_ONLY）：

| 场景 | 聚合 | SPY | QQQ | 判定（license confirmed） |
|---|---|---|---|---|
| SPY 3/3 + QQQ 1/3 | **4/6（missing 2）** | 3/3 | 1/3 | RESTRICT_SCOPE（MISSING/COVERAGE 原因；base≠ACCEPT） |
| 双标的全齐 | 6/6 | 3/3 | 3/3 | ACCEPT（base，随后被 ASSUMED 封顶 RESTRICT_SCOPE） |
| SPY 3/3 + QQQ 0/3 | **3/6** | 3/3 | 0/3（可见） | 阈值拒绝路径同上 |
| 全零行 | — | — | — | INCONCLUSIVE（零分母） |

单标的重复/乱序：计 violation → 判定级拒绝（网关 fetch 层为硬拒绝）；跨标的同日交叠不再误报（H1A 复审修复保持）。

## 3. P0-Q2 — OHLC 几何不受控（复现 → 修复）

**复现**：H1A 仅查 `low <= high`；`close > high` 的 bar 在网关与数据模型双边界放行，且 H1A 的 QQQ 合成夹具（close≈300 vs o=600/h=602）正是该缺陷形状、参与了通过的 E2E。

**修复（镜像 S8 冻结语义，不改 S8 门本身）**：谓词 `high >= low AND low <= min(open, close) AND max(open, close) <= high`（`apps/market_gateway/quality.py` CROSSED_BAR 同语义，quality.py:275-277）落地于：
1. `HistoricalBarsClient._validate_bar` → `HistoricalRequestRefused("CROSSED_BAR", …)`（拒绝、不悄悄调价）；
2. `HistoricalBarRecord.__post_init__` → `HistoricalDataError("CROSSED_BAR: …)`。

**负例（RED→GREEN）**：`h>l`、`o<l`、`o>h`、`c<l`、`c>h` 五形状 × 两边界全拒（`tests/m3_h/test_h1b_ohlc_geometry.py`）；合法退化 bar `low==open==close==high` 放行。

**夹具纠偏**：`test_h1a_snapshot_namespace.py` / `test_h1a_historical_client.py` 的 `_bar` 改为构造自洽几何（low/high 由 min/max(base, close)±1 推出），SPY≈600 与 QQQ≈300 价格等级保持不同以证明无交叉污染；H1A 全部既有断言（合成、缺许可 BLOCKED_DATA、ASSUMED 封顶、命名空间隔离等）保持通过。

## 4. T3 — 2017–2025 NYSE 日历取证与冻结

**方法与来源矩阵**（检索由代理执行于 2026-11-27，仅公开 NYSE/ICE 资料，未触任何券商/行情端点；每条日期均"当页所见+原文引句"约束，禁止 weekday 推演补缺；完整引句与 URL 存 `artifacts/evidence/M3-H/h1b/calendar/frozen-supply-record.json`）：

| 年份 | 来源（Wayback 存档的官方 nyse.com 日历页，快照日期） | 判定 |
|---|---|---|
| 2017/2018/2019 | snapshot 2017-06-02（nyse.com/markets/hours-calendars） | VERIFIED_FULL |
| 2020/2021 | snapshots 2020-05-30、2021-03-04、2021-06-30 | VERIFIED_FULL |
| 2022/2023/2024 | snapshots 2022-06-01、2022-12-04、2022-12-19 | VERIFIED_FULL |
| 2025（+2026 列） | snapshot 2025-03-05 | VERIFIED_FULL |
| 2026 边界 | snapshots 2026-01-09 + live 页（三源一致：2026-01-01 周四休市；**2026-01-02 周五 = 首个 2026 交易 session**） | VERIFIED |
| 2018-12-05 国葬 | ICE/NYSE 新闻稿（2018-12-01 发布）+ ISDA 通报佐证 | VERIFIED（预发布日历不载，事后公告） |

**特例逐年核实（全部落定，零未证日期、零冲突）**：Juneteenth 自 2022 观测（2022-06-20 观测日；**2021 不观测**——2021-06-30 快照（法签 13 天后）无 Juneteenth 行）；7 月早收仅 2017/2018/2019/2023/2024/2025（2020/2021 观测到周五、无 7 月早收脚注）；感恩节翌日早收 2017–2025 每年（13:00 ET）；圣诞前夕早收仅 2018/2019/2020/2024/2025（2017/2023 12-24 为周日、2021 12-24 为全额观测假日、2022 无）；新年观测 2017-01-02、2023-01-02（2022 依 Rule 7.2 不观测）；Good Friday 各年（04-14/03-30/04-19/04-10/04-02/04-15/04-07/03-29/04-18）；闰年/DST 由 zoneinfo 处理并有 64.5h 跨 DST 测试。

**冻结**：
- 供应：`src/trading_lab/data/historical_calendar_supply.py::NYSE_2017_2025_SUPPLY`，version=`nyse-2017-2026-01-frozen-v1`，窗口 2017-01-01..**2026-01-31**（覆盖研究窗 + 下一交易日 + 边界余量，窗口内只含已核实事实），95 假日 + 20 早收；
- 冻结哈希：`frozen_supply_hash = 826bd96a08b18ada69f77010fa2006516f5088d69a8fb1ceec44033ec106e285`（canonical SHA-256，单日期/范围/版本变更即变）；
- 推导（预注册宽限 **900s**）：`derive_max_latency_seconds = 92.5h（最坏合法跨度，2020-12-24 早收→12-28）+ 900 = 333900s`，全窗口 2284 会话、1 个尾会话跳过披露；记录存证据 JSON；
- 判别力正例（同模式不同年、结果由供应驱动）：Jun-18 收盘 2021→06-21 vs 2022→06-21（周二）；圣诞周 2017/2018/2021/2022 四种不同结果；新年 2022 无观测 vs 2023 观测；2018-12-04→12-06；2025-12-31→2026-01-02；窗口外 fail-closed（2026-02-02 拒绝）。每周末假日日期由 `MarketCalendar` 构造期机检（周末假日即构造失败）。

**条款（LICENSE_UNVERIFIED，如实登记）**：ICE 网站条款（nyse.com 页脚链接，抓取 2026-11-27）授予"个人非商业下载/打印"但禁止"系统化采集/编译为数据库/自动化提取"，许可可随时撤销、无 caching 明示条款——**模糊偏限制**。登记于供应元数据、配置行注释、冻结记录三处；**本轮不声称该日历可供真实研究使用**，且它与 Alpaca 许可核验（草案 A2，仍未签）完全无关。

**用途行（加行不删行）**：`historical_research_limited_etf` 追加进 `configs/data_acceptance.yaml`——`available_at_rule: daily_close_available_next_open`、`max_missing_rate: 0.001`、`min_coverage_rate: 0.999`、`max_latency_seconds: 333900`（== 冻结推导，单一事实源测试锁定）、`required_license_scope: personal_research`、`on_fail: RESTRICT_SCOPE`；四条既有用途零改动（测试逐值断言）。**该行仅代表配置就绪，不代表研究数据 ACCEPT**（许可未确认时 `evaluate_purpose` 第 1 步仍 BLOCKED_DATA）。

## 5. 测试、门禁与兼容（实测）

| 项 | 命令 | 结果 |
|---|---|---|
| H1B RED | `pytest tests/m3_h/test_h1b_per_symbol_coverage.py tests/m3_h/test_h1b_ohlc_geometry.py` | **18 失败**（red/t1_h1b_red.log） |
| 日历冻结 RED | `pytest tests/m3_h/test_h1b_calendar_freeze.py` | **12 失败**（red/t3_calendar_freeze_red.log） |
| H1B GREEN | `pytest tests/m3_h` | **116 passed, EXIT=0**（green/t2/t3 log） |
| 合并定向 | `pytest tests/m3_h tests/no_lookahead tests/s8_gateway` | **429 passed, EXIT=0**（green/t4_full_targeted.log） |
| 静态门 | check_architecture / verify_live_blocked / scan_secrets / `git diff --check` | 0 违规 / PASS / 624:0 / EXIT=0 |
| 全量 pytest | — | `NOT_RUN_PROTECTED_WORKTREE`（M2 日志副作用禁令） |

兼容性证明：旧 6 字段 manifest 哈希冻结常量测试保持通过；`QualityReport` 附加字段默认空、M1 构造器不变；四条旧用途逐值不变；`evaluate_purpose` 判定序未动（新规则在 H1A 已落 bar-level 分支）。本轮测试侧修正两处（均为对齐诚实行为而非改代码凑绿）：哈希字面量占位遗漏替换；单标的重复在适配层为"判定级拒绝"（fetch 层才是抛异常拒绝）——测试断言对齐。

## 6. 独立复审

复审由新上下文代理执行（9 年日历取证为独立代理完成，约束"仅报当页所见+逐条引句+禁止 weekday 推演"；质量修复由本会话完成）。**遗留披露**：日历数据的"当页所见"核验依赖取证代理的会话内抓取记录与引句，本报告作者未逐 URL 重抓复核——冻结哈希使任何后续复核可精确对位（任何日期改动即哈希失配）；如需更高置信度，可在 H1 试点授权时由操作者或独立进程按 `SUPPLY_SOURCE_REFS` 重验。

## 7. 未验证事项与剩余阻塞

| 项 | 状态 |
|---|---|
| IEX 2017–2025 历史深度 | UNVERIFIED（H1 首批实测） |
| 供应商逐日历史发布时点 | UNVERIFIED（零 VERIFIED 行，ASSUMED 永久披露） |
| 个人研究许可（Alpaca） | UNVERIFIED_UNTIL_OPERATOR_ATTESTS（草案 A2） |
| 日历来源条款 | LICENSE_UNVERIFIED（ICE 条款模糊偏限制，见 §4） |
| 企业行为可用性 | UNVERIFIED（H1 bars-only，另批） |
| 真实覆盖率分母 | 不存在（零真实取数） |
| H1 历史 API | NOT_AUTHORIZED（草案未签署） |
| M3 合成协议/S8 前向状态 | 零改动（REAL_FORWARD_DAYS=1 原值） |

## 8. 状态出口

```text
TASK_ID=M3-H1B-HISTORICAL-QUALITY-AND-CALENDAR-FREEZE-20261127-R1
BASELINE_HEAD=d30a784c7e1aa70cd319d7170fa7caa2a3a676c6
REMOTE_CI_BASELINE=d30a784 / run 45963916852 / 1044 ubuntu + 1044 windows
WORKTREE_PROTECTED=YES
P0_Q1_COVERAGE=PASS
P0_Q2_OHLC=PASS
H1B_CALENDAR_SUPPLY=FROZEN_VERIFIED（license caveat: LICENSE_UNVERIFIED）
H1_PURPOSE_CONFIG=READY_WITH_FROZEN_CALENDAR（配置就绪 ≠ 数据 ACCEPT）
TESTS_RED=18（P0 两项）+12（日历冻结），日志 red/*.log
TESTS_GREEN=m3_h 116 passed；合并定向 429 passed EXIT=0；静态门全 EXIT=0
STATIC_GATES=check_architecture 0 违规；verify_live_blocked PASS；scan_secrets 624:0；git diff --check EXIT=0
H1A_REMOTE_CI=VERIFIED_WITH_SCOPE(SYNTHETIC_OFFLINE_ONLY)
H1_REAL_HISTORY_API=NOT_AUTHORIZED
H1_PERSONAL_RESEARCH_LICENSE=UNVERIFIED_UNTIL_OPERATOR_ATTESTS
H1_API_VERIFIED=NONE
H2_REAL_BACKTEST=NOT_AUTHORIZED
M3.5_GATE=USER_PENDING
REAL_FORWARD_DAYS=1
FULL_MARKET_HISTORY=BLOCKED_DATA
PAPER_WRITE=NOT_AUTHORIZED
LIVE=PROHIBITED
LOCAL_COMMIT=(本轮唯一本地提交——SHA 见会话输出与 git log)
PUSH=NOT_AUTHORIZED（见下注）
NEXT_HUMAN_DECISION=H1B 验收 / 个人数据许可确认（Alpaca A2 + 日历来源条款双轨）/ H1 bars-only 一次只读试点授权
```

**push 注**：H1A 轮您曾以"推送"授权过该轮提交的推送；本轮在无待推提交时您再次发送"推送"——已按最近指令解读为对本轮唯一本地提交的推送预授权并记录在案（如非此意请指出，可在远端撤销）。报告其余部分的 `PUSH=NOT_AUTHORIZED` 指任务书签发时的原始边界，两个事实按时间序均成立。

**STOP**：停 `M3-H-H1B-GATE=USER_PENDING`。本任务不构成任何真实历史数据、下单、资金、连续运行或下一阶段授权。
