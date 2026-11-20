# Shutu AI Trading Lab — M1 数据供应准入与点时刻可得性：Codex 阶段任务书

> **Task ID:** M1-DATA-FOUNDATION-ARCHITECTURE-QUALITY-001  
> **版本:** v1.0 / 2026-11-20  
> **基线仓库:** `https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> **依据:** `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md` 与 `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`  
> **前阶段远端审查基线:** `36c6ffca6e9810897541d10309333db1971c11e2`；双平台 CI `44762931848`（Ubuntu/Windows PASS）；这不是对任意后续本地提交的背书。  
> **当前审批基线:** `M0_REMEDIATION_VERIFIED / M0_GATE=USER_PENDING / M1_START_APPROVAL_PENDING`。本文件的创建、阅读、提交或复制**不是启动 M1 的授权**。

## 0. 绝对指令：阶段门与禁止范围

1. **先停在审批核查点。** 只有用户在当前项目明确批准 **关闭 M0** 且 **启动 M1**，才可执行后续编码、数据访问与阶段测试。仅见到本任务书、其他 Agent 的阶段报告、`USER_PENDING` 或一次成功的 CI，不得推断人工批准。未获批准只输出审批缺口清单，**不得实现 M1**。
2. 正式执行前核对本地 `git status`、`HEAD`、`origin/main`、M0 三轨报告及 `docs/reviews/M0-independent-remediation.md`，记录尚未推送的本地补记提交（历史提及 `c458b85`）是否真实存在、是否只改动文档。绝不伪称该提交已推送；不覆盖并行工作。
3. **仅执行 M1（P0）**：真实数据供应评估、数据质量、点时刻可得性、市场日历、快照复算、用途准入。保持 M-1～M11（含 M3.5）和 P0–P4 不变。
4. 禁止实现或启动 M2 OMS/BrokerAdapter/订单、M3 回测、M4 AI 研究、M8 Paper 自动交易、M9 Live、真实资金转移和真实签批；不申请/使用 Alpaca 交易密钥。数据 API 只允许使用已有且经用户批准的**只读数据授权**。
5. **不得购买数据、开通付费订阅、注册新账号、绕过 API 限制或接受新合同**，除非用户另行明确批准。供应商无法访问时以 `BLOCKED_DATA` 或按用途 `RESTRICT_SCOPE` 留证，禁止合成数据冒充实际供应商检验。
6. 未经用户另行授权，不推送远端、不合并、不修改历史、不提升审批状态。结束时停在 `M1_GATE=USER_PENDING / M2_START_APPROVAL_PENDING`，或如实标注 `BLOCKED_DATA / BLOCKED_ENV / FAIL`；**不自动推进 M2**。

## 1. M1 要达到的结果（严格对齐 v2.1）

M1 的交付标准不是“能获取一批股票价格”，而是：**给定一种数据来源、一个研究用途和一个指定知识截止时刻，系统能够证明使用的每条数据当时确实可得、质量门达标、许可允许该用途、快照内容可复算；无法证明则拒绝或缩小适用范围。**

必备数据范畴：

- 原始与复权 OHLCV：保存原始值、独立企业行为/复权依据与调整方法；不可重算的预调整数据不得伪装成可验证研究数据。
- 历史证券池/历史指数成分：成员加入、退出、有效日期、数据来源；不得用今天的成分股替代历史证券池。
- 退市及代码映射：历史标的 ID、ticker/venue 有效区间、改名及退市事件；不允许无声删除退市标的。
- 企业行为与事件可用时间：拆股、股息、合并、公告时间、生效时间、实际接收时间须独立表达；不能用 `effective_at` 代替 `available_at`。
- 时间与交易日历：UTC、America/New_York、美国夏令时、节假日、半日交易、盘前盘后、延迟行情实际可得时间与数据入库时间。所有用于决策的数据需满足 `available_at <= decision_cutoff`。
- 统一质量与准入：按用途区分 **仅管道 POC / 工程监控 / 允许历史研究 / 暂不能研究**，不把供应商名称当作许可与数据质量的证明。

## 2. 任务实施顺序（一次只完成当前授权的 M1）

### M1-T0 — 仓库盘点与架构取舍（动代码前完成）

- 完整读取两份 v2.1 计划 M1 任务行，以及 M0 三轨、ADR-002、M-1 `vendor_matrix.md` 和 POC 结论。
- 列出现有可复用契约：`MarketBar`、`CorporateAction`、`MarketSnapshot`、`DataVendorAssessment` 及其时点字段；核对 `src/trading_lab/contracts/` 当前实现，**优先复用，不创建等价第二套 DTO**。
- 明确 `artifacts/poc/M-1/data_poc/` 仅为历史技术证明，正式 `src/trading_lab/data/` 不能直接导入 POC、qlib 样本或 yfinance 适配作为生产事实源。
- 形成基线职责表、依赖图（文本或 Mermaid 即可），并列出准备 **复用 / 修改 / 替换 / 删除 / 隔离为 POC** 的代码与文件；无必要不创建 Adapter/Service/Repository 多级空抽象。
- 审阅是否已有 `AGENTS.md`、Ruff、Import Linter 或其他质量约束，避免重复安装相似检查器。若未有长期说明，可新增**简短** `AGENTS.md` 固化第 5 节原则；不复制第二套 v2.1 规划文档。

### M1-T1 — 供应商真实证据与用途准入矩阵

- 使用 `artifacts/evidence/M-1/vendor_matrix.md` 为待验证输入，核查至少 **Sharadar / Nasdaq Data Link、Polygon/Massive、Alpaca Market Data Basic** 三类候选的官方条款、端点、可访问层级、产品授权、费用、数据延迟和历史覆盖。其他候选仅在能实质补缺时增加。
- 对每一供应商逐字段列出：①历史成员，②退市/标的映射，③企业行为，④ point-in-time 可得性，⑤个人内部研究及存储/再发布许可，⑥当前实际价格/额度，⑦历史覆盖/频率；同时列官方来源 URL、核查日期、实际请求/响应日志或不可测试原因。
- 严格区分 `DOCUMENTED`（官方文档声明）、`API_VERIFIED`（已授权只读 API 实测）、`UNVERIFIED`、`BLOCKED_ACCESS`；不能将文档营销描述当作真实 PIT 实验结果。
- 对每项用途输出准入 `ACCEPT / RESTRICT_SCOPE / REJECT / BLOCKED_DATA`，原因及解除条件；**对缺少历史成分/退市/PIT/许可的全市场策略研究用途不可 ACCEPT**。
- 免费端点若已获许可可试小规模只读请求；需要付费凭证/商业条款则停止并报告，不得“临时抓网页”替代合法数据。

### M1-T2 — 最小正式数据路径与快照

- 在 `src/trading_lab/data/` 下建立职责明确的最小模块：源记录校验、时间/日历、原始与复权变换、历史成员/退市/企业行为、数据质量、快照 manifest；按现有代码实际需要合并或拆分，**不提前搭建大规模 ETL 框架**。
- 复用 M0 Pydantic 契约，新增字段或契约必须有非兼容性评估与测试；避免为兼容 M-1 POC 保留双模型。
- 原始输入采用不可变/可追溯的本地样本或授权的真实只读输入；建立 `source + dataset_version + acquisition_time + available_at + raw_hash + transform_version` 的证据链接。
- 企业行为调整应可重算且对调整规则版本化；源数据无公告/可得时间时显式标 `UNKNOWN_AVAILABILITY` 或降级用途，不能以 K 线日期冒充公告时间。
- 以确定性顺序和标准化数据类型生成 snapshot manifest/hash；同输入与同版本多次运行得到相同 hash，修改一行原始价格、时间戳或因子则 hash 必变。仅用现有必要技术（例如项目已有的 Parquet/Python 工具）；不引入 Kafka、Redis、Postgres、Spark 或分布式组件。

### M1-T3 — 配置化数据验收与负例测试

- 建立 `configs/data_acceptance.yaml`，**每一用途必填且非空**：数据范围、日线/分钟线需求、所需企业行为/历史成分/退市覆盖、`available_at` 规则、缺失率和覆盖率阈值、延迟界限、许可范围、未达标动作；阈值必须事先声明，不得在失败后偷偷降低。
- 定义机器可校验的分母和质量公式；每类输出实际观测的 **分母、缺失数、覆盖率、时延统计（含样本量）及许可状态**，零分母为 `INCONCLUSIVE/BLOCKED_DATA` 而非 100%。
- `tests/no_lookahead/` 必须包含：未来发布记录、公告晚于决策时刻、迟到数据回填、复权因子事后知识混入、今天证券池替代过去证券池、退市证券遗漏、ticker 重用、UTC/ET DST 错算、假日/半日交易、缺失可得时间、重复/乱序 bar、错误企业行为、snapshot hash 篡改等负例。
- 所有“未来不可得”记录 100% 被拒或标为不可研究；数据关键字段缺失必须 `BLOCKED_DATA / RESTRICT_SCOPE`，不得静默填补或将不可判断事项标为 PASS。
- 测试至少包括合成 fixture **与**（有合法可得样本时）真实数据来源的独立小样本验证；synthetic fixture 只能证明逻辑，不能证明供应商覆盖和时延。

### M1-T4 — 回归、文档、正式证据与阶段停止

- 在 Windows/Python 3.13 和现有 GitHub Actions Ubuntu/Windows CI 环境回归；若本阶段暂未获推送授权，远端 CI 状态保持 `PENDING`，不得据本地结果宣称已运行远端。
- 保持 M0 既有安全/合同/审计/配置全绿：任何数据模块都不能导入 `trading_lab.brokers`、创建交易路径、读取 Live 密钥或弱化 Schema Gate。
- 交付第 6 节所有工件，并在报告中准确区分**真实供应商证据不足**与**本地工程缺陷**，二者不得混淆。
- 停在 M1 阶段门，提交本地代码和证据仅限已授权操作；不自动推送或开启 M2。

## 3. 独立数据质量与证据门（M1 E-Gate）

| 判据 | 必须满足 | 失败/证据不足时 |
|---|---|---|
| PIT 可得性 | 预先注入的全部未来泄漏 fixtures 被阻断；不同事件/公告/接收时点各自保留 | `FAIL`，不可自动放宽 |
| 历史证券池/退市 | 历史成分、退市与映射按用途有可追踪实证 | `BLOCKED_DATA / RESTRICT_SCOPE` |
| 复权 | 原始价格与调整因子来源/时间/版本可复算 | `RESTRICT_SCOPE / REJECT` |
| 质量分母 | 缺失数、覆盖率、延迟、样本量、授权状态可机器查验 | `FAIL` 或 `BLOCKED_DATA` |
| 许可/成本 | 供应商许可证真实对应数据用途、费用可核查；禁止无授权付费 | `BLOCKED_DATA / REJECT` |
| snapshot | manifest/hash 稳定可重算、内容被篡改能检测 | `FAIL` |
| 安全回归 | M0 140 用例及相关新增测试仍全绿；不新增 Broker/Live 写路径 | `FAIL` |
| 架构健康 | 第 5 节全部强制项通过并有实证 | `FAIL`（不得被一般测试 PASS 覆盖） |

M1 若仅完成工程数据管道但缺少合规的历史成分/退市/PIT 供应商数据，**不能报告“完整数据供应准入 PASS”**。可将已实现的工程子集列 `PASS_WITH_SCOPE`，对受限用途标 `RESTRICT_SCOPE / BLOCKED_DATA`，总 E-Gate 依据冻结的 M1 必需用途判定 `BLOCKED_DATA` 或 `FAIL`，由用户决定是否调整后续推进范围，不得降低既定验收阈值。

**三轨定位：** `S=N_A, evidence_state=NOT_EVALUATED, deployment_state=NOT_DEPLOYED, strategy_role=NONE, R=NOT_STARTED`。没有 Alpha、策略收益或真实交易资本证据。研究最终 Holdout 未创建/未解封，报告中写明 `SEALED (NOT_CREATED)`，不能虚构检验结果。

## 4. 供应商/数据范围的防误用规则

1. M-1 Yahoo 与 qlib 下载样本继续保留在 `artifacts/poc/` 供复现，**不通过正式 M1 数据质量门**时不能进入 Alpha 研究证据链；缺少许可或可得时点不得“猜测补齐”。
2. Sharadar 是否提供目标历史指数成分、退市和可验证公告时间，必须按具体数据产品/授权版本实测；供应商矩阵先前的肯定描述只是待验证假设。
3. Polygon/Massive、Alpaca Basic 的当前限制、价格、历史深度、授权和 API 行为以审查时的官方文件与实际账户权限为准，不能套用 M-1 日期的价格表。
4. 如果某供应商仅覆盖日线研究而分钟线、新闻时点或历史成员不完整，必须按**用途**限制证券池、频率与结论，禁止全局标“数据已可用”。
5. `available_at` 缺失、数据访问被拒、日历异常或许可证不可确认时，必须保留失败记录；不能事后改样本、删除失败行或用 synthetic 样本冒充实证。

## 5. 强制目标：Architecture Integrity & Code Quality（纳入现有 E-Gate）

**长期原则：M1 新增能力必须融入唯一、可维护、可验证的正式架构；拒绝各阶段按功能堆叠兼容代码。核心职责所有权唯一；只有真实必要时才增加抽象、依赖和持久化状态。** 本节不是建议项，而是必须验收的独立章节；不新增 E/S/R 之外的第四轨。

### 开发前必须提交

- `artifacts/evidence/M1/architecture-health.md` 的**基线部分**：当前模块职责/依赖图、POC 和产品边界、已有可复用契约、已有重复实现及风险、拟修改/删除清单；先审查再开发。
- 为每个候选新增模块解释为何不能直接复用既有模块；职责已有所有者时应优先增强/替换现有实现，不得另起平行数据模型、Schema Gate 或数据管道。

### 开发中硬规则

- 一个职责只有一个正式权威实现；M-1 `artifacts/poc/` 绝不能成为正式数据模块的运行时导入依赖。
- M1 禁止新增 OMS、BrokerAdapter、Risk Engine、策略运行时、复用旧 POC 的兼容层、无消费者的抽象/接口或“未来可能用到”的基础设施。
- 必要重构可以删除/替换旧代码；**安全控制、审计、不可变契约和已有行为的回归测试不能被删弱**。若确需向后兼容，必须给出明确在用消费者、到期移除条件和测试。
- 禁止跨层依赖：数据处理层不能导入 `trading_lab.oms`、`trading_lab.brokers` 或研究 Agent 的执行模块；数据层不持券商写密钥，研究侧无法访问 Live 运行态。
- 每次引入依赖都记录用途、与标准库/现有库的替代比较、Python 3.13 兼容性、许可证与 CI 成本；拒绝无正当理由的基础设施。
- 不为了简单追求低 LOC 牺牲类型、审计、可读性或安全；质量标准是**最小必要复杂度 + 清晰边界 + 可靠证据**。

### 开发后必须输出

在 `artifacts/evidence/M1/architecture-health.md` 提供下表：

| 分类 | 必填记录 |
|---|---|
| REUSE | 复用的现有契约/模块、为何不复制 |
| MODIFY | 修改的责任归属与接口影响 |
| ADD | 新增生产模块、每个模块唯一职责及实际消费者 |
| REPLACE/REMOVE | 被正式实现替换或删除的旧代码、测试迁移与残留确认 |
| POC-ISOLATE | M-1 POC 的隔离方式、生产依赖为零的证据 |
| DEPENDENCIES | 新增运行依赖/开发依赖、必要性、许可与版本 |
| BOUNDARIES | 数据→风险/OMS/Broker 禁止方向的检查方式与结果 |
| DEBT | 真实存在的后续债务、责任阶段与清理期限；不为空时不得隐瞒 |

**架构检查应机器可执行**：在兼容现有 CI 的前提下优先使用轻量 import graph 检查（如经验证可用的 Import Linter，或最小 AST 检查）禁止 `src/trading_lab/data/` 导入 OMS/Broker/POC；视必要性增加 Ruff/类型检查。引入第三方检查器必须有可运行的 Python 3.13 证明，不得为形式搭建独立架构服务。合并前确认开发者 Windows 与 CI Ubuntu/Windows 同一规则成功。

**E-Gate 不得 PASS 的情况：** (a) 生产导入 POC；(b) 同一责任新建第二正式实现；(c) 为旧阶段 POC 添加无消费者的兼容层；(d) 新增未解释的组件和运行依赖；(e) 违反数据→OMS/Broker 禁止依赖；(f) 已删除代码未迁移必要行为/安全测试；(g) 架构检查只做主观评价、无可复现证据。

## 6. 规范交付物

```text
src/trading_lab/data/                         # M1 唯一正式数据实现
configs/data_acceptance.yaml                  # 每用途必填准入/质量阈值
tests/no_lookahead/                          # PIT/DST/退市/复权/质量/快照负例
docs/adr/ADR-003-data-contract.md             # 数据源取舍、许可、事实边界、替代方案
artifacts/evidence/M1/data-vendors.md        # 每供应商七字段/来源/实测及授权矩阵
artifacts/evidence/M1/architecture-health.md # 必须：模块职责、复用/删除、依赖与检查证据
artifacts/evidence/M1/                    # test/quality/snapshot/供应商原始证据与命令日志
docs/reviews/M1-engineering.md
docs/reviews/M1-strategy.md
docs/reviews/M1-real-capital.md
```

三轨报告按 v2.1 的统一字段填写 `stage_id / commit / code_hash / protocol_hash / environment / test_commands / evidence_paths / findings / status / evidence_state / deployment_state / strategy_role / final_holdout_status / forward_window_status / next_gate / approver`。无研究协议时 `protocol_hash=NOT_APPLICABLE (M3 freezes)`；不要把无数据、无策略伪装为 `PASS`。数据价格、供应商能力或许可不能仅凭预期填写为已验证。

## 7. 最终验证命令与阶段停止报告

在仓库真实环境按可用路径执行并记录 **命令、环境、退出码、stdout/stderr、测试数量、失败/跳过原因**：

```powershell
python --version
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/check_environment.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
git status --short
git rev-parse HEAD
```

另执行 M1 新增的 PIT/质量/日历/快照/架构依赖检查命令，并保存原始日志；首次失败应保留红证，修复后有绿证。若供应商不能实测，报告必须附 `BLOCKED_DATA` 证据和最小所需授权/费用，不得“伪造 PASS”。

收尾报告至少包含：

1. 每项 M1 任务 / E-Gate 对照表、实际质量分母与拒绝/限制用途清单。
2. `architecture-health.md` 总结（新增/复用/替换/删除/依赖变化），说明**为什么没有形成阶段堆叠代码**。
3. M0 安全回归与新增 PIT 全套测试结果（本地 + 被授权推送后实际远端 CI）。
4. 三轨 `E / S / R` 与独立数据准入状态、剩余阻断、真实/合成证据界限。
5. 清洁工作树状态、提交 SHA、是否推送及用户批准证据（未推送不得写已推送）。
6. **停止声明：** `M1_GATE=USER_PENDING / M2_START_APPROVAL_PENDING`；无批准不得进入 M2、不得调用交易接口，不得真实资金交易。

## 8. 可直接复制到 Codex 的启动提示词（需要用户另行授权才执行）

> **以下是未来授权后的执行语句模板，不构成本次生成文档时的授权。**

```text
我已独立批准关闭 M0，并明确授权启动 Shutu AI Trading Lab 的 M1 阶段。
请先完整阅读两份 v2.1 docs/plans，并执行仓库中的
Shutu_AI_Trading_Lab_M1_Data_Foundation_Codex_Task.md。
仅执行 M1，严格遵守数据 PIT/供应商许可与 Architecture Integrity & Code Quality 硬门。
开发前出具架构/依赖基线，开发后提交 Architecture Health 证据；不创建重复数据管道、平行契约、无理由兼容层或任何 M2/Live 组件。
无法验证的供应商或用途如实 BLOCKED_DATA/RESTRICT_SCOPE，不得伪造数据、许可或收益。
运行全部本地测试和安全门，形成 M1 三轨报告，按既有授权范围处理本地提交；推送须另获明确授权。
最终停止在 M1_GATE=USER_PENDING / M2_START_APPROVAL_PENDING，等待人工验收。
```

**注意**：只有用户实际发出以上授权（或同等明确授权），Codex 才能启动 M1；本任务书不代表已发生此授权。
