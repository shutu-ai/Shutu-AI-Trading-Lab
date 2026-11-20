# Shutu AI Trading Lab — M2 残余安全不变量定向整改 Codex 任务书

**任务 ID**：`M2-RESIDUAL-SAFETY-GATE-001`  
**目标**：解决本次独立源码审查新发现的 M2 核心安全缺口，保证“未知结果 → 全局停止新增风险”“唯一可信出站口 → 必须有持久化授权意图”以及存储层合法状态/成交数量不变量。  
**优先级**：P0/P1；仍属于 **M2 阶段内整改**，**不是 M3 启动任务**。  
**远端审查基线**：`9a69a162750d5f75a3085977b1a41d3046915708`，GitHub Actions [run 44806785967](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44806785967) Ubuntu/Windows SUCCESS（各 306 passed）。  
**适用计划**：`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md` 与 `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md` 的 M2 / §6.2 / §6.3 / E-Gate；根目录 `AGENTS.md`。  
**当前状态**：`M2_INDEPENDENT_REMEDIATION_VERIFIED`（上一轮 R1–R7）、`M2_GATE=USER_PENDING / REMEDIATION_REQUIRED`（本轮发现新的缺口）、`M3_START_APPROVAL_PENDING`；`BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED` 不变。

## 0. 不可越过的执行边界

1. **先验证用户对本任务的实施授权**。本文件的生成/读取，不等于 M2 正式关闭或 M3 启动授权。不得自动推进 M3。未经独立授权不 `git push`、不改写历史、不 force push。
2. 开始时读取上述 v2.1 计划、当前 `AGENTS.md`、M2 两份整改记录、`artifacts/evidence/M2/architecture-health.md`、既有测试；执行 `git status --short`、`git log -5 --oneline`。检查本地是否有用户所述 docs-only 提交 `9f20f23`；**只在真实存在且确认为文档补记时保留它**，禁止覆盖或推测其内容。
3. 所有测试只能使用 `synthetic-engineering-fixture`、本地 SQLite、FakeBroker、虚构账户及测试 HMAC 密钥。禁止 Alpaca/任何券商网络访问、Paper API、Live API、真实凭证、真实资金、数据服务购买/注册。
4. 禁止降低测试门槛、删除负例、变更 E/S/R 阶段含义。保留 **306 项**现有回归、**1,080 独立故障矩阵**；新增用例须单列，不重复计分。
5. **架构整洁是 E-Gate 硬指标**：只有一个 Risk Engine、一个 OMS/Journal、一个 BrokerEgress、一个 KillSwitch、一个审计链；复用既有 `RiskDecision`、`ApprovalSecrets`、fencing、状态机。禁止第二套安全系统、重复状态机、无消费者兼容层、新中间件/网络服务/数据库。确需修改内部 API，迁移消费者与测试后删除旧入口，**不为兼容 M2 短期实现留下 Wrapper**。
6. 本次是独立**源码审查发现的待复现缺陷**；先 RED 证实行为，再 GREEN 修复。若某发现已被当前本地新代码解决，给出实际源码和负例证据、标记 `ALREADY_FIXED`，不要重复实现。

## 1. 审查发现与本轮冻结范围

### R1 — P0：fence 丧失 / UNKNOWN 必须触发全局持久化 HALT

**原始源码证据**：`src/trading_lab/oms/engine.py::submit()`：

- `except FenceError` 当前仅 `journal.transition_state(intent_id, "SUBMITTING", "HALT_NEW_RISK")` 然后返回；未调用 `KillSwitch.set()`。与此同时 `RiskEngine.evaluate()` 和 `OmsEngine.submit()` 在新增意图入口只检查 `KillSwitch`，不会仅因别的意图状态是 `HALT_NEW_RISK` 而拒绝新单。
- `receipt.acknowledged is None` 分支当前仅把意图改为 `UNKNOWN` 然后返回 `halted=True`；没有设置全局 KillSwitch、未将风险停止落入独立持久态。`halted=True` 是返回标记，不是实际风险阻断。

**必须先写 RED 测试**：

1. 有效且已密封的意图 A 在 egress 校验前后失去 fence；验证 A 被标记不确定后，使用**新的合法 fence**、新的已密封意图 B 尝试发出，整改前能否误放行；**期望 B 0 broker 创建 + KillSwitch 持久 HALT**。
2. 自建仅本地 Fake Broker Port 返回 `SubmitReceipt(delivered=True, acknowledged=None, ...)`；验证 UNKNOWN 后 KillSwitch 激活，下一笔已批准意图仍 0 broker 创建。
3. 崩溃发生在 journal 已写 `SUBMITTING`、尚未来得及设置 KillSwitch：重启/恢复入口必须先发现可能已发送的未知意图并阻断后续新增风险；不得把记录视为“未发送所以可以重试”。
4. HALT 持久化、审计不可用/失败、journal 故障的 fail-closed 行为。**不能通过随意捕获异常并报告 `halted=True` 来冒充全局保护**；失败必须使可信执行入口无法继续风险发送。

**GREEN 原则**：最小改动现有 OMS/Journal/KillSwitch；建立真实、可验证的跨订单 `HALT_NEW_RISK` 不变量。统一不确定回执与 fence 失效的处理语义；不得把“订单级 HALT”误当“账户级 HALT”。保留审计与 UNKNOWN 永不盲重发。

### R2 — P0：BrokerEgress 不得凭 fence 直接无意图发送

**原始源码证据**：`src/trading_lab/oms/egress.py::submit(token, coid, symbol, quantity, side)` 只做 fencing 检查就调用 `BrokerPort.submit_order(...)`，**不检查 Journal 是否存在相应已批准、已持久化、字段精确绑定的意图/尝试**。M2 v2.1 E-Gate 要求“0 无意图直接发单”。

**必须先写 RED 测试**：

1. 构造有效 fence，直接调用公开 `BrokerEgress.submit()`，无对应 Journal 意图：整改前 FakeBroker 创建，**整改后必须 0 创建**。
2. Journal 仅有非法/未批准/未密封/已失效/错误账户环境/错误 `coid`/不匹配 symbol、side、quantity、policy_hash、fence_epoch 的记录：均为 0 创建。
3. 对已合法提交过的同一意图，直接重放 egress submit（单线程及双实例模拟）：**不得第二次到达 FakeBroker**，不能指望 FakeBroker 幂等遮掩。
4. Journal/审计/送达资格校验不可用时必须在调用 Port **之前**拒绝，`created_orders_by_intent` 保持 0。
5. 合法“RiskEngine 密封批准 → OMS 单事务 Journal → 唯一 Egress → FakeBroker”正例仍可产生且只产生一单。

**GREEN 原则**：出站口必须检查**权威 Journal 中的 durable send eligibility**（可在现有 attempt/intent 记录中添加必要且最小的字段/状态或原子发送 claim），并验证现有 ApprovalSecrets 绑定；禁止创建第二个审批引擎。发送资格消耗/并发抢占必须是持久、原子的；进程在资格 claim 之后崩溃，恢复也不能盲重发。更新 OMS→Egress 内部装配和测试；迁移后删除无保护调用入口（不保留后门）。对 `cancel()` 也执行相同账户/订单权限与持久存在性检查；只读 `get_order` 不必制造无关复杂度。正式 `brokers` 写接口调用只能在唯一可信出口；保持合法的测试 fake 注入能力。

### R3 — P1：CAS 必须同时约束合法状态机

**原始源码证据**：`oms/journal.py::transition_state(intent_id, expected, target)` 只执行 `UPDATE ... WHERE state=expected`，并未调用 `oms/states.py::validate_transition(expected, target)`。当前说法“存储层强制状态机”不完全成立。

**RED**：已有 ACKED 记录调用 `transition_state(id,"ACKED","NEW_INTENT")`、UNKNOWN→SUBMITTING、FILLED→ACKED、任意未知状态，验证整改前可能更新；GREEN 必须均拒绝且数据库状态/版本不变。合法转换、CAS 并发失败保留原行为；不要建立第二套合法转换表。

### R4 — P1：成交数量必须是严格正的有限 Decimal

**原始源码证据**：`oms/journal.py::apply_fill` 只检查 `new_filled > quantity`；没有先拒绝 `qty <= 0`、`NaN`、`Infinity`、float 或不合法类型。**负数成交可能减少累计成交量**。

**RED/GREEN**：零、负、负无穷、NaN、float、非 Decimal 输入全拒；无事件插入、无累计/状态更新、无审计误报成功；合法部分成交、足量成交、重复事件、超额成交继续通过。采用现有 Decimal/契约规范，避免新金额模型。

### R5 — P1：OMS 本地环境/账户/策略门与政策 hash 必须强绑定

**原始源码证据**：`OmsEngine` 构造参数 `expected_policy_hash=""` 为可选默认；`submit()` 对 `intent.environment/account_id` 没有显式与 `self._env/_account` 比较。虽然 HMAC 绑定了意图和决策、正常装配时预期一致，仍需验证**错误装配**和**缺省 pin**是否能把 Paper 许可送到不匹配的 OMS/Fence。

**RED/GREEN**：交叉账户/环境/无期望 policy hash 的入口必须拒绝**而非依赖调用方正确装配**，不生成订单；正常 Paper 正例保留。只增强现有构造验证/发送前验证，禁止新增运行模式。Live 继续硬拒，永不接入真实 Broker。

## 2. 实施顺序和提交策略

1. **T0 基线与责任盘点**：给出风险点、现有函数调用图、已存在的 `ApprovalSecrets`/KillSwitch/Journal/Port 复用、修改/替换/删除清单。先核实本地提交、工作树与远端 SHA。记录原有 306 用例和 1,080 故障组合的分母。
2. **T1 RED**：先仅新增定向负例并运行，捕获真实错误结果，单独保存 `red-tests.log`。不得把 ImportError、无关环境异常充作安全缺陷复现。
3. **T2 GREEN**：按 R1 → R2 → R3 → R4 → R5 最小改动现有模块。避免为当前测试引入未来 M3/M4 的功能。
4. **T3 对抗验证**：重点在同一新 fence、多线程/多进程重放、ACK 未知、端口回执不完整、Journal 中断和进程重启场景中证明**0 无意图/未批准/重放创建、0 未解决 UNKNOWN 新增风险**。可增加定向矩阵，但不能把旧 1,080 份报告当作新增矩阵计数。
5. **T4 架构健康**：检查可达生产路径唯一性；合法 BrokerPort 写调用只有 Egress；oms↔risk、data→OMS 禁止；`src`→POC 0 依赖；重复模块/不必要 Adapter/旧入口零保留。优先扩展既有 `scripts/check_architecture.py` 和自测试，而不是另写一套检查器。
6. **T5 全量回归**：至少 `python -m pytest -q`（基线 306 + 新增）；`python scripts/check_environment.py`；`python scripts/check_architecture.py`；`python scripts/scan_secrets.py`；`python scripts/verify_live_blocked.py`；`python scripts/smoke_mock.py`；`git diff --check`；单独完整运行原 1,080 故障组合并记录种子、总分母、0 违例及任何实际异常。所有检查必须有退出码/原始日志。
7. **T6 文档、提交、停止**：向 `docs/reviews/M2-residual-safety-remediation.md`、`artifacts/evidence/M2/residual-safety/`、`artifacts/evidence/M2/architecture-health.md` **追加新证据**；不覆盖既有 M2/M1 报告或原始 red/green/CI 日志。生成本地独立提交、记录 SHA 和工作树状态，未获授权不 push。禁止修改阶段批准状态或自动开始 M3。

## 3. Architecture Integrity & Code Quality（硬门）

- **REUSE**：`contracts`、`security.ApprovalSecrets`、`KillSwitch`、`AuditLog`、`oms.journal`、`oms.states`、`BrokerEgress`、`FenceCoordinator`，不创建第二份对应实现。
- **MODIFY**：原则上只在 `oms/engine.py`、`oms/egress.py`、`oms/journal.py` 与其直接 tests、必要的既有架构检查器内调整；如必须更广，请在报告中逐项解释实际消费者和必要性。
- **REPLACE / REMOVE**：如果改变原有不安全内部 API，必须迁移所有真实消费者并删除旧 API；不允许并存“安全新版+不安全兼容旧版”。
- **ADD**：只允许有直接测试和消费者证明的极小抽象/字段。任何新依赖、网络服务、消息队列、第二数据库或独立 BrokerAdapter 默认不批准。
- **SECURITY NON-REGRESSION**：签批/密封/TTL、FakeBroker 限制、原子 journal、fencing、UNKNOWN 恢复、PIT / BLOCKED_DATA 必须不退化。
- **E-GATE**：提交 `architecture-health.md` 增量章节，说明真实增加/删除的代码、依赖方向、旧代码清理、复杂度变化和可复现证据。若新功能通过增加平行实现/绕过旧安全门实现，则 E-Gate FAIL。

## 4. 证据路径与验收报告模板

最少新增且**不得覆盖历史**：

```text
docs/reviews/M2-residual-safety-remediation.md
artifacts/evidence/M2/residual-safety/
  baseline.md
  red-tests.log
  green-tests.log
  verification.log
  fault_matrix_residual.log
artifacts/evidence/M2/architecture-health.md  # 只追加新节
```

最终报告严格包含：

| 字段 | 要求 |
|---|---|
| baseline_sha / local_head | 实际 SHA，是否有未推送 docs-only 提交 |
| R1–R5 | 原缺陷复现、最小修复、源文件、正负例、残余边界 |
| regression | 现有 306 原样回归 + 新增 tests，不得用合计掩盖删测 |
| fault matrix | 原 1,080 独立验证分母 + 新增定向用例单列，seed/0 violations |
| local gates | 每条命令、完整日志路径、EXIT code |
| Ubuntu / Windows CI | **新最终 SHA** 对应真实 run ID 和真实 job 结果；未推送则 PENDING |
| architecture health | REUSE/MODIFY/ADD/REPLACE/REMOVE/DEBT，POC 与 Broker 唯一出口证据 |
| E / S / R | E 仅 MOCK_ONLY 范围可复核；S=N_A/NOT_EVALUATED；R=NOT_STARTED |
| data/broker | `BLOCKED_DATA`、M1 U-1 UNRESOLVED、`BROKER_BEHAVIOR_UNVERIFIED` 不改变 |
| gate / approver | `M2_GATE=USER_PENDING`，`M3_START_APPROVAL_PENDING` |

**重要**：原始 GitHub Actions `44806785967` 的全绿只适用于 `9a69a16`；新代码必须推送并获得 Ubuntu+Windows 全绿后，才可以称为 `M2_RESIDUAL_SAFETY_REMOTE_VERIFIED`，且仍**不等于**由 Agent 自动关闭阶段门。

## 5. 最终停止条件

- 本地修复通过：`M2_RESIDUAL_SAFETY_LOCAL_PASS / CI_REMOTE_PENDING / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
- 获得用户**独立推送授权**且新 SHA 双平台 CI 全绿后：`M2_RESIDUAL_SAFETY_REMOTE_VERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
- 只有在用户确认 M2 正式关闭后，才可**另外申请** M3「透明规则基线、现实回测与冻结研究协议」的启动授权。未来 M3 的工程研究可以使用 synthetic fixture；但全市场真实研究数据仍 `BLOCKED_DATA`，不得申报任何真实 Alpha/OOS 证据，M9 最终 Holdout 永远不得由 M3 提前解封。
- 未经授权不得连接真实券商、动用资金、购买数据、推送代码、签批 M2、启动 M3/M3.5。

## 6. 交给 Codex 的实际启动语句

> 阅读并执行仓库中的 `Shutu_AI_Trading_Lab_M2_Residual_Safety_Gate_Codex_Task.md`。核实基线与本地文档补录提交，按 R1–R5 先 RED 后 GREEN；仅对既有唯一 OMS/Journal/KillSwitch/BrokerEgress 做最小安全整改，严禁创建平行功能或兼容层。回归原有 306 用例和 1,080 故障矩阵，新增对抗用例独立计数，保存完整日志及 Architecture Health 增量报告。只能使用合成数据 + 本地 FakeBroker，不能连接真实券商或进入 M3。未经单独授权不得推送；停在 M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING。
