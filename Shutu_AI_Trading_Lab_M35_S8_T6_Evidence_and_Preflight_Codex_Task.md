# Shutu AI Trading Lab — M3.5 S8 T6 远端验收对账与操作者预检准备（Codex 任务指令）

> 执行范围：**只读核对 + 必要的本地文档补证**。严禁自动 push、真实行情 API、凭证读取、任何订单（Paper / Live）、M4 启动及阶段门升级。审批纪律优先于任务完成速度。

## 已独立核验基线（2026-11-22）

- 仓库：`shutu-ai/Shutu-AI-Trading-Lab`。
- `origin/main` = `2a60864fd072f1dd3dde0ef62b303224da6f9781`。
- 远端 CI run `45023566557`，head 与 origin/main 一致，Ubuntu `926 passed in 46.92s`，Windows `926 passed in 384.09s`；两平台架构检查 0 违规。
- `fc5c0c5` 初次远端运行 `45018794107` 的 Windows 两项 pin 失败已由 `a3bf463` 的 LF 规范化 pin 修复；随后 `2a60864` 刷新了 3 个 M2 并发证据日志（**提交信息已披露 regeneration**，历史版本保留于 Git）。
- 用户报告本地另有未推送 `94019e9`（remote-ci.md、verification.log、review 状态回填）。**此提交未在远端，尚未独立审阅**。
- `API_VERIFIED=NONE`，`REAL_FORWARD_DAYS=0`，`S8_REAL_DATA_READY=OPERATOR_PENDING`，`M3.5_GATE=USER_PENDING`；`PAPER_WRITE=NOT_AUTHORIZED`，`S=INCONCLUSIVE`，`R=NOT_STARTED`，`BROKER_BEHAVIOR_UNVERIFIED`，`HOST_EGRESS_ISOLATION_UNVERIFIED`，全市场历史 `BLOCKED_DATA`。

## T6.0 — 本地现场只读盘点（STOP/GO）

1. 记录 `git status --porcelain=v1 -uall`、当前 `HEAD`、`git log -5 --oneline`、`git rev-parse origin/main` 和上游跟踪状态。不可假设当前工作树 clean，不可 reset、checkout 覆盖、amend、rebase、cherry-pick、force-push 或清理未跟踪文件。
2. 对比远端 `origin/main` 与上述完整 SHA；若出现新远端 HEAD、意外分支或本地未保存变更，**STOP** 并报告，不做自动合并。
3. 验证 `94019e9` 是否存在，是否直接基于 `2a60864`（或具有清晰、可审核的父链），列出 `git diff --name-status 2a60864..94019e9` 和文档 diff；审查是否严格属于回填及必要补证。若含运行代码、配置、测试阈值、历史事实不实或新证据自称真实，**HOLD**。

## T6.1 — 远端 CI 证据再核对

1. 核对 run `45023566557` 的 HEAD SHA、两平台 job conclusion 与测试原始日志中的 `926 passed`；检查环境、架构、密钥扫描和 live-blocked 相关步骤是否成功。
2. 保留 run `45018794107` 的 Windows RED 事实与 `a3bf463` 修复的因果链；不能写成“首次 CI 全绿”。
3. 在本地文档中准确区分：工程代码 `2a60864` 已 `REMOTE_VERIFIED`；未推送文档提交 `94019e9` 仍 `LOCAL_ONLY`；该 CI 不证明真实市场 API、行情最终性、主机出口隔离或 Broker 行为。

## T6.2 — M2 历史并发日志再生溯源（必要补证）

独立核对 `2a60864` 的提交信息 `chore(M3.5-S8 R1): regenerate A2/A5/A6 self-rewriting evidence logs`，以及以下 3 个文件相对于 `a3bf463` 的内容变更：

- `artifacts/evidence/M2/a5-true-process-race/process_concurrent_50.log`
- `artifacts/evidence/M2/a6-strict-process-proof/barrier_50_rounds.jsonl`
- `artifacts/evidence/M2/final-send-claim/a2-quantitative-close/process_50_rounds.log`

对每个文件记录：旧/新 blob SHA 或 sha256、差异性质、旧版本 Git 可追溯位置、新版本运行来源、轮次数/单胜者等关键不变量的静态核对结果。**不要为消除差异重新跑并覆盖旧日志**，也不要删除 Git 历史。如果只是新一轮有效复跑且提交信息已披露，定性为“已披露的证据再生 + 版本化历史可追溯”，不要错误宣称是未授权篡改；若发现协议判据改变、轮次失真或不可解释的数据漂移，则 HOLD，并明确升级为独立整改项。

## T6.3 — 准备 docs-only 回填候选（不可推送）

1. 审读 `94019e9` 的 `remote-ci.md`、`verification.log`、`docs/reviews/M3.5-s8-contract-remediation.md` 的内容，确保 CI SHA、运行编号、计数、Windows 旧故障、状态字段都准确。
2. 若 T6.2 需要追加说明，只允许**追加式**本地文档/证据索引，不改历史日志、不重写已封存证据、不改生产代码和配置；不得悄悄 amend `94019e9`，变更须单独说明、单独记录 Git diff，必要时新建独立本地提交并报告 SHA。
3. 运行安全的文档差异检查（如 `git diff --check`、无敏感值检查），明确列出待推送提交的**完整有序 SHA 链**。
4. **停止于 `PUSH_AUTHORIZATION_REQUIRED`**，不得执行 `git push`。用户下一轮单独明确授权并确认新的 SHA 列表后才允许推送；推送后再核查新 CI 的 HEAD 与 job 日志，不预先标记成功。

## T6.4 — Operator preflight A–C：只准备核验清单，不代操作者签署

读取 `artifacts/evidence/M3.5/s8-contract-r1/operator-preflight.md`，为账户所有者输出不含秘密的逐项核验表：

- A：由本人核对 Alpaca Paper-only 账户及当前 Basic/IEX 数据使用条款；不假设文档中的 `license_attestation.operator_confirmed: true` 就是已签署事实。
- B：仅本人掌控运行时的进程级凭证注入；Codex 不得查看、记录、回显、复制或索要真实密钥；密钥不得进入仓库、日志、CI、对话和屏幕截图。
- C：由本人在真实执行环境确认只允许 `data.alpaca.markets:443`，并对 `api.alpaca.markets`、`paper-api.alpaca.markets` 及未授权外部主机做无凭证的网络层拒绝验证；同时检查代理/直连不同路径。仅应用层 GET-only 守卫不算完成 C。

目前代码 `preflight()` 主要判断授权 token 和凭证环境变量是否存在，并不会自动证明操作者亲签、许可或主机 egress 已隔离。必须将这些列为**人工外部门槛**；证据不足就保留 `HOST_EGRESS_ISOLATION_UNVERIFIED`，不得将 C 标为通过。

## T6.5 — 出口及下一次授权请求

仅输出以下交付物，随后停止：

1. `T6_AUDIT_VERDICT`：`READY_FOR_DOCS_PUSH_APPROVAL` 或 `HOLD`（附具体原因及证据位置）；
2. `DOCS_ONLY_PENDING_SHA_CHAIN`：完整 SHA 列表与改动文件列表；
3. `M2_REGENERATED_EVIDENCE_PROVENANCE`：三文件对比与审计定性；
4. `OPERATOR_PREFLIGHT_A_B_C`：每项 `VERIFIED_BY_OPERATOR` / `PENDING_OPERATOR` / `BLOCKED`，不得代签；
5. `FIRST_REAL_ONCE_READY`：默认 `NO`；只有外部人工前提全证实且用户**另一次单独授权**后，才能由账户所有者在受控环境执行**一次** `python scripts/run_m35_s8_shadow_real.py collect --once`；真实采集前不得设置 `API_VERIFIED` 或增加 `REAL_FORWARD_DAYS`；
6. 保持：`M3.5_GATE=USER_PENDING`、`PAPER_WRITE=NOT_AUTHORIZED`、`S=INCONCLUSIVE`、`R=NOT_STARTED`、`BROKER_BEHAVIOR_UNVERIFIED`、全市场历史 `BLOCKED_DATA`。

## 绝对禁止

本轮不得 push、不得访问真实 Alpaca API、不得读取真实凭证、不得执行 collect、不得下达 Paper/Live 订单、不得购买数据、不得启动 M4、不得将模拟数据计入真实前向日数、不得通过自报布尔值伪造 PASS。任何缺证都应 fail-closed 并停止于人工阶段门。
