# Shutu AI Trading Lab — M3.5 S8 T8 Codex Task

**任务 ID**：`M35-S8-T8-TERMINAL-FENCE-OFFLINE-RECOVERY-AND-CI-BACKFILL-R1-20261122`  
**执行性质**：仅本地、离线、先 RED 后 GREEN、最小修复、审计留痕、**禁止推送**  
**上游远端基线**：`origin/main = 0b1f3b7900b9fe385bf4579e8126f1641f15d5ca`  
**T7 已远端验证**：GitHub Actions `45031453603`，HEAD 与上述 SHA 一致，Ubuntu **944 passed / 63.26 s**、Windows **944 passed / 517.75 s**，双平台 architecture / secret scan / Paper gate 绿。  
**本任务不等于**：operator A–C 审批、首次真实 API 采集、Paper 写权限、M4 开始或 M3.5 关闭。

## 0. 硬边界与停门纪律

- 允许：本地读取代码、Git 对象和已提交证据；新增隔离在临时目录的测试；针对 T8 范围的最小生产代码修改；离线脚本；文档/证据回填；本地提交。
- 禁止：`git push` / PR 合并 / force push / 无授权修改远端；真实 Alpaca 连接（包括 market-data GET）、使用或显示凭证、账户登录、订单或 Broker 操作；从事证券交易或启用 Paper write；升级付费数据；开始 M4；合成数据计作真实日；擅自关闭 M3.5 阶段门。
- 禁止为了满足测试放宽预注册、删除/跳过基线 944 测试、调整验收阈值、掩盖退出码、或修改历史 r1/r2/M2 原始证据及冻结协议/夹具。
- 保持：`M3.5_GATE=USER_PENDING`；`API_VERIFIED=NONE`；`REAL_FORWARD_DAYS=0`；`PAPER_WRITE=NOT_AUTHORIZED`；`S=INCONCLUSIVE`；`R=NOT_STARTED`；`BROKER_BEHAVIOR_UNVERIFIED`；`HOST_EGRESS_ISOLATION_UNVERIFIED`；全市场历史 `BLOCKED_DATA`；`FIRST_REAL_ONCE_READY=NO`。三项 operator preflight（A/B/C）全部仍为 `PENDING_OPERATOR`。
- 任意 STOP 条件（基线不符、意外脏工作树、需要真实 API/凭证才能证明、历史证据被修改、修改超出范围、测试无法不接触网络而执行）立即停止并提交 `HOLD`，不得擅自扩大授权。

## 1. 发现来源与明确问题（需测试证实，而非预设为已发生事故）

当前远端代码：

1. `scripts/run_m35_s8_shadow_real.py` 的 `cmd_collect`（当前约 221–285 行）在 `--once`、`--complete` 两种命令路径上，都在完成状态校验前执行 `run_collection_cycle()`。
2. `apps/market_gateway/feed_session.py` 的 `run_collection_cycle()`（当前约 160–196 行）先 `feed.collect_once()`、追加 receipt，随后调用 `run_replay(...complete=False)`；未在入口拒绝已经提交 `WINDOW_COMPLETED` 的窗口。
3. `scripts/run_m35_s8_shadow_real.py` 的 `_complete_window()` 已有同 facts 的幂等修复分支，**但是**当前 CLI 没有一个不调用 `collect_once()`、不读取凭证且只修已提交快照的用户级入口；`operator-readiness.md` 建议重跑 `collect --complete` 可能额外收集与写入。

需证明的 P1 家族：

- **P1-A 终态写入隔离**：已提交完成收据后，普通 `collect --once` 不应请求网络，不应追加 receipt/journal/session，不应改变 snapshot/state，也不应默默返回成功并让已完成窗口漂移。
- **P1-B 纯离线恢复**：对 `CHAIN_COMMITTED_SNAPSHOT_MISSING`，应能不接触真实 API/凭证、不新增行情采集、不再次关闭 session 的情况下，只修复可验证的 snapshot；不能误创建首条 `WINDOW_COMPLETED` 或把损坏链伪装成可恢复。

## 2. T8.0 基线核查（STOP/GO）

1. `git status --porcelain=v1`、`git rev-parse HEAD`、`git rev-parse origin/main`、`git log -3 --oneline`：核对 HEAD = origin/main = `0b1f3b7...`。若已出现其他本地提交/改动，记录精确差异并 **HOLD**，不要 reset 或覆盖用户工作。
2. 阅读根目录与父级 `AGENTS.md`；T7 任务书；`docs/reviews/M3.5-s8-completion-integrity-r2.md`；`artifacts/evidence/M3.5/s8-contract-r2/{baseline.md,red-green.md,operator-readiness.md,review.md}`；上述生产文件；旧测试 `tests/s8_gateway/test_completion_integrity.py`；ranged 预注册 v3 配置及 `eligibility` 契约。
3. 实际读取远端 run `45031453603` 的 HEAD、两平台 job 日志和门步骤；记录 run ID、full SHA、job IDs、944/944、耗时；不可复用旧 run 充当新代码验证。
4. 本轮新建证据目录 `artifacts/evidence/M3.5/s8-contract-r3/`，只追加本轮文件。保留 r1/r2、M2 历史日志原样。
5. 明确测试隔离：全部临时目录、假 feed、可判别的 `collect_once()` 哨兵、禁止外部网络。若实现需要更改默认真实配置或读取真实环境密钥，**HOLD**。

## 3. T8.1 RED：精准重现入口风险（先固定负例）

添加新的契约测试文件（如 `tests/s8_gateway/test_terminal_collection_fence.py`），先在旧代码上运行并保存 **真实 RED 失败日志**，至少包括：

1. **完成后再次 `collect --once`**：先使用合成 fixture 建立拥有唯一 `WINDOW_COMPLETED` 的测试状态；设置可计数/抛异常的假 `feed.collect_once()`；断言该入口必须在创建网络客户端/读凭证/调用 feed/写链之前直接拒绝。测试旧行为应 RED。
2. **完成后 `collect --complete`**：不得先补采再“修复”，也不得追加第二完成收据、会话或新 receipt；正常终态的再次调用应拒绝普通采集（纯本地 `repair-completion` 是独立入口）。
3. **已提交收据、快照缺失的状态**：`status` 应仍为 `exit 7` + `CHAIN_COMMITTED_SNAPSHOT_MISSING`，但不得要求运行真实采集才可修复。
4. **终态完整性异常**：重复/冲突完成记录、快照摘要/协议不匹配、损坏 receipt/journal，必须 fail-closed，明确非零退出码；无数据、合法未开始/进行中不得被误当已封存。
5. **多次重复调用/进程重启**：并发或连续的终态检查不能造成新增行情回执/会话，保持原快照和已提交完成收据的确切字节或内容摘要。
6. **operator 误用命令**：`collect --complete` 不得成为修复已完成窗口的隐式网络入口；`repair-completion` 在没有合法已提交完成收据时不得“帮忙完成”。

必要时使用网络哨兵封闭 socket/urllib、凭证读取哨兵。RED 失败必须准确对应 P1-A/P1-B；无法复现则改为记录“NOT_REPRODUCED”，不得为了得到 RED 改写事实。

## 4. T8.2 GREEN：完成窗口的终态隔离

在**唯一现有采集入口**上做最小修复（不引入平行 collector）：

- 在 `cmd_collect` 的任何凭证读取、feed 构建、网络访问及 `run_collection_cycle` 之前，执行只读终态审查：对存在已提交 `WINDOW_COMPLETED` 的目标窗口，普通 `collect --once` 与 `collect --complete` 一律拒绝，保持磁盘状态零变化；状态损坏同样拒绝并给出可审计错误码。
- 如需同时保护内部调用 `run_collection_cycle()`，应评审是否补加复用的读链守卫，避免绕过 CLI；不要把异常解释成允许采集。
- 验证冲突/重复收据、失败的链验证、协议不一致等情况下不产生新状态写入。保持既有未完成合法窗口的采集路径不变。
- 明确防 TOCTOU：若多个进程可能并发写同一状态目录，至少验证现有单写者约束是否覆盖 read-check-write 全流程；如果不覆盖，记录精确残余风险并在工程范围允许时进行最小锁或租约复用。不得声称检查一次状态即可证明跨进程原子性。
- 新增退出码时更新完整 CLI 契约及调用方，保持 `0/3/4/5/6/7` 既有含义，不得用 `exit 0` 掩盖封存窗口误写。

## 5. T8.3 GREEN：纯本地 `repair-completion` 子命令

实现显式的修复子命令（名称建议 `repair-completion`，最终以可用 CLI 帮助为准），要求：

- 必须显式指定 `--state-dir`，使用既有 frozen preregistration（默认 v3/ranged）；不读取凭证环境、不调用任何真实 HTTP、broker、feed/`collect_once`、`run_collection_cycle`、`run_replay(complete=True)`，无新日线事件或 session。
- 修复资格只接受**恰好一条已提交且链完整的 `WINDOW_COMPLETED` 收据 + 缺失快照 + 原链事实摘要/协议身份/eligibility 可独立重算匹配**，禁止凭临时 flag、操作员手填摘要或合成事实升级真实状态。
- 对成功的纯本地修复：原子写入 snapshot，验证链绑定；不追加第二完成收据，不改变 receipt/journal；输出结构化 `REPAIRED_SNAPSHOT` 与 `exit 0`（仅表示修复成功，非 E-Gate PASS）。
- 对 snapshot 已存在且全部验证通过：`ALREADY_COMPLETE_NOOP` 且不修改任何字节；对未提交完成收据：`NO_COMMITTED_COMPLETION`、不得完成窗口；对链损坏、跨协议、摘要漂移、篡改快照：必须拒绝、非零退出；对无法完成原子写入：`exit 7` 可恢复，且不制造假 COMPLETE。
- 原 `collect --complete` 继续服务尚未封存窗口的首次受控完成操作；但不得被当成离线快照修复路径。根据新语义修正 `operator-readiness.md` 相关内容，准确区分 read-only status、offline repair、future operator-authorized real collection。
- 修复命令仅供未来操作者在另行批准的环境中使用；本轮执行全部用临时合成状态。

## 6. T8.4 可选 CI 证据回填（本地，不推送）

- 使用 GitHub 官方原始日志重新确认 `45031453603`，在 `r3/remote-ci-backfill.md`（或单独的 docs 文件）准确记录：完整 HEAD `0b1f3b7...`、job ID、Ubuntu 944/63.26s、Windows 944/517.75s、各静态门 PASS、警告不影响判断；说明它只证明 T7 代码，而非本轮 T8 代码，也不证明真实 API 行为。
- 对操作者未跟踪的 `ci-run-45031453603.log` **只能只读检查后决定是否引用**；不要擅自入库，不要把任何日志中的敏感环境信息复制到 Git。若无法安全读取，直接引用可信远端 CI 链接足够。
- 原 `r2/review.md` 的历史 `LOCAL_ONLY` 是成文时事实；优先用追加回填说明，不通过整体改写历史报告抹除时间上下文。
- 无回填需求则不必强行制造多余提交；无论是否回填，`T7_CI=REMOTE_VERIFIED` 与 `T8_CI=REMOTE_PENDING` 分开记录。

## 7. T8.5 验证门

至少执行（并记录实际命令、退出码、工作目录、环境、测试计数）：

1. 新契约测试：RED 复现 → GREEN；终态隔离、凭证/HTTP/订单负例、完成缺快照修复、无完成记录拒绝、链损坏/协议漂移拒绝；多次重启/故障注入验证。
2. 全量 `pytest`：至少保留基线 944 个测试（零删改/零 skip/零 xfail），新增测试全部通过；不得只报告挑选通过的用例。
3. `python scripts/check_environment.py`、`python scripts/check_architecture.py`、`python scripts/scan_secrets.py`、`python scripts/verify_live_blocked.py`、`python scripts/smoke_mock.py`、既有 T6 M2 溯源审计器、`git diff --check`，按仓库真实可用命令执行；不自动补装未授权依赖。
4. 防自重写证据：M2 A2/A5/A6 如测试重新生成本地日志，应**确认文件原样恢复，且将新鲜输出仅追加到 r3**；r1/r2 历史必须逐字冻结；红绿/故障测试不得写入真实 evidence 副本。
5. 跨平台注意：`os.replace`、Windows 路径/换行与子进程重复检查。新增代码只完成本地验证时，明确标 `T8_CI=REMOTE_PENDING`，**不得自行推送后冒称远端通过**。
6. 如发现新增 P0（无法在当前范围安全解决），及时 HOLD，说明受影响路径和复现证据，先不扩大修复边界。

## 8. T8.6 交付与阶段门

在新目录 `artifacts/evidence/M3.5/s8-contract-r3/` 形成 `baseline.md`、`red-green.md`、`fault-injection.log`、`full-regression.log`、`remote-ci-backfill.md`（如适用）、`review.md`；相应 `docs/reviews/M3.5-s8-terminal-collection-fence-r3.md` 报告本轮结果、残余风险、交付清单和 HEAD。

可在**本地**创建可审计提交（如需要多个本地提交，按父链说明）；任何推送必须得到未来新的单独授权。输出至少包含：

```text
T8_AUDIT_VERDICT=LOCAL_PASS_WITH_SCOPE | HOLD
T7_CI=REMOTE_VERIFIED (run 45031453603, head 0b1f3b7...)
T8_CI=REMOTE_PENDING
BASELINE_HEAD=0b1f3b7900b9fe385bf4579e8126f1641f15d5ca
LOCAL_HEAD=<actual new sha>
REMOTE_HEAD=<actual current origin/main sha>
RED_TESTS=<actual failed counts and cases>
GREEN_TESTS=<actual counts>
FULL_TESTS=<actual counts / exit>
TERMINAL_FENCE=<PASS|HOLD>
OFFLINE_REPAIR=<PASS|HOLD>
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
HOST_EGRESS_ISOLATION_UNVERIFIED
FIRST_REAL_ONCE_READY=NO
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
PUSH=NOT_AUTHORIZED
REAL_API_CALLS=0
BROKER_ORDERS=0
M4=NOT_STARTED
NEXT_APPROVAL_REQUIRED=separate push approval, then operator A-C and later one-cycle real read-only collection approval
```

**STOP at local commit.** 用户需要先审阅本地验收结果并另行批准推送；远端 CI 验证只可能在未来受授权推送后成立。账户所有者必须本人完成 A/B/C；任何真实 `collect --once` 需要再一次独立授权。
