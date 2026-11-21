# M3-R1 T2 — 协议注册、哈希冻结与审计硬门

- 日期: 2026-11-21
- 协议文件: `configs/evaluation_protocol.yaml`（唯一权威，重写以补治理能力）
- 加载器: `src/trading_lab/validation/protocol.py`（唯一 sanctioned 加载器）

## 冻结事实（当前生效版本，v1.1 修订后）

| 项 | 值 |
|---|---|
| protocol_id / version | `m3-synthetic-engineering-v1` / 1 |
| **protocol_hash（现行）** | `48dee8613dd727b3fce04230851c75062c9a6e85e634709d8bab09df1cf6ed83` |
| 计算方式 | `security.canonical.canonical_digest(整个解析 payload)` —— 复用既有 canonical，无第二套实现 |
| SET 门 | conservation / pit / determinism + validation 工程阈值（min_bars=100, min_trades_for_stats=10） |
| NOT_SETTABLE 门 | statistical_alpha → verdict 恒 INCONCLUSIVE（无真实数据依据不出 PASS） |
| 已删除假阈值 | `max_drawdown_pct: 100`（3505799 桩中的无约束名义门） |
| 预算 | per-arm 等试验预算结构（B0/B1/B2 各 3 = ×1/×2/×3 各一次官方运行，首 seed；失败/重试同额计费）；等经济预算 `NOT_APPLICABLE_YET`（M4 继承冻结定义） |
| M9 Holdout | `SEALED_NOT_MATERIALIZED`；sample_ids/dataset_hash = null（不伪造）；max_unlocks=1；候选选择规则已文字预注册（M8 末独立治理执行） |
| B3–B8 | 定义冻结登记（enabled=false），M3 不建空壳代码 |

## 修订记录（先声明后执行；修订早于任何官方实验消耗旧 hash）

| 版本 | hash | 变更 | 依据 |
|---|---|---|---|
| v1.0（T2 初冻结） | `9158028541dc0fc7bc6f96b5291d1bee2f43277e055d962ef13f23b684b6e587` | 初次治理冻结 | 本文档上文（原表） |
| v1.1（现行） | `48dee8613dd727b3fce04230851c75062c9a6e85e634709d8bab09df1cf6ed83` | per_arm_trials 1→3（×1/×2/×3 各一次官方运行；种子固定 protocol.seeds[0]；跨种子确定性由测试套件强制，不额外计费） | T7 官方实验矩阵与预算必须同源；修订发生在任何 ledger TRIAL 记录之前（`experiment-ledger.jsonl` 首条 TRIAL 引用即为新 hash，可验证） |

修订合法性：AGENTS.md 规则 8 要求"先声明后执行"。v1.0 仅被测试套件（非官方实验）
消费过；官方账本（`experiment-ledger.jsonl`）的全部条目绑定 v1.1 hash。两版 hash
均留存于本文件，禁止事后改写——任何后续变更将产生 v1.2 新 hash。

## RED → GREEN

- RED（`t2-red.txt`）：测试先行，25 项全部 FAILED（`trading_lab.validation.protocol`
  不存在，ImportError），证实测试真实约束实现。
- GREEN（`t2-green.txt`）：实现后 **25 passed, EXIT=0**。

## 覆盖的治理断言（25 项）

1. 加载 + hash 绑定；hash 跨进程重载确定（3 项）
2. hash = canonical_digest(payload)（无私有 canonical 化）（1 项）
3. 冻结完备性：9 个受控节探针（seeds/cost_model/execution/pit_rule/arms/budget/
   validation/holdout/multiplicity）任一受控字段变更 → 新 hash（9 项参数化）
4. fail-closed：缺文件、缺 `budget` 节拒绝加载（2 项）
5. 运行时不可变：属性写入 AttributeError；budget 视图写入 TypeError（2 项）
6. 诚实门：无不设限名义阈值；NOT_SETTABLE → INCONCLUSIVE；工程门 SET；
   `max_claimable_evidence=ENGINEERING_ONLY` 禁止合成结果声称 alpha（4 项）
7. 臂与预算：B0–B2 enabled、B3–B8 冻结登记非空壳；预算为结构非布尔；
   limits 可枚举供账本执行（3 项）
8. 封存登记：SEALED_NOT_MATERIALIZED、无伪造 ID、max_unlocks=1、选择规则与
   verdict 状态齐全（1 项）

## 与旧桩（3505799）的差异声明

| 旧桩问题（独立审查 P1） | 本轮处置 |
|---|---|
| "文件标题写 frozen 视为冻结完成" | hash 冻结 + 运行时不可变 + 变更即新版本，机器可验证 |
| `equal_*_budget: true` 两布尔冒充公平 | 结构化 per-arm 预算 + ALL_BILLED 计费规则 + 经济预算诚实 NOT_APPLICABLE_YET |
| `max_drawdown_pct: 100` 无约束阈值 | 删除；指标如实报告，无假风险门 |
| 无 M9 选择规则/封存状态 | 选择规则文字预注册 + SEALED_NOT_MATERIALIZED + 一次解封污染语义 |
