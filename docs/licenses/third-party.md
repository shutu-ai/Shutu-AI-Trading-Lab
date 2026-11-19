# Third-Party License Ledger（唯一许可台账）

> M-1 阶段产出 · 2026-11-19。所有 SHA 为当日克隆/安装时锁定的上游 commit。
> 完整安装清单见 `artifacts/evidence/M-1/env/main_venv_pip_freeze.txt` 与各候选 `pip list` 日志。
> 规则（架构 §3）：锁定 commit/版本；审查 LICENSE/NOTICE；任何修改上游源码的行为需重新评估许可义务。

## 1. M-1 评估的候选仓库（克隆于 third_party/，未 fork、未修改）

| 仓库 | 锁定 SHA | 版本 | 许可证 | NOTICE | 用途评估结论 |
|---|---|---|---|---|---|
| microsoft/RD-Agent | `484776c211e4fbbeef03e0ec00d6bbee7362a4f4` | 见 eval.md | MIT | 未见 | 研究侧候选（LLM 循环 BLOCKED_ENV，详见 eval） |
| microsoft/qlib | `54355232463878d2eebb91fe0ee5fa7fa1f5976c` | 见 eval.md | MIT | 未见 | 研究数据/回测候选 |
| AI4Finance-Foundation/FinRL-Trading ("FinRL-X") | `4409abe925c904e570be78ebfb5e77ac3491dff8` | 见 eval.md | Apache-2.0 | 未见 | 交易侧候选（评估结论见 ADR-001） |
| alpacahq/alpaca-py | `f8fd9555ec182ccc0f8f6b5b819779fe7b2fb6d3` | 0.45.0 (PyPI) | Apache-2.0 | 未见 | **采用**：BrokerAdapter 基座 |
| nautechsystems/nautilus_trader | `8a4ac22fc08990a96c6e5750c76a3fa744f4d141` | 1.231.0 / 2.0.0rc9 | **LGPL-3.0** | 未见 | 不采用（ADR-001 §C） |

许可证义务要点：
- **MIT / Apache-2.0**：允许闭源商用集成，保留版权声明即可；Apache-2.0 另含专利授权与变更声明义务（NOTICE 传播）。
- **LGPL-3.0（nautilus_trader）**：pip 安装未修改使用 → 本项目代码无开源义务；一旦修改其源码，被修改部分须以 LGPL 发布。结论：不 fork、只通过上游 PR 反馈。因不采用，此义务当前不触发。

## 2. 本项目运行/POC 直接依赖（main venv，Python 3.13.15）

| 包 | 版本 | 许可证 | 角色 |
|---|---|---|---|
| alpaca-py | 0.45.0 | Apache-2.0 | 券商 SDK（评估目标） |
| pandas | 3.1.1 | BSD-3-Clause | 数据处理 |
| numpy | 2.5.5 | BSD-3-Clause | 数值计算 |
| pyarrow | 26.0.1 | Apache-2.0 | Parquet 存储 |
| yfinance | 1.8.0 | Apache-2.0 | Yahoo 行情客户端（POC 数据源） |
| pytest | 9.2.0 | MIT | 测试框架 |

（候选独立 venv 的完整依赖清单在各候选 `artifacts/evidence/M-1/candidates/*/logs/` 中。）

## 3. 数据源许可与使用约束（POC 层面）

| 数据源 | 许可/约束 | 本项目可用范围 |
|---|---|---|
| Yahoo Finance (via yfinance) | 非官方 API；Yahoo ToS 禁止再分发/商用转售；接口随时可能变动 | **仅限本地研究 POC**；不进入证据链作为长期数据源；M1 前需替换 |
| Alpaca Market Data Basic | $0；实时仅 IEX；SIP 延迟 15 分钟；200 请求/分钟；websocket 30 标的 | 工程验证可用；跨股票 Alpha 研究不足 |
| Alpaca Algo Trader Plus | $99/月，全 SIP 实时 | 需要实时 SIP 时评估（架构 §4.1） |
| Polygon.io（2026 年起品牌迁移为 Massive） | Basic $0（EOD、5 请求/分）；Starter $29/月；Developer $79/月（历史数据主力档）；Advanced $199/月（实时） | 候选（M1 实测） |
| Sharadar (via Nasdaq Data Link) | 含退市公司（10,000+）与 S&P 500 历史成分（含生效日期）；订阅制（价格未核实，历史参考 $35–75/月，须以订购页为准） | 历史成分/退市研究的主力候选（M1 实测） |
| qlib 公开样本数据 | Microsoft GitHub 发布，MIT 仓库附带；数据本身授权条款需单独核实；CN 样本为主、US 样本有限 | 仅 POC/测试 fixture |

## 4. 待办与义务

1. NOTICE 文件：各候选仓库未见独立 NOTICE；Apache-2.0 依赖（alpaca-py、pyarrow）在本项目分发时需保留版权与许可声明（当前仅内部使用，暂不分发）。
2. qlib 样本数据若进入 M3 研究，需补查数据集附带条款（区别于代码 MIT）。
3. Yahoo 数据不可进入任何对外发布物；M1 需以正式授权数据源替换（对应 `DataVendorAssessment` 契约）。
4. 本台账为唯一许可清单；后续阶段新增依赖必须更新此处（架构 §11.3）。
