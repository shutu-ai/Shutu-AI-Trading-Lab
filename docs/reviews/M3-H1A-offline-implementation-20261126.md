# M3-H1A — 历史数据管线离线实现与验收报告

| 字段 | 值 |
|---|---|
| Task ID | `M3-H1A-OFFLINE-HISTORICAL-DATA-PIPELINE-20261126-R1` |
| 日期 | 2026-11-26 |
| 阶段门 | 本轮结束停 `M3-H-H1A-GATE=USER_PENDING`；**不进入 H1 真实 API、不进入 H2、不推进 M3.5 前向窗口** |
| 验收依据 | `H1A_OFFLINE_ENGINEERING=LOCAL_PASS_WITH_SCOPE(SYNTHETIC_OFFLINE_ONLY)`——仅证明离线数据管线工程路径，不代表 H1 真 API 完成；`S=INCONCLUSIVE`、`R=NOT_STARTED` 原值保持 |

## 1. 完整真实基线（本轮实测）

| 项 | 实际值 | 核对方式 |
|---|---|---|
| 本地 HEAD | `a604fa77734df9df864d4bdc209403d3f85dd067` | `git rev-parse HEAD` 实测 |
| origin/main | `a604fa77734df9df864d4bdc209403d3f85dd067`（== HEAD，无漂移） | `git rev-parse origin/main` 实测 |
| H1 文档整改 CI | run `45816148658` = completed/success，headSha=`a604fa7…` | `gh run view` 实测 |
| H0 治理 CI | run `45357179029` = completed/success，headSha=`1a06f81…` | `gh run view` 实测 |
| Python | 3.14.7（仓库要求 ≥3.13） | 实测 |
| 保护文件 | 3 份 M2 脏日志与全部 9 个既有未跟踪文件**原位未动**（仅登记路径名，正文零读取） | `git status --short` 前后对照 |

只读盘点与允许变更路径详见 `artifacts/evidence/M3-H/h1a/t0-inventory-20261126.md`。

## 2. 实现位置（本轮全部代码变更）

**新增（数据层）**：

| 文件 | 职责 |
|---|---|
| `src/trading_lab/data/historical_calendar.py` | `CalendarSupply`（版本/来源 URL/检索时刻/有效期窗口/假日半日表，构造期 fail-closed 校验）+ `VersionedMarketCalendar`（组合复用 `MarketCalendar`，窗口外一律拒绝；`session_open_after` 次开盘规则，覆盖外 `CalendarError`，绝不按"周一到周五"静默推演） |
| `src/trading_lab/data/historical.py` | PIT 分级 `VERIFIED/ASSUMED/UNKNOWN` 闭集 + `PIT_ASSUMED_NOT_VERIFIED` 标记；`HistoricalBarRecord`（三时点绑定 + 证据种类一致性 + VERIFIED 必须有供应商证据且早于接收时刻）；`pit_level_of_manifest`（与 `research_admissible` 正交）；`derive_max_latency_seconds`（冻结日历+预注册宽限推导，推导记录含跳过尾会话披露）；`calendar_deadline_violations`（逐行日历截止门，UNKNOWN 行显式标记）；`evaluate_historical_research`（完整性失败→BLOCKED_DATA；pit UNKNOWN→BLOCKED_DATA；pit ASSUMED 把 ACCEPT 封顶为 RESTRICT_SCOPE 并附 `PIT_ASSUMED_NOT_VERIFIED`，只封顶不升级）；`build_historical_snapshot` + `write_historical_namespace`（仅写调用方给定根目录，确定性 canonical 字节） |

**新增（网关层，唯一网络平面内、零新网络代码路径）**：

| 文件 | 职责 |
|---|---|
| `apps/market_gateway/historical_bars.py` | `HistoricalBarsClient`：完全复用 `GuardedGetClient`（GET-only/HTTPS/host 白名单/路径正则/拒重定向/无 body/Decimal JSON）。业务入口强制：标的 ∈ {SPY,QQQ}、`feed=iex`、`timeframe=1Day`、`adjustment=raw`（常量非参数）、日期 ∈ 冻结许可窗口、请求预算 ≤30（超限请求**发出前**拒绝）、`next_page_token` 链（循环 token 检测、symbol echo 契约、空页拒绝、跨页去重/乱序拒绝、日期边界校验）；请求审计只含 URL/计数，永不含凭证值 |

**最小扩展（向后兼容）**：

| 文件 | 变更 | 兼容性证明 |
|---|---|---|
| `records.py` | `SourceRecord` 增可选尾字段 `availability_basis`（闭集 vendor_fact/assumed_next_open/unknown；assumed 需 datetime、unknown 需 marker，双向一致） | 6 字段旧构造不变 |
| `snapshot.py` | `_entry_dict` 仅当 basis ≠ 默认值时追加键 | 旧式 manifest 哈希**字节不变**——测试冻结常量 `5be7617bd65b26863458af3b5ebb1aee812c740fd924a343a2ad0f07c8f6a597`（改动前捕获）锁定 |
| `acceptance.py` | `AVAILABLE_AT_RULES` 受控新增 `daily_close_available_next_open`（带模型假设注释） | 判定顺序零改动：新规则自然落入 bar-level 分支；三种旧词表行为不变；非法词仍 fail-closed |
| `data/__init__.py` | 导出新公共 API（纯增量） | — |

**新增测试**：`tests/m3_h/`（5 文件，81 用例）+ `tests/helpers_m3_h.py`。**配置零变更**：`configs/data_acceptance.yaml` 本轮**不改**（见 §7）。

## 3. 客观交付演示（零网络、零凭证、零真实 API 调用）

同一批两标的（SPY/QQQ）多页**合成**历史 bars，经假 HTTP transport 注入 `GuardedGetClient`，走统一数据模型产出确定性快照：

```text
manifest_hash = b4a008713b55473d3ef4ecb2dd2bacc64f11c31426d0300e373379cd94657743
manifest.verify()      = True（内容哈希可重算）
research_admissible    = True（完整性+cutoff 门通过——注意：这不等于 PIT VERIFIED）
pit_level              = ASSUMED（+PIT_ASSUMED_NOT_VERIFIED 标记）
decision               = BLOCKED_DATA（许可未确认——如实，不冒充 ACCEPT/RESTRICT）
请求审计               = 3 次（≤30 预算），凭证=NONE，feed=iex/timeframe=1Day/adjustment=raw 全程锁定
API_VERIFIED           = NONE
```

证据工件：`artifacts/evidence/M3-H/h1a/offline-demo/`（request-audit、quality-summary、historical_research 命名空间 manifest/admission/分区行）；`max-latency-derivation.json`（模板推导：最坏合法跨度 92.5h=333000s + 宽限 3600s = 336600s，含跳过尾会话披露）。复现命令：`python -m pytest tests/m3_h -q`（离线夹具）。

本轮明确**未演示**的：2017–2025 真实历史覆盖（未下载，无覆盖率可填）；任何真实供应商发布时点（无 VERIFIED 行存在）。

## 4. 定向测试与 RED→GREEN 证据（T5 要求逐项覆盖）

| # | 任务书要求 | 测试位置 | RED 证据 | GREEN 证据 |
|---|---|---|---|---|
| 1 | 规则新旧词表与 3 种时间字段 | `test_h1a_calendar_rule.py::TestRuleVocabulary`、`test_h1a_pit_records.py::TestAvailabilityBasis/TestHistoricalBarRecord` | red/t1（19 失败）、red/t2（19 失败） | green/t1、green/t2 |
| 2 | NYSE 半日/节假日/DST/长周末/缺日历 fail-closed | `TestNextOpenRule`（65.5h/41.5h/68.5h/92.5h/64.5h DST 跨变）、`TestSessionClassification`、`TestVersionedCalendarSupply` | red/t1 | green/t1 |
| 3 | 假设 PIT 不得标 VERIFIED、次开盘前拦截、下载时刻≠历史时点 | `TestHistoricalBarRecord`（VERIFIED 需供应商证据 + available≥received 拒绝；UNKNOWN 不得升 ASSUMED；ASSUMED 不得带供应商证据） | red/t2 | green/t2 |
| 4 | 日历期限而非简单 48h、阈值先冻结 | `TestCalendarDerivedThreshold`（92.5h 推导、>172800s 断言、负宽限拒绝）、`TestPerRowCalendarGate`（合法 92.5h 不违例、推迟 2h 拒绝、UNKNOWN 显式标记）、`TestOfficialRowPendingCalendarFreeze` | red/t3（13 失败，截断态诚实重构） | green/t3 |
| 5 | IEX 历史 bars 双标的/多页/预算上限/严格只读 | `test_h1a_historical_client.py`（10 用例：预算、循环 token、空页、乱序去重、日期越界、echo 契约、非 200、守卫路径漂移、零凭证） | red/t4（20 失败） | green/t4 |
| 6 | 快照确定性/单字段篡改/历史↔前向零写入 | `TestSnapshotSensitivity`、`TestEndToEndOffline`（同输入同 hash、单 close 改动异 hash）、`TestNamespaceIsolation`（S8/M3 垫圈文件字节不变、仅写命名空间根内） | red/t2、red/t4 | green/t2、green/t4 |
| 7 | license 未确认→BLOCKED_DATA、零分母→INCONCLUSIVE、仅假设 PIT 不得无限 ACCEPT | `TestHistoricalPurposeWrapper`（6 用例：BLOCKED/INCONCLUSIVE/RESTRICT 封顶/UNKNOWN 阻断/完整性行为阻断/VERIFIED 才可 ACCEPT） | red/t3 | green/t3 |
| 8 | M1 既有四用途与 T9.9 静态安全门不退化 | `test_official_yaml_unchanged_four_purposes` + `tests/no_lookahead` 全套 + `tests/s8_gateway` 全套 | — | green/t5（394 passed, EXIT=0） |

**实测计数**：`tests/m3_h` = **81 passed**；`tests/m3_h + tests/no_lookahead + tests/s8_gateway` 合计 = **394 passed, EXIT=0**（`green/t5_full_targeted.log`）。如实声明：**全量 960+ 未在本轮重跑**（任务书禁止全量 pytest——M2 日志副作用），`tests/{architecture,backtest,contract,fault_injection,forward_smoke,m2_remediation,oms,risk,security,validation}` = `NOT_RUN_PROTECTED_WORKTREE`。

**静态门实测**：`check_architecture` EXIT=0（5 包 51 文件，0 违规）；`verify_live_blocked` EXIT=0 PASS；`scan_secrets` EXIT=0（593 文件 0 发现）；`git diff --check --<允许路径>` EXIT=0。

**环境备注（如实）**：本机 Windows 下 pytest 输出重定向到文件时末行 summary 被缓冲吞掉（管道可见），以退出码为准；`pytest_asyncio` 插件的 DeprecationWarning 噪声来自用户 site-packages，非本轮代码。

## 5. 本轮发现并修复的缺陷（全部 RED→GREEN 闭环）

1. **代码缺陷（本轮修复）**：`HistoricalBarRecord` 原实现允许 VERIFIED 行的 `available_at_utc == received_at_utc`（下载时刻冒充发布时刻的边界情形）→ 改为 `>=` 即拒绝（`green/t2`）。
2. **代码缺陷（本轮修复）**：`build_historical_snapshot` 的重复/乱序计数跨标的拼接序列，QQQ 首行与 SPY 末行同 ts 被误判 → 改为按标的分别计数（跨标的同会话交叠是合法的）（`green/t4`）。
3. **代码缺陷（本轮修复）**：`derive_max_latency_seconds` 把覆盖窗口尾会话（12-31）纳入推导，其"次开盘"在窗口外触发 fail-closed 拒绝 → 改为跳过并在推导记录中显式披露 `sessions_skipped_next_open_outside_coverage`（真实日历冻结须覆盖研究窗+1 会话）（`green/t3`）。
4. **测试侧修正（非代码缺陷）**：非法词在 pydantic 直接构造下包装为 `ValidationError`（`DataAcceptanceConfigError` 仅在 `load_acceptance_config` YAML 边界出现）——负例改为双边界断言；3 处测试漏本地 import；哈希基线测试输入与 T0 捕获不一致；夹具把价格写成 JSON 字符串（守卫客户端 `parse_float=Decimal` 契约下应为 JSON 数字）；`request_count` 语义为执行窗累计（设计如此），断言对齐。
5. **任务书错误夹具纠正（T1 要求）**：固化 NYSE 2026 官方事实——2026-11-26 感恩节**休市**、11-27 **开市且 13:00 ET 提前收市**；11-25 收盘→11-27 开盘 = **41.5h**（取代 2026-11-24 勘误文本中"11-27 休市→11-30 开盘=113.5h"的错误数字）；另固化 65.5h（周五→周一）、68.5h（半日周五→周一）、92.5h（圣诞前夕→周一）、64.5h（DST 春季跨变周末）。

## 6. 独立复审（新上下文代理，只读）与修复闭环

复审范围：8 个变更/新增文件 × 6 项威胁模型（PIT 诚实性/日历 fail-closed/网络守卫/命名空间隔离/旧证据兼容/测试诚实性）。复审独立复算了改动前 `_entry_dict` 公式并确认与冻结常量 `5be7617b…a597` 及新代码三方一致；81 项定向测试复跑全绿；41.5h 感恩节夹具被独立重推为算术正确。

**发现 1（IMPORTANT，已修复 RED→GREEN）**：`write_historical_namespace` 的分区目录取自 `entry.name.split("/")[1]` 且 `build_historical_snapshot` 未校验符号段——复审代理实际执行复现 `symbol='..\..\escape'` 逃逸命名空间根。修复：build 与 writer 双重校验符号段 `^[A-Z]{1,5}$`（`SYMBOL_SEGMENT_UNSAFE` 拒绝）；两个逃逸负例 RED（修复前均成功逃逸/写入）→ GREEN。

**发现 2（MINOR→升级修复）**：预算计数在成功响应之后（`request_count += 1` 位于 `get_json` 返回后）——传输失败不计入，操作员重试循环可在授权 30 次之外发送任意多次失败线上请求，与模块契约"超限请求永不发出"矛盾。鉴于预算是 H1 验收治理控制（与发现 1 同属授权边界类），升级修复：`validate_request` 后、发送前计数（失败线上尝试与成功同耗预算；守卫拒绝未到线上、不计）。RED（失败后计数仍为 0）→ GREEN（失败计入、第三次请求被拒）。

**MINOR（登记延后，未修复——按"minor 不进修复通道"纪律）**：

| # | 内容 | 处置 |
|---|---|---|
| 3 | `verified_vendor_row` 接受任意非空自由文本 `evidence_detail`，仓库无回执工件核验——"自我声明式 VERIFIED"理论可行（本轮唯一生产路径只产 ASSUMED 行，纯潜在） | 登记：未来 VERIFIED 路径必须把 `evidence_detail` 绑定到回执 hash（H1 执行时以回执链落实） |
| 4 | 旧式 6 字段 `SourceRecord` 默认 basis=`vendor_fact`，经 `pit_level_of_manifest` 归类 VERIFIED（冻结哈希的既定兼容代价，已披露） | `evaluate_historical_research` docstring 增加路由警示；真正 VERIFIED 行只能产生于 H1 回执链 |
| 5 | `VersionedMarketCalendar.__init__` 不断言日历与 supply 表一致（`from_supply` 为唯一使用路径，构造即一致，纯潜在） | 登记 |

复审其余四项威胁模型（PIT 不可冒充/UNKNOWN 不可升 ASSUMED/下载时刻不可回溯、日历全 fail-closed、网络守卫全负例、旧哈希字节不变）全部判定 clean；测试诚实性判定 clean（无同义反复断言）。复审结论 FIX-FIRST → 两项修复后全绿：`tests/m3_h` 84 passed；合并定向套件 EXIT=0（`green/t5_review_fixes_green.log`）；静态三门复跑 EXIT=0。

## 7. 用途行状态：`PURPOSE_ROW_PENDING_CALENDAR_FREEZE`

`configs/data_acceptance.yaml` **本轮零变更**（机器断言：`test_official_yaml_has_no_historical_research_limited_etf_row`）。理由（勘误 P0-1/P1-4 延续）：

- 受控新规则 `daily_close_available_next_open` 本轮已实现并通过 81 项定向测试；
- 但 `max_latency_seconds` 必须由**冻结研究日历**推导——2017–2025 NYSE 完整假日/半日表本轮**未取得、未核验、未冻结**（离线轮不下载任何数据集），仅提供 Nov 20 – Dec 31 2026 夹具日历（`nyse-2026-h1a-fixture-v1`，来源 URL+检索日期登记）；
- 候选用途行以**可自动验证模板**存在于测试（`_requirements()`：`historical_research_limited_etf`，on_fail=RESTRICT_SCOPE，阈值=模板推导数），冻结日历到位后按既有治理"加行不删行"写入 configs。

## 8. 尚缺实测事实（剩余数据缺口——全部如实 UNVERIFIED/BLOCKED，不因本轮工程完成而改变）

| 缺口 | 等级 | 解除条件 |
|---|---|---|
| IEX feed 在 2017–2025 的真实历史深度 | UNVERIFIED（`data-vendors.md` 仅 DOCUMENTED "自 2016 起"） | H1 首批真实请求实测 |
| 供应商逐日历史发布/可得时点 | UNVERIFIED——**本轮零 VERIFIED 行**，全部 ASSUMED | 供应商发布时点证据（多数免费档不提供；缺失则永久保持 ASSUMED+限范围结论） |
| 2017–2025 NYSE 完整假日/半日表（版本化供应） | 未取得 | 用户授权获取官方日历数据（离线可做）并冻结 |
| 个人研究许可条款 | UNVERIFIED（`H1_PERSONAL_RESEARCH_LICENSE=UNVERIFIED`） | 操作者本人核对账户协议并书面记录 |
| 企业行为/复权可用性 | UNVERIFIED（勘误 P0-2：H1 bars-only，CA 延至另行申请） | 未来独立 CA 探测授权 |
| 真实历史覆盖成功率 | 不存在（零真实取数，零分母→INCONCLUSIVE 语义） | H1 执行 |
| H1 历史接口 `API_VERIFIED` | NONE（T9.9 的单日范围不自动继承，工作流 E14） | H1 实测逐条登记 |

## 9. Goal Alignment Check（A3-H.4 要求）

对照产品总目标（真实历史数据准入能力）：本轮把该能力从"零代码路径"推进到"**离线可审查工程路径就绪**"（可注入假 HTTP 响应、可产生确定性快照、可客观拒绝错误数据、可证伪篡改）。**真实历史数据准入本身仍为 0**：未发生任何真实 API 调用（REAL_API_CALLS=0）、未下载任何真实数据、前向窗口未增加（REAL_FORWARD_DAYS=1 不变）。引用证据：本文 §3/§4 工件路径。该检查不构成 PASS 门权，不得据此自动推进任何阶段。

## 10. 真实 API 授权决定卡（NEXT_HUMAN_DECISION）

本轮**不发起、不预设**任何真实请求。若用户决定进入 H1 真实试点，需**逐项明确**：

1. **签署 H1 授权**：`docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md` §7 文本（或逐字等价）——SPY+QQQ、日线、ranged bars、feed=iex、adjustment=raw、候选 2017–2025（起止实测后冻结）、≤30 请求、$0、bars-only（勘误 P0-2）。
2. **个人研究许可核对**：操作者本人查阅账户协议行情条款并书面记录（A2），未确认 = BLOCKED_ACCESS 停止。
3. **日历冻结授权（可选先行动作，离线）**：批准获取 2017–2025 官方 NYSE 假日/半日表并冻结版本化供应 → 解锁用途行写入 configs（解除 `PURPOSE_ROW_PENDING_CALENDAR_FREEZE`）。
4. **push 独立授权**：本轮唯一本地提交不 push；远端 CI 回归需另行授权 push。

## 11. 状态出口（实际值）

```text
TASK_ID=M3-H1A-OFFLINE-HISTORICAL-DATA-PIPELINE-20261126-R1
BASELINE_HEAD=a604fa77734df9df864d4bdc209403d3f85dd067
ORIGIN_MAIN=a604fa77734df9df864d4bdc209403d3f85dd067
WORKTREE_PROTECTED=YES（3 份 M2 脏日志与全部既有未跟踪文件原位未动，仅路径名登记；本轮新增未跟踪：本轮代码/测试/证据文件 + .superpowers/ 执行 ledger 临时目录——后者不进提交）
CODE_CHANGED=src/trading_lab/data/{historical_calendar.py,historical.py,records.py,snapshot.py,acceptance.py,__init__.py} apps/market_gateway/historical_bars.py tests/m3_h/{conftest.py,test_h1a_calendar_rule.py,test_h1a_pit_records.py,test_h1a_quality_purpose.py,test_h1a_historical_client.py,test_h1a_snapshot_namespace.py} tests/helpers_m3_h.py configs/data_acceptance.yaml(未改) artifacts/evidence/M3-H/h1a/* docs/reviews/M3-H1A-offline-implementation-20261126.md
TESTS_RED=t1:19(6F+13E) t2:19F t3:13F(截断态诚实重构) t4:20F/E，日志 red/*.log
TESTS_GREEN=m3_h 81 passed；m3_h+no_lookahead+s8_gateway 394 passed EXIT=0；分段 green/t*.log
TESTS_NOT_RUN=全量 960+（任务书禁令：M2 日志副作用）；非任务范围目录 NOT_RUN_PROTECTED_WORKTREE
STATIC_GATES=check_architecture EXIT=0(51 文件 0 违规)；verify_live_blocked EXIT=0 PASS；scan_secrets EXIT=0(593/0)；git diff --check EXIT=0
LOCAL_COMMIT=(本轮唯一本地提交——SHA 见会话输出与 git log，本报告随该提交落库)
PUSH=NOT_AUTHORIZED
H0_REMOTE_CI=VERIFIED(1a06f81,45357179029,success)  # gh 本轮实测
H1_CONTRACT_DOCS_REMOTE_CI=VERIFIED(a604fa7,45816148658,success)  # gh 本轮实测
H0_OPERATOR_ACCEPTANCE=USER_PENDING
H1A_OFFLINE_ENGINEERING=LOCAL_PASS_WITH_SCOPE(SYNTHETIC_OFFLINE_ONLY)
H1A_PURPOSE_CONFIG=PENDING_CALENDAR_FREEZE
H1_REAL_HISTORY_API=NOT_AUTHORIZED
H1_PERSONAL_RESEARCH_LICENSE=UNVERIFIED
H1_API_VERIFIED=NONE
H2_REAL_BACKTEST=NOT_AUTHORIZED
M4=NOT_STARTED
M3.5_GATE=USER_PENDING
REAL_FORWARD_DAYS=1  # 仅继承 T9.9 报告事实，不增加
FULL_MARKET_HISTORY=BLOCKED_DATA
PAPER_WRITE=NOT_AUTHORIZED
LIVE=PROHIBITED
REAL_API_CALLS=0
BROKER_ORDERS=0
NEXT_HUMAN_DECISION=H1A 代码验收后，是否明确签署个人研究许可核对与 H1 bars-only 单次只读试点（草案 §7）、是否先行批准 2017–2025 日历冻结（离线）、独立授权 push
```

**STOP**：本轮结束只交付离线可审查代码/测试/证据。未启动真实历史采集、未加入 M3.5 前向日、未执行 H2/OOS 真实回测、未接触 Paper/Live。请把本轮验收结论交回会话，再决定首次真实历史数据试点授权。
