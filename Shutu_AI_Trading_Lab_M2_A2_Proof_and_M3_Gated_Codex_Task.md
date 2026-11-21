# Shutu AI Trading Lab — M2 并发门验收数量补证 + M3 冻结研究协议（双阶段门控 Codex 任务）

> Task ID: `M2-A2-CONCURRENCY-EVIDENCE-CLOSE-AND-M3-GATED-002`  
> 编制日期：2026-11-21  
> 代码审查远端基线：`b7d11aa2a70d5d470bb46197e8bafb1a6eb6fa7a`  
> GitHub Actions 已核实：<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44878925093>；Ubuntu / Windows 均 SUCCESS，334 passed。  
> **注意：这证明已有 334 项测试通过，但未达到上一任务书 A2 指定的 ≥100 轮双线程、≥50 轮真实双进程的数量要求。**  
> **当前只允许执行 A4 补证；M3 B0–B8 未获授权，不执行。**

## 0. 必须遵守的全局约束

1. 先读 `AGENTS.md`、`docs/plans/` 两份 v2.1，以及仓库根目录 `Shutu_AI_Trading_Lab_M2_to_M3_Gated_Codex_Execution_Task.md`，并逐条核对前文 A2 的量化要求。
2. 先验证当前本地与远端 HEAD；独立确认本地 `29ecf54` 是否是先前 CI 报告补录提交。不要将尚未推送的提交当作远端证据，不覆盖他人更改；不能 reset --hard / force push。
3. 以当前 `b7d11aa` 的唯一 `OrderJournal.claim_send_attempt` / `_transaction` / `BrokerEgress` 为工程基线。**优先补测试与证据，不得因计数缺口就重写生产组件。**
4. 只允许合成数据和本地 FakeBroker。禁止使用 Alpaca Paper/Live 凭证、真实券商网络、真实订单/资金操作、购买/注册数据、解封真实 Holdout；M1 `BLOCKED_DATA`、`U-1` 和 `BROKER_BEHAVIOR_UNVERIFIED` 一律维持。
5. M2 门必须由用户明确批准才可关闭；M3 启动必须另获用户明确授权。读取任务书、CI PASS、A4 完成均不等于授权。未获单独推送批准不可 push。
6. 保留 334 既有用例、原 1,080 fault matrix 与三轨证据，新增计数独立分母。Architecture Health 必须证明无重复 OMS、第二套发送凭证或新中间件，无长期兼容层。

## A4. M2 Send Claim 最小补证（**本次执行，完成后强制 STOP**）

### A4-1 先辨明差距（不得夸大）

上一份任务书 A2 有明确门槛：**双线程同 COID ≥100 轮受控竞争、两个真实进程 ≥50 轮竞争**。当前 `tests/fault_injection/test_send_claim_race.py` 可验证已有单轮确定性竞争，报告称本地 5 次稳定性重跑，但不能按现有证据宣称已经执行 100/50 轮。独立逐项标注 `PASS/NOT_MET/UNVERIFIED`，不得暗改或删除此前门槛。

### A4-2 双线程 ≥100 轮

- 以真实 `OrderJournal` 和 `BrokerEgress.submit` 为入口，两个并发线程持有相同有效 fence，使用 `Barrier` 或等价确定性协调机制让二者竞争**同一个 COID**。每一轮用新的独立 COID/已密封意图，避免因上一轮已经 claim 而制造空过。
- 至少执行 100 轮；每一轮都记录意图、获胜次数、真实 `BrokerPort.submit_order()` 进入次数（不能以 FakeBroker 的去重最终订单数替代）、失败类型、是否出现异常；**每轮至多 1 次真实 Port 调用，总重复次数必须为 0**。
- 测试必须证明竞争真实发生且至少一个尝试到达 Port；禁止通过 SQLite 线程检查异常/测试配置失败形成虚假绿色。Windows 与 Ubuntu 采用确定性同步，不靠 `sleep`/随机时间巧合取得通过。
- 追加负例：成功 claim 后超时/崩溃不重复开放资格；错误 fence、错参数、错账户、无 journal 意图都不得进入 port。原测试保持，不替换原 A-RED1 的对抗证明。

### A4-3 两个真实 OS 进程 ≥50 轮

- 使用两个真正不同 PID 的 worker + 独立 SQLite 连接；建议长期存活的 spawn-compatible worker + 跨进程 Barrier/IPC 控制，不强制每轮创建新进程，以避免 Windows 进程启动开销污染竞争。
- 至少 50 个**各自独立**的合法 COID，每轮两个进程对同一 COID 竞争。每轮开始前由独立 setup 准备合法 `SUBMITTING`/attempt、对应 fence epoch；不能先让其中一个消费资格。
- 每轮输出两个 worker 的竞争结果、PID、claim 事实及数据库 `SEND_CLAIMED` 持久状态，按 COID 验证 `sum(success)==1`，无 0 winner 的无效测试、无 2 winners；数据库错误、超时不能静默按 PASS 计数。
- 如果要证明跨进程真实 Broker Port 进入次数，请为每个 worker 记录受控的进程外计数/事件日志后聚合；若仅测试 Journal 原子 claim，必须明确证据只覆盖 `claim` 仲裁，不能谎称跨进程 Port E2E。
- 额外覆盖进程 A 在 claim 后 crash、进程 B 竞争 claim：B 不得再次取得资格，后续恢复必须保留 UNKNOWN/HALT 直到对账与人工解锁；不得自动补发。

### A4-4 运行完整质量门

- 先跑新对抗测试，再跑全量 pytest（既有 334 项不删不弱）、原 1,080 fault matrix、`scripts/check_environment.py`、`scripts/check_architecture.py`、`scripts/scan_secrets.py`、`scripts/verify_live_blocked.py`、`scripts/smoke_mock.py`、`git diff --check`。
- Windows + Ubuntu 必须在新提交 SHA 上经真实 CI 全跑（需先获得用户**单独推送授权**）；不要借用 `44878925093` 作为新代码验证。不要 xfail / skip / 降低测试轮数来追求绿色。
- 如果新增测试发现真实竞争漏洞，RED → 最小 GREEN，优先修改既有 claim/egress 并补证；如未发现，则不触碰产品代码。

### A4-5 留存且不覆盖旧证据

建议新增：

```text
artifacts/evidence/M2/final-send-claim/a2-quantitative-close/
  baseline.md
  thread_100_rounds.log
  process_50_rounds.log
  crash_recovery.log
  full_checks.log
  architecture_health.md
  ci-verification.md         # 尚未远端跑绿则 CI_REMOTE_PENDING

docs/reviews/M2-a2-quantitative-closure.md
```

报告必须对照以前量化要求列出真实总轮数、每类有效竞争次数、0/1/2 port-enter 与 claim-winner 分母、进程 PID、错误与重试数；每个证据文件关联命令、SHA、环境、退出码和日志路径。

**A4 通过但未经远端确认时**：
`M2_A2_QUANTITATIVE_LOCAL_PASS / CI_REMOTE_PENDING / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

**新 SHA 双平台 CI 真实通过后**：
`M2_A2_QUANTITATIVE_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

**A4 完成后必须 STOP。不得自动签批 M2、不得开始 B。** 若用户选择对原 100/50 门槛作显式验收例外，也须记录是谁、在何时、基于什么证据批准，不能由 Agent 代签。

---

## B. M3：透明规则基线、现实回测与冻结研究协议（**仅在用户明确批准 M2 关闭与 M3 启动后执行**）

> 唯一权威：上述两份 v2.1 计划的 `M3`，并遵守 Architecture v2.1 §4.3 B0–B8。以下只落地 M3 范围能力，不提前开发 M3.5、M4、M6、M7。

### B0 — M3 启动证据门

执行前必须具备：

- 已明确存档 `M2_GATE=CLOSED`、`M3_START=APPROVED` 的**用户批准事实**（人类签批，不由 Codex 代签）；
- `git status --short`、远端/本地 SHA、`29ecf54` 等此前 docs-only 提交的处理及 CI 新跑次记录；
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
5. 安全回归 334 项及 M2-A2 额外回归全部保留，原 1,080 故障矩阵和双平台 CI 不允许削弱/跳过。

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

## 授权和执行提示词（分开使用，切勿混淆）

**本次可交给 Codex 的命令（仅 A4，不授权 M3）：**

> 请阅读本任务书、原 `Shutu_AI_Trading_Lab_M2_to_M3_Gated_Codex_Execution_Task.md` 以及 `AGENTS.md` 和两份 v2.1。只执行 A4：补足上一份 A2 的双线程 ≥100 轮和双真实进程 ≥50 轮定量证据，先审视现有测试，优先只扩展测试/证据；若发现真实缺陷再实施最小修复。保留 334 基线与 1,080 故障矩阵；执行所有工程/架构/安全门。禁止任何真实数据或券商调用，不自动 push。到 M2_GATE=USER_PENDING 强制停止，禁止执行 B。

**未来仅在用户分别明确批准 `M2_GATE=CLOSED` 和 `M3_START=APPROVED` 后，才可使用的命令（仅 B）：**

> 已取得人类对 M2 关闭及 M3 开工的两项明确授权；先核验授权记录、最终远端 SHA 与真实 Ubuntu/Windows CI 证据，再执行本文件 B0–B8。仅合成数据、离线回测工程验证；独立最终 Holdout 保持 SEALED_NOT_MATERIALIZED，真实全市场研究 BLOCKED_DATA，任何合成收益绝不得当作 Alpha。冻结评估协议先于实验，B0–B2 可执行，B3–B8 仅冻结定义和预算。架构质量按 E-Gate 证明；不自动 push，完成停在 M3_GATE=USER_PENDING。
