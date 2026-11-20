# Shutu AI Trading Lab — M2 独立验收安全整改 Codex 任务书

> Task ID: `M2-INDEPENDENT-REVIEW-REMEDIATION-001`  
> 类型：M2 已完成代码的 **安全不变量定向整改**；不是 M3 实施许可。  
> 独立审查基线：GitHub `shutu-ai/Shutu-AI-Trading-Lab` `main` = `708833dd38552344a97823c44f52c573f0cac4f1`（2026-11-20）。  
> 远端已验 CI：run [44792814901](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44792814901)，Ubuntu/Windows 各 `282 passed`；这只证明旧测试，不代表下列缺口已经解决。  
> 阶段状态：`M2_REMOTE_CI_VERIFIED`（既有测试范围）／**`M2_INDEPENDENT_REVIEW_REMEDIATION_REQUIRED`**／`M2_GATE=USER_PENDING`／`M3_START_APPROVAL_PENDING`。  
> 环境权限：**仅合成数据 + 本地 FakeBroker**；禁止真实 Alpaca Paper/Live、券商凭证、外部交易网络、真实资金、订阅购买、M3 代码开发。  
> 注意：本任务书是整改执行指令，**不是用户的阶段签批**；未经用户对执行、推送、阶段关闭及 M3 启动分别明确授权，不得自行越权。

## 0. 启动前必须核对的事项

1. 阅读并遵守 `AGENTS.md`、两份 `docs/plans/*v2.1.md`（M2、E-Gate、§6.2、OMS UNKNOWN/fencing）和 `docs/adr/ADR-002-addendum-m2.md`；阅读 M2 三轨报告与 `artifacts/evidence/M2/` 原始证据。以**仓库实况**为准，发现本任务记录的源码事实已变化时先给出 commit/file/line 证据，不要重复造轮子。
2. 执行 `git status --short`、`git log -8 --oneline`、`git rev-parse HEAD`、`git diff --check`。用户称本地另有 docs-only 提交 `30429f4`（补录旧 CI），**未在远端核验**；仅保留、检查其真实 diff，禁止 `reset --hard`、`rebase`、`force push`、覆盖用户工作、擅自修改历史验收日志。若本地还有未知变动，先隔离/保全，禁止破坏性操作。
3. 列出 M0/M1/M2 的现存正式契约、`security.SchemaGate`、`KillSwitch`、`AuditLog`、`RiskEngine`、`OrderJournal`、`OmsEngine`、`BrokerEgress`、`FenceCoordinator` 与 `brokers.port` 的责任/依赖图和输入信任边界。核对 M2 已实现的不变量与本任务遗漏断言。
4. 为每个发现严格实施 **RED → 最小 GREEN → 回归 → 跨平台**：RED 优先构造可观察的错误行为，不能仅用 `ImportError` 代替缺陷证明；保留原始 RED 日志、目标文件与原因。先冻结要新增的安全负例及分母，禁止失败后降低标准。
5. 本次只允许 M2 所属目录与必要的测试、CI、架构健康、补充审查文档发生变更；若不得不动 §2.2 契约或 M0 安全基础，请提交显式兼容性/安全性论证，禁止静默扩展模型。

## 1. 已审查源码发现（需要独立复现）

| ID | 优先级 | 现有具体代码路径/问题 | 必须证实的安全不变量 |
|---|---|---|---|
| `M2-R1` | P0 | `src/trading_lab/oms/engine.py::OmsEngine.submit` 只保存 `RiskDecision`，未见任何 `decision.allow`、`intent_id`、`policy_hash` 或实际 `symbol/side/quantity` 的可信一致性验证 | 不经唯一 Risk Engine 真实批准，就不可能发往 FakeBroker；伪造/错配批准 = 0 发送 |
| `M2-R2` | P0 | `src/trading_lab/risk/engine.py` 仅在 `environment == LIVE and approval_verifier is not None` 执行 Live 验签；`None` 缺失未被显式拒绝 | Live 缺任何有效签批验证器必须失败；M2 不提供任何可下单 Live 路径 |
| `M2-R3` | P0 | `OmsEngine.operator_unlock` 直接 `KillSwitch.clear`；未先验证 Journal 中所有 UNKNOWN/HALT 与 broker orders/positions/cash 对账状态 | UNKNOWN 未解决、查单失败或对账不完整时，任何形式的“授权文本”都不能清除新增风险锁 |
| `M2-R4` | P1/P0（按复现升级） | `OmsEngine.submit` 连续调用 `record_intent`、`set_state(PERSISTED)`、`mark_submitting`，属于多个事务；注释/ADR 说“完整意图 + SUBMITTING 尝试同事务提交” | 明确真实原子边界；持久化故障或崩溃不得导致无意图发送、盲重发或无法判定的可继续提交状态 |
| `M2-R5` | P1 | `OmsEngine.process_fill` 计算 `target=FILLED` 后只记录 broker event，没有 `set_state`，也没有持久累计部分成交；事件/状态可能分裂 | 回报与状态/累计成交必须原子一致、幂等；部分成交、重复/乱序/撤单后回报不双计、不非法跳转 |
| `M2-R6` | P0（单写者主张） | `BrokerEgress._validated()` 校验 fence 后，调用 `_port.submit_order` 之间有 TOCTOU；新的 `FenceCoordinator.acquire` 可能在窗口内提升 epoch | 实际 dispatch 时不得出现被新 epoch 取代的旧写者造成第二并发写；事故记 UNKNOWN/HALT，不盲重发 |
| `M2-R7` | P0/P1（风控字段约束） | `RiskPolicy` 定义 §6.2 全字段，但 `RiskEngine.evaluate` 现主要消费 gross/order/cash/market freshness；`max_net_exposure_pct`、`max_single_symbol_pct`、daily loss、drawdown、order-rate、account-snapshot-age、ack-wait 等缺乏完整执行证据；`desired_change` 按美元模拟，不与 OMS 实际数量绑定 | 每个强制字段都有运行时验证/拒绝或明确可审计的 MOCK_ONLY 不可执行路径；数据不足 fail-closed，不能仅“字段非空”视为已执行 |

注意：上表是**远端源码静态审查发现**，不是声称所有攻击均已在用户机器实测成功。Codex 必须用 RED fixture 指出实际失败形态，再决定最小修改。不得为绿灯删掉负例。

## 2. R1 — 唯一风控批准必须被 OMS 强制执行（阻断项）

- 先写 `allow=False` 但其他字段完全合法的 `RiskDecision`，调用 `OmsEngine.submit`，断言 **broker 0 submit / journal 无 SUBMITTING / 审计拒绝原因**；修复前检查是否真实发送。
- 添加：`decision.intent_id` 与 `intent.intent_id` 不同、policy hash 不同/不属于当前运行时已加载 policy、决策过期/决策发生在未来、账户/环境不符、重复使用批准/错误策略 build hash、过期 intent、非法币值/方向等负例。
- 强制 `symbol/side/quantity` 与**批准的订单意图**原子绑定，不能允许 `desired_change=50` 经参数替换成任意标的、卖出或超大数量。当前 §2.2 `RiskDecision` 本身没有 `symbol/side/quantity` 字段：**不能仅检查 `allow=True` 就宣称解决伪造批准**；需设计最小受信装配/不可伪造的一次性批准上下文，或经唯一受信风险入口签发并验证明确绑定的批准对象。保证依赖规则 `oms` 不导入 `risk`、`risk` 不导入 `oms`；不创建第二套风控引擎/平行 DTO。
- 审计在放行前持久可用；无可信批准/批准被消费后重放/装配失败必须 fail-closed。保留 M0 Schema Gate 是数据准入、Risk Engine 是交易风险批准的职责划分。

## 3. R2 — Live 在 M2 必须绝对不能执行

- 先复现 LIVE policy + `approval_verifier=None` 的 `RiskEngine.evaluate` 不因缺验签器明确拒绝的情况。
- `LIVE` 一律禁真实下单，M2 本地可用仅 mock 测试/契约验证；缺失、抛异常、返回失败、过期、撤销、错误账户/hash/额度的验签函数均拒绝并审计。禁止实现任何 live broker adapter，禁止启用 `dry_run=false`。
- 对未实施的真实 Live 凭证/签批，不得以测试密钥自签来冒充人类授权。

## 4. R3 — UNKNOWN 对账与解除冻结双因子不变量

- RED：`submit_timeout` → `UNKNOWN/HALT_NEW_RISK` → `recover` 的 `get_order(found=False)` → 随后 `operator_unlock("op", "approved")`，检查此前是否能解锁。另测 broker 查单 429/5xx/超时、部分成交、持仓/现金不一致、多个 UNKNOWN 混合状态、重启再解锁。
- GREEN：解除锁必须由**可信、可持久验证的对账状态**和独立操作人批准共同决定；只提供非空字符串不是对账完成证据。严禁 agent 自签或在没有 broker 订单/持仓/现金对应事实时将 UNKNOWN 当作“未送达”。
- 若 M2 FakeBroker 尚无持仓/现金完整账本，就必须在确证不足时**保留 HALT**，而不是假装生产恢复条件已达成；可单独验证订单回报部分对账，但不能据此恢复新增风险。
- 处理 `BrokerError`/I/O/审计/Journal 错误必须 fail-closed、可重放；不要吞掉状态写盘失败。非终态仍在时不得解除风险锁。不得重做第二个 KillSwitch。

## 5. R4 — Journal 原子事务、崩溃恢复和幂等

- 以 SQLite WAL FULL 为单一权威；核实意图与第一次发送尝试的设计原子边界。推荐提供最小明确的 `record_intent_and_submitting(...)` 事务入口，统一持久 `intent + attempt`，再允许 egress；并发唯一键/CAS 状态保护、同一意图重复调用不得新增尝试或 broker 订单。可调整阶段内接口，但应迁移旧测试，禁止保留无消费者的兼容方法。
- RED 故障点覆盖：写意图前/后、写 attempt 前/后、commit 前/后、broker 调用前/后、收到 ACK 但回执持久化前、写审计失败、进程重启后恢复；证明 `0 no-intent broker sends`、`0 blind resend`、`0 duplicate order`，且未知事实保持 UNKNOWN/HALT。
- 重复提交、恢复和事件应用不能让状态机转换只在 Python 中校验而 SQLite 允许旁路写入；统一持久状态转换校验，必要时 `WHERE state=? AND version=?` CAS。
- 不要宣称持久化事务与外部 broker 写请求是分布式单原子事务；它们不可能由单个 SQLite transaction 共同承诺。

## 6. R5 — 成交回报原子处理和状态一致性

- RED：`ACKED + fill(qty)` 后 Journal 仍然 ACKED；重复相同 `broker_event_id`；部分成交后补足、超量、未知订单、乱序、取消后仍收到成交、重复 ACK/CANCEL 事件。
- GREEN：事件去重、已成交数量变化、合法状态转换**同一 SQLite 原子事务**；不能因 process_fill 返回 True 而未持久化新状态。若存在不确定/乱序无法判定，HALT/待对账而不是错误终态。
- 使用 Decimal，审计结果与 Journal 一致；可重复回放得到同一成交累计状态；单笔不得超量或产生负成交。不要引入第二套 orders ledger。

## 7. R6 — Egress fencing 的“验证→dispatch”竞争窗口

- 创建可确定性阻塞的 FakeBroker/端口钩子：A 校验通过之后暂停；B 获取更高 epoch；A 继续执行。另测试取消操作、租约过期、进程休眠恢复、WAL busy、数据库不可达；记录同一账户所有 broker writes 的真实序列。
- 接受的最小方案必须有可信**串行写入边界**，并证明在 dispatch 提交权转移时不会形成双主同时发单；要明确是否持有受信单进程订单出口/独占资格。不能靠 mock 端 `valid_fences` 假装安全。
- 不引入 Redis/Kafka/分布式锁等无消费者基础设施；若当前 SQLite 设计在任意长的真实网络调用期间不能证明互斥，保持 `MOCK_ONLY / BROKER_BEHAVIOR_UNVERIFIED`，把真正的 in-flight UNKNOWN/切主证据留给已获单独授权的 Alpaca Paper 阶段。**不得把单次 validate 解释成 broker 侧远端 fencing**。
- 不得为了通过测试而无限持有 SQLite 事务跨任意外部 I/O；如采取仅适用于 mock 的临界区，必须标注边界并禁止据此开放真实券商。

## 8. R7 — 风控强制字段与危险默认值

- 对照 v2.1 §6.2 的每个 mandatory 字段列两列：`配置/类型校验`、`执行时来源及拒绝逻辑`。至少逐项复核 gross/net、单股权重、单单 notional、每日损失、峰谷回撤、异常订单速率、bar freshness、账户快照 freshness、ACK 等待、已交收现金、margin、short、symbol pool、解锁条件。
- 未有可信输入的指标不得用零或固定值默默代替真实状态；必须拒绝、HALT 或显式保持只限合成 fixture 的能力。配置字段验证强，不等于实际风控生效。
- RED：分别越过每个强制上限，预期全部拒绝；状态缺失、过期、NaN/Infinity/float、账户错配、无外部实时行情同样 fail-closed。`max_market_bar_age_seconds`、`max_account_snapshot_age_seconds` 等不得用 `or` 逻辑意外绕过 0 或缺省含义。
- **不重写现有 RiskEngine**；只补齐真实会被使用的检查，不为 M3/M9 预建整套基础设施。如果某项需未来真实 broker/account 数据，M2 不得谎称已生产验证，保留显式 gate 标记并证明 mock 不能提升 Live。

## 9. 遗留上游数据风险与架构整洁硬门

- `artifacts/evidence/M2/upstream-data-risks.md` 中 U-1：M1 `VendorFacts` 非法枚举值可误放行。**不在 M2 整改中擅自修改 M1**，维持 `BLOCKED_DATA`；真实研究数据解除封锁前，需另获授权并通过词表/严格枚举 fail-closed 测试。U-2 数据商凭证/订阅仍 BLOCKED_ACCESS。
- **唯一职责**：只有一个 RiskEngine、一个 OMS、一个 Journal、一个 broker egress；使用 M0 `KillSwitch`、`AuditLog`、`SchemaGate`，不添加平行状态机/无消费者 adapter/重复审计日志。
- **POC 隔离**：不得将 M-1 `artifacts/poc/` 的危险恢复/幂等思路提升为正式生产逻辑；`scripts/check_architecture.py` 扩展规则要有正负例，保持静态检查已知边界。
- 开发前后的 Architecture Health 记录：`REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES / BOUNDARIES / DEBT`，说明为何新增抽象不可避免；迁移已失效的代码与测试，删除多余兼容层。
- 优先最小可证明方案；不要为了形成更多代码而增加工具/中间件/全面重写。可使用已安装的代码质量工具，但不能取代安全负例。

## 10. 验收矩阵（必须可机器复核）

| 门 | 硬要求 |
|---|---|
| Risk→OMS | 拒绝、伪造、过期、错账户/策略/build/policy、错标的/方向/数量、被重复消费的批准：**0 broker sends** |
| Live fail-closed | 无验证器、不可信/故障验证器、未签批 Live 模式：**0 writes**；仅允许 mock 契约负例 |
| UNKNOWN | 未证实 broker orders/positions/cash 对账不得 unlock；查单临时查无 ≠ 未发送；0 盲重发 |
| Journal | 设计承诺的 atomic transaction 实际落实；commit/重启/故障注入后仍 0 no-intent writes |
| Fill | 重复事件 = 0 双计；合法部分/完全成交状态在数据库持久化；非法乱序 fail-closed |
| Fencing | 旧 writer 校验后暂停，另一进程新 epoch 接管的竞态被复现实测并按明示边界阻断；0 双主、0 陈旧 dispatch |
| Risk policy | §6.2 全字段逐项映射为执行断言或明确禁止路径；不得“字段存在”即当生效 |
| 故障矩阵 | 保留旧 1,080 实例覆盖，另增加以上对抗用例；所有已注册安全负例 0 违反、完整分母和 seed 固定 |
| CI | `pip install -e '.[dev]'`、`pytest`、`check_environment.py`、`check_architecture.py`、`scan_secrets.py`、`verify_live_blocked.py`、`smoke_mock.py` 在 ubuntu/windows 实际通过；不得 skip/xfail 弱化 |
| 架构 | 边界检查 0 违反；旧正式功能/测试不削弱；无新增未解释依赖/兼容层/POC 运行依赖 |

执行 Windows PowerShell 推荐最小验证集（按仓库既定 Python 命令适配环境，不破坏已有解释器）：

```powershell
python scripts/check_environment.py
python -m pytest -q
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
git status --short
```

实际执行必须记录可复现版本/OS/解释器、命令、EXIT、失败案例和测试统计；重复测试单独说明是否占用原 1,080 分母，不得重复合并虚报。

## 11. 交付工件与证据纪律

- `docs/reviews/M2-independent-review-remediation.md`：逐条 `M2-R1..R7` 的 RED 证据、GREEN 方案、残余风险、逐项验证、审批状态及 SHA。
- `artifacts/evidence/M2/independent-remediation/`：新的 `red-tests.log`、`green-tests.log`、`checks.log`、`fault_matrix_delta.log`、可复验竞争测试报告（如有）；历史 M2 原始日志/报告不可覆盖。
- `artifacts/evidence/M2/architecture-health.md` **仅追加整改补遗**（不覆盖 A/B 历史）；必要时在 ADR-002 addendum 后续追加精确纠正条款，禁止重写历史结论。
- 三轨报告保持 `S=N_A / NOT_EVALUATED`、`R=NOT_STARTED`；E 只有在整改通过后可按 `PASS_WITH_SCOPE(MOCK_ONLY)` 提交用户复审；当前 M2 旧 CI 通过仅是旧测试范围。
- `BROKER_BEHAVIOR_UNVERIFIED`、`BLOCKED_DATA(全市场研究)`、U-1 未授权修复状态不变。任何真实 broker / Paper 实测必须单独获用户授权。
- 本地 commit 分开：代码/新增测试、报告/证据；工作树 clean。**未经用户明确批准不得 push 或启动 M3**。推送后新 SHA 的 Ubuntu/Windows CI 真实成功才能标 `M2_INDEPENDENT_REMEDIATION_VERIFIED`；最终 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`，绝不由 Agent 自签。

## 12. 必须提交的最终简报模板

```text
Baseline remote SHA: 708833d...
Local baseline: <真实 HEAD，含 30429f4 是否存在及 diff 核实>
Remediation commits: <SHA> (local-only / pushed separately)
M2-R1..M2-R7: RED evidence / GREEN files / negative tests / evidence paths
Full pytest: <N> passed / failed / skipped
Fault matrix: <new counts> + original >=1,080, 0 violations? <true/false>
Architecture Health: REUSE/MODIFY/ADD/REPLACE/REMOVE/DEBT; CI architecture checker result
Ubuntu CI: <run/sha/conclusion or PENDING>
Windows CI: <run/sha/conclusion or PENDING>
E: PASS_WITH_SCOPE(MOCK_ONLY) or REMEDIATION_REQUIRED
S: N_A / NOT_EVALUATED
R: NOT_STARTED
M1 VendorFacts U-1: UNRESOLVED / BLOCKED_DATA
Broker behavior: BROKER_BEHAVIOR_UNVERIFIED
M2_GATE: USER_PENDING
M3_START_APPROVAL: PENDING
No live broker/no credentials/no real orders/no M3/no autonomous push: CONFIRMED or exception
```

## 13. Codex 直接启动提示词

请读取本任务书 `Shutu_AI_Trading_Lab_M2_Independent_Review_Remediation_Codex_Task.md`，先核对仓库实际 HEAD、M2 v2.1 约束与已完成模块，按 R1–R7 先 RED 再最小 GREEN。严禁为了通过测试复制风控或 OMS、引入多余基础设施、削弱旧门禁；保留 FakeBroker 和 BLOCKED_DATA 限制，禁止真实券商接入。输出审查整改报告、架构健康补遗和机器可复验证据，提交本地 commit，**不推送、不关闭 M2、不启动 M3**，终止于 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
