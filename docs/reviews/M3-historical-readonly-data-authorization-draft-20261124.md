# H1 受限只读历史数据试点 — 正式授权草案（未签署）

| 字段 | 值 |
|---|---|
| 文档状态 | **`AUTHORIZATION_PENDING`** — 本文件是待用户签发的审批草案，**不是授权、不是签批、不构成任何 API 调用许可**。用户未发送明确签批前：`H1_REAL_HISTORY_API=NOT_AUTHORIZED`，任何 Agent 不得发起任何历史数据请求 |
| task_id | `M3-H-H1-LIMITED-ETF-HISTORY-PILOT-20261124`（批准后以下达指令为准） |
| 上游 | 工作流定义 `docs/plans/M3-historical-research-workstream-20261124.md` §2；根因 `docs/reviews/M3-historical-research-gap-audit-20261124.md` |
| 编制日期 | 2026-11-24 |
| 编制依据（仓库内证据，本轮零联网） | `artifacts/evidence/M1/data-vendors.md`（2026-11-20 实抓）；`artifacts/evidence/M3.5/s8/source-license-and-feed.md`（2026-11-22 检索）；T9.9 报告（2026-11-23 实测一次） |

---

## 0. 本草案申请什么（一句话）

申请**一次**受限的、只读的、免费档范围内的真实历史日线数据获取试点：SPY+QQQ 两只 ETF、日线、ranged bars 端点、IEX feed、候选区间 2017–2025（起止日在实测与协议批准后冻结），用于建立"受限 ETF 历史研究"用途的数据准入事实。**禁止**执行任何 API 调用，直到本草案被签署。

## 1. 账户 / 用途授权核对（执行前置，操作者本人逐项确认）

| # | 核对项 | 判定层级现状 | 执行时动作 |
|---|---|---|---|
| A1 | 账户为用户本人的 Alpaca 账户（Paper/Basic 档即可，无需入金） | DOCUMENTED（T9.9 已有真实账户与只读成功事实） | 操作者确认账户仍有效 |
| A2 | 该账户的数据许可允许**历史**数据用于**个人研究**（条款全文以账户协议当期文本为准） | **UNVERIFIED**（`data-vendors.md:41`；S8 草案已声明不能把可登录当许可验证） | 操作者亲自查阅账户协议行情条款并书面记录结论；不确认=BLOCKED_ACCESS 停止 |
| A3 | 免费档（Basic）对 `feed=iex` 历史 ranged bars 的可用性 | DOCUMENTED 层：Basic $0、200 req/min、历史 bar 自 2016 起（`data-vendors.md:40-42`）；**IEX feed 的历史深度 = UNVERIFIED** | 以 H1 首批请求实测；深度不足则回退登记 |
| A4 | 企业行为端点/复权因子在免费档的包含性 | **UNVERIFIED**（`data-vendors.md:39`） | H1 内单次只读探测端点存在性；不可用则 raw+披露（§4-Q3） |
| A5 | 凭证安全注入（值盲，同 T9.9 机制：脚本直读 `private/credentials.json`，Agent 上下文/日志/命令行零明文） | 已有成功先例（T9.9 授权链 E13） | 操作者复用同一机制；跑后环境清理核验 |

## 2. 授权范围（申请获批的确切边界）

```text
标的上限:        2（固定 SPY, QQQ；不得增加）
粒度:            1Day 日线
端点（唯一允许）: GET https://data.alpaca.markets/v2/stocks/{symbol}/bars
                 参数限定: timeframe=1Day, feed=iex, adjustment=raw,
                 start/end 为授权区间内日期, 逐页 next_page_token
查询日期范围:     候选 2017-01-01 .. 2025-12-31（ET 日历）；
                 ——最终起止必须在"实测 A3 IEX 深度 + 协议批准"后冻结，冻结前不得全量拉取
请求预算:        ≤ 30 次 HTTP 请求/单日执行窗（分页按 1 页 ≤10000 根估算，
                 全区间每标的约 1-3 页；预算含 ≤6 次质量/边界探测请求），
                 速率 ≤ 200 req/min（供应商 DOCUMENTED 限值以下留余量）
执行窗:          批准后单次连续执行；中断即停，续跑需重新申请
预算:            $0.00 —— 禁止任何付费升级/SIP/websocket/订阅（v2 加载器已拒绝付费计划，
                 `configs/forward_observation_s8_real_v2.yaml:47` 同语义延续）
权限:            零提升 —— 不申请 Paper 写、不申请额外 scope、不修改账户设置
```

## 3. 数据出口隔离与凭证处理

1. **复用既有只读采集层**：`apps/market_gateway` GET-only 守卫客户端（交易主机构造期+每请求双拒，`apps/market_gateway/http_client.py:45`；负例 `tests/s8_gateway/test_http_guard.py`）——历史试点不新增网络代码路径、不新增凭证读取路径。
2. **出口白名单**：仅 `data.alpaca.markets`；`TRADING_API_HOSTS`（paper-api/api.alpaca.markets 等）命中即 fail-closed。
3. **凭证**：操作者本机值盲注入（A5）；采集进程直读 `private/`（git-excluded）；日志/回执/证据只记**布尔事实与 hash**（`credential_env_visible` 名称级、值永不出现在任何工件）。
4. **落地隔离**：全部输出进 `artifacts/datasets/historical_research/` 与 `artifacts/evidence/M3-H/h1/`（工作流文档 §5.1）；**不写** `s8-real-pilot` 状态、journal、receipts、anchor；不写 M3 合成账本。
5. **不可入前向账本**（硬门）：H1 数据永不冒充前向观察；重叠披露见工作流文档 §5.2。

## 4. 质量退出条件与失败即停

| 条件 | 动作 |
|---|---|
| 任何 transport error、非 200 响应、重定向尝试、白名单外主机 | 立即 STOP，保留原始证据，登记 UNVERIFIED/BLOCKED |
| 质量拒绝数 > 0 且无法归因为供应商已知口径（Decimal/tz/OHLC/成交量门，复用 S8 质量门语义） | STOP，证据入 `artifacts/evidence/M3-H/h1/` |
| IEX 历史深度 < 冻结区间起点 | 不降区间标准：改为**申请缩短区间**（新批准）或登记 BLOCKED_DATA 回退 H0 态 |
| A2 许可条款不允许个人研究缓存/使用 | 立即 STOP，BLOCKED_ACCESS，数据不落地 |
| 请求计数接近上限（>25）仍未完成 | STOP，报告缺口，剩余另批 |
| 覆盖率/缺失分母可计算但低于新用途行阈值 | 按判定顺序给 RESTRICT_SCOPE 或 BLOCKED_DATA（ADR-003 D5 冻结顺序），不静默补齐 |

**零分母 = INCONCLUSIVE**（D4 语义延续）；本试点**永不**以"部分成功"冒充 ACCEPT。

## 5. 证据脱敏与登记义务

- 证据只含：请求参数、响应行（价格/量/时间戳）与其 hash、质量分母、布尔事实、请求数计数；**不含**任何密钥值、账户标识明文、个人身份信息。
- 供应商事实表按 DOCUMENTED / API_VERIFIED(仅实测端点×参数×日期) / UNVERIFIED / BLOCKED_ACCESS 逐条登记，附检索/实测日期——T9.9 的升级范围不自动继承（E14）。
- 全部结论可被第三方从本仓库文件+hash 复核。

## 6. 明确不授权清单（签署本草案**不等于**批准以下任何一项）

```text
- feed=sip 或任何付费计划/升级          - websocket 实时流
- 第 3 只及以上标的                     - 分钟线/其他粒度
- collect --complete / 连续采集调度      - 写入 s8 前向账本或任何 journal/receipts
- Paper 写（PAPER_WRITE=NOT_AUTHORIZED）- Live（PROHIBITED）
- 购买 Sharadar/任何付费数据             - M4 启动
- 解封 M9 Holdout                        - push（另行单独授权）
- 引用 T9.9 一次采集作为历史能力证明     - 引用 H1 成功作为全市场能力证明
```

## 7. 建议签批文本（用户逐字发送或等价明确表述后方生效）

> 我批准 H1 受限只读历史数据试点（`M3-H-H1-LIMITED-ETF-HISTORY-PILOT-20261124`），范围以
> `docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md` §2 为准：
> SPY+QQQ、日线、ranged bars、feed=iex、adjustment=raw、候选区间 2017–2025（最终起止实测后冻结）、
> ≤30 请求、$0 预算、个人研究用途（我已亲自核对账户许可条款）、凭证值盲注入、数据只进
> historical_research 命名空间。我不批准 Paper 写、Live、SIP、付费、M4、解封 Holdout、push；
> 前向账本与 M3 合成证据零改动。执行完成后停在 M3-H-H1-GATE=USER_PENDING。

**签署栏**：（空白——本文件在用户实际发送签批文本前无任何效力）

---

## 附:C 节 — `configs/data_acceptance.yaml` 新用途行草案（H1 执行轮才写入，本轮不改配置）

```yaml
  - purpose_id: historical_research_limited_etf
    description: >
      Restricted-ETF daily-bar historical research pilot (H1/H2, M3-H
      workstream): admitted REAL history for a FIXED small symbol list
      (<=2) with per-row received_at disclosure. NOT full-market research;
      membership/delisting remain out of scope. Never enters the forward
      ledger; ceiling evidence_state = HIST_OOS_SUPPORTED (H2).
    data_scope: us_equities_daily_limited_etf_history
    requires_daily_bars: true
    requires_minute_bars: false
    requires_corporate_actions: false   # raw-only pilot; CA availability UNVERIFIED on Basic
    requires_history_membership: false  # fixed 2 surviving ETFs
    requires_delisting: false
    available_at_rule: daily_close_available_next_open   # declared assumption, disclosed as unverified per-day
    max_missing_rate: 0.001
    min_coverage_rate: 0.999
    max_latency_seconds: 172800          # retrospective ingest: bounded, disclosed
    required_license_scope: personal_research
    on_fail: RESTRICT_SCOPE
```

（阈值先声明后执行；失败不降；`on_fail=RESTRICT_SCOPE` 而非 ACCEPT——试点级准入始终带范围限制，工作流文档 §2 验收⑤一致。）
