# M3-R2 — 研究证据完整性定向补强独立验收报告

| 字段 | 值 |
|---|---|
| stage_id | M3-R2（研究证据完整性补强；SYNTHETIC_ENGINEERING_ONLY） |
| task_id | `M3-R2-RESEARCH-EVIDENCE-INTEGRITY-20261121-001` |
| 基线 / 受测 | 基线 HEAD `4ae119fe17ab7118075adb2899def69eafe2cd78`（= origin/main）；本轮在其上工作（**未提交、未 push**，SHA 由用户提交时产生） |
| 协议 | v2：`m3-synthetic-engineering-v2`，`protocol_hash=8afb5207819bcd51ee66072f95d85355ed91b0e73d52e8ed24cc3fcd1ed43901`（审计链 v1.0 `9158028…` → v1.1 `48dee861…` → v2，双旧 hash 留痕未改写） |
| 代码身份 | `code_hash=af7ff10c425c0f153b2e7c1d1a86c6185267438610a81fa39a268a0f8d15f611`（24 文件全量清单，schema `research-code-identity-v1`；legacy r1 `c0a9ede5…` 钉为 RUNNER_ONLY_LEGACY） |
| 官方数据 | `m3-r2-official-v1`：120 sessions 纯 Decimal 公式合成，`dataset_hash=803b11b4e64ba97351dd2f2fb5cab24c814512fef91d4e84465a4bd5c9433286` |
| environment | Windows 11 Pro，Python 3.13.15（`.venv`，pytest 9.2.0），离线（gh CI 核验经代理 192.168.1.2:8080）；零新第三方依赖 |
| test_commands | 全套件 `572 passed` EXIT=0；backtest+validation 186 passed；1,080 故障矩阵专项 11 cases EXIT=0；check_environment / check_architecture(5 包 27 文件 0 违规) / scan_secrets(370 文件 0 findings) / verify_live_blocked / smoke_mock 全 EXIT=0；git diff --check 干净；官方运行 EXIT=0（verification.log 逐条真实退出码） |
| evidence_paths | `artifacts/evidence/M3/r2/{baseline.md, red-tests.log, red-pytest.txt, red-probe.txt, green-probe.txt, pytest-green-full.txt, verification.log, code-identity-manifest.md, code-identity-manifest.json, protocol-change-and-budget.md, ledger-integrity-negative-tests.md, architecture-health.md, experiment-ledger.jsonl, experiment-summary.json, ledger-anchor.json, probe-red-gaps.py}` |
| status | **M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)**（受测代码 SHA `906bf6f`，run `44998829308` 双矩阵 572 passed；见 §7）。前置状态 `LOCAL_PASS / CI_REMOTE_PENDING` 已被本记录取代 |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED_NOT_MATERIALIZED |
| forward_window_status | NOT_APPLICABLE |
| next_gate | M3 关闭、push（双矩阵 REMOTE_VERIFIED）、M3.5/M4 启动均需用户分别签批 |
| approver | USER_PENDING |

## 0. 裁决

三个审查项 **P0 R2-P0-1、P1 R2-P1-1、P1 R2-P1-2 全部修复并有机制性正反测试**；
RED 先于实现、5/5 行为缺口实证在先；既有目标 522→572 只增不减；M2 安全资产
零触碰；官方 100+ 根合成验证在新冻结协议批次下完成且预算血缘清晰。
**未验证项**：新 SHA 的远端 CI 双矩阵（未 push，无授权）——
`CI_REMOTE_PENDING`。在本报告出具时**不存在**已完成的 REMOTE_VERIFIED 事实。

## 1. R2-P0-1（P0）：研究代码身份 — FIXED

- RED：legacy runner-only hash 对 engine 字节变更不敏感（5/5 探针之一 +
  19 项身份测试 ImportError）。
- GREEN：`validation.code_identity` 为唯一权威——runner + backtest + validation +
  contracts + security(全包) + 顶层 init，共 24 文件，归一化内容 SHA、排序清单、
  canonical JSON 复用 security.canonical；跨进程（`-I` 双进程）与跨平台
  （CRLF/LF/BOM 检出噪声）一致专测；缺失 scope fail-closed；git commit/tree
  仅记录不参与 hash。
- 结果身份一致性：官方运行的 runner→arms/engine run_id/output_digest→账本
  14 条 entry→summary→manifest.json 引用同一 `af7ff10c…`。
- 历史不改写：r1 legacy hash 钉住（专测：r1 runner 源归一化 digest == legacy
  值，改动即响亮失败）；v2 注册表标 `RUNNER_ONLY_LEGACY`；新身份打开旧账本
  被 identity-binding 拒绝（无法静默混用）。

## 2. R2-P1-1（P1）：min_bars=100 样本门 — FIXED

- RED：20 根数据跑完官方路径无拒绝、无样本字段（探针 + 12 项测试 ImportError）。
- GREEN：`sample_gate` API（99/100/101 边界、session 计数≠曲线点专测）；
  `official_sample_gate()` 在结论出具前强制（不足 → `OfficialRunRefused` exit 2）；
  `ArmResult` 每结果强制携带 `sample_bars/sample_gate_verdict/trade_stats_status`。
- 旧 20-bar 证据：数据、账本、报告零改动；v2 注册表降级为
  `SYNTHETIC_SMOKE_ONLY_LEGACY`（verdict=INSUFFICIENT_SAMPLE_SMOKE_ONLY，永不
  支撑 min_bars PASS）。r1 三轨报告原文本来就没有声称 100 根 PASS，本轮以
  机制补齐"不足即拒"的防线并如实降级注册。
- 新官方验证：120 sessions 完全合成（`dataset_hash=803b11b4…`）；B0/B1/B2 ×
  ×1/×2/×3 全矩阵、PIT、守恒、决定时点规则保持；B2 参数 Train/Val 选择后冻结
  （4 grid queries 计费）；0 失败；成本单调退化一致。trade-stats 诚实语义：
  B0/B1 `N_A_INSUFFICIENT_TRADES`（如实不可计算，非"工程无效"），B2 20 笔 OK。
- 治理：v1.0→v1.1→v2 协议审计链 + `experiment_batches` 受控节；r2 BATCH_INIT
  显式引用 legacy 批次（hash + 消耗 9 trials/4 queries + r1 账本外部锚）；
  旧账本零改动、无法清空/换名绕过（身份绑定 + 拒绝重跑）。

## 3. R2-P1-2（P1）：账本恢复前完整性 — FIXED（含能力边界如实声明）

- RED：篡改账本可加载续写；尾截断无锚不可检测；并发双写无保护（探针实证）。
- GREEN：构造器"取锁→解析→验链→身份绑定→计数一致性→锚比对→才可写"的
  fail-closed 顺序；半行/坏 JSON、链断、digest 错、身份不符、`counters_after`
  与重放不一致（含重链攻击分层实证）全部拒绝。
- 并发：`O_CREAT|O_EXCL` 锁文件；同进程/跨进程第二写者拒绝（真实子进程实测）；
  崩溃留陈旧锁 → fail-closed，显式恢复后历史与 ALL_BILLED 预算逐项保留
  （os._exit(37) 子进程全链实证）。
- 锚与边界：`LedgerAnchor` 外部锚使尾截断/整文件替换/清空可检测；**诚实边界
  三处钉住**（模块 docstring、证据文档、永久测试）：无独立锚的 JSONL 只能检测
  保留头尾的中间篡改，**不具备不可抵赖性**；锚的信任=其存储位置
  （仓库提交记录防静默本地篡改，不能抗账本+锚同时重写）。
- 官方账本：14 entries 链验证 + `verify_ledger_file` 复核 + 锚落盘 +
  带锚重开正控（counters 9 trials/4 queries、per-arm 3/3/3）。

## 4. 不变量与范围纪律

| 不变量 | 状态 |
|---|---|
| M2 A7 五轮真实 crash + HALT 负例 | 完整保留（未触碰 fault_injection 断言） |
| 1,080 故障矩阵 | 专项重跑 11 cases EXIT=0 |
| 522 项既有测试目标 | 全保留；572 = 522 + 50 新增；3 处既有测试更新均非弱化（§见 architecture-health.md §2） |
| SYNTHETIC_ENGINEERING_ONLY / BLOCKED_DATA / U-1 UNRESOLVED / BROKER_BEHAVIOR_UNVERIFIED / S=INCONCLUSIVE / R=NOT_STARTED / evidence_state=NOT_EVALUATED / SEALED_NOT_MATERIALIZED | 全部未推进（零真实供应商/券商/Paper/Live/资金/Holdout 接触；verify_live_blocked EXIT=0） |
| M3/r1、M2 证据 | git 零改动；r1 账本 re-verify True |
| 范围 | 未重写回测/OMS；未新增数据库/消息队列/通用事件系统；账本锁为 stdlib 单机制 |

## 5. 已知风险与边界（如实）

1. `CI_REMOTE_PENDING`：572 项在本机双确认（全绿 + 每文件独立复跑），新 SHA
   的 Ubuntu/Windows 双矩阵未执行——push 需用户单独授权。
2. 静态架构检查不覆盖计算性动态导入/exec（r1 钉子如实披露，延续）。
3. 账本/锚在仓库内自证有限：能抗静默本地篡改与操作失误，不能抗同时重写
   账本与锚存储的攻击者；跨进程锁对"写者进程被 kill -9"选择 fail-closed
   （陈旧锁需人工恢复），这是审计安全性与运维便利性的权衡，已文档化。
4. 官方账本文件为 Windows 文本模式 CRLF（r1 同源行为）；链 digest 按行解析
   不含行尾，跨 OS 写入的语义与验证等价。
5. 交收/日历为协议假设（T+N），BROKER_BEHAVIOR_UNVERIFIED 不变。
6. code_hash 之 git_commit 记录值为提交前 HEAD（`4ae119f`）：代码身份以 24 文件
   清单 digest 为准；R2 提交后可从提交树重算 manifest 复核一致（提交不改
   工作文件字节）。
7. 全套件运行按既有测试设计再次重生成 A2/A5/A6 自身日志与 1,080 矩阵聚合
   报告（M2 lineage 行为，r1 已披露，未改断言）。

## 6. 建议门状态（不预设 PASS；依实据）

- 本地：`M3_R2_RESEARCH_INTEGRITY_LOCAL_PASS / CI_REMOTE_PENDING`。
- 若用户授权 push 且新 SHA 双矩阵 PASS：`M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED /
  E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`；范围不变（S/R/evidence 等
  各轴状态不变）。
- M3 最终关闭、M3.5/M4 启动、真实数据/券商/资金任何一步：仍需用户分别签批。

**STOP**：本轮工程与验收准备到此为止；未 push、未代签、未动 M3 门。

## 7. 远端验证记录（2026-11-22 追加，用户授权"提交推送"后）

以下为 push 后发生的实测，§0–§6 保持出报告时点原貌（当时 CI_REMOTE_PENDING 如实）。

- 推送：`4ae119f..9e640bd`（R2 代码+证据）与 `9e640bd..906bf6f`（CI 缺陷修复）均 EXIT=0。
- run `44996858265`（SHA `9e640bd`）如实记录两次失败与归因：
  attempt1 ubuntu `1 failed, 571 passed` —— 失败项为**既有 M2 A6 进程竞争测试**
  （真实进程 spawn 握手时序；R2 diff 零触碰 fault_injection/oms，50 项新测试全过；
  windows 被 fail-fast 取消）；attempt2 ubuntu `572 passed`、windows
  `1 failed, 571 passed` —— 失败项为 **R2 自身 CRLF 前置断言测试缺陷**
  （Windows runner 检出为 CRLF 所暴露；已在 `906bf6f` 修复，测试目的不变）。
- **VERIFIED 基准 run `44998829308`（SHA `906bf6f`）**：ubuntu job `137135622818`
  `572 passed in 64.78s`；windows job `137135622437` `572 passed in 482.39s`
  （一手 job 日志，经代理提取）——与本地 572 分母一致。
- **A6 flake 观察项**（不弱化、处置留用户决定）：5 次 A6 执行中 1 次握手时序
  失败（attempt1-ubuntu），复跑即绿；属共享 CI runner 负载敏感的既有风险，
  与本轮 diff 无因果证据。
- 结论：`M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED /
  E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`；M3 关闭、M3.5/M4 启动仍需
  用户分别签批（`M3_GATE=USER_PENDING` 不变）。
