# Shutu AI Trading Lab — M2 并发发送资格收口 → M3 冻结研究协议与合成回测（双阶段门控 Codex 任务）

> Task ID: `M2-FINAL-SEND-CLAIM-AND-M3-GATED-001`  
> 编制日期：2026-11-20  
> GitHub: `shutu-ai/Shutu-AI-Trading-Lab`  
> 远端审查基线：`fc9c3d492135f4de56ef16b4c5d55cd14e768002`  
> 已核实 CI：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44823606397`（Ubuntu / Windows 均 SUCCESS，330 passed）  
> **本任务书有 A、B 两段。首先只允许执行 A；B 必须在 A 完成、远端 CI 通过、用户明确关闭 M2 且另行授权启动 M3 后执行。**

## 0. 优先级、权限与安全边界

1. 阅读 `AGENTS.md`、`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`、`docs/adr/ADR-002-addendum-m2.md`、`docs/reviews/M2-residual-safety-remediation.md`、`docs/reviews/M2-engineering.md`、`docs/reviews/M1-engineering.md`、`artifacts/evidence/M2/architecture-health.md`。
2. 用户提供的本地状态中还有 `a4f1413`（CI 文档补录，未推送）。执行前必须在本地用 `git show --stat a4f1413` / `git diff origin/main...HEAD` 核实真实存在、是否 docs-only、工作树是否 clean。**不得覆盖或假设远端已有这次补录**；若存在其他本地变动，保留并报告，禁止强制重置。
3. 本任务的“已核实远端 CI”**只覆盖 `fc9c3d4`**；后续新提交必须获得独立的 Ubuntu + Windows CI PASS，不能借用旧跑次。
4. **禁止**申请/使用真实券商凭证、Alpaca Paper/Live 网络调用、真实订单/资金操作、采购数据、解封真实 Holdout、绕过 M1 `BLOCKED_DATA`。所有执行与研究均为合成数据、离线、FakeBroker、`MOCK_ONLY`。
5. 不修改 §2.2 冻结契约、E/S/R 三轨与原有人工签批流程；不降低既有风险阈值、不删除弱化原 330 项测试、不覆盖原证据。不引入并行 OMS、第二套风控、第二发送出口、消息队列/Redis/Kafka 或无消费者兼容层。
6. **A 阶段允许本地代码与测试修改、建本地提交；不自动 push。A 通过后必须 STOP。** 本文包含 B 的可执行规划，但并不授权 Codex 在同一次会话自动进入 B。收到用户明确的 `M2_GATE=CLOSED` 与 `M3_START=APPROVED` 后方可继续 B。
7. 若审查推翻本文对并发竞争的判断，必须以确定性竞争测试及可复现证据说明，而不是单靠理论/静态自评；允许记录 NOT_REPRODUCIBLE 并提请用户裁决，不允许无证据把 M2 关门。

## A. M2 最后一个定向核验门：并发 Send Claim 原子性

### A0 — 风险描述与 RED 验证

`src/trading_lab/oms/egress.py::submit()` 当前执行：fence validate → `journal.get_send_eligibility()` **普通 SELECT** → `_port.submit_order()` → fence validate。`get_send_eligibility()` 只检查 `SUBMITTING` 意图和 `SUBMITTING` attempt，**没有原子地独占/消耗同一订单的发送许可**。当两个拥有同一有效 fence 的调用者在状态变化前并发通过 SELECT，可能双双进入 `_port.submit_order()`；顺序重放测试不足以证明并发单发保证。

先写并运行明确的**受控 RED 证明**，不可只用 sleep 或随机竞争：

- A-RED1：两个线程，同一真实 Journal / 同一 COID / 同一有效 fence，使用 Barrier/可阻塞 Port 使两次 `get_send_eligibility()` 尽可能同时完成并在第一个 port 返回前竞争；统计 **真实 `_port.submit_order` 次数**与 `created_orders_by_intent`，不能由 FakeBroker 去重掩盖；要求最终只允许 1 个外部 submit。
- A-RED2：两个真实 OS 进程、两个 SQLite 连接竞争同一个合法 send claim（先构造持久 `SUBMITTING` 和密封决策），每个进程的 send-attempt 事实落到独立文件/共享审计以避免进程私有计数误报；要求单个 COID 合计至多 1 次 port 进入。
- A-RED3：成功 claim 后、port 调用前崩溃或超时，重启不得自动复位为可发送；只允许 UNKNOWN/全局 HALT + 查单对账，不得盲重发或生成替代 COID。
- A-RED4：同一 COID 在 `ACKED/UNKNOWN/HALT_NEW_RISK/RECONCILED` 及过期 fence 下反复直接调用 egress，拒绝并保持 0 新建订单；CAS 失败不应影响成功已持久化的既有订单。
- A-RED5：检查 `tests/m2_remediation/test_residual_safety.py::test_direct_egress_without_intent_zero_created`：其中 `except Exception: pass` 可能吞掉内部的 AssertionError。改为**精确预期异常 + 无 port 调用计数**；审查同类宽泛 except、`or True`、空 `pass` 测试占位，修补无效断言，但不扩大生产改动。

RED 结果需区别“代码确能重现双发”与“静态上存在窗口但测试未复现”，两种情况都不能凭未经证实的日志造假。

### A1 — 最小修复要求（如证实/不能排除上述窗口）

1. **唯一权威：继续使用现有 `OrderJournal` + `BrokerEgress` + SQLite**，不引入第二发送器、数据库、中间件或外部锁。
2. 在 Journal 内建立**原子一次性 Send Claim**：单 SQLite 写事务对匹配的 `SUBMITTING` attempt 执行受限 CAS（例如 `SUBMITTING → SEND_CLAIMED`）；匹配 COID + `intent_id` + fence epoch + 状态 + 参数 + 密封证明，且仅有一个调用者能成功取得 claim。
3. claim 应在调用 Port 之前 durable commit；claim 失败/库不可用/审计故障 → **零 Port 调用**；不允许取得 claim 后自动回滚成可重发状态。进程崩溃可能导致“尚未送达但已 claim”的保守 `UNKNOWN`，这是允许的安全成本，必须进行对账才能恢复；不可用“可能未到”作为重发证据。
4. 保持 `journal-before-send`、fence 前后验证、账户级 KillSwitch、OMS 批准 HMAC 与参数绑定。严格限定发送次数为 **0 或 1**，**不是要求每个意图都最终可发出**。取消路径如受更改影响，回归验证取消意图资格和未知取消结果的处理；`get_order` 保持只读。
5. 使用**单一发送资格状态事实**；禁止在多个模块复制独立的 `sent` 标志或再造 Wrapper。若需要扩展 attempt 状态，沿用现有 attempts 表/`OrderJournal` 方法和审计，而不是新建另一套订单状态机。
6. 竞争获胜者即使 port 报错也不能释放 claim 给竞争者；失败/未知保留高优先级 HALT，恢复只对账。更新相关测试 helper，不留下旧 SELECT-only 可绕过入口。
7. 修复前后分别留存可复现的红/绿日志；维护原 1,080 fault matrix，新增并发测试分母**单列**，不能将原矩阵二次计数。

### A2 — 强制测试与证据

验收至少包含：两个线程同 COID ≥100 轮受控竞争、两个真实进程 ≥50 轮竞争、claim 后崩溃/连接不可用/进程重启/新旧 fence、fake broker 无去重、顺序重放、ACK 丢失及 UNKNOWN 对账；若 CI 环境导致测试不稳定，修正并发测试的确定性同步，**不可跳过 Windows、不增加 `xfail`**。

全部满足：

- 单 COID port-submit 次数 ≤1，违例 0（必须在真正端口入口统计，不以同一 FakeBroker 最终订单数代替）；
- 0 未持久化/未批准/跨账户/旧 epoch 发送；
- 任一未确认结果账户级 HALT，0 自动重发、0 自动解锁；
- 330 既有用例零删除零削弱，1,080 矩阵依然绿；
- Ubuntu 与 Windows CI 在**新 SHA** 上均真实运行并 PASS；
- 生产新增依赖为 0，职责唯一、POC 零运行依赖。

新增工件（不得覆盖之前证据）：

```text
artifacts/evidence/M2/final-send-claim/
  baseline.md
  red-tests.log
  green-tests.log
  cross-process.log
  checks.log
  architecture-health.md
docs/reviews/M2-final-send-claim-review.md
```

更新 M2 三轨报告只能通过清晰补遗，历史记录不能改写；报告中区分 `REPRODUCED/NOT_REPRODUCIBLE`、`FIXED/UNRESOLVED`、`MOCK_ONLY/UNVERIFIED`。GitHub Actions run URL、head SHA、各作业测试数及结论必须基于真实远端证据；未推送就写 `CI_REMOTE_PENDING`。

### A3 — 第一强制停止门

完成 A 本地修复和测试后停在：

`M2_FINAL_SEND_CLAIM_LOCAL_PASS / CI_REMOTE_PENDING / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

**推送须用户另行授权**。若推送后真实 Ubuntu/Windows CI 都绿，可报告：

`M2_FINAL_SEND_CLAIM_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

**即使 CI 绿也不能代替用户关闭 M2 或启动 M3。A 结束后必须停止并回报。以下 B 为“下一次明确授权后”才执行的计划。**

---

## B. M3：透明规则基线、现实回测与冻结研究协议（**待单独授权**）

> 唯一权威：上述两份 v2.1 计划的 `M3`，并遵守 Architecture v2.1 §4.3 B0–B8。以下只落地 M3 范围能力，不提前开发 M3.5、M4、M6、M7。

### B0 — M3 启动证据门

执行前必须具备：

- 已明确存档 `M2_GATE=CLOSED`、`M3_START=APPROVED` 的**用户批准事实**（人类签批，不由 Codex 代签）；
- `git status --short`、远端/本地 SHA、`a4f1413` 等此前 docs-only 提交的处理及 CI 新跑次记录；
- M1 `BLOCKED_DATA(全市场研究)` 不变；M1 U-1 未修，绝不自动将真实供应商数据认定合格；`BROKER_BEHAVIOR_UNVERIFIED` 不变；
- M3 只允**合成数据与纯离线回测工程验证**，不产出可用于投资决策的 Alpha 证据，绝不声称支持真实历史 OOS、真实行情回测或真实前向表现。

若缺任一授权，STOP；不得把收到/打开本文件视作批准。

### B1 — 预注册协议先于正式实验

先在 `configs/evaluation_protocol.yaml` 与 `docs/adr/ADR-004-evaluation.md` 冻结协议 v1，至少包括：

- 唯一 `protocol_id` / `protocol_hash` 计算规范、canonical JSON/配置版本、仓库 commit、运行环境、随机种子集合、Decimal 数值容差；版本更新产生**新 hash**且保留旧版，严禁失败后暗改阈值。
- 每个用途的数据类型和证据状态：`synthetic-engineering-fixture` → `ENGINEERING_ONLY`；真实历史数据必须同时过 M1 供应商许可/PIT/质量及 Snapshot `research_admissible()`，否则 `BLOCKED_DATA`。
- 训练、Validation、滚动 OOS、独立 Sealed Final Holdout、未来 Forward cohort 之间的时间/事件/证券隔离规则；标签横跨边界时 Purge/Embargo 的计算与理由。
- 执行价格的可得时间、订单延迟、价差、费用、冲击、未成交/部分成交、成交量限制、退市/企业行为、可用现金与交收；成本 ×1/×2/×3 的预声明方案。
- 每个主要检验的样本最低数量、效应下限、显著性或置信区间准则、多重比较控制、最大失败/重试/搜索次数、单独计算**全研究成本**。若无足够依据给出可辩护数值，明确写 `PROTOCOL_INCOMPLETE / INCONCLUSIVE` 并禁止研究 S-Gate PASS；不得临时选择“容易通过”的阈值。
- **唯一候选事前选择规则**（未来 M8 结束、M9 解封前才冻结具体 `strategy_hash`/build hash）、一次性终检审批流程、`PASS/FAILED/INCONCLUSIVE/INVALIDATED` 的机器判定及污染事件日志。
- 两套 AI vs 规则预算：等试验预算（候选数、参数、训练、失败与重试全部计入）和等经济预算（LLM/算力/数据/人工干预时间分项）；两者无法等额时明确不能宣称等价。

协议在第一次正式研究数据运行前冻结；可用合成 fixture 自测判定函数，但其结果绝不记为真实 S 支持。

### B2 — 现有契约与架构盘点（不堆叠）

开发前提交以下表：`REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES`，标注所有新增模块的**唯一消费者**。优先复用 `contracts` 的 MarketBar/MarketSnapshot/ExperimentRecord/FinalHoldoutResult、`data` 的 snapshot/PIT/membership/actions/calendar、`security.canonical` 的 hash 和已有 `AGENTS.md`/`check_architecture.py`。

禁止：回测层连接 OMS/Risk/Broker 写接口、复制 M1 数据准入层、第二套 Schema Gate、第二个订单持久化账本、未经消费者需求的插件框架、通用事件总线或多重功能包装器。M3 仿真账本可为独立纯回测内存计算对象，但必须明确**不是** OMS live/order journal，不能向 BrokerPort 发送订单。

### B3 — 现实但确定性的纯回测内核

建议交付：

```text
src/trading_lab/backtest/    # 纯计算、无真实经纪写权限
src/trading_lab/validation/  # 纯验证协议、预算、分区与 sealed-gate
configs/evaluation_protocol.yaml
docs/adr/ADR-004-evaluation.md
tests/backtest/
tests/validation/
artifacts/evidence/M3/
docs/reviews/M3-{engineering,strategy,real-capital}.md
```

要求：

- 现金、股数、权益、收益、成交成本、持仓、未结算资金与交易日志按 **Decimal** 守恒；合成场景覆盖拆股、分红、退市与代码重用；不在可得时间前使用复权因子或退市资料。
- 信号仅可在 `ts_available_utc <= decision_at` 时使用；成交价格不能来自信号已知时刻之前或不可能成交的 bar。测试特别注入未来价格、事后调整、同日收盘买同日收盘（无可执行依据）并全部阻断。
- 订单延迟、价差、手续费、滑点/冲击、部分成交、未成交、撤单、量能上限、现金交收（模拟 T+N 根据协议明确假设，不假定真实券商）均要产生可重放结果。
- 同数据 hash + 同 seed + 同协议 hash => 结果 hash/指定数值容差一致。随机性只能由注入 seed 控制，不能使用系统隐性随机数；市场日历、时区、DST 必须复用数据层语义。
- 仿真器与 OMS/Live 风控要明确隔离；研究期不调用真实 BrokerPort，不把历史模拟成交作为 Paper/Live 执行证明。

### B4 — B0–B8 冻结基线与可执行范围

按 Architecture v2.1 §4.3 原样登记全部 9 臂：`B0` 现金、`B1` 宽基 ETF 买入持有、`B2` 透明单策略、`B3` B2+Regime、`B4` 固定权重多策略、`B5` B4+Regime、`B6` B5+Champion–Challenger+AI、`B7` 同进化规则但只有规则搜索、`B8` 简单再平衡。

M3 **实际开发/运行** B0、B1、B2 的最小合成实验夹具并验证确定性、公平成本与 PIT；为 B3–B8 仅冻结**协议中的定义、必需输入与两套预算验证规则**，不预建不存在消费者的 Regime/AI/evolution/Portfolio 实现，不以空壳模块或虚假运行结果充数。未来各阶段按同一协议实现 B3–B8。

所有 B 臂共享同一个数据/时间/成本约束口径；实验账本必须登记成功、失败、被拒和未完成的所有试验及搜索成本，禁止只报告赢家。

### B5 — Walk-Forward / Purge / Embargo / 三队列隔离

- 生成不可重叠的开发/滚动 OOS/最终 Holdout/前向 cohort 索引，并可机器检测相同日期/资产/事件、重叠标签跨度与提前可得字段；重叠存在必须披露并降级独立性，不许无条件 PASS。
- 时间窗边界精确，训练点可得时间必须严格早于对应验证决策；Purge/Embargo 防止标签前视。检测违反时拒绝评估，不得静默剔除后报完美绩效。
- 只有经授权独立验证流程可触达真实封存样本；M3 中仅创建**合成 Holdout 占位/合成密封演练**，真实 Holdout 若尚未获得合法数据，状态必须是 `SEALED_NOT_MATERIALIZED`（或等价明确语义），不能伪造真实封存内容与 hash。
- M9 解封前的唯一候选选择规则在 M3 预注册；具体候选策略及 build hash 必须留待 M8 结束冻结，M3 不选假候选占位冒充将来唯一候选。

### B6 — 防“偷看”与终检污染演练

最少覆盖：

- 研究角色直接读取/聚合查询/统计侧信道请求 sealed 合成 Holdout → 100% 拒绝并审计；只测试 Python 函数权限是不够的，应针对模拟权限边界做可执行验证，同时诚实说明 OS 级强隔离尚未完成（归 M4）。
- 用**合成 Holdout** 演示解封后污染，任何第二次选择或第二次解封 → `INVALIDATED/REJECT` 且不可重置；`PASS/FAILED/INCONCLUSIVE/INVALIDATED` 四种情境可用合成 fixture 明确覆盖。
- 篡改协议、修改阈值后不改 hash、不同 trial/search 预算、重复实验删失败记录、未来特征、错误快照、超额实验、随机种子变化与同标的/同事件多队列重复计数 → 负例必须失败。
- 不得开放真实 Holdout、不得调用券商、不得将测试桩的 PASS 宣传为真实策略表现。

### B7 — 架构与代码质量硬门（E-Gate 子项）

1. `backtest` 与 `validation` 不得导入 `oms`、`brokers`、`risk` 或 POC；不得读取券商环境变量、发网络请求；依据实际依赖关系将这两包纳入 `scripts/check_architecture.py`，扩展现有检查器规则，不创建第二个。
2. 对新增的规则和检查器自身补正负测试；移除过期入口/重复函数、无消费者 Adapter/Wrapper、无用配置；不要为追求“零重复”而过度拆分。
3. 针对新增运行依赖按用途、替代、许可、Windows/Linux 隔离环境可安装性给出证据；优先使用已有依赖与 Python 标准库。
4. 提交 `artifacts/evidence/M3/architecture-health.md`：职责唯一、依赖方向、复杂度理由、重复实现扫描、POC 隔离、REUSE/ADD/REPLACE/REMOVE、真实与合成证据界限、遗留债清单。
5. 安全回归 330 项及其后 A 阶段新增用例全部保留，原 1,080 故障矩阵和双平台 CI 不允许削弱/跳过。

### B8 — 全量验证、三轨与阶段门

在 Python 3.13 的干净虚拟环境执行（Windows PowerShell 示例）：

```powershell
python -m venv .venv-m3-review
.\.venv-m3-review\Scripts\python.exe -m pip install --upgrade pip
.\.venv-m3-review\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-m3-review\Scripts\python.exe scripts/check_environment.py
.\.venv-m3-review\Scripts\python.exe -m pytest -q
.\.venv-m3-review\Scripts\python.exe scripts/check_architecture.py
.\.venv-m3-review\Scripts\python.exe scripts/scan_secrets.py
.\.venv-m3-review\Scripts\python.exe scripts/verify_live_blocked.py
.\.venv-m3-review\Scripts\python.exe scripts/smoke_mock.py
git diff --check
git status --short
```

每项命令必须保存实际 EXIT CODE、运行环境、测试总数、负例数量、所有失败和原因；不使用 `--no-build-isolation` 来掩盖打包缺陷。每次新增代码按用户单独批准推送后，需在 GitHub Actions 上确认 Ubuntu/Windows 都 PASS；没有远端证据的提交只能标本地 PASS。

三轨标准：

- `E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`：仅当确定性、PIT 与研究协议防泄漏测试真正通过，允许工程合成测试；若协议缺硬阈值等则如实 `REMEDIATION_REQUIRED/INCONCLUSIVE`。
- `S=N_A / INCONCLUSIVE`、`evidence_state=NOT_EVALUATED`：只要真实全市场数据保持 `BLOCKED_DATA`，不能使用 `HIST_OOS_SUPPORTED/SUPPORTED` 描述合成回测。真实研究数据解封另需 U-1 及许可/API/PIT/覆盖闭环。
- `R=NOT_STARTED`，真实 Broker 仍 `BROKER_BEHAVIOR_UNVERIFIED`。
- 初始最终 Holdout = `SEALED`（若真实数据不存在，则明确 `SEALED_NOT_MATERIALIZED`，不要伪造持有真实样本）。
- 完成 M3 后停在 `M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`，不得自行签批或启动 M3.5 / M4 / 任何 Paper/Live。

M3 报告至少需要 `docs/reviews/M3-engineering.md`、`M3-strategy.md`、`M3-real-capital.md` 和 `artifacts/evidence/M3/verification.log`、`architecture-health.md`、`protocol-freeze.md`、`negative-tests.log`、`cohort-overlap-report.md`，其中要明确哪些是真正实测、哪些是模拟。

---

## 给 Codex 的本次执行命令（只执行 A）

> 先阅读本文件、`AGENTS.md` 和两份 v2.1 计划。**本轮只执行 A0–A3 的 M2 并发 Send Claim 闭环**：先用真实线程/双进程竞争、Barrier 和 port-entry 计数证明有无双发，再最小修复现有 Journal/egress，修正无效测试断言，保留安全回归、故障矩阵、架构健康和远端 CI 证据。禁止新增平行引擎、Broker 实联、真实交易、数据订阅与 M3 开发；未经单独授权不得 push。完成后停在 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。**B0–B8 仅为用户未来明确授权 M3 后的工作，不得自动执行。**
