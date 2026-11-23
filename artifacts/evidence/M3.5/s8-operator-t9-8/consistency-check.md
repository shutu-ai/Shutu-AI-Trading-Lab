# 离线静态一致性检查（consistency-check — T9.8.4，LOCAL_ONLY，2026-11-23）

> 全部为只读 grep/文件存在性检查 + 工具链；未执行网络、未重跑全量测试
> （纯文档轮，避免触发 M2 自重写——如实标 NOT_RUN）、未触碰历史证据。
> 基线 `b38d0c4da5202b3b3d55c5faa7e3bff0e2a26ff3`（远端验证 run
> `45042155239`，Ubuntu/Windows 各 960 passed）。本轮零生产代码变更。

## 1. T9.8 治理交付清单（本轮实际变更）

新增：

- `artifacts/evidence/M3.5/s8-operator-t9-8/windows-direct-pilot-approval-record.md`
  （例外审批记录：批示原话/范围/F-2 实测失败事实/风险接受边界/停止与
  撤销机制/两授权门/空白签署栏）；
- 本目录工具链日志 3 份 + 本检查记录；
- `docs/reviews/M3.5-s8-windows-direct-pilot-approval-t9-8.md`（轮次记录）。

最小修订（全部为带 `2026-11-23 T9.8` 日期标注的**增量附录**，旧原文
零改写）：

- 根目录 `Shutu_M35_S8_Windows_Direct_A_C_Operator_Runbook.md`（新增 §6
  门协调附录；§0–§5 原文不动）；
- `s8-operator-t9-7/b-only-authorization-request.md` §1（替代分支注）；
- `s8-operator-t9-7/operator-action-card.md`（步骤 2/4 前置扩展注）；
- `s8-operator-t9-7/operator-gate-reconciliation.md`（新增 §9 附录，
  §1–§8 不动）；
- `s8-operator-t9/first-real-once-approval-request.md` §1/§6（替代分支注）；
- `s8-operator-t9/operator-preflight-pack.md`（签署节替代分支注）。

批示原件 `Shutu_M35_S8_T9_8_Windows_Direct_Limited_Pilot_Approval.md`
按原样入库（登记；仅规范化两份操作者 authored 根文件中 5 行 Markdown
行尾硬换行空格，零文字修改——见 §3）。

## 2. 冻结事实与门语义静态核对

| 检查项 | 方法 | 结果 |
|---|---|---|
| 替代门公式 `A_verified AND ((C_verified AND environment_frozen) OR (direct_pilot_exception_approved AND local_risk_acceptance_signed AND environment_frozen))` 落位 | grep `direct_pilot_exception_approved` | PASS——8 文件：批示原件、审批记录、runbook §6、b-only-request §1、action-card、reconciliation §9、first-real-once-request §1/§6、preflight-pack；公式逐字一致 |
| 例外不得写成 `C=VERIFIED_BY_OPERATOR` / `F-2=PASS` | grep 两词全库 | PASS——全部命中均为**禁止句式**（"不得把例外写成/例外不写成/例外 ≠"），无一处断言例外=C 通过 |
| 现势状态 `OPERATOR_PREFLIGHT_C=BLOCKED`（2026-11-23 实测 F-2 失败）+ `HOST_EGRESS_ISOLATION_UNVERIFIED` 保持 | grep | PASS——批示、审批记录、runbook §6、reconciliation §9、action-card、b-only-request、first-real-once-request 一致标注；旧文 `PENDING_OPERATOR` 行按"保留旧原文"纪律未改写，均由日期标注注明时点 |
| 两授权独立性（B-only 成功签署后才可申请 First Once；任一批准不自动延伸） | 人工比对 | PASS——approval-record §7、action-card 铁律、reconciliation §9.3/§9.5、first-real-once-request T9.8 注、runbook §6.4 表述一致 |
| 原 C 全矩阵路径保持可用（不删除前置，只新增析取分支） | 人工比对 | PASS——五份修订文件均为增量注；F-1～F-8 判据、环境切换重验规则未被修改 |
| 停止/撤销机制（泄露迹象/交易域访问/意外订单/环境改变/版本漂移即停；Key 撤销轮换由账户所有者执行；不自动清证据、不自动续采；用户可明示撤销例外并回落全矩阵路径） | 人工比对 | PASS——approval-record §6、reconciliation §9.5、runbook §6.4 一致 |
| 交叉引用文件存在性 | 文件检查 | PASS——`../s8-operator-t9-8/windows-direct-pilot-approval-record.md`（自 t9-7/t9-9 两证据目录）、根目录批示/runbook、attestation 模板、reconciliation §5/§6 均存在 |
| 状态枚举纪律（三态 + 准备事实不冒充签署）未被削弱 | 人工比对 | PASS——本轮新增文本沿用三态枚举与 `B_PLAN_READY` 语义 |
| 生产代码/依赖/配置零变更 | `git status` 比对 | PASS——本轮变更仅 .md 文档与证据目录 |

## 3. 工具链退出码（本轮实跑，日志在本目录）

| 命令 | 退出码 |
|---|---|
| `python scripts/check_architecture.py` | **0**（`architecture-check.log`） |
| `python scripts/verify_live_blocked.py` | **0**（`verify-live-blocked.log`） |
| `python scripts/scan_secrets.py` | **0**——首轮 584 个跟踪文件（全部内容文档已暂存后运行）、终态树复扫 587 个（含 3 份日志）均 0 发现 |
| `git diff --cached --check` | **0**——首次运行曾报 5 行 Markdown 行尾硬换行空格（仅两份操作者 authored 根文件头部，零文字修改地规范化行尾空白后复检干净） |

## 4. 明确未执行（NOT_RUN，如实标注）

- 全量 pytest / M2 故障矩阵：**NOT_RUN**——纯文档轮（同 T9.7.4.2 先例），
  避免自改写 M2 历史证据；无代码变更故无重跑必要性；
- 任何网络探针 / `collect` / 凭证注入：**未执行**（最高优先级禁令）；
- `REAL_API_CALLS=0`、`BROKER_ORDERS=0`；
- r1/r2/r3 及 t9/t9-7 既有验收日志：**零触碰**；
- 工作树中 3 份 M2 证据日志在本轮开始前已有未提交修改
  （`a5-true-process-race/process_concurrent_50.log`、
  `a6-strict-process-proof/barrier_50_rounds.jsonl`、
  `final-send-claim/a2-quantitative-close/process_50_rounds.log`）：
  本轮**不读取其差异、不改动、不入提交**，留待用户处置。

## 5. 安全卫生发现（如实记录，无任何凭证值/派生标识）

- 仓库根目录存在**未跟踪**本地笔记文件 `alpaca.markets.txt`，内含
  Alpaca **Paper** Key ID 与 Secret 的**明文**。处置：本轮未转录其值、
  未入库、未在任何文档/日志/提交中复制其内容；该文件**排除在本轮全部
  提交之外**（提交使用显式路径清单，未使用 `git add -A`）。
- **偏差披露**：治理会话在盘点未跟踪文件时接触到该文件头部内容（属
  T9.8 批示 §2 所列"发往 Agent"形态的意外接触；非主动读取凭证指令）。
  按 approval-record §6 停止原则，列入操作者待办：**在仓库外安全留存
  凭证、将该文件移出仓库目录、并轮换该 Paper Key**。
- 工具链边界如实记录：`scan_secrets.py` 扫描 **git 跟踪文件**（经
  `git ls-files`），未跟踪文件不在其覆盖面内——故上述文件即使存在也
  不会出现在其报告中；该局限不掩盖事实，特此注明。
- `git diff --check`：2（5 行 Markdown 尾随空格）→ 行尾规范化后 **0**；
  暂存后终态复扫 587 文件 **0 发现**（日志文件本身由工具在扫描后写出，
  仅含工具 stdout，已经人工审阅）。

## 6. 待人工动作清单（本轮停门后，全部由账户所有者本人完成）

1. A 项账户与许可核验（attestation §A1–A5，本人登录核对 Paper Only /
   Basic+IEX / 条款许可）并本地签署；
2. 直连残余风险接受记录签署（approval-record §8.2 模板，仓库外本地）；
3. 凭证卫生整改：`alpaca.markets.txt` 移出仓库目录至私有留存处，轮换
   该 Paper Key，确认工作树不再含明文凭证文件；
4. 固定环境身份（reconciliation §5 登记表）+ 持久状态卷落实
   （reconciliation §6：独占/权限最小化/加密/跨日不覆盖/每日备份摘要）；
5. 完成上述后才可提交 B-only 申请（随附 T9.8 批示 + 非敏感环境摘要）；
   B-only 批准、执行、本人签署完成后，才可另行提交 First Once 申请。

## 7. 状态出口（逐字）

```text
T9_8_GOVERNANCE_GATE=LOCAL_READY_FOR_REVIEW
S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE
HOST_EGRESS_ISOLATION_EXCEPTION=APPROVED_WITH_SCOPE(WINDOWS_DIRECT_READ_ONLY_PILOT)
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=BLOCKED
HOST_EGRESS_ISOLATION_UNVERIFIED
B_PLAN_READY=UNVERIFIED_OR_PENDING_OPERATOR
B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED
FIRST_REAL_ONCE_READY=NO
FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
REAL_API_CALLS=0
BROKER_ORDERS=0
M4=NOT_STARTED
FULL_TESTS=NOT_RUN
PUSH=NOT_AUTHORIZED
```
