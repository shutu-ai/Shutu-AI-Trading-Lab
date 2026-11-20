# ADR-003: 数据契约与供应准入决策（M1）

| 字段 | 值 |
|---|---|
| 状态 | ACCEPTED_WITH_SCOPE（工程子集验收；全市场研究用途 BLOCKED_DATA） |
| 日期 | 2026-11-20 |
| 阶段 | M1（数据供应准入与点时刻可得性） |
| 依据 | v2.1 §4.1、M1 任务行、M1 任务书 §1–§4 |

## 决策

### D1 — PIT 语义：三时点独立，`available_at` 是唯一准入钥匙

沿用 §2.2 契约（`ts_event_utc` / `ts_available_utc`；企业行为 `announced_at` /
`effective_at` / `available_at` 三时点独立），M1 将其落为可执行规则：
`available_at <= decision_cutoff` 才可用于决策（`calendar.MarketCalendar.
is_available`）；缺失可得时间一律显式标 `UNKNOWN_AVAILABILITY` 并降级用途，
**不得以 K 线日期冒充公告/可得时间**。
- 备选（事件表自带生效时间即可用）：拒绝——用 effective_at 代替
  available_at 正是任务书明令禁止的未来泄漏形态。

### D2 — 历史证券池只来自历史记录

`MembershipTable.universe_asof()` 仅从区间记录（含 available_at 门）推导
任何时点的成分；今天的列表在任何历史查询中不可达。退市标的水久保留查询
（`delisted_symbols`）；ticker 重用显式检测返回，不合并区间；区间重叠视为
数据缺陷拒绝构建。
- 备选（允许当前成分 + 手工修正历史）：拒绝——不可复算、不可审计。

### D3 — 复权必须可重算、版本化、受 asof 知识约束

`actions.adjust_series` 以原始价 + 因子记录重算调整价（`adj-1` 版本）；
应用动作的资格由 asof 时的可用性决定——`available_at > asof` 的动作不参与
（事后知识不回溯）；`UNKNOWN_AVAILABILITY` 动作永不静默应用而是显式上报。
预调整、不可重算口径（如 yfinance adjclose）按 §4.1 维持 `REJECT_DATASET`
约束，仅限 POC。
- 备选（直接存储供应商复权价）：拒绝——不可重算即不可验证，且因子事后
  变化无法检测。

### D4 — 质量分母显式化，零分母 = INCONCLUSIVE

`quality.py` 每项指标输出分母/缺失/观测率/样本量；延迟统计单独计数
UNKNOWN 可得性行；零分母永不报 100%。阈值在 `configs/data_acceptance.yaml`
按用途**先声明**（每字段必填，缺失即配置错误），评估时不可下调。

### D5 — 准入判定顺序固定

`acceptance.evaluate_purpose`：结构不可观测 → INCONCLUSIVE；许可未确认 →
BLOCKED_DATA；要求维度未知（未实测）→ BLOCKED_DATA；要求维度缺失 → 声明的
on_fail；质量阈值违反 → 声明的 on_fail；全部满足 → ACCEPT。
**"未知" ≠ "没有" ≠ "有"**——未经实测的覆盖一律 BLOCKED_DATA，不得乐观放行。

### D6 — 快照 manifest 确定性

`build_snapshot` 对排序后的 entries（内容 hash + 溯源链）做 canonical JSON
SHA-256：同输入同版本必同 hash；单值改动必变 hash（属性测试锁定）。复用
`security.canonical` 序列化——平台唯一字节规范。

### D7 — 边界与依赖

数据层禁止导入 oms/brokers/risk/研究执行/POC（`check_architecture.py` AST
强制，CI 接入）。新增运行依赖仅 `tzdata`（Windows zoneinfo 必需，干净环境
实测复现其必要性）。未建供应商适配层/ETL 框架——等真实授权数据源出现再按
其 API 实现（无消费者抽象不作预建）。

## 已知限制

1. **无 API_VERIFIED 供应商行**：三家候选均 BLOCKED_ACCESS（无凭证，任务
   禁止注册/购买）；全部覆盖结论为 DOCUMENTED 级（官方页声明，附 URL 与
   检索日期），PIT 粒度/延迟/退市深度的实测结论不存在。
2. 假日/半日表为运行时参数（测试 fixture 固定合成日期），真实日历待授权
   数据源接入。
3. Sharadar 是历史成分+退市的唯一可行解（M-1 结论维持），订阅价格与个人
   研究许可条款仍 UNVERIFIED（官方页 JS 渲染，订购页需登录）。

## 影响

- 满足 M1 E-Gate 的工程可执行部分（PIT 负例 100% 拦截、分母可机查、snapshot
  可重算、M0 回归全绿）。
- 按任务书 §3：全市场研究用途 **BLOCKED_DATA**；工程子集 **PASS_WITH_SCOPE**；
  完整"数据供应准入 PASS"不做声称。解除条件：用户授权订阅/凭证后完成
  API_VERIFIED 实测（M1 增量或 M3 前置）。
