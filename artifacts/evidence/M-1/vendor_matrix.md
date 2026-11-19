# M-1 数据供应商可行性矩阵（七字段）

> 架构 §4.1 要求 M-1 做可行性盘点（M1 完成实测，M3 冻结研究适用范围）。
> 检索日期：2026-11-19。标注 UNVERIFIED 的项在 M1 必须实测/以官方订购页核实。
> 判定动词沿用基线：`REJECT_UNIVERSE / RESTRICT_SCOPE / REJECT_DATASET / BLOCKED_DATA`。

| 供应商 | 历史成分 | 退市与符号映射 | 企业行为 | 点时刻可得性(PIT) | 许可与用途 | 成本（2026-11-19 检索） | 覆盖 |
|---|---|---|---|---|---|---|---|
| **Alpaca Market Data (Basic, $0)** | 无历史指数成分产品 → `RESTRICT_SCOPE` | 无退市研究产品；仅当前可交易标的 | 有公司行为 CA API（拆股/分红/代码变更） | 实时仅 IEX（非全市场）；SIP 延迟 15 分钟；历史 bar 无发布时点保证 | 账户附带授权，允许交易与研究用途；再分发受限 | $0 | 美股全标的 bar/quote（历史深度见官方文档，M1 实测） |
| **Alpaca Algo Trader Plus** | 同上（无成分） | 同上 | 同上 | 全 SIP 实时 | 同上 | $99/月 | 同上 + 实时 SIP |
| **Yahoo Finance via yfinance** | 无 → `RESTRICT_SCOPE` | 退市标的不可靠获取（幸存者偏差风险高）→ `RESTRICT_SCOPE` | 有拆股/分红字段（adjclose 隐式复权，不可重算口径）→ `REJECT_DATASET` 风险 | 无发布时点；日线时间戳=交易时段，无 available_at → 禁用于事件类特征 | 非官方 API，ToS 禁再分发/商用 → 仅本地 POC | $0 | 全球日线+分钟线（5m 限最近 60 日，已实测） |
| **Polygon.io / Massive** | 无指数成分（S&P 授权另议） | tickers 端点含退市标志（M1 实测确认深度）→ 待定 | 有 splits/dividends 端点 | 全量历史 bar/quote/trade 带时间戳（SIP 级）；发布时点=成交/报价时间本身 | 允许内部研究与展示；再分发受限（以 EULA 为准，M1 核实） | Basic $0（EOD，5 req/min）；Starter $29/月；Developer $79/月；Advanced $199/月 | 美股全市场，历史深度大（~2015+ 全量，M1 实测） |
| **Sharadar (Nasdaq Data Link)** | **有**：S&P 500 历史成分含生效日期、季度快照、增删记录 | **有**：10,000+ 退市公司（含映射） | 有（Equity Prices 含 corporate actions） | 按日发布，无盘中事件时点（EOD 定位） | 订阅许可，允许研究/内部展示；再分发受限 | 订阅制（现价未核实，UNVERIFIED；历史参考 $35–75/月，个人 vs 商用不同） | 美股全历史（fundamentals 回溯至 1998） |
| **Databento** | 无现成指数成分产品（需 S&P/Nasdaq 授权数据集） | 有（符号映射 dataset 内含退市合约） | 有（raw feed 内含 MBO/CA 通道） | **最强**：逐笔原始时间戳，发布时点=事件时间 | 数据集 EULA，按用途授权（M1 核实研究用途条款） | 按用量计费（具体单价 UNVERIFIED） | 美股全市场 tick 级 |
| **qlib 公开样本数据** | 无（固定快照样本） | 无（样本集不含退市） | 不可重算（预生成二进制） | 无 available_at → 只能做管道测试，禁用于 Alpha 研究 | MIT 仓库附带；数据集条款单独核实 | $0 | CN 样本为主，US 样本有限 |

## POC 实测事实（本项目真实运行，见 data_poc_run.log）

- Yahoo 经代理实测可用：SPY/QQQ 日线 2 年（501 行/标的）、SPY 5 分钟 60 日（4,661 行）。
- 日线时间戳带 America/New_York 时区（2026-11 为 EST -05:00，DST 正确）。
- raw vs adjusted 差异行 457/501（SPY）→ 复权口径可见、公司行为被反映，但**不可重算**（yfinance 不提供因子序列）→ 按 §4.1 属 `REJECT_DATASET` 级别约束，仅限工程管道 POC。

## M1 实测优先级建议

1. Sharadar（成分+退市唯一可行解，解决幸存者偏差）
2. Alpaca Basic（交易闭环的实时工程验证，零成本）
3. Polygon/Massive Developer 档（历史 bar 深度与企业行为可重算性）
4. Databento（仅当需要逐笔事件时点研究时）
