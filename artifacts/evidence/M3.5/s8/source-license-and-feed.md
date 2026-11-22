# S8 行情来源、许可与 Feed 证据分层

> 证据词表：`DOCUMENTED`（文档证据，未实测）/ `API_VERIFIED`（实测）/ `UNVERIFIED` / `BLOCKED_ACCESS`。

## 来源（批准的）

| 事实 | 状态 | 证据 |
|---|---|---|
| 行情来源 = Alpaca Markets（US equities/ETF） | `DOCUMENTED`（2026-11-22 检索） | https://docs.alpaca.markets/us/docs/getting-started-with-market-data ；审批草案官方核对节 |
| 免费 Basic 计划提供 IEX feed，单符号限制内可用 | `DOCUMENTED` | https://docs.alpaca.markets/us/docs/about-market-data-api （Basic 免费、IEX 单一交易所、有速率限制） |
| IEX 为单一交易所聚合（非全市场 SIP）——样本偏 IEX 成交 | `DOCUMENTED` | 同上；预注册已按 IEX-only 声明 |
| bars/latest 端点与响应形状（t/o/h/l/c/v[/n/vw]） | `DOCUMENTED` | https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data 及 REST bars 文档；自测夹具按此形状 |
| 凭证头 `APCA-API-KEY-ID/SECRET`（Data API 与 Trading API 共用变量名） | `DOCUMENTED` | https://docs.alpaca.markets/us/v1.1/docs/authentication |
| Paper Only 账户对 IEX 的访问资格 | `DOCUMENTED` | https://docs.alpaca.markets/us/docs/paper-trading （**以用户账户界面与当期条款为准，由账户所有者确认——签批条款 3**） |
| 2026-11/12 NYSE 交易日历（感恩节 11-26 休市、11-27 13:00 早收、圣诞 12-25 休市、12-24 13:00 早收、2027-01-01 休市） | `DOCUMENTED`（交易所历年既定规则；**首次采集前由操作者对照交易所当期公告复核**） | 预注册 `market_clock` 表 |
| 上述全部 | **未 `API_VERIFIED`** | 本机无凭证（`BLOCKED_ENV`）；任何 `API_VERIFIED` 升级必须来自**真实到达数据**本身，采集器 receipt 链留证 |

## 许可与预算（签批边界）

- 用途范围：个人工程 Shadow 观察（预注册 `license_attestation.scope=personal_engineering_shadow_only`）；不用于 Alpha 主张、不用于全市场研究。
- 预算：**$0**（`plan=basic_free`）；付费计划（SIP/Algo Trader Plus）在 v2 加载器即拒绝，无自动订阅路径。
- 账户注册、许可条款确认、密钥安全注入：**账户所有者本人**（签批条款 3）；代理不得读取/打印/提交/上传密钥，采集器仅在使用时构建请求头，值不入日志、回执、git。

## Blockers（当前）

`BLOCKED_ACCESS`（外部条件未备）：本机无 `APCA_*` 凭证；真实连接在预检双门（授权标记 + 凭证可见性）齐备前被拒绝（exit 3/4，负例见 `negative-tests.log` 与 `test_runner_cli.py`）。

## 升级路径（须如实）

1. 用户完成账户/许可/凭证（条款 3）→ 采集器 `collect` 预检转 `READY`；
2. 首个真实周期 receipt 链落证 → 该来源/形状升级 `API_VERIFIED`（以 receipt 为证）；
3. 累计 ≥5 个全覆盖真实交易日 + 断线/重启/重复恢复 + 0 订单 + 审计过 → 方可依机器评估 `E=PASS`；不足则 `PENDING_FORWARD_WINDOW/ACCUMULATING`（签批条款 5）。
