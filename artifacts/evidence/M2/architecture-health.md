# M2 Architecture Health — 基线与验收记录

> M2-OMS-RISK-ARCHITECTURE-GATE-001 §2/§8。基线（开发前，HEAD `d0d81b6`）；开发后章节随实现追加。

## A. 基线（开发前，T0）

### A1. 现状依赖图（233 用例全绿基线）

```text
src/trading_lab/
  contracts/   # §2.2 契约（含 TradeIntent/DurableOrderIntent/ExecutorFence/
               #  RiskDecision/OrderEvent/LiveRelease）+ RuntimeConfig
  security/    # canonical/signing/verifier/SchemaGate/KillSwitch/audit/isolation
  data/        # M1 数据层（BLOCKED_DATA 边界持有者）
（无 risk/ oms/ brokers/ —— M2 前不存在）
tests/: contract+security 140 / no_lookahead 71 / architecture 22 = 233
```

允许依赖方向（M2 后）：risk → contracts/security；oms → contracts/security/brokers(port)；
brokers → contracts（无外部网络）。**禁止**：risk→oms/brokers；oms→risk（决策以
RiskDecision 契约数据传递）；任何 src→artifacts/poc；data 不变。

### A2. 复用清单（REUSE，不复制）

| 既有 | M2 用途 |
|---|---|
| `TradeIntent`/`DurableOrderIntent`/`ExecutorFence`/`RiskDecision`/`OrderEvent` 契约 | 意图/尝试/fence/决策/回执的唯一 DTO |
| `security.canonical` | journal/snapshot 唯一字节规范与哈希 |
| `security.KillSwitch` | HALT 状态唯一权威（不重写 halt） |
| `security.AuditLog` | 全部风险/OMS 事件的唯一审计链 |
| `security.SchemaGate` | 策略信号唯一准入（ALLOW 只代表数据准入） |
| `data.acceptance` | 合成数据边界维持 BLOCKED_DATA 的证据源 |

### A3. POC 处置（DO-NOT-PROMOTE 逐项）

`artifacts/poc/M-1/fake_broker_poc/`：**阅读参考**。
- `oms.py recover()` 的 `get_order=None → _send_once` 分支：**已知缺陷（M-1 审查 R3），正式实现绝不继承** —— UNKNOWN 一律对账，不补发。
- `fencing.py valid_fences`（mock 内存集合）：**REPLACE-IDEA** —— 正式保证在可信出口（SQLite epoch/租约），mock 仅是被出口调用的下游。
- journal 简化模型：**REPLACE** —— SQLite WAL FULL 事务方案（ADR-002-addendum D1）。
- 正式 `src/trading_lab/oms|brokers/` 零导入 POC（检查器强制）。

### A4. 拟新增（ADD，各自唯一消费者）

| 模块 | 职责 | 消费者 |
|---|---|---|
| `brokers/port.py` | Broker 写接口（submit/get/cancel）+ 结果类型 | oms.egress、fake 实现自身 |
| `brokers/fake.py` | 可重复 FakeBroker：故障注入钩子、`created_orders_by_intent` 计数 | tests/fault_injection、egress 装配 |
| `risk/policy.py` | §6.2 风控字段模型（Decimal、必填非空） | risk.engine、configs/policies yaml |
| `risk/engine.py` | 唯一 RiskEngine：冻结检查序 → APPROVE/REJECT/HALT_NEW_RISK | M3+ 交易链、tests/risk |
| `risk/producer.py` | 不可伪造 TrustedProducer 绑定（MOCK_ONLY） | risk.engine、oms 装配 |
| `oms/journal.py` | SQLite WAL FULL 意图/尝试/事件持久化 | oms.engine |
| `oms/states.py` | 订单状态机 + 合法转换表 | oms.engine |
| `oms/egress.py` | 唯一 Broker 写出口（fence 校验 + port 调用） | oms.engine |
| `oms/engine.py` | 意图生命周期：journal-before-send、UNKNOWN 语义、恢复对账 | tests/fault_injection、M3+ |

不建：风控策略 DSL、插件系统、通用厂商适配层、第二审计器、第二 Gate、消息队列。

### A5. 先红后绿计划（RED 矩阵）

新增测试先于实现写入并记录红证：journal 持久性（重启后意图仍在）、
UNKNOWN 不重发、stale fence 拒写、双进程争写、重复回报不双计、越权生产者
拒绝、≥1,000 故障组合计数断言。依赖缺失类 ImportError 单列，不算安全证明。

### A6. 冻结指标（T4）

≥1,000 次可复现故障/重放组合；累计 0 重复 fake 订单、0 双主写、0 无意图
发单、0 UNKNOWN 盲重发、0 风控越权；分母/种子/故障类分项报告；失败保留原日志。

---

## B. 开发后验收（2026-11-20，M2 实现完成）

| 分类 | 记录 |
|---|---|
| REUSE | 全部 §2.2 交易侧契约（TradeIntent/DurableOrderIntent/ExecutorFence/RiskDecision/OrderEvent/LiveRelease）零复制；`security.canonical`（journal 哈希）、`security.KillSwitch`（HALT 唯一权威，OMS 复用不重写）、`security.AuditLog`（全部风险/OMS 事件唯一审计链）、`security.SchemaGate`（信号准入前置，未复制）、`data.acceptance`（BLOCKED_DATA 边界证据源） |
| MODIFY | `scripts/smoke_mock.py`：M0 的"brokers 模块不存在"断言更新为 M2 语义"brokers 平面零网络/真实券商导入"（正则扫描）；`scripts/check_architecture.py`：扩展为 3 平面规则（data/risk/oms 各自禁用集 + 包内导入豁免 + 包边界匹配）；CI 步骤沿用（命令不变） |
| ADD | `risk/`（policy/engine/producer：唯一风控决策点，冻结检查序，Decimal 强制）、`oms/`（journal：SQLite WAL FULL；states：唯一状态机；fence：SQLite 原子 epoch+租约；egress：唯一出口校验 fence 后调 port；engine：journal-before-send+UNKNOWN 语义+恢复对账）、`brokers/`（port+fake：零网络，故障注入钩子，created_orders_by_intent 计数）；`configs/policies/risk_policy.paper.example.yaml`；`tests/fault_injection/`（矩阵 1,080 实例 + 真实双进程争写） |
| REPLACE | M-1 POC 的 journal 模型 → SQLite WAL FULL 事务方案（旧 POC 文件原样保留于 artifacts/poc，不删除历史工件）；POC `valid_fences` 思路被可信出口 fencing 替代；POC `recover()` 补发分支被 UNKNOWN-对账语义替代（不继承） |
| REMOVE | 无删除；233 基线用例全数保留并全绿（现 282 = 233 + 19 risk + 14 oms + 12 fault_injection），安全测试零削弱 |
| POC-ISOLATE | `check_architecture.py` 片段扫描（artifacts/poc）覆盖全部 3 包 EXIT=0；src 布局下 POC 不在导入路径；oms/risk 零 POC 导入 |
| DEPENDENCIES | **零新增运行依赖**（SQLite=标准库；未引入 Redis/Kafka/分布式锁/消息总线/适配层） |
| BOUNDARIES | 检查器 3 包 18 文件 0 违规（risk→oms/brokers/data 禁、oms→risk/data 禁、data→全平面禁、oms→brokers 唯一 sanctioned）；brokers 平面零网络导入（smoke 扫描）；检查器 26 自测含 12 违禁形态拦截 + plane 规则正反例；`d0367f4` 等历史提交未触碰 |
| DEBT | ①生产者跨进程身份（MOCK_ONLY/UNVERIFIED）→ 真实 Paper 阶段；②多宿主 fencing（无消费者不预建）→ Live 前；③smoke 的 brokers 平面零网络扫描是文本级（动态构造导入不可检）→ 进程隔离阶段；④M-1 POC 文件保留原样作为历史参考，其已知缺陷（recover 补发）已在正式实现中被替代语义覆盖 |

### §5 违例自查：(a)-(g) 全部无（对照 §M2-T5 清单，见上表各行依据）；重复出站调用点=1（egress）；额外凭证读取入口=0；循环导入=0（检查器扫描+导入成功）。

---

## D. 独立安全整改补遗（M2-INDEPENDENT-REVIEW-REMEDIATION-001，2026-11-20）

> 不覆盖 A/B/C 历史；本节记录 R1–R7 整改的差异。

### D1. 依赖图变化

方向不变：risk→contracts/security(+approval)；oms→contracts/security/brokers(port)。
`ApprovalSecrets` 落在 **security**（共享设施），因此 oms 不依赖 risk——平面规则
保持成立（检查器 EXIT=0 证明）。

### D2. 分类账

| 分类 | 记录 |
|---|---|
| REUSE | `security.canonical`（审批密封字节规范）、既有 RiskDecision/TradeIntent 契约字段（密封与绑定信息放 `limits_snapshot`，零契约扩展）、KillSwitch/AuditLog 原样 |
| MODIFY | `risk/engine.py`（R2 LIVE 验签器缺失硬拒 + LIVE×MOCK_ONLY 不可执行字段硬拒 + R7 net/short/single-symbol 执行 + `or` 默认值陷阱修复 + R1 HMAC 审批密封签发）；`oms/journal.py`（R4 单事务 `record_intent_and_submitting` + R4 CAS `transition_state` + R5 原子 `apply_fill` + `filled_qty` 列 + `unresolved_count`；移除无消费者的两步法 record_intent/mark_submitting/set_state）；`oms/engine.py`（R1 发送前决策校验、R3 解锁双因子、R5 原子成交、R4 迁移）；`oms/egress.py`（R6 出口后重校验，被取代写者结果不采纳）；`oms/fence.py`/`journal.py`（跨线程连接参数——仅 R6 测试模拟飞行窗口用，默认线程锁定） |
| ADD | `security/approval.py`（ApprovalSecrets HMAC 密封，约 40 行，唯一职责）；`tests/m2_remediation/`（24 个安全负例/正例） |
| REPLACE | journal 两步持久化 → 单事务原子入口（旧方法删除，测试已迁移——无兼容层） |
| REMOVE | record_intent / mark_submitting / set_state（均无消费者残留，transition_state CAS 覆盖全部转换） |
| POC-ISOLATE | 零 POC 导入（检查器不变） |
| DEPENDENCIES | 零新增（hmac/hashlib 标准库） |
| BOUNDARIES | 3 包 18 文件 0 违规；oms→security.approval 为共享设施方向（合法） |
| DEBT | R6 TOCTOU 缩窗后残余：端口调用进行中的 epoch 接管使结果降级 UNKNOWN/HALT（不被采纳）——单进程内已可证明；真实 broker 侧 fencing 归 Alpaca Paper 专项（BROKER_BEHAVIOR_UNVERIFIED 不变）。R7 六个 MOCK_ONLY 不可执行字段逐决策审计 + LIVE 硬拒（生产 Live 不可用）。R3 解锁为订单级对账（MOCK_ONLY 标注），positions/cash 证明归后续。 |

### D3. 检查器负例

`tests/architecture/` 26 项保留全绿；本整改未新增违禁方向（oms→security 合法已验证）。
