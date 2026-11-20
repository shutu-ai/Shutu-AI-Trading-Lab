# M1 Architecture Health — 基线与验收记录

> M1-DATA-FOUNDATION-ARCHITECTURE-QUALITY-001 §5 强制工件。
> 基线部分于开发前完成（2026-11-20，HEAD `463838f`）；开发后章节随实现更新。

## A. 基线（开发前，T0）

### A1. 模块职责与依赖图（现状）

```text
src/trading_lab/
  contracts/    # §2.2 事件契约（Pydantic strict）+ RuntimeConfig —— 全平台唯一契约层
  security/     # canonical/Ed25519 签批/verifier/SchemaGate/KillSwitch/audit/isolation
（无 data/、oms/、brokers/、research/ —— M1 前不存在）
artifacts/poc/M-1/
  data_poc/     # yfinance 技术证明（501 行日线/4661 行 5min，见 data_poc_run.log）
  fake_broker_poc/  # M-1 OMS 契约 POC（20 用例）
tests/
  contract/ security/   # 140 用例
```

依赖方向（M0 已实现并测试）：security → contracts；contracts →（仅标准库+pydantic）。
禁止方向（M1 起由 import 检查强制）：data → oms/brokers/risk/POC。

### A2. 可复用契约（复用，不建第二套 DTO）

| 契约 | M1 用途 | 复用判定 |
|---|---|---|
| `MarketBar` | 原始/复权 bar（`ts_event_utc`/`ts_available_utc`/`adjustment`/`quality`） | **REUSE** —— 字段完备，`ts_available_utc` 即 PIT 语义 |
| `CorporateAction` | 拆股/分红（`announced_at`/`effective_at`/`available_at` 三时点独立） | **REUSE** |
| `MarketSnapshot` | 快照 manifest（`asof_utc`/`knowledge_cutoff_utc`/`dataset_hash`） | **REUSE** |
| `DataVendorAssessment` | 供应商七字段矩阵 | **REUSE** |
| `RegimeAssessment`/其余交易侧契约 | M1 不触及 | 原样保留 |

### A3. POC 与产品边界

- `artifacts/poc/M-1/data_poc/data_poc.py`：**POC-ISOLATE** —— 仅为 yfinance 可得性技术证明；正式 `src/trading_lab/data/` 零导入 POC/qlib/yfinance；yfinance 数据按 M-1 结论（不可重算复权、无 available_at、ToS 禁商用）不得进入 Alpha 研究证据链。
- `artifacts/poc/M-1/fake_broker_poc/`：M2 的实现参考，M1 不触碰。

### A4. 已有重复实现与风险

- 无平行数据模型。唯一风险点：M0 `MarketSnapshot.dataset_hash` 语义需在 M1 固化为**确定性 canonical-JSON manifest hash**（同输入同版本 → 同 hash），由 data 模块实现并在测试中锁定。
- 仓库无既有 lint/架构检查器（无 ruff/import-linter/AGENTS.md）→ M1 新增最小 AST import 检查（标准库实现，零新依赖），不引入重型工具。

### A5. 拟修改/删除/新增清单（开发前承诺）

| 分类 | 对象 | 理由 |
|---|---|---|
| REUSE | contracts 四契约（见 A2） | 字段已按 §2.2 冻结，创建第二套即违反唯一权威 |
| ADD | `src/trading_lab/data/`：`calendar.py`（UTC/ET/DST/假日/半日）、`quality.py`（分母/覆盖率/延迟/许可状态）、`snapshot.py`（确定性 manifest/hash）、`actions.py`（企业行为重算与版本化）、`membership.py`（历史成分/退市/代码映射）、`acceptance.py`（按用途准入判定） | 各自唯一职责、消费者为 tests/no_lookahead 与后续 M3/M4；不建 ETL 框架 |
| ADD | `configs/data_acceptance.yaml`（每用途必填阈值） | 计划 M1 工件 |
| ADD | `scripts/check_architecture.py`（AST import 检查：data 不得导入 oms/brokers/risk/POC） | §5 机器可执行要求，标准库实现零依赖 |
| ADD | `tests/no_lookahead/`（PIT/DST/退市/复权/质量/快照负例） | 计划 M1 工件 |
| ADD | 根 `AGENTS.md`（简短，固化 §5 原则） | 任务书允许；不复制 v2.1 文档 |
| MODIFY | 无既有生产模块需要修改（contracts 不动；若新增字段须另行非兼容性评估） | — |
| REPLACE/REMOVE | 无（M0 代码零删除；安全控制与回归测试不削弱） | — |
| DEPENDENCIES | 目标：**零新增运行依赖**（标准库 datetime/zoneinfo/hashlib/json 覆盖全部需求；zoneinfo 为 3.9+ 标准库，Windows 需 tzdata 包——见开发后记录） | — |

### A6. 数据→交易面边界（待开发后验证）

数据层不得导入/调用 `trading_lab.oms`、`trading_lab.brokers`、`trading_lab.risk`、`artifacts.poc.*`；不持有券商写密钥；`scripts/check_architecture.py` + CI 断言。

---

## B. 开发后验收（2026-11-20，实现完成后）

| 分类 | 记录 |
|---|---|
| REUSE | `MarketBar`/`CorporateAction`/`MarketSnapshot`/`DataVendorAssessment`（§2.2 契约）字段未动、零复制；`security.canonical` 的 canonical JSON + SHA-256 复用于 snapshot 哈希（平台唯一字节规范，而非第三套序列化） |
| MODIFY | `pyproject.toml`：新增条件依赖 `tzdata`（见 DEPENDENCIES）；CI 增加 check_architecture 步骤。**contracts 与 security 零修改** |
| ADD | `src/trading_lab/data/`（7 模块，各唯一职责）：`records.py`（SourceRecord 溯源链；消费者 snapshot/actions/manifest 测试）、`calendar.py`（UTC/ET/DST/假日/半日+PIT 门；消费者 no_lookahead 测试、后续 M3）、`actions.py`（企业行为确定性重算+版本化；消费者 M3 复权）、`membership.py`（历史成分/退市/重用检测；消费者 M3/M4）、`quality.py`（显式分母质量报告；消费者 acceptance+M3）、`snapshot.py`（确定性 manifest；消费者 M3/M4 证据）、`acceptance.py`（按用途准入判定；消费者 configs/data_acceptance.yaml+M1 报告）。`scripts/check_architecture.py`、根 `AGENTS.md`、`tests/no_lookahead/`（47 用例） |
| REPLACE/REMOVE | 无删除；M0 全部 140 用例原样保留且全绿（安全回归未削弱） |
| POC-ISOLATE | `check_architecture.py` AST 检查：data 包 0 处导入 oms/brokers/risk/strategies/research/evolution/portfolio/monitoring、0 处 `artifacts`/`poc` 片段、动态导入常量亦被扫描（EXIT=0）；`src` 布局下 artifacts 不在导入路径上 |
| DEPENDENCIES | 新增 `tzdata>=2024.1`（仅 Windows marker）：stdlib zoneinfo 在 Windows 无系统时区库即抛 ZoneInfoNotFoundError（干净 venv 实测复现）；Apache-2.0；无替代标准库方案；CI windows-latest 同样需要。除此之外零新增运行依赖（ETL 框架/数据库/消息队列均未引入） |
| BOUNDARIES | data→oms/brokers/risk：check_architecture EXIT=0 证明禁止方向无一处违反；数据层无券商凭证读取（无 os.environ 凭证访问）；M0 smoke/verify_live_blocked 全绿证明未弱化任何安全门 |
| DEBT | ①假日/半日表目前为测试 fixture 与运行时参数，接入真实供应商日历属数据订阅到位后的 M3 前工作；②`producer_id`/供应商适配层刻意未建——等真实授权数据源出现再按其 API 实现，避免无消费者的适配层；③`min_coverage_rate` 阈值字段已在 config 声明，acceptance 判定当前消费 missing_rate 侧（两者语义冗余），M3 接入真实质量报告时统一为一个公式——责任阶段 M3 前 |

### §5 E-Gate 负向清单自查

| 违例 | 结果 |
|---|---|
| (a) 生产导入 POC | 无（AST 检查 EXIT=0） |
| (b) 同一责任第二实现 | 无（唯一 data 层，契约层复用） |
| (c) 无消费者兼容层 | 无（未创建任何 POC 兼容模块） |
| (d) 未解释组件/依赖 | 无（上表逐项说明；唯一新依赖 tzdata 有实测理由） |
| (e) 数据→OMS/Broker 违禁依赖 | 无（EXIT=0） |
| (f) 删除代码未迁移测试 | 无删除 |
| (g) 检查仅主观 | check_architecture.py 可复现命令，CI 接入 |

---

## C. 整改补遗（M1-REVIEW-REMEDIATION-001，2026-11-20）

> 不覆盖 A/B 节历史基线；本节记录整改后的差异。

### C1. 依赖图变化

方向不变（data → contracts/security.canonical），无新增模块间依赖、零新依赖。
修改全部发生在既有文件内部：`acceptance.py`（PIT 矩阵+阈值一致性+冻结判定序）、
`quality.py`（failures 与统一比率公式一致）、`membership.py`（半开区间重叠校验）、
`snapshot.py`（+`research_admissible` 显式 PIT 门）、`check_architecture.py`
（包边界匹配/别名成员/相对层级解析/越包 fail-closed）。REUSE=既有全部；
ADD=仅测试（46 个：整改负例+检查器自测）；REMOVE=无。

### C2. 检查器负例证明（R4）

`tests/architecture/test_check_architecture.py`：12 种违禁形态（绝对/父包成员/
相对 1–3 级/子路径/POC 片段/常量动态导入）全部被拦截断言；6 种合法形态
（含 `oms_tools` 前缀相似不误报、`security.canonical` 合法依赖）不误报；
`main()` 仓库扫描保持 EXIT=0。已知边界如实记录于脚本 docstring：静态字面
导入与常量动态导入可检；变量化动态导入/exec/扩展不可检（归后续阶段进程隔离）。

### C3. 剩余债务更新

| 债务 | 责任阶段 |
|---|---|
| 供应商适配层等真实授权数据源 | M2/M3 按实际 API 建 |
| 真实假日表接入 | M3 前 |
| coverage/missing 双阈值的消费者统一（已由 R2 一致性校验缓解：宽松组合加载即拒） | M3 接真实质量报告时复核 |
| 变量化动态导入的进程级隔离 | M2+ 进程边界 |
