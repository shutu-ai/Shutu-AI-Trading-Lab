# Shutu AI Trading Lab — M2 独立风控与 OMS 崩溃一致性 Codex 执行任务

> Task ID: **M2-OMS-RISK-ARCHITECTURE-GATE-001**  
> 版本：2026-11-20 / Candidate for user approval  
> 适用仓库：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> 唯一权威：`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`  
> 当前证据基线：M1 整改 `b8d0200c126d9e0c19f867f3a9126bddcaf9ac3d`；CI `44777967708` Ubuntu/Windows 均 SUCCESS、各 **233 passed**。用户另报告本地尚有仅补录 CI 结果的 `d0367f4` 未推送；**先用 Git 验证，不能凭本任务书假设其存在或内容**。

## 0. 人工授权及范围：先执行此门，再做任何开发

**本任务书的交付或阅读不构成启动授权。** 目前核实状态：

- `M1_REMEDIATION_VERIFIED`，但 `M1_GATE=USER_PENDING`，`M2_START_APPROVAL_PENDING`。
- M1 正式全市场策略研究、历史成分/退市、企业行为重算用途仍 **`BLOCKED_DATA`**；仅工程管道/合成数据用途可用。`S=N_A / NOT_EVALUATED`；`R=NOT_STARTED`。
- 用户需独立明确批准：**关闭 M1 工程门（`M1_ENGINEERING_CLOSED_WITH_DATA_BLOCK`），并授权 M2 在合成数据 + Fake Broker 范围内启动**。也可仅批准其中一项，绝不自动推导另一项。

**Codex 启动门：**
1. 先确认当前对话或项目审批记录中是否存在真实的用户 M1 关闭及 M2 启动明确授权。不能将 Agent 自述、CI 通过、某份任务书、commit message 当作审批。
2. 若任一授权缺失，**只允许只读检查**仓库和输出 `M2_NOT_AUTHORIZED / M1_GATE=USER_PENDING`，不得创建开发提交、修改阶段状态或执行 M2 任务。
3. 若已有明确授权，记录原话、日期、批准范围和证据位置，之后才能进行 M2-T0～T8。不得代用户签署结论。
4. 切实核对 `git status --short`、`git rev-parse HEAD`、`git log --oneline -8`、`git rev-list --left-right --count origin/main...HEAD` 和现有用户改动。尤其检查本地 `d0367f4` 是否存在，**保留、不覆盖、不重排**；发现冲突或陌生变更须暂停并报告。
5. 除非再次明确授权，**不得 push、force push、改写历史、创建 Release、连接任何券商、申请/读取任何交易凭证**。本地正常提交须遵守 Codex 环境已有授权策略。

### 绝对禁止

- 实际 Alpaca Paper/Live API 调用、创建券商订单、用真实账户/密钥、资金动作、接触 Live 交易出口。
- 将 M1 `BLOCKED_DATA` 改写为已准入，下载、购买、订阅或注册数据服务；使用 yfinance/qlib POC 冒充有 PIT/退市证据的研究数据。
- 开发策略收益、Alpha 回测、M3+ 功能；将 Fake Broker 结果宣称为真实券商保证。
- 引入 Kafka、Redis、分布式锁、消息总线、微服务、重复 OMS 或第二套 Risk Engine，除非有明确可复现的工程必要性且经独立审批。
- 伪造测试日志、重复使用旧 CI 作为当前 SHA 的通过证据、修改冻结阈值来获得 PASS。

## 1. 先读的权威材料与当前真实边界

逐项打开并引用代码和行号（不得只凭摘要）：

1. 两份 `docs/plans/*v2.1.md` 的 **M2**、跨阶段工程 E-Gate、UNKNOWN 盲重发和 fencing 增补。
2. `AGENTS.md`、`docs/adr/ADR-001-core-selection.md`、`ADR-002-isolation.md`、`ADR-003-data-contract.md`。
3. `docs/reviews/M-1-independent-review.md`、`docs/reviews/M0-independent-remediation.md`、`docs/reviews/M1-independent-remediation.md`、M1 三轨报告。
4. `src/trading_lab/contracts/`（§2.2 20 类既有契约）、`security/{schema_gate,verifier,kill_switch,audit,isolation,canonical}.py`、`data/{acceptance,snapshot}.py`、`configs/paper/`、`configs/live/`。
5. `artifacts/poc/M-1/fake_broker_poc/`：只作为实验参考，特别检查 `recover()`、`get_order=None`、`_send_once()` 和 fake `valid_fences`。**生产模块绝对不导入这里。**
6. `tests/`、`.github/workflows/ci.yml`、`scripts/check_architecture.py`，识别现有 233 个回归及检查器能力。

M-1 已采用 **方案 B：`alpaca-py + 自有最小 OMS`**，但 **本任务只实现可验证的本地 Fake Broker 接缝，不实例化或联系真实 Alpaca 客户端**。将真实 Alpaca 幂等、撤单、429/5xx、查单可见性标记 `BROKER_BEHAVIOR_UNVERIFIED`；未经单独凭证和 Paper 授权不得变为 `API_VERIFIED`。

## 2. 不变的目标架构与复杂度预算

### 唯一责任链

```text
研究进程／合成测试生产者（无券商写权限）
    -> 既有 SchemaGate（只接受可信 JSON/契约；来源身份由可信通道绑定）
    -> 唯一 Risk Engine（强制预算、PIT/环境/账户/签批条件）
    -> 唯一 OMS（持久订单意图 + 状态机 + UNKNOWN 对账 + 审计）
    -> 唯一可信 Broker Egress（M2 只接 Fake Broker）
    -> 本地 Fake Broker（可重复、故障注入、绝无外部网络）
```

- Risk 不得直接写 Broker；AI 不得直接写 Risk 运行状态/OMS/Broker；外部 AI JSON 不是交易授权。
- `contracts` 是唯一领域契约权威，`security.canonical` 是唯一字节规范；不得复制已冻结 DTO 或再造 Schema Gate、Kill Switch、签批服务、审计系统。
- Paper 与 Live 的**代码可复用，但运行实例、身份、数据状态、密钥、订单出口必须相互隔离**；本阶段只有 fake Paper dry run，Live 仅保留无法真实下单的测试模板。
- `artifacts/poc/` 只可供阅读/基线测试，不作为正式 import/运行依赖。M2 唯一正式 OMS 实现落在 `src/trading_lab/oms/`，不要将 POC 原封不动复制产生平行状态机。
- 先从单进程/单可信写出口开始。避免尚无消费者的抽象、厂商通用适配层、过度配置、插件系统、跨环境共用持久化。

### 必交的 Architecture Health 工件

`artifacts/evidence/M2/architecture-health.md` 必须记录 **REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES / DEBT** 八类，包含开发前后依赖图、每个新模块实际消费者、删除或不继承 POC 的理由、兼容层清单（理想为零）、测试迁移表、复杂度增加的必要性。**不可只写主观 PASS，必须附命令和真实结果。**

## 3. M2-T0 — 阶段盘点、契约冻结与先红后绿计划

1. 完成仓库/权限/审批检查；锁定当前 HEAD、测试数、现有 P0 骨架和 M1 数据状态。
2. 输出模块职责及允许依赖图、单写者边界、故障模型、数据/审计持久性假设；列出全部安全不变量及对应测试。
3. 在 `docs/adr/` 中增补最小 M2 ADR（如 `ADR-004-oms-risk.md`，先核验已有 ADR 编号，防止与计划给 M3 预留 `ADR-004-evaluation.md` 冲突；可用 `ADR-002-addendum-m2.md` 或其他**不冲突编号**，先记录选择依据）。
4. 写先红后绿测试矩阵，确保缺陷/新功能的 RED 真实失败可解释，不能把依赖缺失误当安全证明。
5. 冻结 M2 工程安全指标：**至少 1,000 次可复现的故障/重放组合**，累计：0 重复 fake-broker 创建订单、0 双主写、0 无持久意图发单、0 UNKNOWN 盲重发、0 风控越权/非法信号执行；失败实例及覆盖分母单独报告。

## 4. M2-T1 — 最小独立风控（`src/trading_lab/risk/`）

- 从 v2.1 §M2 和已有契约读取强制风险字段，不得简化：账户与环境绑定、资金/单笔/组合额度、风险预算、仓位、未结算现金、价格异常、允许证券池、订单新鲜度、数据/快照可得性、强制 Kill Switch、审计可用性、授权工件有效性。
- 用现有 M0 `SchemaGate` 接收**数据型信号**；信号 `ALLOW_*` **只代表准入，不代表可发单**。必须经独立风控作出 `APPROVE / REJECT / HALT_NEW_RISK`，记录结构化原因。
- 拒绝缺失/null/非有限/过期/错账户/错环境/错误策略或 build hash/未审核生产者/越预算/禁用证券/失效数据/未结算额度/非法价格；量化金额用 `Decimal`，不隐式接受 `float`。
- M1 全市场数据为 `BLOCKED_DATA`：只允许显式标记、不可用于生产研究证据的**synthetic-only engineering fixture** 输入；真实研究准入必须仍拒绝。不得通过 `engineering_mode=True` 一类易误用的生产开关绕过风控；测试身份/数据用途应独立标记并在真交易路径不可达。
- `producer_id` 的身份必须**由受信运行时/进程入口绑定**，不能仅由测试发来的文本自称。至少对 fake 进程边界做不可伪造的受信调用凭据或不可替换的内部对象绑定，核对配置中的 reviewed build hash；进程间生产保证若未实现，必须明确 `MOCK_ONLY/UNVERIFIED`，绝不能宣称完整生产隔离。
- 复用 Kill Switch，并明确 HALT/恢复责任；不得为 M2 重写一套 halt 状态。
- 产出有效/恶意/过期/跨环境/交叉账户/越预算/断开审计的正反测试。

## 5. M2-T2 — 唯一 OMS + 持久化意图/Outbox/账本

- 正式模块置于 `src/trading_lab/oms/`，以最少文件实现：**订单意图持久化、稳定 client_order_id、确定性状态机、唯一出站路径、账本恢复、对账**。`src/trading_lab/brokers/` 仅提供最小的 fake-only Broker Port 和适配器，禁止实际网络调用。
- **Journal-before-send**：任何下单、撤单和变更必须先持久化完整意图，包含账户、环境、策略/构建、风险许可、意图 ID、单调版本、幂等关联、时间与 Hash，写盘失败 = 零发送。可选最小 SQLite WAL FULL 或已验证的本地单进程持久化方案，必须记录选型、fsync/事务边界、crash consistency 证据；**不要为了持久化引入服务集群**。
- 明确订单状态如 NEW_INTENT、PERSISTED、SUBMITTING、ACKED、PARTIALLY_FILLED、FILLED、CANCEL_PENDING、CANCELLED、UNKNOWN、HALT_NEW_RISK、RECONCILED（名称可按既有契约调整）；非法转换必须拒绝并审计。
- 分离“本地从未真正发送的**可证明事实**”与“券商查单暂时不存在的**不确定事实**”：一旦请求可能越过出口边界，响应丢失、`get_order=None`、404/429、超时、5xx 或未知网络状态 **绝不能自动 `_send_once`、换 coid 重发、创建替代意图、清理 UNKNOWN**。状态保持 UNKNOWN/HALT_NEW_RISK，等待可靠对账/操作人解锁。
- 若要重试，必须具有 **可复现实证的未送达证明** 或（未来）**经实际券商验证的幂等保证**，默认没有该保证。FakeBroker mock 的 dedupe 不能成为真实 Alpaca 语义的证明。
- ACK/成交回报可能重复、延迟、乱序；成交累积不可双计；部分成交、撤单在途、取消失败、账户持仓/资金不一致时不得新增风险。
- 崩溃/重启恢复必须验证 AuditLog、Journal、Kill Switch、版本、状态，并执行真正的 fake Broker reconcile。审计或持久化不可用时明确 fail-closed；不能用内存缓存假装 durable。

## 6. M2-T3 — 单写者可信出口和 fencing

- 对同一 `(environment, account_id)` **只有一个可信 Broker 写出口**；**所有**下单/改单/撤单/恢复/Agent/MCP/运维脚本路径都必须走同一出口，不能用各自 SDK 绕过。
- 旧 executor 的内存锁不可靠。建立可重复验证的 lease/epoch/fencing：旧 token、租约过期、双实例并发、冻结进程恢复、出口不可用时全部拒绝。
- 核心保证发生在**可信本地出口**，不是 FakeBroker 专用 `valid_fences` 帮你模拟出的券商侧安全；下游 mock 不认识 epoch 也应由受信出口阻止陈旧写入。
- 对出口与持久化竞争（TOCTOU、提交顺序和单写者失效恢复）做负例。若不能证明“无旁路写者”，不得把 `SINGLE_WRITER_VERIFIED` 标为 PASS。
- 真实 Alpaca adapter、API key、Paper endpoint 连通性：**不在本次授权范围内**。保留 `BROKER_BEHAVIOR_UNVERIFIED`，标记需用户另行授权的 Paper 专项阶段。

## 7. M2-T4 — 故障注入与确定性验收

最少覆盖六大组，附每组尝试总数、通过数、种子、证据；总计 **≥1,000 次独立的重放/故障组合实例**，避免 1000 次纯相同空操作：

1. 请求发出后 ACK 丢失，broker 已接单；请求发出后 ACK 延迟或乱序返回。
2. `get_order` 返回暂时 `None`/404、429、5xx、超时；网络分区；恢复后迟到的订单出现。
3. Journal 提交前/后、出口发出前/后、ACK 落盘前/后各关键时点崩溃；进程重启与恢复重入。
4. 双进程/双 executor 争写、旧租约恢复、陈旧 epoch、重启期间旧写者存活。
5. 部分成交、重复成交回报、取消在途、取消请求回执丢失、迟到成交、成交/现金/持仓不一致。
6. 假签批、越风险额度、错误账户/环境、非法 JSON/命令注入、PIT 数据过期/不可得、Kill Switch 已激活、Audit/Journal I/O 故障。

**测试断言（覆盖已登记的所有相关路径）**：

- `fake_broker.created_orders_by_intent` 每个可确认订单意图最多 1 条有效提交（不得靠同一个 FakeBroker 内的强制去重掩盖 OMS 反复调用）；审计与出口尝试另计数。
- UNKNOWN 无确认时 **0 新风险、0 盲重发、0 替代意图**；记录 `UNKNOWN` / `HALT_NEW_RISK`，审计前置；状态恢复须对账后才解锁。
- stale writers **0 accepted broker writes**；无持久化意图的写 **0**；未授权策略代码/越权请求 **100% 拒绝**。
- 真实并发测试不能只用单线程交替模拟冒充多进程；如果环境限制无法进行必须 `BLOCKED_ENV` 并记录，对应能力不得 PASS。
- 对每次测试运行输出：git SHA、Python 版本、OS、随机种子、fault class、attempts、violations、mock broker submission/created 数、持久化证明、退出码和可复现脚本；运行失败也保留原日志。

## 8. M2-T5 — Architecture Integrity & Code Quality 硬门

**目标：M11 时是简洁、单一责任的系统，而不是 M-1～M11 代码层层叠加。**

### 开发前

- 列出现有 `contracts/security/data` 可复用接口，标注最终依赖方向与不能变化的安全不变量；对 FakeBroker POC 做 `REUSE-IDEA / REPLACE / DO-NOT-PROMOTE` 逐项决策。
- 先说明需新增的 OMS、risk、broker mock 各自消费者；若功能已有正式实现，默认复用或重构，而非新增同类模块。

### 开发中

- 一个状态机、一套 order intent ID 规则、一个 risk 决策点、一个 broker 写出口。拒绝重复审计器、重复签批器、重复 canonical serializer、重复 Schema Gate。
- 不添加死代码、未消费抽象、历史兼容层、第二份领域 DTO、隐式 fallback；已被替代的临时代码和导出必须合理移除或隔离，并迁移必要测试。**安全控制和测试不许削弱**。
- 不要求为降低 LOC 牺牲正确的 fsync/对账/fencing。复杂度必要时可以增加，但必须给出对应故障证据。

### 可机查的边界

- 将 `scripts/check_architecture.py` 最小扩展为 **有自测** 的全链边界规则，保留 M1 22 项检查器自测；至少证明 `data` 不依赖 `risk/oms/brokers/POC`，`risk` 不依赖真实 `brokers` 或 `oms` 写实现，研究进程不得直接依赖交易写能力，生产 `src` 不依赖 `artifacts/poc`。
- 检查是否存在重复出站调用点、额外凭证读取入口、反向导入、循环依赖、未授权网络连接、重复 DTO。静态检查不能发现的动态导入/外部脚本旁路必须结合运行边界负例和诚实说明。
- 依赖新增须说明作用、许可证、替代方案与 CI 负担；不因“流行”装大型架构 Skill 或套件。可以选择 Ruff/Import Linter，但若现有简洁检查器够用，优先复用和扩展。

### 工件与硬性状态

- `artifacts/evidence/M2/architecture-health.md`；无理由重复职责、未解释依赖、POC 正式依赖、交易边界旁路、检查器绿但负例漏检，**E-Gate 不得 PASS**。

## 9. M2-T6 — 上游 M1 数据风险登记，不准偷偷解封

M1 全市场研究准入 `BLOCKED_DATA` 不变，即使本轮 OMS 全绿也不改变。新增独立的**待闭合上游检查项**：

- `VendorFacts` 的 `pit_availability` 目前为未枚举校验的 dataclass 字符串，`evaluate_purpose()` 对未知字面值之外的**非法词值**可能按有效 PIT 处理；类似的 coverage 枚举也需 fail-closed 证明。Codex **只读复核/用隔离合成测试确认或驳回**这一风险，并在 `artifacts/evidence/M2/upstream-data-risks.md` 登记路径、复现步骤和责任阶段。不要借 M2 范围擅自重写 M1 数据模块；如确认，列为 **真实研究数据解封前必须解决** 的阻断项，单独申请改动授权。
- 无 Sharadar 订阅、Alpaca/Massive 凭证或许可全文：`API_VERIFIED=NONE`，M1 历史研究不可用；M2 只采用合成的已标注数据和本地 FakeBroker。
- M3 的真实数据研究能力不得因本 M2 通过而解锁。

## 10. M2-T7 — CI、测试和证据链

基于原始 **233 passed** 基线，不删减或修改旧断言以掩盖退化：

```text
python -m pip install -e ".[dev]"
python scripts/check_environment.py
python -m pytest -q
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
# 额外 M2 fault injection / single writer / recovery 可复现入口
# git diff --check
```

- 执行 TDD 红绿日志、最终全量测试（含 M0 140、M1 93、M2 新增），故障注入 ≥1,000 次日志、单进程/多进程 crash 证据、架构检查负例、依赖差异、扫描结果。
- 若需要修改 CI，必须让新增 M2 测试及架构检查在 Ubuntu/Windows 两套作业实际运行；不得跳过、xfail、空测试假绿。
- 本地 PASS 与远端 CI PASS 独立报告：仅在用户明确授权 push，且**最终代码 SHA 的两套 CI 作业真实成功**时，才可标记 `M2_REMOTE_CI_VERIFIED`。若 CI 尚未运行记 `CI_REMOTE_PENDING`。
- 所有证据新建在 `artifacts/evidence/M2/`，不能覆盖 M-1/M0/M1 原始工件。证据中的账户和密钥一律测试假数据，不能出现真实凭证。

## 11. M2-T8 — 三轨报告与阶段门

必交：

- `docs/reviews/M2-engineering.md`、`M2-strategy.md`、`M2-real-capital.md`。
- `artifacts/evidence/M2/`：代码/契约散列、配置、全部验证日志、故障注入分母、状态恢复与 UNKNOWN 证据、双主写证据、architecture-health、上游数据风险表。
- `src/trading_lab/risk/`、`src/trading_lab/oms/`、`src/trading_lab/brokers/`（**仅 fake**）、`configs/policies/risk_policy.paper.example.yaml`、`tests/fault_injection/`。
- ADR（编号不冲突），阶段后变更清单、未实现项/限制及后续授权需求。

报告不允许含糊：

| 维度 | 可报告的真实结论 |
|---|---|
| 工程 E | 仅当 M2 本地全部安全门达标可报 `PASS_WITH_SCOPE (MOCK_ONLY)`；受阻必须如实为 `BLOCKED_ENV` / `REMEDIATION_REQUIRED`；真实 Alpaca 行为仍 `BROKER_BEHAVIOR_UNVERIFIED`。 |
| 策略 S | `N_A / NOT_EVALUATED`，合成交易不产生 Alpha/OOS 证据。 |
| 资金 R | `NOT_STARTED`，真实账户、资金、Live 一律不可用。 |
| 数据 | `BLOCKED_DATA`（全市场研究），不可因 fake 交易 PASS 被提升。 |
| CI | `LOCAL_PASS / CI_REMOTE_PENDING` 或有真实 GitHub 两矩阵 SHA 证据的 `REMOTE_VERIFIED`。 |
| 用户审批 | `M2_GATE=USER_PENDING`，`M3_START_APPROVAL_PENDING`；不得代签。 |

**结束时必须停止：**不得自动启动 M3，不得提交真实 Alpaca 凭证或请求用户在日志/聊天中发送密钥，不得购买数据订阅或启动真实 Paper/Live 交易。若条件不足，只交付真实的部分结果和 blocker，不要降低验收阈值。

## 12. Codex 启动提示词（只有收到明确审批才可执行开发）

```text
请先读取 AGENTS.md、两份 v2.1 计划、本任务书与 M-1/M0/M1 验收报告，并核实 HEAD/工作树/审批链。
目前 M1_REMEDIATION_VERIFIED，但 M1_GATE=USER_PENDING、M2_START_APPROVAL_PENDING：
如果没有当前用户明确批准关闭 M1 且授权启动 M2，只进行只读盘点并停止，绝不擅自执行 M2。
获得授权后严格执行 M2-T0～T8：仅 synthetic engineering data + 本地 Fake Broker；
必须实现独立 Risk、单一 OMS、durable intent/outbox、UNKNOWN 不盲重发、可信单写者出口/fencing、≥1000 故障注入。
优先复用 M0/M1 的 Contracts/SchemaGate/Audit/KillSwitch，禁止双实现、POC 运行时依赖、无必要中间件。
执行先红后绿、现有233项回归、全量 CI/架构检查并记录真实证据。
全市场研究 BLOCKED_DATA、BROKER_BEHAVIOR_UNVERIFIED、S=N_A、R=NOT_STARTED 均不得改变。
未经另行授权不 push、不连接真实券商、不启动 M3；完成后停在 M2_GATE=USER_PENDING。
```

---

**重要：** 此文件只是下阶段执行规范，**不是批准文件**。用户必须单独对 M1 关闭与 M2 启动做出明确授权。
