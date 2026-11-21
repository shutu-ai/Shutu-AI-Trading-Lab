# Shutu AI Trading Lab — M2 最终人工阶段门收口与 M3 受控启动任务书

> **Task ID**：`M2-FINAL-GATE-AND-M3-GATED-20261121-001`  
> **日期**：2026-11-21  
> **仓库**：`shutu-ai/Shutu-AI-Trading-Lab`  
> **远端 main 基线**：`1988cab264e6f76ee280eb245e3ce16378be9ba2`  
> **最终 A7 已验证代码 SHA**：`379bd72b19a6ee416e48444c4e4bab6e1eb8f120`  
> **CI**：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44912904901 （Ubuntu + Windows SUCCESS；各 347 passed）  
> **唯一权威**：`AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`。若本任务与以上文件冲突，必须报告并停止，不得自行放宽约束。

## 0. 授权边界：本轮只允许 A 阶段

**本文件同时列出 A（M2 人工关闭准备）与 B（未来的 M3）两个阶段，但当前用户仅要求检查验收并生成下一任务指令，不构成 M2 关闭或 M3 开工授权。**

- **当前允许运行**：A0–A3 的证据核对、文档补遗和关闭审批材料准备。生成本地提交可行，但未经单独授权不 push。
- **A 阶段必须 STOP** 于 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`，除非能够核对用户之后明确发出的 M2 关闭指令；绝不替用户代签。
- **B 阶段必须同时具备用户两条独立的明确授权**：`M2_GATE=CLOSED` 与 `M3_START=APPROVED`。用户批准 M2 关闭不等于批准 M3；阅读本文件不等于批准任何阶段。
- 禁止真实 Broker 网络调用、Alpaca Paper/Live 密钥、真实行情/供应商访问、购买服务、真实订单、实盘资金、M9 Holdout 解封。M3 仅合成数据 + 离线研究工程，不包括 M3.5 Shadow/Paper 或 M4 AI Research Factory。
- 始终保持 `BLOCKED_DATA(全市场研究)`、`U-1=UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=N_A/NOT_EVALUATED`、`R=NOT_STARTED`；本任务不授权处理 U-1 或任何上游供应商事务。

---

# A 阶段 — M2 关闭审批材料准备（本轮可执行；完成后停止）

## A0. 远端与本地基线审计

1. 阅读两份 v2.1 计划、AGENTS.md、M2 三轨报告、`docs/reviews/M2-a7-independent-closure.md`、A5/A6/A7 的审查记录、`artifacts/evidence/M2/`。
2. 记录 `git status --short`、`git rev-parse HEAD`、`git rev-parse origin/main`、所有本地额外提交或改动。保留任何未知工作，不执行 reset --hard、force push、rebase 改写旧证据。
3. 从远端核对 `1988cab` → parent `379bd72`；`379bd72` CI Run `44912904901` 的两个系统通过，区分“运行 SHA”与“docs-only 后记 SHA”。
4. 审计 A7 5 轮 crash、A7-T2 的无条件 OMS 阻断，以及 A6 Barrier(2) 两进程 50 轮；缺证不得合并称通过。
5. 核对实际 pytest 分母：A5 338 → A6 +2 = 340 → A7 +7 = 347；本地故障矩阵为独立的 1,080 注入实例，不能与 pytest 用例数混算。

## A1. M2 最终技术裁决范围

整理最终 `docs/reviews/M2-final-gate-recommendation.md`（**仅建议，不是批准记录**），清楚声明：

- `E=PASS_WITH_SCOPE(MOCK_ONLY)`，仅 Mock 本地安全工程验证；`S=N_A/evidence_state=NOT_EVALUATED/R=NOT_STARTED`。
- 具备的证明：journal-before-send、单次 claim、线程与进程竞争、本地 fencing、UNKNOWN 不盲重发、恢复前对账与人工解锁、KillSwitch 自动持久 HALT、Risk 与 OMS 双层防线、Mock 安全约束。
- 未具备的证明：真实 Broker 幂等/撤单/查单可见性、真实账户与持仓现金对账、跨宿主故障一致性、真实市场数据适用性/策略收益。保留 `BROKER_BEHAVIOR_UNVERIFIED`、`BLOCKED_DATA`、`U-1=UNRESOLVED`。
- 准确区分：A7-T1 有条件 OMS 提交 vs A7-T2 无条件 OMS 拒绝；A7-T1 未独立证明第二次 claim 和第三个 KillSwitch 实例；历史 A2/A5/A6 日志曾被重生成；manifest 非全库完整性证明。
- 报告残余风险、后续责任阶段和是否阻断 M3 **合成数据离线工程**。这三项外部依赖不应阻断 M3 的 SYNTHETIC_ENGINEERING_ONLY 模式，但继续阻断真实全市场研究与实盘。

## A2. 审批包与不可伪造阶段门

- 只创建“待审批”记录，建议路径 `docs/reviews/M2-gate-decision-packet.md`，含：仓库及 SHA、CI URL、测试分母、主要 E/S/R 字段、剩余限制、审计说明、待用户审批原文。
- 不填 `approver=USER`，不伪造签批时间，不写 `M2_GATE=CLOSED` 为既成事实。不根据 CI 自动转换阶段门。
- 建议供用户选择的独立审批语句（此处只是候选文字，并非授权）：
  - `我批准 M2_GATE=CLOSED，范围 E=PASS_WITH_SCOPE(MOCK_ONLY)，保留 BLOCKED_DATA、U-1 UNRESOLVED、BROKER_BEHAVIOR_UNVERIFIED、S=N_A、R=NOT_STARTED；不授权 M3 启动和任何真实券商交易。`
- 仅当收到用户真正发送的相同含义审批后，才可在新的授权任务中写入已签批事实，附实际来源、时间、审批范围；如果审批事实不可核验，始终保持 USER_PENDING。

## A3. 验证、交付与强制 STOP

- 文档变更优先；如无实证安全缺陷，不再修改 OMS/risk/brokers 测试或运行时代码，不新增 A8。
- 需要的本地检查：`python -m pytest -q`、`python scripts/check_environment.py`、`python scripts/check_architecture.py`、`python scripts/scan_secrets.py`、`python scripts/verify_live_blocked.py`、`python scripts/smoke_mock.py`、`git diff --check`；重跑 1,080 矩阵沿用仓库既有入口，保存真实 EXIT 及运行环境。不声称执行没有做过的检查。
- 输出：`docs/reviews/M2-final-gate-recommendation.md`、`docs/reviews/M2-gate-decision-packet.md`、`artifacts/evidence/M2/final-gate/verification.md`（含证据索引、异常、SHA/CI对应关系与诚实范围）及简短架构健康补遗。
- 不覆盖既有原始日志；不回写历史结果以粉饰。报告所有变化和本地 commit；未经用户另行授权绝不 push。
- **完成即停止**，最终状态必须为：`M2_FINAL_GATE_RECOMMENDED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING / E=PASS_WITH_SCOPE(MOCK_ONLY)`。

---

# B 阶段 — M3 透明规则基线、现实回测与冻结研究协议（只能在双授权后启动）

> M3 工程不是实盘交易策略验证；范围严格 `SYNTHETIC_ENGINEERING_ONLY`。本节是未来可执行任务，不得在本轮 A 结束后自动继续。

## B0. 双授权与预检硬门

需要同时获得来自用户的两个**独立**审批事实，并可核验审批来源：

1. `M2_GATE=CLOSED`，明确仅 `E=PASS_WITH_SCOPE(MOCK_ONLY)`；
2. `M3_START=APPROVED`，明确范围只限合成数据、离线回测与研究协议工程。

缺任一：停止，不建 M3 代码、不生成“伪批准”签批记录、不假设已经授权。获得授权后检查本地/远端 SHA、工作树、现有契约与约定数据状态，先输出 M3-T0 实施方案和最小改动集。

## B1. 先冻结协议，后做研究实验

交付 `configs/evaluation_protocol.yaml` 和 `docs/adr/ADR-004-evaluation.md`：

- `protocol_id/protocol_hash`、canonical serialization、代码及数据 hash、seed、计算环境、日期与 UTC 可得时间、可重复性数值容差；协议变更形成新版本与新 hash。
- Train/Validation/历史 Walk-Forward OOS/Sealed Final Holdout/未来前向 cohort 独立角色；Purge/Embargo、重叠事件披露、信息可得时点；最终 Holdout M9 前不得解封。
- 预注册指标、效果阈值、样本量、费用假设 ×1/×2/×3、假设数/搜索次数/验证查询预算，AI vs 规则等试验预算与等经济预算；失败、被拒与人工试探计入。
- M9 一次性最终测试的唯一候选**选择规则**、`PASS/FAILED/INCONCLUSIVE/INVALIDATED` 机器判定、一次解封后污染；实际 `strategy_hash`/build hash 待 M8 结束、M9 解封前冻结，M3 不提前指定未来获胜策略。
- 若没有可辩护的统计门槛，应 `PROTOCOL_INCOMPLETE/INCONCLUSIVE`，不得伪造显著性或为了通过回测而事后调低标准。

## B2. 最小架构：复用优先

建议目录（按现有库结构调整，不要创建空壳）：

```text
src/trading_lab/backtest/
src/trading_lab/validation/
configs/evaluation_protocol.yaml
docs/adr/ADR-004-evaluation.md
tests/backtest/
tests/validation/
artifacts/evidence/M3/
docs/reviews/M3-engineering.md
docs/reviews/M3-strategy.md
docs/reviews/M3-real-capital.md
```

复用已有 `contracts` 数据类、M1 的 PIT/membership/actions/calendar/snapshot、`security.canonical` 等；只扩展已有架构检查器。禁止 backtest/validation 导入 OMS/risk/brokers 执行出口、网络 SDK、真实凭证；不新建第二套订单状态机/Schema Gate/消息队列或无消费者适配层。

## B3. 纯离线、可重放的现实回测内核

- 合成股票与宽基 ETF 测试数据；Decimal 现金与数量守恒、股票拆分与分红、退市与 ticker 复用，清楚标识假设，不把合成回测当真实市场证据。
- 严格 point-in-time：`available_at <= decision_at`；当日收盘才产生的信号不能按此前同日收盘成交；企业行为与历史成分只在其当时可用之后生效。
- 成本/执行模型：成交延迟、bid-ask spread、滑点、费用、量能、部分/未成交、保守现金交收，费用 ×1/×2/×3；不调用 BrokerPort。
- 同协议 hash、数据 hash、代码 hash、seed → 同样结果 hash（或事先声明的可接受数值容差）；随机性均由可注入 seed 控制。
- 合成负例必须覆盖：未来特征、错时钟、未来调整因子、退市漏算、交易成本变化、现金不足、重复事件与不可能的成交价。

## B4. 正确实现 B0–B8 范围

- 只**实现并运行**：`B0` 现金/合成现金收益；`B1` 宽基 ETF 买入持有（分红、费用、PIT）；`B2` 透明的单规则策略（只在 Train/Validation 选择并锁版本）。
- 只**冻结定义和预算**：`B3` Regime filter；`B4` 静态多策略；`B5` Regime routing；`B6` AI Champion–Challenger；`B7` 同规则预算的非 AI 对照；`B8` 简单再平衡/风险预算。
- 保证各臂相同数据快照、执行可得信息、成本、风险与评价口径；登记所有成功/失败/拒绝/重试及研究成本；不能只展示选中的最优结果。
- 本阶段不新增 Kelly、CVaR、风险平价、复杂 RL/大模型自主交易等完整策略引擎；这些可登记为未来研究候选，但不能抢跑 M3 所要求的透明对照基线。

## B5. Holdout 隔离与负例

- M3 真实最终 Holdout 未具合格数据时应 `SEALED_NOT_MATERIALIZED`；用独立**合成** fixture 验证角色拒绝、统计查询阻断、一次性解封、污染不可重用和 4 种终检状态。
- 历史 OOS、最终 Holdout 与前向队列须按时间/资产/事件记录 `cohort_overlap_report`，交叉信息或重复事件拒绝/降级独立性；Purge/Embargo 严格测试标签泄露。
- 研究预算超额、静默修改协议、删除失败试验、二次 Holdout 查询或解封、偷看未来数据均必须 fail-closed，并留下审计证据。

## B6. 验收与停止门

- 验收：新旧测试全量成功；M2 现有 347 项安全回归不减少、不跳过；1,080 故障矩阵保留；Ubuntu/Windows CI 在**新增 M3 代码 SHA** 上成功才可称远端验证。
- 检查：`check_environment`、`check_architecture`、`scan_secrets`、`verify_live_blocked`、`smoke_mock`、`git diff --check`；新增验证层负例与确定性测试必须有明确断言。
- 报告：`docs/reviews/M3-engineering.md`、`M3-strategy.md`、`M3-real-capital.md`；`artifacts/evidence/M3/` 内保留协议冻结、验证命令、失败负例、重叠披露、架构健康、实验注册记录。
- 允许的结论上限：`E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`、`S=N_A/INCONCLUSIVE` 且 `evidence_state=NOT_EVALUATED`、`R=NOT_STARTED`。绝不声称真实样本外 Alpha 支持。
- `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING` 后强制 STOP；不得在本任务中启动 Shadow、Alpaca Paper、M4 或任何 Live。

---

# 本轮可直接粘贴给 Codex 的短指令（只执行 A）

请阅读 `Shutu_AI_Trading_Lab_M2_Gate_Closure_and_M3_Gated_Codex_Task.md`、`AGENTS.md` 和两份 v2.1 权威计划。核实 A7 最新远端 main `1988cab`、CI 在 `379bd72`（Run 44912904901）双平台 347 passed 的事实，复核累计 M2 Mock 安全证据。仅执行 A0–A3：形成 M2 最终关闭建议与待签批决定包，纠正阶段证据描述的不一致，但不得覆盖历史记录。保留 `BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`，严格区分 M2 工程通过与 Broker/Live 未验证。完成后停在 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`；不得擅自代签关闭、不得自动 push、不得执行 B 阶段 M3。
