# T6 审计记录（T6.0–T6.5，2026-11-22，只读核对 + 追加式补证）

> 任务：`M35-S8-T6-EVIDENCE-AND-PREFLIGHT`（用户会话指令，只读审查 + 必要本地文档补证；**未推送**、未触碰真实 API/凭证/订单/M4）。
> 审计工具：`scripts/audit_t6_m2_provenance.py`（只读，静态核对 git 对象与工作树，不重跑不覆盖）；本记录与该脚本为**新增文件**，独立提交，不改任何历史日志/封存证据/生产代码/配置。

## T6.0 本地盘点（STOP/GO → GO）

- 工作树：仅未跟踪的 T6 任务书本身（输入文档）；HEAD = `94019e9093d7ed8daaa9ba1fd671c22d9781d7e9`。
- `origin/main` = `2a60864fd072f1dd3dde0ef62b303224da6f9781`（与任务书独立核验基线一致，无意外远端 HEAD/分支）；`main...origin/main [ahead 1]`。
- `94019e9` 存在，parent = `2a60864`（直系子提交，父链清晰）；`git diff --name-status 2a60864..94019e9` = 恰 3 个文档文件。

## T6.1 远端 CI 再核对（run 45023566557）

- head = `2a60864fd072f1dd3dde0ef62b303224da6f9781` = origin/main ✓；event=push；conclusion=success。
- 双 job conclusion = success，**每 job 失败步骤数 = 0**；原始日志计数：ubuntu `926 passed in 46.92s`（job 137211543143）、windows `926 passed in 384.09s`（job 137211542872）。
- 门步骤双平台全部 success：Environment check / Architecture boundary check / Secret (leak) scan / Paper runtime live-artifact gate。
- 因果链保持：run `45018794107`（head `fc5c0c5`）windows ✗（2 failed, 924 passed，两个字节冻结 pin）→ `a3bf463` LF 规范化修复 → run `45023566557` 同平台矩阵绿——**未写成"首次 CI 全绿"**。
- 精确区分（本地文档口径）：工程代码 `2a60864` = `REMOTE_VERIFIED`；未推送文档提交 `94019e9` = `LOCAL_ONLY`；该 CI **不**证明真实市场 API、行情最终性、主机出口隔离或 Broker 行为。

## T6.2 M2 三份再生日志溯源（`m2-provenance-audit.txt` 为完整机器输出）

| 文件 | blob（old@a3bf463 → new@2a60864） | 不变量核对（两版各自） | 掩码结构一致 |
|---|---|---|---|
| `a5-true-process-race/process_concurrent_50.log` | `aa25474aa63a…` → `80170a633c4c…` | 50 回合、coid 唯一单调、每回合恰一 claimant、winner=claimant（pidA/pidB 位置显式）、双 worker pid 不同、SUMMARY rounds=50/violations=0 且胜者=双 worker | True |
| `a6-strict-process-proof/barrier_50_rounds.jsonl` | `c3fc3b1759fc…` → `a987dddc8ec4…` | 52 行真实形状（注释头 + 50 回合 + SUMMARY）；回合 1..50 单调；每回合恰一 claimant；winner ∈ 本回合两 pid；双 pid 均有胜出（活性）；SUMMARY violations=0 且 pid 集一致。**已声明局限**：A6 的 `claimed` 向量为到达序非 pid 位置序，winner↔claimant 的位置绑定由生成器自身 `violations=0` 计数佐证（静态审计不冒充该绑定） | True |
| `final-send-claim/a2-quantitative-close/process_50_rounds.log` | `714c18bcef9f…` → `0f336e4e7351…` | 50 竞争回合（coid 唯一、单 claimant、winner=claimant、ok=True）+ 5 crash 回合（crash_claimed=True/survivor=False/ok=True）+ SUMMARY 50/5/0 | True |

- 差异性质：运行身份掩码（pid/胜者/claimed 取向/coid 序列/解释器版本）后**三文件结构逐字一致** → 新版 = 同一协议的一次新鲜有效运行，判据零改变、轮次零失真。
- 可追溯：三个旧 blob 均可由 `git show a3bf463:<path>` 复现；`2a60864` 提交主题明示 "regenerate …"（已披露）；历史上同惯例先例 `4d7acfb`/`e1301c5` 佐证流程一致性。
- **定性：已披露的证据再生 + 版本化历史可追溯——非未授权篡改；无 HOLD 事项。** 运行来源：`2a60864` 由修复后（`a3bf463`）本地全量验证套件的 smoke_mock 步骤再生（verification.log 时间线一致）。

## T6.3 `94019e9` 审读（docs-only 校验）

- 范围：恰 3 文件（`remote-ci.md`、`verification.log`、`docs/reviews/M3.5-s8-contract-remediation.md`），16+/12-，零代码/配置/测试改动。
- 事实逐项核对（对照 T6.1 实测）：run 编号、head SHA（含 `2a60864` 全长 SHA）、双 job ID、双平台计数与时长、run 1 失败数字（2 failed / 924 passed）、根因描述、`45013402697` 旧代码口径、边界状态字段（`API_VERIFIED=NONE` 等）——**全部准确**。
- 无新证据自称真实事实；无历史改写；`git diff --check` 干净；改动文件经 `scan_secrets.py` 全仓扫描 0 发现。
- 结论：**严格属于回填及必要补证，不构成 HOLD。**

## T6.4 Operator preflight A–C（只准备清单，不代签）

状态定义：`VERIFIED_BY_OPERATOR`（账户所有者签署）/ `PENDING_OPERATOR`（清单就绪待人工）/ `BLOCKED`（缺证不得推进）。

| 项 | 状态 | 说明 |
|---|---|---|
| A 账户与许可（Paper-only + Basic/IEX 条款本人核对） | `PENDING_OPERATOR` | 清单见 `operator-preflight.md` §A；`license_attestation.operator_confirmed: true` 是配置声明，**不**视为已签署事实 |
| B 凭证进程级注入（仅本人掌控；Codex 零接触） | `PENDING_OPERATOR` | `operator-preflight.md` §B；本审计全程未读取/记录/索要任何密钥（`scan_secrets` 0 发现佐证仓库侧干净） |
| C 主机出口隔离（仅 `data.alpaca.markets:443`；两个交易主机 + 泛互联网网络层拒绝负例；代理/直连双路径） | `PENDING_OPERATOR` | `operator-preflight.md` §C；`preflight()` 应用层双门**不**证明 C——证据不足即保持 `HOST_EGRESS_ISOLATION_UNVERIFIED`，不得标通过 |

## T6.5 出口

1. `T6_AUDIT_VERDICT` = **`READY_FOR_DOCS_PUSH_APPROVAL`**（T6.0–T6.3 全部通过；无 HOLD 事项）；
2. `DOCS_ONLY_PENDING_SHA_CHAIN`（按序）= `94019e9`（remote-ci.md + verification.log + 报告回填）→ `<本审计提交 SHA>`（t6-audit.md + 审计脚本 + m2-provenance-audit.txt）；改动文件清单见两提交的 name-status（全为 docs/evidence/新审计工具，零生产代码）；
3. `M2_REGENERATED_EVIDENCE_PROVENANCE` = 已披露的证据再生 + 版本化历史可追溯（§T6.2，机器输出 `m2-provenance-audit.txt`）；
4. `OPERATOR_PREFLIGHT_A_B_C` = A/B/C 均 `PENDING_OPERATOR`（不代签）；
5. `FIRST_REAL_ONCE_READY` = **NO**（外部人工前提 A–C 未证实；即便证实，首次 `collect --once` 仍需用户**另一次单独授权**并由账户所有者在受控环境执行；真实采集前 `API_VERIFIED`/`REAL_FORWARD_DAYS` 不得变动）；
6. 保持：`M3.5_GATE=USER_PENDING / PAPER_WRITE=NOT_AUTHORIZED / S=INCONCLUSIVE / R=NOT_STARTED / BROKER_BEHAVIOR_UNVERIFIED / BLOCKED_DATA(全市场历史)`；**停止于 `PUSH_AUTHORIZATION_REQUIRED`，本轮零推送。**
