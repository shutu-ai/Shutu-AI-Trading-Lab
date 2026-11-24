# Shutu AI Trading Lab — M3 历史研究路线纠偏与双工作流治理任务书

**Task ID**：`M3-HISTORICAL-RESEARCH-ROADMAP-CORRECTION-20261124-R1`  
**日期**：2026-11-24  
**目标**：纠正“真实前向采集被持续推进，而真实历史数据研究长期停留在 BLOCKED_DATA”的执行路线偏移，形成可独立审批、可逐步落地的历史研究工作流；不破坏现有 M3/M3.5 工程证据。  
**本轮性质**：**DOCS / OFFLINE AUDIT ONLY**。只授权本任务的本地只读检查、治理文档新增和限定范围的追加式修订；**不授权**任何真实数据调用、数据购买、生产代码改造、M4 启动、Paper/Live 下单或远端推送。将本任务书保存在仓库中，并不自动构成执行授权；仅当操作者明确将本指令交给 Codex 执行时，才视为授权上述离线文档工作。

---

## 0. 不可违反的硬约束（P0）

1. 严格遵守仓库 `AGENTS.md` 与两份 v2.1 计划；它们仍是**权威基线**，本轮不得另建冲突的“v3 总规划”，不得篡改已有阶段签批、阈值、协议、日志或历史验收结论。
2. **绝对不调用 Alpaca 或其他行情、券商 API**：无 `collect`、`--complete`、历史 bar 下载、websocket、Paper/Live 订单、网络探测；不调用付费供应商、不开通订阅。`REAL_API_CALLS=0`，`BROKER_ORDERS=0`。本轮以仓库已有文件和本地离线事实为据，不把供应商文档声明冒充实际权限验证。
3. 不接触、不打开、不打印、不复制任何 `private/`、`.env`、`*credentials*`、API Key/Secret 等内容。`git status` 若暴露疑似凭证文件，仅记录**脱敏风险提示**，不要 cat/grep 其正文，不要自动删除/移动/提交。不得使用 `git add -A`。
4. 保持 `M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 的既有历史裁决；M3 本次只能补齐真实历史研究**路线与准入计划**，不能追认真实 Alpha 支持。
5. 保持 `M3.5_GATE=USER_PENDING`、`REAL_FORWARD_DAYS=1`（除非有新的、独立合法证据，**本轮不得更新**）、`E=PENDING_FORWARD_WINDOW`、`S=INCONCLUSIVE`、`R=NOT_STARTED`、`M4=NOT_STARTED`、`PAPER_WRITE=NOT_AUTHORIZED`；不得修改冻结的 S8 协议、代码身份、回执、journal、anchor、真实本机状态目录或历史 Holdout。
6. T9.9 已有真实只读成功采集，仅限 SPY/QQQ、IEX 1Day、2026-11-23 ET：可将其作为**工程数据路径实证**，不得据此断言 Alpaca 历史接口、全市场完整性、历史 PIT/退市覆盖、策略有效性已通过。
7. 不静默改动原有 M3/M3.5 测试，禁止重新初始化研究账本、重算覆盖已有证据的 hash、覆盖合成基线；不借“纠偏”删除安全门、绕过授权或提前开启 M4。
8. 如发现任务范围不够、基线冲突、私有证据缺失或关键结论不能验证：**标记 BLOCKED/UNVERIFIED 并停门，不得自行扩大授权**。

## 1. 执行前基线核对（必须先做）

- 核对本地 `HEAD`、`origin/main`（仅使用已有远端引用；本轮不必 `git fetch`）、工作区变更及未跟踪文件名；不要修改、读取或清理其他工作流正在使用的文件。
- 最近已知公开基线是 `999b9ba8a958cb2b668f5403320e9501ce838b84`（T9.9 文档提交，已推送）；这是**审查参考**，不是对当前 HEAD 的预先断言。如实际不同，应记录差异；冲突则停止写入。
- 阅读并交叉引用：
  - `AGENTS.md`
  - `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`
  - `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`
  - `artifacts/evidence/M1/data-vendors.md`、`docs/reviews/M1-engineering.md`、`docs/reviews/M1-strategy.md`
  - `docs/reviews/M3-engineering.md`、`docs/reviews/M3-strategy.md`、M3-R2 验收与相应受控证据
  - `Shutu_AI_Trading_Lab_M3_5_S8_ReadOnly_Data_and_Paper_Approval.md`
  - `docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md`
  - `configs/data_acceptance.yaml`、`configs/evaluation_protocol.yaml`、`docs/adr/ADR-003-data-contract.md`、`docs/adr/ADR-004-evaluation.md`（如存在）
  - `src/trading_lab/data/`、`src/trading_lab/backtest/`、`src/trading_lab/validation/`、`artifacts/poc/M-1/`（只读盘点，不将 POC 当正式数据源）
- 建立**证据定位表**：每项发现必须给出真实文件路径和章节/行号/测试名；缺少文件不得臆造。

## 2. T1 — 目标偏移根因复盘（先事实，后结论）

对照原始产品目标“AI 自动研究、严格验证、Champion–Challenger、Paper/Live 隔离”及 P0→P4 路线，输出以下矩阵：

| 能力 | 规划要求 | 已实现/实测 | 仅合成工程验证 | 数据阻塞或权限阻塞 | 下一行动 | 需谁审批 |
|---|---|---|---|---|---|---|
| 原始/复权历史数据 |  |  |  |  |  |  |
| 历史 PIT 可得性 |  |  |  |  |  |  |
| 历史证券池/退市 |  |  |  |  |  |  |
| 回测成交/成本模型 |  |  |  |  |  |  |
| Walk-Forward / OOS |  |  |  |  |  |  |
| 独立最终 Holdout |  |  |  |  |  |  |
| 真实前向 Shadow |  |  |  |  |  |  |
| AI 自动研究/策略对抗 |  |  |  |  |  |  |

必须明确回答：

1. M1 的 `BLOCKED_DATA` 是什么**具体用途**无法准入？是否被错误地当成“所有 SPY/QQQ 历史 ETF 研究都不能启动”？
2. M3 的 `CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 可以证明什么、**不能**证明什么？历史研究需要怎样的独立补充证明？
3. 为什么 M3.5 的真实前向工程在持续推进，但历史研究没有一个独立排期、数据供应授权申请和阻塞解除责任？
4. 哪些是实际设计缺陷、哪些是资源/许可证限制、哪些只是未执行的工作？不得把“未授权”描述成“技术不可行”。
5. 为什么不能仅通过改变 `S/E` 状态或将真实行情回填成“前向数据”来解决研究缺口？

输出结论必须有优先级 P0/P1/P2，不能泛泛建议“以后再研究”。

## 3. T2 — 历史数据用途分级和准入路线（本轮只评估，不联网）

分别设计**两种不同研究用途**，不能混为一个全局 PASS/BLOCKED：

### Scope H1：受限 ETF 历史研究试点（优先推进）

- 候选标的 SPY、QQQ；日线优先；候选研究区间 2017–2025，具体起止、可用数据、预热长度、交易日历必须在**未来数据实测与协议批准后**冻结。
- 评估 Alpaca 现有账户的历史数据能力和可用 `feed` 选项，但**本轮只能引用仓库已有文档证据**；区分 `DOCUMENTED`、`API_VERIFIED(仅明确实测端点)`、`UNVERIFIED`、`BLOCKED_ACCESS`。
- 不得将 T9.9 `GET /v2/stocks/{symbol}/bars` 对 **2026-11-23 当日 IEX 单周期**的成功，自动升级为跨年历史 SIP/IEX、复权或数据许可验证。
- 明确 IEX 单交易所数据与 SIP 全市场汇总数据的差异，不得将二者混算；评估与买入持有基准比较的可比性、缺失/调整/分红风险。
- 设计 `available_at` / `knowledge_cutoff`、原始与调整数据、企业行为的 PIT 限制；不能证明过去决策时点可得的因子/公告/修正数据，必须拒绝或降级推断等级。
- H1 可以申请 `RESTRICT_SCOPE` 或试点级 `ACCEPT`，**仅当相应研究用途的质量门、许可、PIT/执行时点规则均实证满足**；缺条件时标 `BLOCKED_DATA/UNVERIFIED`。即使通过，也不代表全市场选股能力已解锁。

### Scope H2：全市场 / 历史指数成分 / 退市 / 横截面策略研究

- 仍以 M1 缺口为基线：历史指数成员、退市证券/更名映射、企业行为、PIT、数据用途许可。
- 对现有供应商候选列出 `已知事实 / 缺少的原始证据 / 预计必须的人类动作 / 是否可能付费 / 风险`，不得猜测可免费得到真实历史成分数据。
- H2 **继续 BLOCKED_DATA**，除非以后有独立授权和实证，不因 H1 成功、M3.5 前向成功或编写本任务书而放行。

### 共同的可执行产出

提供**最小只读真实历史数据试点（未来申请）**的正式授权草案，至少写明：账户/用途授权核对、最多 2 标的、日线、查询日期范围、允许的具体 endpoint/feed、数据出口隔离、个人研究许可、预计请求数及上限、0 美元付费预算、禁止权限提升、凭证处理、质量退出条件、不可入前向账本、证据脱敏、失败即停止。**这只是申请，禁止执行 API。**

## 4. T3 — 双工作流执行路线（在原 v2.1 上追加，不改写旧事实）

建立清晰的两条独立工作流：

**A. M3.5 Forward Engineering（现有路线）**
- 使用已冻结 S8 协议及既有每周期单独授权规则；后续仍需真实自然积累交易日、真实发生的恢复事件与全审计；禁止以历史回填、模拟事件或设计文档代替。
- 本轮不启用新自动调度、不批准未来周期，不执行 `collect --once` 或 `collect --complete`，不更改 `REAL_FORWARD_DAYS`。

**B. M3-H Historical Research Readiness → Restricted ETF Historical Study（新增独立补充工作流）**
- **H0（本轮）**：数据用途矩阵、现有能力盘点、阻塞清单、试点授权草案；只做离线文档与治理。
- **H1（待独立批准）**：限定只读 API 获取最小真实历史 SPY/QQQ 数据，持久化供应商原始事实与数据/许可/质量证明；不得写入真实前向账本。
- **H2（待独立批准）**：在获准 H1 数据上复用 M3 的单一正式回测引擎，进行 B0/B1/B2、成本 ×1/×2/×3、滚动 OOS 和基准比较；不声称已有 Alpha。
- **H3（待独立批准）**：若 H2 合格，提出 M4 AI 自动研究开工申请；M4 必须另行审批，不以历史试点通过推导已授权。

对每一级写出 **进入条件 / 输出工件 / 验收判据 / 失败回退 / 明确禁止事项 / 人类批准节点 / 下一个任务 ID**。并说明现有 M-1～M11 主干保持不变，新增工作流只是对 M3 真实数据研究范围的补证，不重新开关已关闭的 M3 合成工程门。

## 5. T4 — 数据、样本与证据隔离设计

必须以明确契约解释和图示说明：

1. 历史批量导入存放在独立 `historical_research` 数据集/命名空间；实时 `s8-real-pilot` 状态目录、Journal、Receipts、Anchors 保持不动。
2. 同一标的同一日的价格可能同时出现在历史、前向、未来 Holdout：要有按日期/资产/事件关联的重叠披露，不能冒充独立证据、不能重复计入样本。
3. 历史数据在今天下载的 `received_at` 不等于历史真实 `available_at`；披露历史回溯 PIT 不确定性，禁止伪造事件可得时间。
4. 后续 H1/H2 新协议及数据快照 hash 独立版本化；不可修改已封存 M3 合成实验账本、M3.5 前向协议和未来 M9 Holdout 定义。
5. 数据层依赖、研究沙箱、OMS/Risk、Paper/Live 和凭证隔离全部维持；历史研究执行不能获得券商写能力。
6. 如果使用现有 `artifacts/poc/M-1/` 的样本，仅能作为 POC 参考，不能作为未经准入的正式研究证据。

## 6. T5 — 变更现有计划与阻塞治理（只允许追加式文档改动）

- 向 `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md` **附加带日期的“历史研究并行补证治理附录”**，只写**执行顺序/准入分叉/阶段门/阻塞治理**；保留 M-1～M11 原表、E/S/R 三轨、M9 最终 Holdout 和全部原始阈值不变。
- 在 `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md` 加最小日期化交叉引用说明（如审计证实必要），**不重写架构主干**。
- 建立 `BLOCKED_DATA` 专项“开放问题登记表”：每个阻塞项都要有 `scope/use_case, evidence, owner_role, blocker, impact, permitted_next_action, authorization_needed, objective_unblock_condition, review_trigger, status`。明确“记录阻塞”不等于“解决阻塞”，须能持续跟踪至真实研究解锁。
- 增加面向下一次阶段验收的 **Goal Alignment Check（目标对齐检查）**：必须报告核心业务目标能力的进展或偏离，但**不是 E/S/R 外的第四种准入状态**。不能以测试计数、CI 绿替代真实研究能力。
- 保留 T9.9 报告中当时 `PUSH=NOT_AUTHORIZED` 的历史语境；已推送是后来的事实，不得改写旧段落来伪造当时授权。若需说明，仅在新审计报告中引用 Git 事实。

## 7. 必须形成的文件

**新增**（若路径已有文件，先检查并保留原文，避免覆盖）：

1. `docs/reviews/M3-historical-research-gap-audit-20261124.md`：事实差距、根因、证据定位、P0/P1/P2、现状断言矩阵。
2. `docs/plans/M3-historical-research-workstream-20261124.md`：H0→H3 具体任务、双工作流依赖、用途准入与样本隔离设计、验收门和回退。
3. `docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md`：**未签署/未授权**的只读历史数据 H1 申请草案（明确 `AUTHORIZATION_PENDING`）。
4. `docs/reviews/M3-historical-data-blocker-register-20261124.md`：按用途追踪的开放问题登记表，禁止空泛的“等数据”。

**修订**：上述两份 v2.1 计划仅允许最小日期化追加，不删、不静默改写旧文、不建立不一致的独立权威来源。涉及超出追加式文档的变更，列为待审批提案，不得实施。

## 8. 本轮验收（硬门，必须逐项留证）

- [ ] 已核对当前 HEAD、脏工作区、保护其他未跟踪文件，记录真实基线；没有打开私有凭证或覆盖证据。
- [ ] 所有结论都有仓库文件/行号/事实支撑；清楚区分规划、合成实测、真实 API 实测和未验证事项。
- [ ] 已列出 H1/H2 两个独立用途；**H1 没有被错误地强行继承 H2 的全市场数据缺口**；也没有在无凭证实测/许可验证时伪造 H1 的 `ACCEPT`。
- [ ] M3 历史回测工程存在，但真实历史策略研究仍无已证明的统计优势；E/S/R 状态与 `BLOCKED_DATA` 不被擅自升级。
- [ ] M3.5 的现有 S8 协议、真实状态目录、回执、journal、anchor、历史测试证据零修改；前向天数仍依事实为 1。
- [ ] 两工作流各自有授权门、可执行后续任务、验收判据和失败/阻塞路径；H1/H2 完全不构成 M4/Paper/Live 授权。
- [ ] 历史研究与前向 cohort 的 PIT、重叠样本、最终 Holdout 污染风险明确并有机器可验收的后续测试清单。
- [ ] 做到 append-only：两份 v2.1 原有章节和关键门槛不被删除、弱化、改写。
- [ ] `git diff --check` 通过；若可离线安全运行，执行 `scripts/check_architecture.py`、`scripts/verify_live_blocked.py`、`scripts/scan_secrets.py` 等既有**非网络、不会改写受保护证据**的静态门；不适用则明确 `NOT_RUN` 原因。
- [ ] 不执行联网、数据采集、写券商、付费操作，不改变所有权限状态；`REAL_API_CALLS=0` / `BROKER_ORDERS=0` / `M4_NOT_STARTED`。
- [ ] 输出一页以内 **Operator Decision Card**：下一轮只需要审批什么、预期费用与额度、成功/失败判据、怎样保证不污染 M3.5。

## 9. 提交与停止

- 只将本任务明确新增/追加的文档**逐个显式指定**加入暂存区，不得 `git add -A`；不得提交本任务之外的旧日志、私有文件、凭证、运行态或其他未跟踪内容。
- 在通过相关文档与静态门后，允许 **一次本地 docs-only commit**（例如 `docs(M3-H): correct historical-research execution roadmap`）；若检查不通过，保留未提交的安全工作和问题报告，不制造 PASS。
- **禁止 push**、创建 PR、重写历史、改 main 的真实运行时配置；不启动后续 H1、H2、H3，也不执行下一次真实前向窗口。
- 最终按下列字段原样汇报（不能预填 PASS）：

```text
TASK_ID=M3-HISTORICAL-RESEARCH-ROADMAP-CORRECTION-20261124-R1
BASELINE_HEAD=<实际值>
WORKTREE_PROTECTION=<实际情况>
DOCS_CHANGED=<具体文件>
LOCAL_COMMIT=<SHA 或 NOT_COMMITTED>
REMOTE_PUSH=NOT_AUTHORIZED
H0_READINESS=<READY_FOR_OPERATOR_REVIEW | BLOCKED | FAIL>
H1_REAL_HISTORY_API=NOT_AUTHORIZED
H2_REAL_BACKTEST=NOT_AUTHORIZED
H3_M4_RESEARCH=NOT_AUTHORIZED
M3_GATE=CLOSED_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)
M3.5_GATE=USER_PENDING
REAL_FORWARD_DAYS=1  # 仅引用已有 T9.9 事实，不能凭本轮升级
FULL_MARKET_HISTORY=BLOCKED_DATA
PAPER_WRITE=NOT_AUTHORIZED
LIVE=PROHIBITED
REAL_API_CALLS=0
BROKER_ORDERS=0
NEXT_HUMAN_DECISION=<是否批准 H1 最小真实历史数据只读试点；不是默认批准>
```

**STOP**：完成 H0 离线审计、规划修订与授权草案后停在人工阶段门。用户批准 H1 之前，任何 Agent 都不得开始历史数据 API 请求。此任务的目标是让“真实历史研究”恢复为受治理、可执行的重点工作流，而不是再次制造一套只有工程 PASS、没有真实研究结果的流程。
