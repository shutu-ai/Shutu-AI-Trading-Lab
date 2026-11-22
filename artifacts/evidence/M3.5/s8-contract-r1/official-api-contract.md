# 官方 API 契约核实（P0，2026-11-22 检索）

> 检索方式：WebFetch 公开文档页（只读文档，无凭证、未调用行情 API）。以下每条标注来源 URL 与检索日期；未检索到的字段明确写"未定义"，不猜。

## 1. `GET /v2/stocks/{symbol}/bars/latest`（单标的最新 bar）

来源：https://docs.alpaca.markets/us/reference/stocklatestbarsingle-1（检索 2026-11-22）

- **语义（原文）**："The latest bar endpoint returns the latest **minute bar** for the given ticker symbol." —— 即该端点是**分钟线**，无 `timeframe` 参数（文档参数仅 `symbol`/`feed`/`currency`）。
- **响应形状（schema `stock_latest_bars_resp_single`）**：必填键为 **`bar`（单对象）** 与 `symbol`；可选 `currency`。**不是本仓库旧 fixture 伪造的 `bars` 数组**。示例 200：`{"symbol":"AAPL","bar":{"t":"2022-08-17T09:07:00Z","o":172.98,"h":173.04,"l":172.98,"c":173,"v":2748,"n":49,"vw":173.007817}}`。
- bar 字段：`t`（RFC-3339，纳秒精度）、`o/h/l/c/v/n/vw` 均必填。
- 结论：旧 S8 v1 协议/夹具/质量门与该端点真实契约**双重错配**（①形状错：期待 `bars` 数组；②语义错：把分钟 bar 当日 bar；③无 timeframe 概念）。多标的变体（`stocklatestbars-1`，`bars` 为按符号键的**字典**）本仓库未使用，仅列出备查。

## 2. `GET /v2/stocks/{symbol}/bars`（区间日线，本轮唯一权威日线来源）

来源：https://docs.alpaca.markets/us/reference/stockbarsingle-1（检索 2026-11-22）

- 参数：`timeframe` **必填**（`1Day`/`1D` 合法）；`feed` 枚举含 `iex`（**默认 `sip`——必须显式传 iex**）；`adjustment` 默认 `raw`（仍显式传）；`start`/`end` RFC-3339 或 YYYY-MM-DD，**含边界**，缺省 start=当日零点、end=当前时间（无实时权限时回退 15 分钟）；`limit` 默认 1000、最大 10000；`page_token` 分页；`sort` 默认 asc。
- **响应形状（schema `stock_bars_resp_single`）**：必填 `bars`（**数组**）、`next_page_token`（**恒存在，可为 null**）、`symbol`。bar 必填 `t/o/h/l/c/v/n/vw`。示例 200：`{"bars":[{"t":"2022-01-03T09:00:00Z","o":178.26,"h":178.26,"l":178.21,"c":178.21,"v":1118,"n":65,"vw":178.235733}],"next_page_token":"QUFQTHxN...","symbol":"AAPL"}`。
- **日线 `t` 的时间戳约定：文档未定义**（示例仅见 `09:00Z`＝04:00 ET，盘前戳）。⇒ 本仓库**不得**用时间戳启发式冒充"已完成日线"证明；日线/分钟的本质区分在**请求契约**（显式 `timeframe=1Day` + 有界窗口），对戳的盘前/盘中特征只作**纵深防御**（盘中戳 ⇒ 拒绝 `NOT_A_DAILY_BAR`，并在文档中如实标注该约定为"示例佐证、非权威定义"）。
- 错误码（文档化）：400 参数错 / 401 认证 / 403 订阅权限 / 429 限频（附 `X-RateLimit-*` 头）/ 500 内部（建议重试）。**404 未文档化**。⇒ 断连恢复证据只认 `TRANSPORT`/429/5xx 类；401/403/400 是凭证/配置错误，**不算断连**。

## 3. 本轮契约决定（依以上文档事实）

1. 唯一日线来源 = ranged `/v2/stocks/{symbol}/bars`，显式 `timeframe=1Day&feed=iex&adjustment=raw&limit=10000` + 会话有界窗口 `start={session_date}T00:00 ET`（含边界以覆盖盘前戳约定）、`end=received_at`，`sort=asc`；`next_page_token` 循环取尽，页数上限预注册（超限拒绝）。
2. 响应校验：`symbol` 回显一致；`bars` 空 = 合法"当日无数据"（`MISSING_BAR` 回执，0 事件、0 日数）；`len(bars)>1` = `SCHEMA` 异常（1Day 窗口单标至多 1 根）；bar 级校验沿用（tz/有限正值/OHLC 关系/日期归属）+ 纵深防御 `NOT_A_DAILY_BAR`（ET 盘中戳）。
3. 分钟 bar 的可能性被三层封死：请求契约（path/timeframe/窗口）+ 响应形状（`bar` 单对象不是数组）+ 盘中戳拒绝。任何一层误配 ⇒ fail-closed 拒绝并回执，0 日线事件、0 前向日数。
4. "已完成日线"的诚实边界：ranged + 收盘后轮询窗口（16:05–17:30 ET）是**预注册的完成性边际**，供应商不保证收盘后即终稿；供应商后补修订走既有"同 id 异载荷 → CONFLICT + 保守挂起"路径，静默改写被禁止。
