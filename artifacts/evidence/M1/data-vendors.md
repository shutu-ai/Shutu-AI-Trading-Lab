# M1 数据供应商验证矩阵（data-vendors.md）

> 检索/核查日期：**2026-11-20**（本会话实际抓取官方页面；代理按环境策略）。
> 判定层级：`DOCUMENTED`（官方页面声明，附 URL）/ `API_VERIFIED`（已授权只读 API 实测）/ `UNVERIFIED` / `BLOCKED_ACCESS`（无授权/无凭证，且本任务禁止注册或购买）。
> 输入：`artifacts/evidence/M-1/vendor_matrix.md`（M-1 待验证假设）。本表全部为 **2026-11-20 时点事实**，不沿用 M-1 价格表。

## 1. Sharadar（经 Nasdaq Data Link 及 sharadar.com 直营）

| 字段 | 事实 | 层级 | 来源 |
|---|---|---|---|
| ① 历史成员 | 提供 `sp500` 表（S&P 500 成分，含增删与生效日期）+ 季度快照；覆盖回溯至 90 年代 | DOCUMENTED | sharadar.com 产品页（2026-11-20 抓取） |
| ② 退市/标的映射 | `tickers` 表为 securities master，**含退市公司**；覆盖"active and delisted companies"回溯至 90s | DOCUMENTED | 同上 |
| ③ 企业行为 | `actions`（公司行为）+ `events`（重大事件）独立表；`stocks` 为 EOD 价格（SEP 经 Nasdaq Data Link 声明含 adjusted/unadjusted + corporate actions，20,000+ 公司回溯 1998） | DOCUMENTED | sharadar.com；data.nasdaq.com/publishers/SHARADAR 摘要 |
| ④ PIT 可得性 | 官方声明 "point-in-time ready"；每日两次更新（17:30 / 23:30 ET）；**无盘中事件时点**（EOD 定位）——公告时间粒度为日级 | DOCUMENTED（粒度限制如实记录） | sharadar.com |
| ⑤ 许可（个人研究） | 具体许可条款文本页未在本次抓取中获得 → **UNVERIFIED**（订阅时以订购页条款为准） | UNVERIFIED | — |
| ⑥ 现价 | 产品页无静态价格（JS 渲染）；第三方流传 "$115–150/月 bundle" **不采信** → **UNVERIFIED**（需登录订购页核实）；免费档仅 DJIA 30 公司 | UNVERIFIED（免费档 DOCUMENTED） | sharadar.com |
| ⑦ 覆盖 | 美股全历史 EOD（1998+），fundamentals 1998+ | DOCUMENTED | 同上 |
| API 实测 | 本机无订阅凭证，且任务禁止注册/购买 → **BLOCKED_ACCESS** | BLOCKED_ACCESS | — |

## 2. Polygon.io / **Massive**（品牌迁移实证：polygon.io 301 → massive.com）

| 字段 | 事实 | 层级 | 来源 |
|---|---|---|---|
| ① 历史成员 | 定价页与产品列表无指数成分产品 → 维持 M-1 判定：无 → 全市场研究用途 `RESTRICT_SCOPE` | DOCUMENTED（absence） | massive.com/pricing（2026-11-20） |
| ② 退市/标的映射 | 定价页未涉及退市历史深度 → **UNVERIFIED**（需授权账户实测 tickers 端点） | UNVERIFIED | — |
| ③ 企业行为 | splits/dividends 端点存在（M-1 SDK 审查确认 API 面）；免费档是否含 → UNVERIFIED | UNVERIFIED | — |
| ④ PIT 可得性 | bar/quote 带 SIP 时间戳（发布时点=事件时间本身）；EOD 档（免费）无盘中时点价值 | DOCUMENTED（能力面） | 历史文档+定价页 |
| ⑤ 许可 | 条款索引页明确：Individual plans 限 **"personal, individual, and non-business use"**；商用走 Businesses terms；再分发细则在子文档 → 个人内部研究匹配 Individual 范围（DOCUMENTED 粗粒度），再分发细节 UNVERIFIED | DOCUMENTED/UNVERIFIED | massive.com/terms（2026-11-20） |
| ⑥ 现价 | Stocks Advanced **$199/月**（实时 + "20+ years of history" + websockets）；Financials & Ratios **$29/月**；年付省 20%；个人档标注 "Individual use only"；免费档现状未渲染 → 免费档细节 UNVERIFIED | DOCUMENTED（$29/$199 档） | massive.com/pricing |
| ⑦ 覆盖 | 美股全市场，Advanced 20+ 年 | DOCUMENTED | 同上 |
| API 实测 | 本机无 API key，任务禁止注册 → **BLOCKED_ACCESS** | BLOCKED_ACCESS | — |

## 3. Alpaca Market Data（Basic 免费档）

| 字段 | 事实 | 层级 | 来源 |
|---|---|---|---|
| ① 历史成员 | 无历史指数成分产品 → `RESTRICT_SCOPE`（维持 M-1） | DOCUMENTED（absence） | docs.alpaca.markets（2026-11-20） |
| ② 退市/标的映射 | 文档页未说明退市标的历史可得性 → **UNVERIFIED** | UNVERIFIED | — |
| ③ 企业行为 | CA API 存在（M-1 alpaca-py SDK 审查：API_VERIFIED 于离线契约层）；Basic 免费档是否包含 → UNVERIFIED | UNVERIFIED | — |
| ④ PIT 可得性 | Basic：SIP 历史延迟 15 分钟；实时仅 IEX；历史 bar **自 2016 起**；无逐事件发布时点保证 | DOCUMENTED | docs.alpaca.markets/docs/market-data |
| ⑤ 许可 | 文档页未载明再分发/存储条款 → UNVERIFIED（以账户协议为准） | UNVERIFIED | — |
| ⑥ 现价 | Basic $0（限速 200 req/min 历史；websocket 30 标的） | DOCUMENTED | 同上 |
| ⑦ 覆盖 | 美股全标的 bar/quote/trade，2016+；CTA/UTP 源 | DOCUMENTED | 同上 |
| API 实测 | 本机无 APCA 凭证（check_environment 确认 absent）→ **BLOCKED_ACCESS** | BLOCKED_ACCESS | — |

## 4. 按用途准入判定（ACCEPT 仅限满足全部前置的用途）

| 用途 | 判定 | 依据 | 解除条件 |
|---|---|---|---|
| 全市场日线策略研究（需成分+退市+PIT+许可齐备） | **BLOCKED_DATA** | 唯一具备成分+退市的 Sharadar 无订阅（BLOCKED_ACCESS）；Alpaca/Polygon 均无历史成分 | 用户购买 Sharadar 订阅并书面授权，完成 API_VERIFIED 实测 |
| 历史成分/退市映射研究 | **BLOCKED_DATA** | 同上 | 同上 |
| 企业行为可重算研究 | **BLOCKED_DATA** | Sharadar `actions`/`stocks` 需订阅；Alpaca CA 免费档含否 UNVERIFIED | 订阅后实测 / Alpaca 凭证实测 |
| 日线管道工程验证（有限标的、合成+真实混合 fixture） | **ACCEPT（仅工程用途）** | 逻辑门与格式验证不依赖供应商覆盖；真实样本按授权只读获取 | — |
| 工程监控/延迟探测 | **ACCEPT（仅工程用途）** | Alpaca Basic $0、200 req/min、IEX 实时可用 | 需用户提供已授权凭证 |
| 分钟线研究 | **RESTRICT_SCOPE** | Basic 仅 IEX 实时 + 15 分钟 SIP 延迟；深度历史需付费档 | 付费档订阅并实测 |
| 事件/公告时点研究 | **RESTRICT_SCOPE** | Sharadar EOD 粒度（无盘中事件时点）；Massive 事件时间戳为成交时间本身，公告时点 UNVERIFIED | 逐笔/新闻时点数据集另行评估（如 Databento，M-1 已列） |

## 5. 与 M-1 待验证项的闭合

| M-1 标注 UNVERIFIED | M1 核查结果 |
|---|---|
| Sharadar 现价 | 仍 UNVERIFIED（官方页 JS 渲染，无静态价；禁止注册）→ 维持历史参考区间并标注未核实 |
| Polygon → Massive 迁移 | **已实证**：polygon.io/pricing 301 → massive.com/pricing；$29/$199 档为 2026-11-20 实抓 |
| Massive tickers 退市深度 | 仍 UNVERIFIED（需授权账户） |
| Alpaca Basic 历史深度 | **已实证（DOCUMENTED）**：2016+，15 分钟 SIP 延迟，200 req/min |
| Sharadar 个人研究许可条款 | 仍 UNVERIFIED（订购条款需登录可见） |

## 6. 证据边界声明

- 本表所有事实标注了来源 URL 与检索日期；**无任何 API_VERIFIED 行**（三家均 BLOCKED_ACCESS：无凭证且任务禁止注册/购买/绕过限制）。
- 因此：**供应商覆盖、延迟、PIT 粒度的真实实验结论不存在**；`tests/no_lookahead/` 的 synthetic fixture 只证明本地逻辑，不证明供应商覆盖——该界限写入 M1 工程报告与 ADR-003。
- 总准入判定：**全市场策略研究 BLOCKED_DATA；工程子集 ACCEPT（限定用途）**——不冒充"完整数据供应准入 PASS"。
