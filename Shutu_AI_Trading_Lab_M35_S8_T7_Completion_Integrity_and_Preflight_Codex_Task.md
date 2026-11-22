# Shutu AI Trading Lab — M3.5/S8 T7 证据完成性 Fail-Closed 与真实采集前预检准备任务

**任务 ID**：`M35-S8-T7-COMPLETION-INTEGRITY-AND-OPERATOR-PREFLIGHT-R1-20261122`  
**推荐执行范围**：本地代码/测试最小修复 + 纯离线审计与文档；**禁止推送和真实 API 调用**  
**参考远端基线**：`a0b1f58d29ecb4bf25646ac22a5791ea04ca6cdb` (`origin/main`，GitHub 实测 2026-11-22)  
**CI 已核实**：run [`45026250819`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45026250819)，head 与上述 SHA 一致，Ubuntu `926 passed in 34.04s`、Windows `926 passed in 505.85s`，双平台架构检查均 0 violations，扫描 511 文件、0 secrets，Paper/Live 隔离门通过。  
**截至基线的事实**：`T6_AUDIT=ACCEPTED_WITH_SCOPE`；`M3.5_GATE=USER_PENDING`；`API_VERIFIED=NONE`；`REAL_FORWARD_DAYS=0`；`OPERATOR_PREFLIGHT_A/B/C=PENDING_OPERATOR`；`FIRST_REAL_ONCE_READY=NO`。

> **执行指令**：本文件为用户拟授权 Codex 进行下一轮**本地离线整改**的任务书，不是对推送、真实行情/凭证接触、网络隔离操作、Paper/Live 交易的授权。执行前按 AGENTS.md 和阶段门核对现状；若 HEAD 漂移或有用户未说明的修改，停止并报告。

## 一、T6 复核结论（本次独立读取 GitHub 而得）

1. `origin/main` 的 HEAD 为 `a0b1f58`。`94019e9` parent=`2a60864`，`a0b1f58` parent=`94019e9`。前者恰修改三份 CI 回填文档，后者新增四个 T6 审计/任务/工具文件，未修改生产代码。远端不能证明操作者本地工作区当前是否 clean，这一事实仍需本地验证。
2. CI run `45026250819` 的 head 为 `a0b1f58...`，双 job 及其测试、架构检查、密钥扫描、Paper/Live 阻断步骤全部 success；**只证明已有测试覆盖范围的工程正确性，不证明真实市场、券商行为或主机级出口隔离**。
3. `artifacts/evidence/M3.5/s8-contract-r1/t6-audit.md` 与 `m2-provenance-audit.txt` 记录了 M2 三份再生证据日志的双版本不变量和结构对账；A6 claimant 向量的到达序局限已披露，不准将其写成静态审计完全证明 winner 的位置映射。

## 二、本轮新识别的必须 RED→GREEN 问题（源代码可静态复现的风险路径）

**P0-A：完成收据落盘失败可能继续产出成功形态快照。**
`script/run_m35_s8_shadow_real.py` 的实际文件名是 `scripts/run_m35_s8_shadow_real.py`：`_complete_window()` 在追加 `WINDOW_COMPLETED` 时捕获异常并仅把 `window_completed_receipt` 设置为 `FAILED: ...`，之后仍写入 `forward-window-evaluation.json` / 真实证据副本。外层 `cmd_collect()` 未检查该字段，可能返回 `EXIT_OK`。

**P0-B：完成状态的 digest mismatch 未反映在 CLI 失败退出码。**
同文件 `cmd_status()` 已计算 `evaluation_snapshot.digest_match`，即使不匹配仍返回 `EXIT_OK`。自动化使用者可能把状态命令零退出码误认为完整性通过。

> 两项均为代码审查发现的可疑故障通路，先写精确的 RED 用例验证当前行为；不要仅凭文字描述宣布已被利用或已造成真实数据错误。若已有其他调用路径防护，须指明并以测试证明。

### T7.0 — STOP/GO：确认边界和基线

- 运行 `git status --short`、`git rev-parse HEAD`、`git rev-parse origin/main`、`git log -3 --oneline`、`git diff --check`；验证 `HEAD=origin/main=a0b1f58...` 或明确说明可追溯偏差。**有不明改动时 STOP，不 reset、不覆盖。**
- 阅读 AGENTS.md、T6 审计、S8 预注册 v3、原有任务书、`_complete_window()`、`cmd_status()`、`window_facts_from_journal()`、`evaluate_window()` 与对应测试；记录当前不变量、收据链格式、文件名和失败码语义。
- 先界定正常 `NOT_STARTED`/无快照状态的 CLI 合法行为，避免错误地把尚未完成窗口当成完整性损坏。
- 本轮不得改动已冻结 v1/legacy 协议、事实/原始历史日志、基础研究策略、OMS/风控/Paper/Live 业务边界。

### T7.1 — P0-A RED：注入完成性落盘故障，证明旧路径

- 在临时目录中使用纯合成状态；对 `append_receipts`（`WINDOW_COMPLETED`）注入 `OSError`/权限失败/写入失败；断言未修复代码出现的异常路径并存档 RED 结果。
- RED 反例至少覆盖：完成收据未写而快照存在、CLI 错误零退出；若现有测试已防护则存档证据，不为制造失败刻意破坏契约。
- 设计期望：**任何未持久化或不可核验的完成收据，不得产生可被认为成功的完成证据，也不得返回成功退出码。** 保留诊断信息，但不能误报完成。
- 完成性跨两个持久文件无法靠简单 try/except 实现原子事务：设计可恢复、幂等的提交顺序/状态机，并明确在崩溃后如何恢复、如何避免重复完成收据、如何阻止半完成状态被提升 PASS。不要只删除异常处理而忽略中途崩溃一致性。

### T7.2 — P0-B RED：状态完整性失败须 fail-closed

- 用独立临时状态分别注入：snapshot `facts_digest` 被篡改；snapshot `protocol_hash` 不匹配；snapshot 存在但无对应合法 `WINDOW_COMPLETED` 链记录；链记录存在但 snapshot 缺失/部分写入；同协议重复完成记录且不符合幂等语义；receipt/journal 损坏。
- 对预期应拒绝的情况建立 CLI 子进程退出码断言，要求**非零、可区分且稳定**（优先采用既有错误码体系，新增码必须文档化），不能仅在 JSON 中显示 `digest_match=false` 却退出 0。
- 保持未开始窗口合法查询的既有行为；完整性与可用性分开陈述，不能把 `status EXIT=0` 等同于真实资格 PASS。
- 检查 `status` 是否核对**快照与链记录的绑定关系**，而不只是 `facts_digest` 的字符串相等。必要时增加最小校验，不接受“重算摘要相等但无对应已提交记录”作为 COMPLETE。

### T7.3 — GREEN：最小修复并保持原有安全不变量

- 只在既有正式 runner / 完成性状态逻辑中改动，不新建平行实现或改写旧协议。
- 以 fail-closed 的完成状态机/收据验证/快照落盘恢复流程修复 T7.1、T7.2；输出内容准确区分 `COMPLETE_VERIFIED`、`INCOMPLETE`、`INTEGRITY_FAILURE`、`BLOCKED` 等，**具体枚举须与现有契约兼容**。对写文件使用合适的临时文件 + 原子替换方案，明确 Windows/Linux 的差异，失败时可复原且不可默许升级。
- 注入 `os._exit` 或等价“异常终止”时只对**模拟状态**进行，绝不接触真实采集状态目录。覆盖收据写入前、写入后、snapshot 写入前后四个故障点；以全新进程状态读取证明不会产生假 COMPLETE 或二次完成。
- 复测模拟输出永不写入真实 `artifacts/evidence/M3.5/s8-contract-r1/real-forward-window-status.json`；真实证据副本只能沿受控 operator `collect --complete` 路径生成。
- 复测原有 E-Gate 不变量：`events_synthetic`、receipt↔journal、protocol identity、`disconnect_recoveries`/`duplicate_recoveries`/`audits_passed`、>=5 全覆盖交易日、0 订单。任何 synthetic PASS 只能标注 `SIMULATED_REAL_SHAPE_TEST_ONLY`，不能升级 `API_VERIFIED`。
- 不通过“放宽校验”、伪造断连或异常、人工标绿、吞掉异常来使测试通过。

### T7.4 — 操作者 A–C **资料准备**（不代替本人验证）

只读检查 `operator-preflight.md` 的核验项并产生一份**不含密钥**的本地操作手册草案，重点：

- **A 账户/授权**：账户本人确认 Paper-only、Basic/IEX 权限、适用市场数据条款及成本；不要因配置中 `operator_confirmed: true` 就认定签署已完成；状态维持 `PENDING_OPERATOR`。
- **B 凭证**：只给出操作边界，不要求粘贴密钥、不读取、截屏、打印、传给 Agent；真正的进程级注入由操作者本人完成，并且**只有在未来单独授权真实采集时**才进行。Codex 不得代办。
- **C 出口隔离**：设计无凭证的网络层负例核验步骤，仅作为**操作者以后在其受控主机亲自执行的说明**；不得由 Codex 在本轮执行外连探针。明确 `urllib.request`/环境 HTTP(S)_PROXY/系统代理/CONNECT、DNS/IPv4/IPv6、子进程出口、代理机与家庭直连差异。GET-only 进程校验不等于主机 egress 隔离。未证实则 `HOST_EGRESS_ISOLATION_UNVERIFIED`。
- 明确每次 `collect --once` 只允许一个未来的受控真实周期；`MARKET_CLOSED`/`OUTSIDE_POLL_WINDOW` 或 `EXIT_OK` **不能**自动认定 `API_VERIFIED`；真实事件须从可审计回执证明。不得因 5 天过去就认定完成，断连/重启/重复恢复须真实可信，不准故意制造线上断连或往真实链混入合成证据。
- 仅**审阅** `check-config`、`selftest`、`status` 离线流程并拟定使用说明；本轮只可在独立临时目录运行无凭证离线测试，不可打开真实采集状态或网络连接。

### T7.5 — 验证与验收门

最低要求：

1. P0-A、P0-B 的 RED/修复后 GREEN 对照入档，包含旧行为、修复行为及退出码。
2. 新增正/负例：收据写失败、快照写失败、部分写入、重复完成、链不匹配、快照篡改、跨进程崩溃恢复、合成事件拒绝真实资格；每项必须失败关闭。
3. 全量现有 `pytest` 回归；原 926 测试不得删减、skip、xfail 或降低阈值。报告新增用例与总数。对 Windows/Linux 的落盘/换行/原子重命名差异给出证据；无法实际验证的平台明确 `REMOTE_PENDING`。
4. 原有 M2 fault matrix、`check_environment.py`、`check_architecture.py`、`scan_secrets.py`、`verify_live_blocked.py`、`smoke_mock.py`、`git diff --check`，逐项记录退出码。运行测试前将输出/缓存重定向到临时目录，避免覆盖既有 M2 历史证据日志；若工具不可重定向，先设计保护措施并报告。
5. 检查没有新依赖、没有密钥、没有订单/经纪商模块导入或未授权主机调用，没有数据口径/协议准入放宽；所有文件改动可归因。

### T7.6 — 证据、提交与阶段门

- 新建 `artifacts/evidence/M3.5/s8-contract-r2/`（不得覆盖 `s8-contract-r1/`、T6、M2 证据），包含：
  - `baseline.md`（基线 SHA、工作区状态）
  - `red-green.md`（两个 P0 的独立复现与修复验证）
  - `fault-injection.log`（退出码和崩溃验证）
  - `verification.log`（测试、架构、扫描等实际执行结果）
  - `operator-readiness.md`（A–C 的**未签署**清单与缺失证据，不含凭证）
  - `review.md`（残余风险和判定）
- 可另附 `docs/reviews/M3.5-s8-completion-integrity-r2.md`。所有说明标注 `LOCAL_ONLY`，不把先前 run 当成新代码的 CI。
- 本轮允许**本地提交**修复、测试和新证据，记录实际 SHA/文件清单；绝不 `git push`、不开 PR 自动合并，不打 tag 或 Release。
- 最终输出以下状态：
  - `T7_COMPLETION_INTEGRITY=LOCAL_PASS_WITH_SCOPE | HOLD`
  - `T7_CI=REMOTE_PENDING`
  - `OPERATOR_PREFLIGHT_A/B/C=PENDING_OPERATOR`（不得擅自升级）
  - `HOST_EGRESS_ISOLATION_UNVERIFIED`
  - `FIRST_REAL_ONCE_READY=NO`
  - `M3.5_GATE=USER_PENDING`
  - `API_VERIFIED=NONE / REAL_FORWARD_DAYS=0`
  - `PAPER_WRITE=NOT_AUTHORIZED / S=INCONCLUSIVE / R=NOT_STARTED / BROKER_BEHAVIOR_UNVERIFIED / BLOCKED_DATA(全市场历史)`。

## 三、绝对禁止项

- 不读取、不请求、不打印、不传递真实 Alpaca 或券商凭证；不执行有凭证的命令或任何对真实行情 API 的请求。
- 不主动发起对 `data.alpaca.markets`、`api.alpaca.markets`、`paper-api.alpaca.markets` 的网络调用；不执行 `collect --once`、`collect --complete` 的真实路径。
- 不调用 Paper/Live broker API，不发任何订单、不开启 Paper 写入、不启动 M4、不付费订阅数据、不尝试提升 E/S/R。
- 不替操作者签署 A/B/C；不把离线正例、合成恢复、CI 绿或运行成功退出码当成真实市场证据。
- 未经另一轮用户授权，不推送任何代码、证据或文档，不自动延伸到真实采集。

## 四、最终报告格式（Codex 必须逐字提供这些字段）

```text
BASELINE_HEAD=<full_sha>
LOCAL_HEAD=<full_sha>
T7_COMPLETION_INTEGRITY=LOCAL_PASS_WITH_SCOPE|HOLD
P0_A_RED=<evidence>; P0_A_GREEN=<evidence>
P0_B_RED=<evidence>; P0_B_GREEN=<evidence>
FULL_TESTS=<count passed, skip/xfail info, exit code>
M2_FAULT_MATRIX=<result>
ARCHITECTURE_CHECK=<result>
SECRET_SCAN=<result>
PAPER_LIVE_GATE=<result>
CI_REMOTE=REMOTE_PENDING
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
HOST_EGRESS_ISOLATION_UNVERIFIED
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
FIRST_REAL_ONCE_READY=NO
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
NEXT_APPROVAL_REQUIRED=<exact SHA chain for optional future push; real capture always separate>
```

**STOP 条件**：任何 P0 修复不完整、新旧证据被覆盖、模拟写入真实证据集、平台完整性检查不一致、凭证泄漏、意外网络调用、身份链漂移或存在不明确的外部授权，立即 HOLD 并停在阶段门。

**阶段门纪律**：本任务执行成功后只是获得“**T7 本地整改验收**”，下一次必须由用户**另行授权推送**，核实新 HEAD 的双平台 CI，然后操作者本人完成 A–C。首次 `collect --once` 仍是未来的**另一项独立单独授权**，此文件并不授予该权限。
