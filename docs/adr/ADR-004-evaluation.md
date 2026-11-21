# ADR-004 — M3 评估协议、回测可信度与验证边界

- 状态: ACCEPTED（M3 SYNTHETIC_ENGINEERING_ONLY 范围内）
- 日期: 2026-11-21
- 关联: v2.1 §4.2/§4.3/§4.5、ADR-003（数据契约）、M3-R1 任务书 T2/T3/T4/T5

## 背景

M3 引入研究层（`trading_lab.backtest` / `trading_lab.validation`）。3505799 曾以一份
仅声明的 YAML（含 `max_drawdown_pct: 100` 这类无约束阈值与两个布尔"公平"标志）冒充
协议冻结。本 ADR 固化本轮修复后的评估治理规则。

## 决策

### 1. 协议权威与哈希冻结
- `configs/evaluation_protocol.yaml` 是唯一权威协议；`trading_lab.validation.protocol`
  是唯一加载器，fail-closed（缺文件/缺受控节/不可解析即 ProtocolError）。
- `protocol_hash` = `security.canonical.canonical_digest(整个解析后 payload)`。
  **不建第二套 canonical**；任何受控字段变更必然改变 hash = 新协议版本。
- 加载后的对象运行时不可变（属性写入抛 AttributeError，视图为 mappingproxy/tuple）。
- 当前冻结版本 hash：
  `9158028541dc0fc7bc6f96b5291d1bee2f43277e055d962ef13f23b684b6e587`

### 2. 诚实的门（Gate）语义
- SET 门（合成范围内可约束、可执行）：`conservation` / `pit` / `determinism`
  （附 `validation.min_bars`、`min_trades_for_stats` 等工程阈值）。
- NOT_SETTABLE 门：`statistical_alpha` —— 合成数据不存在可辩护的效应量/显著性/
  样本功效依据，其 verdict 恒为 `INCONCLUSIVE`，永不出 PASS。
- **删除** `max_drawdown_pct: 100` 之类的名义阈值：各臂如实 REPORT 回撤/尾损等指标，
  但不声称存在实际上不约束任何东西的"风险门"。

### 3. 预算与公平性
- 等试验预算是主因果预算：per-arm 结构（B0/B1/B2 各 1 次），失败与重试同额计费
  （`failure_retry_billing: ALL_BILLED`），由试验账本（T5）fail-closed 执行。
- 等经济预算如实标注 `NOT_APPLICABLE_YET`：M3 各臂不消耗 LLM/人工预算，美元对等
  声明在此范围为空话；结构现_registered_，M4（B6/B7）激活时继承同一冻结定义。
- 多重比较：全部试验（成功/失败/重试/不完整）入账本，按实际计数报告；校正方法
  仅在适配样本结构时使用，否则报原始计数 + INCONCLUSIVE。

### 4. 回测内核可信度（T3 规则）
- bar 语义唯一来源 `contracts.MarketBar`（删除桩 `Bar`，不保留第二套 bar 类型）。
- Decimal 全链；负/零价格数量、float 混入、资金不足买、超持仓卖、缺权益价、
  无效/重复时间戳一律 fail-closed 拒绝。
- 现金守恒：`cash_available + cash_unsettled(+在途费用) + 成本 = 初始现金 − 净买额…`
  事件级可复算；T+2 交收是协议假设，不冒充真实券商保证。
- 未来信息隔离：`available_at <= decision_at`；收盘信号当根收盘不得成交
  （`order_delay_bars: 1`，执行价为决策后可达报价）；成本含 spread/slippage/
  commission，量上限 10% bar volume，部分成交/未成交为事件。
- 确定性：同 seed + protocol_hash + dataset_hash + code_hash → 输出 digest 在
  `decimal_tolerance` 内一致；不使用系统时间或未显式随机源；缺源数据 fail closed。

### 5. cohort 卫生与封存（T5 规则）
- Train/Validation/滚动历史 OOS/Sealed-final/前向 cohort 边界不可重叠；按日期、
  symbol、事件 ID、标签区间与 `available_at` 检测重叠；跨界标签 Purge/Embargo；
  overlap 报告固定产出（`cohort-overlap-report.md`）。
- Sealed Holdout：M3 仅登记 `SEALED_NOT_MATERIALIZED`（真实数据 BLOCKED），不伪造
  sample ID/dataset hash；候选选择规则现以文字预注册（M8 末独立治理选唯一候选）；
  研究角色的读/聚合/差分/重复探测全部拒绝并审计；一次合法解封即
  `polluted_for_future_selection=true`，二次解封与再选冠军无条件拒绝。
- 应用边界模拟 ≠ OS 沙箱：权限模拟的剩余限制如实标注，OS 级隔离归 M4。

### 6. 研究包架构边界（T6 规则）
- `backtest`/`validation` 允许导入 `contracts`（只读契约）与 `security`（canonical/
  审计 digest）；禁止导入 `oms/risk/brokers/data`、POC、artifacts，禁止任何网络
  或密钥载入；`data` 层禁止导入研究包（既有方向规则的镜像扩展）。
- 唯一 OMS/Risk/Broker 与 M1 数据准入权威不变；M3 不引入第二执行器/订单持久化/
  事件总线。

## 后果
- 正面：协议可验证（hash 变更即检测）、INCONCLUSIVE 语义可执行、预算公平性结构化、
  回测结果可复算可审计。
- 限制：合成范围结论仅为 ENGINEERING_ONLY；`statistical_alpha` 恒 INCONCLUSIVE；
  OS 级封存隔离与美元预算对等留待 M4；真实数据解封仍被 BLOCKED_DATA/U-1 阻断。

## 验证
- `tests/validation/test_protocol.py`（25 项）：hash 确定性/受控变更→新 hash（9 节探针）/
  fail-closed/运行时不可变/诚实门/预算结构/封存登记。
- `tests/backtest/`、`tests/validation/` 其余套件见 T3–T5 证据。
