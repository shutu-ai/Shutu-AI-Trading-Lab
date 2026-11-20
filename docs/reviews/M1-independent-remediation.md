# M1 独立验收定向整改记录（M1-REVIEW-REMEDIATION-001）

| 字段 | 值 |
|---|---|
| 任务 ID | M1-REVIEW-REMEDIATION-001（任务书：仓库根 `Shutu_AI_Trading_Lab_M1_Review_Remediation_Codex_Task.md`） |
| 远端基线 | `db25064`（CI run `44770370359` 双矩阵 PASS，187 tests——仅代表旧代码） |
| 本地基线 | **`a1a18cb`**（领先远端 1 提交：仅 `M1-engineering.md` 1 行 CI 结果补录，docs-only；真实存在、未推送、未覆盖，按其内容沿用） |
| 执行日期 | 2026-11-20 |
| 性质 | M1 原阶段范围内缺陷复现（RED）→ 最小修复（GREEN）→ 全量回归；不降低任何冻结阈值，不重做 M1 |
| 三轨地位 | `M1-engineering/strategy/real-capital.md` 原状保留（策略/资金两轨未提升）；本文件为补充整改记录 |
| approver | **USER_PENDING**（M1 阶段门 + 推送 + M2 启动均待用户决定） |

## 0. 执行协议记录（§0.2）

`git status --short` 干净（仅任务书自身未跟踪）；HEAD=`a1a18cb`；`git diff --check` 干净；`a1a18cb` 仅改 1 行文档（已核实），与新整改提交的先后关系：a1a18cb → 本次整改提交（后续 SHA）。无并行工作需要规避。

## 1. R1 — PIT 能力实质参与准入（P0）→ **PASS**

- **RED 复现**：直接脚本证明 `pit_availability='none'` 的供应商在其他条件全满足时获 `historical_research_daily` **ACCEPT**（整改前判定根本不读该字段）；测试 `test_full_research_pit_none_must_not_accept` 等 6 例先红（`red-tests.log`）。
- **GREEN**：`src/trading_lab/data/acceptance.py`
  - **PIT 兼容矩阵**：`available_at_rule ∈ {announced_or_published_before_use}` 要求 `event_level`（`eod_only` → `PIT_GRANULARITY_INSUFFICIENT`，`none` → `PIT_CAPABILITY_ABSENT`）；bar 级规则要求至少 `eod_only`（`none` → absent）；`unknown` 一律 `BLOCKED_DATA`（未实测 ≠ 没有 ≠ 有）。判定只看 `VendorFacts` 层级化事实，不接受营销声明。
  - **记录层双重校验保留**：数据行本身缺 `available_at` → `UNKNOWN_AVAILABILITY_PRESENT` 仍独立拒绝（供应商声称具备 PIT 不能替数据放行）。
  - **规则词表**：`available_at_rule` 限定 `{bar_ts_plus_0, bar_ts_plus_15min, announced_or_published_before_use}`，拼写错误在配置加载即拒（无 DSL、无规则引擎）。
  - 正例更新：全条件满足且 `event_level` → ACCEPT（原 `pit='none'` ACCEPT 已修正并留回归锚点 `test_historical_research_pit_none_no_longer_accepts`）。
- **层级不变**：`VendorFacts` 仍全部来自 DOCUMENTED/BLOCKED_ACCESS；全市场研究用途维持 **BLOCKED_DATA**，未冒充 API_VERIFIED。

## 2. R2 — 质量阈值统一、零分母不误放行（P1）→ **PASS**

- **RED**：`min_coverage_rate` 声明后从未被 `evaluate_purpose` 消费（代码审查 + `test_stricter_min_coverage_is_consumed` 先红）；`bar_completeness` "缺 1 根即失败" 覆盖了预声明缺失率（`test_bar_missing_within_tolerance_not_a_failure` 先红）。
- **GREEN**：
  - **唯一公式**：`missing_rate = missing/denominator`、`coverage_rate = observed/denominator`，零分母 → INCONCLUSIVE；`QualityReport.failures` 与 `evaluate_purpose` 同一比率语义（bar 不再任何缺失即败）。
  - **配置一致性**：`min_coverage_rate < 1 - max_missing_rate`（宽松/死配置）加载即拒；相等=同严格，更大=更严格且**真实参与判定**（`COVERAGE_RATE_BELOW_MIN`）。
  - **冻结判定优先级**（测试锁定）：①许可未确认 → BLOCKED_DATA；②PIT/覆盖 unknown → BLOCKED_DATA；③字段/分母/延迟零样本 → INCONCLUSIVE；④PIT 缺失/粒度不足、覆盖缺失、质量超阈 → on_fail；⑤全过 → ACCEPT。零分母+许可不明并存 → BLOCKED_DATA（顺序与输入构造无关）。
- **验收对照**：延迟 0 样本 → INCONCLUSIVE；少量允许缺失不失败；超阈失败落预声明 on_fail；交叉边界（相等/略高/略低/矛盾配置）各有用例。

## 3. R3 — 历史成员区间重叠拒绝（P1）→ **PASS**

- **RED**：不同起点重叠区间被接受（直接脚本证明 + `test_overlapping_different_starts_rejected` 等先红）。
- **GREEN**：`MembershipTable._check_interval_overlaps` 对每 `(index_id, symbol)` 按 `effective_from` 排序，半开区间 `[from, to)` 语义：重叠拒、开区间后接任何记录拒、边界相接（`to == next.from`）允许、间断允许、跨指数同 symbol 独立。PIT 门（`available_at <= asof`）与"不拿当前池替代历史池"语义原样保留，未建第二套 store。

## 4. R4 — 架构检查器证明有效（P1）→ **PASS**

- **RED**：21 个检查器自测先红——`from trading_lab import oms` 漏报、相对导入无解析上下文（检查器无 package 参数）、`oms_tools` 前缀误报、越包相对导入无规则。
- **GREEN**：`scripts/check_architecture.py`
  - 包边界匹配（`oms` 及子路径禁止，`oms_tools` 不误报，非 ASCII 形近不误报）；
  - `ImportFrom` 同时检验模块与**成员名**（`from trading_lab import oms` 可拦）；
  - 相对导入按 PEP 328 以文件包上下文解析（`from .. import oms`、`from ..oms import X` 可拦）；
  - 越出顶层包的相对导入 fail-closed 记违规；
  - 常量动态导入（`__import__`/`import_module`）保留。
- **诚实边界**（docstring 记录）：静态字面导入 + 常量动态导入可检；变量化动态导入/exec/C 扩展不可检——归后续阶段进程隔离，不宣称能拦任意动态执行。仓库 `data` 包实测 0 违反；CI 步骤保留（远端验证 CI_REMOTE_PENDING）。

## 5. R5 — 快照完整性 ≠ 研究准入（P1）→ **PASS**

- **RED**：`research_admissible` 不存在（ImportError）；hash 正确 + `UNKNOWN_AVAILABILITY` / `available_at > cutoff` 的 manifest `verify()` 通过即被当作可用。
- **GREEN**：`snapshot.research_admissible(manifest)` 显式 PIT 门：完整性失败、未知可得时间、可得时间晚于 knowledge_cutoff、naive 时间戳 → 逐项 reason 拒绝。`verify()` 语义与 API 未动。ADR-003 新增 **D8**：完整性 ⊥ 时间有效性/许可/准入为正交属性，"snapshot hash PASS" 不得引述为"研究准入 PASS"；研究使用需 ① 本门 + ② 用途级 acceptance 判定同时满足。未造第二套 manifest/数据模型。

## 6. R6 — 证据与报告闭环 → **PASS（远端 CI = CI_REMOTE_PENDING）**

- 证据（不覆盖式，`artifacts/evidence/M1/remediation/`）：`red-tests.log`（整改前红：21+ 失败/错误含直接缺陷证明）、`green-tests.log`（**233 passed**）、`verification.log`（命令/退出码/解释器 3.13.15/分项计数：contract+security 140、no_lookahead 47+33、architecture 13——以 verification.log 实际计数为准）。
- 原三轨报告与 `architecture-health.md` A/B 节历史未覆盖；架构整改补遗见其 **C 节**；`M1-engineering.md` 不需勘误（本整改未推翻其结论，仅在其范围内收紧判定）。策略/资金两轨未提升。
- `a1a18cb` 处理：按任务书 §8.5 沿用其内容（旧 CI 补录），新旧 CI 不混淆——**旧 CI（db25064, run 44770370359）不代表本整改代码；新代码远端 CI 未跑**（无推送授权）。
- 供应商证据层级不变：无 API_VERIFIED；全市场研究 **BLOCKED_DATA** 不解除。

## 7. 状态与停止声明

**`M1_REMEDIATION_VERIFIED / M1_ENGINEERING_CLOSED_WITH_DATA_BLOCK / M2_IN_PROGRESS`**（2026-11-20 第三次更新）

- **门记录**：用户于 2026-11-20 经审批核查点明确确认（AskUserQuestion 记录）两项**相互独立**的授权：①批准关闭 M1 工程门（`M1_ENGINEERING_CLOSED_WITH_DATA_BLOCK`，**BLOCKED_DATA 不解除**，全市场研究数据准入维持封锁）；②授权启动 M2（`M2-OMS-RISK-ARCHITECTURE-GATE-001`，范围仅合成数据 + Fake Broker，含 ≥1,000 次故障注入）。M2 结束停在 `M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。
- 远端 CI 双矩阵 PASS 于最终代码 SHA（run `44777967708`，URL 见上）。本地：233 用例全绿，工作树 clean。
- **BLOCKED_DATA 不解除**（无 API_VERIFIED，供应商凭证/订阅仍缺失）；S=N_A、R=NOT_STARTED 不变。
- approver = **USER_APPROVED**（M1 关闭 + M2 启动，2026-11-20，用户直接确认）。
