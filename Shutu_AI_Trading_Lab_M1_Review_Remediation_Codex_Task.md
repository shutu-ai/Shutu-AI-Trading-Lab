# Shutu AI Trading Lab — M1 独立验收定向整改 Codex 任务书

> **任务 ID**：`M1-REVIEW-REMEDIATION-001`  
> **工作类型**：M1 原阶段范围内的缺陷复现、最小修复、测试补强及审计闭环  
> **设计依据**：仓库内两份 `docs/plans/*v2.1.md`、`AGENTS.md`、`docs/adr/ADR-003-data-contract.md`、`docs/reviews/M1-*.md`  
> **已核实的远端基线**：`main = db250644690d77dced6ba05b301a6198db078f59`；GitHub Actions `44770370359` 的 Ubuntu / Windows 两个 job 均 PASS（各 187 tests）  
> **可能存在的本地更新**：用户报告未推送的 `a1a18cb`（仅补录远端 CI 结果）；执行时必须检查本地 HEAD、状态及提交差异，不得覆盖或假定它已上行。  
> **本任务不构成阶段批准**：`M1_GATE=USER_PENDING / M2_START_APPROVAL_PENDING`，未获批准不得进入 M2。

## 0. 执行协议（必须先读）

1. 阅读两份 v2.1 计划的 **M1 任务、E-Gate、PIT / BLOCKED_DATA** 约束，阅读 `AGENTS.md`、ADR-003、现有 M1 三轨报告、`architecture-health.md` 和当前源码与测试。**文档中的不一致不得通过悄悄降低标准来解决**。
2. 检查并记录：`git status --short`、`git rev-parse HEAD`、`git log --oneline -8`、`git remote -v`、`git diff --check`。若存在非本任务变更，先记录归属，避免覆盖；已存在的 `a1a18cb` 只按其真实内容处理。
3. 先用针对性测试复现每个问题（**RED**），保存测试名和实际失败输出；再做最小修复（**GREEN**），最后运行全量回归。对于无法复现的审查发现，须用源码路径与实验说明为什么不成立，不能凭主观宣称 PASS。
4. 修改范围原则上仅限 `src/trading_lab/data/`、`configs/data_acceptance.yaml`、`scripts/check_architecture.py`、`tests/no_lookahead/`、架构检查器测试、M1 文档与证据。若必须修改其他生产代码，先在整改报告中写明必要性及架构影响。
5. **禁止**：购买/注册数据服务、获取或使用供应商凭证、进行 Alpaca Paper/Live 调用、启动 OMS/M2/M3、声称 Alpha 验证、开放真实资金权限、修改既有冻结验收阈值来取得 PASS、修改 M0/M1 原始历史日志、无授权 push 或 force push。
6. 即使本地通过，**仍停止在人工阶段门**；远端 CI 需经用户另行授权 push 后取得真实运行证据，不能提前标为 PASS。

## 1. 整改清单与优先级

| ID | 优先级 | 当前发现（需要先复现） | 处理边界 |
|---|---|---|---|
| R1 | P0 | `VendorFacts.pit_availability` 已声明但 `evaluate_purpose()` 不检查；无 PIT 能力的供应商可能获得研究用途 `ACCEPT` | 修复现有 data acceptance，不新建准入引擎 |
| R2 | P1 | `min_coverage_rate` 已声明却未被准入判定消费；字段级零分母、延迟样本缺失与 bar 缺失阈值的行为需核实 | 统一权威公式，不建立第二套 quality 模块 |
| R3 | P1 | `MembershipTable` 对相同 `(index_id, symbol)` 的重叠成员区间可能漏检 | 在现有 `_validate()` 中修复，保持 PIT 语义 |
| R4 | P1 | AST 检查对 `from trading_lab import oms`、部分相对导入形态可能漏报 | 加固现有脚本并做检查器自身负例 |
| R5 | P1 | snapshot hash 可验证完整性，但不自动证明 PIT 合格；文档/测试需明确两种属性 | 最小可执行 PIT 检查或显式 gate，不创建平行 snapshot 框架 |
| R6 | E-Gate | 证据、CI、架构健康与三轨报告闭环 | 不冒充真实供应商 API 验证，不自动签批阶段门 |

## 2. R1 — PIT 供应商能力必须实质参与准入（P0）

**现状关注点**：`src/trading_lab/data/acceptance.py` 的 `VendorFacts.pit_availability` 包含 `event_level / eod_only / none / unknown` 等语义，但当前 `evaluate_purpose()` 可能忽略该值；既有 `test_historical_research_accepts_with_full_facts` 在 `pit_availability='none'` 时仍可能通过。

**要求**：

- 以用途的 `available_at_rule` / 时点需求为准，定义**明确、可执行、可测试的 PIT 能力兼容矩阵**。例如事件/公告时点研究不能由仅 EOD 的供应商冒充事件级可得性；无 PIT (`none`) 不能获完整研究准入；`unknown` 必须 `BLOCKED_DATA`。对 EOD 研究，只有足够的可得时点事实、决策截止时点与用途规则同时满足时才能允许 `eod_only`；**不得仅凭营销页面的 `PIT-ready` 声明提升准入**。
- 同时校验数据记录层的真实 `available_at` / `ts_available_utc`（如数据本身未知，不得因供应商声称具备 PIT 而放行）。
- 清楚规定 `known-absent`、`unknown / undocumented` 与 `known-sufficient` 的不同判定，沿用现有 `ACCEPT / RESTRICT_SCOPE / REJECT / BLOCKED_DATA / INCONCLUSIVE` 词汇；只在严格满足用途需求时返回 `ACCEPT`。
- `VendorFacts` 数据若仍来自手工/文档描述，不得表述为 **API_VERIFIED**；仍保留真实全市场研究用途 `BLOCKED_DATA`。
- 覆盖 `historical_research_daily`、`event_research`、`pipeline_poc` 的正负例；必须有“其他条件全部满足但 PIT=none/unknown”不能 `ACCEPT` 的回归用例。
- 若 `available_at_rule` 当前以自由文本实现，应使用已有配置模型做最小合法值校验，避免拼写错误悄悄形成宽松准入；不得额外创建 DSL 或规则引擎。

**验收**：每种用途的 PIT 能力判断可从测试及记录追溯；非法、未知、粒度不足的场景 **0 个研究级误放行**。

## 3. R2 — 质量阈值统一、零分母不误放行（P1）

**现状关注点**：`PurposeRequirements.max_missing_rate` 与 `min_coverage_rate` 同时存在，`evaluate_purpose()` / `QualityReport.failures()` 对部分字段的执行可能不一致；`bar_completeness` 可能以“只要缺失一根即失败”覆盖了预声明的缺失率容忍度，而其他字段按比例判定。

**要求**：

- **只保留一条权威的缺失/覆盖率数学语义**：`coverage_rate = observed / denominator`，`missing_rate = missing / denominator`，零分母为 `INCONCLUSIVE`；字段级与 bar 完整度都必须使用一致且预先声明的用途阈值。
- 现有配置若同时保留 `max_missing_rate` 和 `min_coverage_rate`，必须验证二者的互补关系/严格性一致；不一致应在**配置加载时拒绝**，而不是有一个字段被悄悄忽略。优先选择最小、向后清晰的修复方式；任何删除或合并字段均需同步所有消费者与文档并给出理由。
- 对字段级 **0 denominator**、bar **0 denominator**、必须的延迟测量 **0 samples**，返回 `INCONCLUSIVE` 或更严格的 `BLOCKED_DATA`（如许可未确认），绝不能 `ACCEPT` 或“100%”；对不要求延迟样本的工程用途需按已定义规则解释，不能随意放松全市场研究用途。
- 数据质量不合格时必须落到预声明 `on_fail`；已确认许可不匹配、供应商范围未知、PIT 能力未知等硬阻断，不得被质量的宽松配置绕过。零分母与许可不明同时存在时，需冻结并测试判定优先级，避免同一事实因检查顺序得到不稳定结果。
- 新增交叉边界测试：阈值刚好相等、略高/略低、配置矛盾、字段零分母、bar 零分母、延迟无样本、少量允许缺失、超过允许缺失；要求理由码稳定、分母/分子可追溯。

**验收**：配置中没有被声明却未消费的质量阈值；不存在“绿色 PASS 但未检查实际覆盖率”的情形。

## 4. R3 — 历史成员区间重叠必须拒绝（P1）

**现状关注点**：`src/trading_lab/data/membership.py` 的 `_validate()` 主要检测完全重复的 `(index_id,symbol,effective_from)`；同一指数、同一证券的**不同起点、同一时间范围重叠**可能被接受。

**要求**：

- 对每个 `(index_id, symbol)` 按 `effective_from` 排序，显式检验半开区间 **`[effective_from, effective_to)`**：重叠拒绝、同一边界接续允许、开放上界之后出现新记录拒绝；不同指数同一证券允许各自独立区间。
- 补充起点不同的重叠、同起点不同终点、开放区间重叠、刚好相邻、同 symbol 不同 index、退市后 ticker 重用等合成测试。
- 不把“已公告”错误当作“已生效”，不允许当前证券池代替历史证券池；保留 `available_at <= asof` 的 PIT 门。
- 不新建一套 membership store / 历史映射服务。

**验收**：上述冲突模型在构造时被拒绝、合法边界保留，M0 与 M1 既有测试不退化。

## 5. R4 — 架构检查器须证明能阻断违规依赖（P1）

**现状关注点**：`scripts/check_architecture.py` 以 AST 为基础检查 `data` 包非法导入，但 `ast.ImportFrom` 可能只看 `node.module` 而漏掉导入的实际成员名称。

**要求**：

- 修复并自测：`import trading_lab.oms`、`from trading_lab import oms`、`from .. import oms`、`from ..oms import X`、POC 直接导入、可识别的常量动态导入等；正确处理 `data` 包上下文和相对层级。测试需同时证明合法 `data -> contracts/security.canonical` 等依赖不误报。
- 检测 `trading_lab.oms_tools` 之类**前缀相似但不是受禁模块子路径**时不得随意误报（包路径边界而非原始字符串前缀）。
- 对检查器自身建立 pytest 测试，用临时源文件/内存 AST 注入违规语句，明确断言拦截；仅有“仓库当前 0 违反”不足以证明检查器有效。
- 如果检查器仍只覆盖静态已知导入，必须标注此真实边界，不能宣称可捕获任意动态代码执行。无需引入新的 lint 框架、插件链或重型依赖。

**验收**：现有数据模块 0 非法依赖，故意插入的受禁导入 100% 被测试检测；CI 仍实际执行此检查。

## 6. R5 — Snapshot 完整性 ≠ 研究 PIT 准入（P1）

**现状关注点**：`SnapshotManifest.verify()` 只重算 Hash；包含 `available_at_utc=UNKNOWN_AVAILABILITY` 或晚于 `knowledge_cutoff_utc` 的 entries，仍可能通过 Hash 完整性验证。

**要求**：

- 保留现有 Hash 完整性含义和 API；不能将 `verify() == True` 解释为“PIT 研究可用”。
- 在**现有 data acceptance / snapshot 责任边界内**提供显式、可测试的研究用途可用性判定（例如明确验证全部必需 SourceRecord 可得时间不晚于 `knowledge_cutoff`，并结合用途准入结果）。工程留档允许完整保存“不合格/未知”快照，但不允许其进入研究合格数据集。
- 用合成负例证明：Hash 正确但 `UNKNOWN_AVAILABILITY`、Hash 正确但 `available_at > cutoff`、Hash 正确但研究用途 `BLOCKED_DATA` 均不可能被报告为研究合格；Hash 篡改仍失败；合法正例保留。
- 补充 ADR-003 或相关测试说明“内容完整性”与“时间有效性/许可/研究准入”为**正交属性**；不要再造第二套 SnapshotManifest 或重复数据模型。

**验收**：工程日志中的“snapshot hash PASS”不能被误用成“研究准入 PASS”。

## 7. Architecture Integrity & Code Quality（强制 E-Gate）

这是跨 M1–M11 长期目标：**每轮开发让正式系统更清晰，不让临时 POC、兼容包装和重复责任持续累积。**

- **开发前**：列出原有模块、职责、消费者和依赖方向；说明拟 `REUSE / MODIFY / REPLACE / REMOVE / ADD` 的代码。
- **开发中**：优先修复 `acceptance.py`、`quality.py`、`membership.py`、`snapshot.py` 和现有架构检查器；禁止新建平行数据质量服务、另一套 PIT 规则引擎、供应商适配平台、全局兼容层、消息队列或 OMS 代码。
- **开发后**：以 AST / 测试证据核验 `data` 不依赖 OMS、Broker、Risk、Research 执行与 `artifacts/poc/`；检查循环导入、重复实现、未使用函数/配置、死兼容代码。解释新模块/依赖的唯一必要性。
- **不允许以“代码行数越少越好”为由**删除真正的风险控制、PIT 负例或审计信息；性能优化必须有真实基准，不能想象提速。
- 更新 `artifacts/evidence/M1/architecture-health.md` 中的**整改补遗**，记录前后依赖图、复用/修改/删除/增加、检查器负例证明和剩余债务。**不要覆盖 M1 原始基线/历史结论**。
- 如果质量门与现有 CI 不一致，必须修正到可复现；一律不得通过跳过、`continue-on-error`、降低阈值或删减测试取得 PASS。

## 8. 验证矩阵及必须生成的证据

目标不是凑测试数量，而是对 R1–R5 逐项提供 **先红后绿、正负场景和失败关闭证据**。

建议在 Python 3.13 的干净虚拟环境执行（PowerShell 可直接运行；使用已批准的本地 Python，确保与 GitHub Actions 3.13 相容）：

```powershell
python -m pip install -e ".[dev]"
python scripts/check_environment.py
python -m pytest -q
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
```

**验证条件**：

1. M0 既有 140 个用例与 M1 原有 47 个用例全部保留；增加的负例不得替代原测试。记录最终真实测试数，不预设“必须达到某个整数”。
2. GitHub Actions `ubuntu-latest` 与 `windows-latest` 必须在**最终整改代码提交 SHA** 上实际全部 SUCCESS，且安装/测试/架构检查/密钥扫描/Paper 纯度门未跳过；在获得用户 push 授权前只能记 `CI_REMOTE_PENDING`。
3. `artifacts/evidence/M1/remediation/` 新建不覆盖式证据：`red-tests.log`、`green-tests.log`、`verification.log`，必要时另有 `ci-verification.md`（记录 SHA、run URL、作业结果）。日志中应包含命令、退出码、解释器版本和本次测试统计。
4. `docs/reviews/M1-independent-remediation.md` 记录 R1–R6 逐项结论、真实源码位置、复现方式、修复范围、测试与架构证据、未解决问题、提交 SHA 及人工审批状态；需要时在 `M1-engineering.md` 追加勘误或对新证据的指引，不覆盖原工程日志。策略与真实资金两轨不允许被提升。
5. 如果 `a1a18cb` 仅补记之前 CI 的事实，可以沿用其内容、在报告注明它与新整改提交的先后关系；**不得混淆旧 CI（`db25064`）和新代码的 CI**。

## 9. 阶段门与禁止越界

完成整改后建议使用以下状态，按实际证据选择而非提前宣布：

| 场景 | 工程状态 | 数据状态 | 阶段状态 |
|---|---|---|---|
| 本地全绿、最终提交尚未推送或远端未跑完 | `M1_REMEDIATION_LOCAL_PASS / CI_REMOTE_PENDING` | 全市场研究 `BLOCKED_DATA` | `M1_GATE=USER_PENDING` |
| 远端同一最终代码 SHA 的 Ubuntu/Windows 全绿 | `M1_REMEDIATION_VERIFIED` | 无 API_VERIFIED 仍 `BLOCKED_DATA` | `M1_GATE=USER_PENDING` |
| 真实供应商凭证、许可及覆盖仍缺失 | 只可认定工程子集 `PASS_WITH_SCOPE` | `BLOCKED_DATA` 不解除 | 无法宣称完整 M1 数据准入 PASS |
| 任何关键 PIT/许可/阈值负例误放行 | `REMEDIATION_FAILED / NO_GO` | 不得晋级研究 | 停止，不得进入 M2 |

- **S-Gate**：`N_A / evidence_state=NOT_EVALUATED`。合成测试不证明 Alpha。
- **R-Gate**：`NOT_STARTED`。本轮禁止任何真实资金、真实交易和真实券商 API 调用。
- **M2**：即使 M1 工程整改完成，也只能在用户**另行批准关闭 M1 并启动 M2**之后进行；如用户批准在数据 `BLOCKED_DATA` 下启动，则 M2 仅允许合成数据与 Fake Broker 的工程工作，不得借 M2 绕开研究数据准入。
- **推送**：提交本地代码和报告，保持工作树 clean；未经本轮用户明确 push 授权不得推送。不得 force push、改写历史或额外提交无关变更。

## 10. Codex 最终回报格式

按以下顺序给出**简洁但可审计**的报告：

1. 基线 SHA、本地与远端差异、是否包含 `a1a18cb`；
2. R1–R6 的 RED 复现、GREEN 验证及实际源码改动；
3. 测试总数、各检查 EXIT、Windows/Ubuntu CI（如未推送写 PENDING）；
4. 研究用途逐项准入状态及其真实证据层级（DOCUMENTED / API_VERIFIED / UNVERIFIED / BLOCKED_ACCESS）；
5. 架构健康：`REUSE / MODIFY / REPLACE / REMOVE / ADD`、依赖变化、重复与兼容层结论；
6. 新文件/变更文件、提交 SHA、工作树状态、是否推送；
7. 仍留给 M2/M3 的责任，以及明确的停止声明：`M1_GATE=USER_PENDING / M2_START_APPROVAL_PENDING`。

**结束条件：停在 M1 阶段门等待人工审查，不得自行批准、不进入 M2。**
