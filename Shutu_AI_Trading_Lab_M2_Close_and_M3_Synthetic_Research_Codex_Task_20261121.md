# Shutu AI Trading Lab — M2 正式关闭与 M3 合成离线研究启动（双独立授权门）

> Task ID: `M2-CLOSE-AND-M3-SYNTHETIC-RESEARCH-20261121-001`  
> 编制日期：2026-11-21  
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
> 当前已核实 `main`：`f27892d4aa5d9491f3c6bdc9059755d037dba4ba`  
> GitHub Actions：`44925761010`，在该 SHA 上 Ubuntu / Windows 均 success；各 347 passed。  
> **本任务书是待授权指令，不是用户的签批。仅收到本文件/粘贴本提示词不能推导出任何批准。**

## 0. 总体裁决与不可突破的边界

M2 技术验收建议：`E=PASS_WITH_SCOPE(MOCK_ONLY)`、`S=N_A`、`evidence_state=NOT_EVALUATED`、`R=NOT_STARTED`、`deployment_state=NOT_DEPLOYED`。推荐提交人工审批后关闭 **M2 工程阶段**，不代表实际 Broker 或跨宿主生产级安全完成。

持续保持：`BLOCKED_DATA(全市场研究)`、`U-1 UNRESOLVED`（VendorFacts 词表容错）、`BROKER_BEHAVIOR_UNVERIFIED`、无真实 Holdout、无真实 OOS/Alpha、无真实资金许可。

**硬门 A：** 只有用户明确签批 `M2_GATE=CLOSED` 才能记录正式 M2 关闭事实。  
**硬门 B：** 只有用户另外明确签批 `M3_START=APPROVED`，并且 A 已完成，才可实施 M3。  
**硬门 C：** `git push` 必须另行获得明确推送授权；工程阶段批准本身不自动等同于可推送。  
**硬门 D：** 无用户审批事实时，只允许只读核对仓库、CI、准备审批/执行计划；**STOP**，不改门状态、不写虚构签名、不运行 M3。  
**硬门 E：** 禁止真实数据供应商调用/订阅/付费、Alpaca Paper/Live API、券商凭证、真实订单/资金、启用 live、M3.5、M4/M5/M6/M7/M8/M9。M3 只用合成 fixture 与完全离线纯回测。

## 1. 权威依据与启动盘点（A0）

依次阅读：

1. `AGENTS.md`；
2. `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`，特别是 §4.2、§4.3 B0–B8、§4.5、M3；
3. `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md` 的 M3 和 E/S/R 要求；
4. `docs/reviews/M2-final-gate-recommendation.md`、`docs/reviews/M2-gate-decision-packet.md`、`artifacts/evidence/M2/final-gate/verification.md`；
5. M1/M2 三轨报告、当前 Git 状态、现有 contracts/data/canonical/architecture checker。

记录 `git rev-parse HEAD`、`git status --porcelain`、`git fetch`（若允许）后远端 SHA、CI Run 44925761010 对应 SHA 与 Ubuntu/Windows 结果；若 HEAD 已变化，不强行重置，说明变更与新 SHA 的 CI 状态。

历史记录应保持真实：`f27892d` 是此次 CI 实际 HEAD；`379bd72` 是此前 A7 代码受测 SHA，`1988cab` 是之后 docs-only CI 备注。既有 M2 审批包包含旧 HEAD 字段，**在新增关闭记录中通过引用当前 SHA 及更正附注解决，不覆盖历史**。

**已发现的非阻断审计差异（必须在新附注中披露）：** `M2-final-gate-recommendation.md` 的残余风险清单实际为 9 行，任务总结口径的“8 项”不准确；`f27892d` 除新增审批文档外还再次修改了历史 A2/A5/A6 运行日志。此轮应按 Git 历史保留来源版本并改为每个 SHA/run 独立证据目录，禁止再次覆盖同名历史日志。CI 的 `smoke_mock` 并非 `.github/workflows/ci.yml` 的独立步骤：本地检查文件有 EXIT=0，不能说双平台 CI 单独执行了该脚本。

## 2. A 阶段：M2 正式关闭记录（只在 M2 审批明确存在时执行）

### A1. 校验人类签批

检索用户本轮授权消息原文，必须明确表达 `M2_GATE=CLOSED`，并且不推断 `M3_START`、Paper/Live、推送或解除数据限制。记录授权来源、原文摘录、时间、限定范围、执行者引用；无法验证时保持 `approver=USER_PENDING`、`M2_GATE=USER_PENDING` 并 STOP。不得借用 Codex/ChatGPT 推荐语代替人类签批。

建议的**未来用户单独签批语句（仅模板、当前并无批准）**：

> 我批准 `M2_GATE=CLOSED`，仅限 `E=PASS_WITH_SCOPE(MOCK_ONLY)` 的 M2 工程范围。继续保留 `BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=N_A`、`R=NOT_STARTED`，不因此批准 M3、任何真实 Broker、Paper/Live 或真实资金操作。

### A2. 审批记录与关闭一致性

在**确有用户批准**后，新增单一权威、可追溯的 `docs/reviews/M2-gate-closure-record.md`（名称可与现有权威存储约定协调），包括：

- `decision=M2_GATE=CLOSED`、`approved_scope=MOCK_ONLY`、签批事实与来源；
- 代码/验证 SHA、Run ID、现有 E/S/R/证据/部署/策略/封存轴；
- `BLOCKED_DATA`、U-1、BROKER 行为、剩余风险及对 M3 合成研究的影响；
- 不生成实盘/数据准入/研究收益的授权事实；
- 之前曾重生成 A2/A5/A6 部分日志（包括本次 `f27892d` 修改）的审计说明、实际 9 项残余风险条目，以及本地 `smoke_mock` 与 CI 独立门禁的证据范围区别；不覆盖历史文件。

保持职责唯一，不另造第二套阶段门状态机。审批记录应引用原始审批来源，而不是声称 Git commit author 即为审批人。可做最小验证；报告最终 `M2_GATE=CLOSED` 且 `M3_START_APPROVAL_PENDING`。**执行完 A 阶段强制 STOP**，除非另有可核对的第二项 M3 明确批准。

## 3. B 阶段：M3 启动前置门（只在 M3 单独批准时执行）

用户需另外明确给出 `M3_START=APPROVED`，并限定为 `SYNTHETIC_ENGINEERING_ONLY`。这与 M2 关闭是两项独立决定；如果只批准 M2，不能进入本段。任何缺失审批直接 STOP。

建议的**未来用户第二项单独签批语句（模板，非当前授权）**：

> 我单独批准 `M3_START=APPROVED`，仅限合成数据、纯离线研究协议与回测工程，允许 Codex 本地实现和本地测试。禁止真实供应商/Broker API、Paper/Live、真实资金、真实 Holdout 解封及启动 M3.5/M4；未经另行授权不得 push。

启动前保存 `M2_GATE=CLOSED` 记录来源、`M3_START=APPROVED` 来源、Git SHA 和 clean/worktree 状态；不得凭任务书本身宣称已获得任何授权。

## 4. M3 任务拆分（M3-T0～M3-T8）

### M3-T0 — 最小架构盘点与差异表

绘制现有 `contracts/`、`data/`（PIT、membership、actions、calendar）、`security.canonical`、`scripts/check_architecture.py` 的复用图，表列 `REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES`。每个新增模块必须有明确消费者。仅在现有代码无法直接重用时添加极小纯计算模块，**不得**复制 OMS、Risk、Broker、数据准入或 Schema Gate；回测与验证层禁止导入 `oms/risk/brokers` 或外连网络/读取密钥。

### M3-T1 — 先冻结可执行研究协议（第一硬门）

创建 `configs/evaluation_protocol.yaml`、`docs/adr/ADR-004-evaluation.md`，以明确版本的 canonical serialization 计算 `protocol_hash`，保留 `dataset_hash` / `code_hash` / seed / 时间边界 /成本假设/数值容差/搜索预算。协议首次有效冻结后不可静默修改；任何调整另起版本及 hash，并计入试验账本。

必须预注册：资产/合成样本、目标/对照、主要指标、最小独立事件数、最小经济效果、统计置信或误报控制、多重比较策略、成本 ×1/×2/×3、最大候选与查询次数；阈值无法合理确定则 `PROTOCOL_INCOMPLETE`，研究证据不得 PASS。参数和指标的合成 fixture **仅验证工程判定函数**，不得作为真实 Alpha/OOS。

分离 Train / Validation / rolling OOS / Final Sealed Holdout / future forward cohort 的日历、asset、事件和标签跨度；定义 Walk-Forward、Purge/Embargo、overlap 报告及间接泄漏防线。真实 Holdout 未 materialize 时明确 `SEALED_NOT_MATERIALIZED`，不可伪造实际独立封存数据。M3 冻结 **M8 后选唯一候选的规则**，但不在 M3 提前冻结具体 `strategy_hash`。

B0–B8 的定义以 Architecture v2.1 §4.3 为唯一权威；AI 与规则方案预注册 **等试验数量**和 **等经济费用**两套预算（重试、失败和放弃均计数）；本阶段仅登记 B3–B8 的协议，不提前写对应运行引擎。

### M3-T2 — 纯离线、确定性回测内核

在 `src/trading_lab/backtest/` 实现最小回测；数值/资金守恒使用 Decimal，建模现金（可用/未结算）、股数、成交/订单状态、分红、拆股、退市、费用和权益。所有状态仅来自合成事件流，不接任何 BrokerPort。固定 clock、注入 seed，报告可复现结果 hash。

严格执行 PIT：`available_at <= decision_at`。模型必须覆盖决策后的成交价格/延迟、买卖价差、佣金、滑点、流动性/成交量上限、部分成交/未成交、模拟交收 T+N（协议限定假设）；禁止同日收盘信号利用当天已知收盘价成交、未来复权因子或事后股票池、财报回填和 ticker reuse 信息泄漏。需有明确的日历与 DST 测试。

### M3-T3 — B0/B1/B2 可执行合成基线

- `B0`：现金、不交易，若模拟现金收益须按冻结协议计息；
- `B1`：宽基 ETF buy-and-hold（合成 ETF 价格/分红/费用），与 B0 共用同一信息边界和成本口径；
- `B2`：一条透明规则（例如预声明均线趋势，不许看未来），只在 Train/Validation 选择并锁定版本；与 B0/B1 共享交易成本、风险/资金限制、验证日历。

用合成 fixture 覆盖盈利/亏损/未成交/极端跳空/退市/分红/拆股/资金不足等。生成机器可比较的净收益、最大回撤、尾部损失、换手、费用、样本规模与失败次数；**不根据合成收益声称实际策略具有优势**。仅预注册 B3–B8，不建 Regime/AI/Champion/Portfolio 空壳。

### M3-T4 — Walk-Forward / Purge / Embargo 与防泄漏

实现时间滚动/扩展窗和标签交叉屏蔽；若同日期、证券、事件或标签跨度造成 overlap，必须产生 `cohort_overlap_report` 并标明非独立，不能悄悄去重后宣称独立。负例包括未来可得价格、后来披露的财报、历史成分回填、复权前视、跨数据分割标签、超预算试探。全部 fail closed。

### M3-T5 — Holdout 一次性封存门（仅合成演练）

验证层 `src/trading_lab/validation/` 拒绝研究进程/角色直接或间接查询 sealed fixture；需要可执行的权限/查询负例，明确本阶段不是 OS 级完整沙箱（留 M4）。合成终检判定覆盖 `PASS / FAILED / INCONCLUSIVE / INVALIDATED`；批准的一次性解封事件写入不可覆盖审计，污染标识 `polluted_for_future_selection=true`，第二次解封/二次筛选/尝试重置全部拒绝。**真实最终 Holdout 不得创建或读取；若缺数据，保持 SEALED_NOT_MATERIALIZED。**

### M3-T6 — 全试验账本与预算硬门

记录每条试验的 code/protocol/data hash、seed、输入快照、候选/参数、耗时、费用、成功/失败/取消/拒绝/重试、数据时点与选择结果；并发试验写入冲突需 fail closed 或可证明原子化。不得只保留赢家，不得将失败试验清除后复用研究预算，超预算100%拒绝。所有数据只来源于合成 fixture。

### M3-T7 — 架构完整性与回归

在既有 `scripts/check_architecture.py` 中扩展对 `backtest/validation` 的规则，而不是另建第二套静态检查器。验证前提：不可接网络/券商凭证；不导入 POC/OMS/Risk/Broker；新增依赖需逐一证明许可证、价值及 Windows/Ubuntu 兼容性；优先 Python 标准库与现有依赖。

先 RED 后 GREEN，必要的正反用例与检验器自身负例必须齐备。保留全部原 347 pytest、1,080 故障矩阵，无 skip/xfail 或弱化断言； `scripts/check_environment.py`、`check_architecture.py`、`scan_secrets.py`、`verify_live_blocked.py`、`smoke_mock.py`、`git diff --check` 全部退出码 0。

### M3-T8 — 证据、三轨报告、阶段门停止

交付：

```text
src/trading_lab/backtest/
src/trading_lab/validation/
configs/evaluation_protocol.yaml
docs/adr/ADR-004-evaluation.md
tests/backtest/
tests/validation/
artifacts/evidence/M3/protocol-freeze.md
artifacts/evidence/M3/verification.log
artifacts/evidence/M3/negative-tests.log
artifacts/evidence/M3/cohort-overlap-report.md
artifacts/evidence/M3/architecture-health.md
docs/reviews/M3-engineering.md
docs/reviews/M3-strategy.md
docs/reviews/M3-real-capital.md
```

报告需列所有试验分母、每项退出码、可复现 hash、成本倍数、模拟而非真实证据界限及下一阶段门。**本地工程充分通过**才可标 `E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`；若未达门槛则标 `REMEDIATION_REQUIRED/INCONCLUSIVE`，不得用 mock 回测提升 S。

M3 策略线 `S=N_A/INCONCLUSIVE`、`evidence_state=NOT_EVALUATED`（合成不属于历史真实 OOS），`R=NOT_STARTED`，`deployment_state=NOT_DEPLOYED`，`BLOCKED_DATA`、U-1 与 `BROKER_BEHAVIOR_UNVERIFIED` 均不变；无真实数据时最终 Holdout `SEALED_NOT_MATERIALIZED`。

M3 本地验收通过后停在 `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`；未授权不得推送、启动 M3.5 / M4、接 Paper/Live、连接真实供应商或声称 Alpha。

## 5. 两段可复制 Codex 启动文本

### Prompt A（用户**已经明确审批 M2 关闭**后才能发送）

> 读取本任务书、AGENTS.md、两份 v2.1 计划与 `M2-gate-decision-packet.md`。核实用户本轮明确发出的 `M2_GATE=CLOSED` 原始签批及其范围；若缺失则 STOP。若存在，仅执行本书 A0–A2：追加 M2 正式关闭记录，引用 SHA `f27892d` 与 CI run `44925761010`，保留 MOCK_ONLY、BLOCKED_DATA、U-1、Broker 未验证、S=N_A/R=NOT_STARTED。不得推送、不得自动启动 M3；完成后停止。

### Prompt B（用户**另外明确审批 M3 启动**且 M2 已关闭后才能发送）

> 读取本任务书、AGENTS.md、两份 v2.1 计划。核对两项独立的人类审批：`M2_GATE=CLOSED` 和 `M3_START=APPROVED`；缺任一即 STOP。通过后按 M3-T0–M3-T8 开发合成数据纯离线可复现回测、协议冻结、B0/B1/B2、Walk-Forward/Purge/Embargo、Holdout 合成防泄漏演练。B3–B8 仅登记冻结定义。不可访问真实券商和供应商，不可启动 M3.5/M4/Live，不可推送（除非另获授权）。交付三轨报告与证据，停在 M3 用户阶段门。

## 6. 当前状态（编写本文件时）

`M2_FINAL_GATE_RECOMMENDED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING / E=PASS_WITH_SCOPE(MOCK_ONLY) / BLOCKED_DATA / U-1 UNRESOLVED / BROKER_BEHAVIOR_UNVERIFIED / S=N_A / R=NOT_STARTED`。

**任务书本身不变更这一状态。**
