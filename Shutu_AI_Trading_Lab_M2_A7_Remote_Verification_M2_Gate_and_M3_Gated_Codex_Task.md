# Shutu AI Trading Lab — M2 A7 远端验收、M2 阶段门关闭准备与 M3 条件启动任务

> Task ID: `M2-A7-REMOTE-ATTESTATION-AND-M3-GATED-001`  
> 日期：2026-11-21  
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
> 审查时远端 `main`: `5c3c5cbd3980a02637de1511f6e908dcc2b922db`（A6）  
> 已验证 A6 CI：<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44900846467>，Ubuntu + Windows success，运行 SHA 为 `5c3c5cb`。  
> 用户报告的**本地**提交链：`5c3c5cb` → `8a5f9c5`（A6 CI 记录）→ `ea259c0`（A7 修正）。在本任务编制时，GitHub 尚未查到后两次提交；**不得假定它们已上行或已有远端 CI**。  
> 当前权限：**只允许核查、生成本地报告与阶段门建议，不构成 push、M2 关闭或 M3 启动授权。**

## 0. 目标、裁决与硬边界

本次不启动 A8、不扩大 M2 产品架构整改；目标是核对 A7 本地实证并完成**有授权条件的**远端双平台 CI、提交链验证及 M2 阶段门送审材料。M2 人工关闭与 M3 人工启动是**两个独立决策**，绝不能因为 CI 绿自动执行。

目前独立可确认的是：A6 SHA `5c3c5cb` 的 GitHub CI 成功；A7 只有用户提供的本地报告（目标 `ea259c0`）；不能独立证实 A7 代码及其本地测试日志。用户报告 `347 passed`，相对 A6 `340 passed` 实际增量为 **7**；`338 baseline + 9 A7 new` 可能是将 A6 的 2 个测试也计算为后续总增量，必须以 pytest 收集表和真实提交差异说明，不可双重计数。报告所写“7 passed (5 rounds × 2 assertions each)”也须准确区分 **pytest 测试用例数** 与 **测试内部循环轮次/断言数**。

保留：`E=PASS_WITH_SCOPE(MOCK_ONLY)`（仅限已被证实的 M2 mock 工程范围）、`BLOCKED_DATA`（全市场研究）、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=N_A/evidence_state=NOT_EVALUATED`、`R=NOT_STARTED`。绝不把本地 journal/MockBroker 并发保证扩展为真实券商幂等或实盘可用保证。

**禁止事项**：不得使用 Alpaca Paper/Live 凭证或网络、真实券商订单或资金、解封真实 Holdout、采购数据、放宽风控、删除安全用例、引入第二 OMS/发送出口。不得重写 A2/A5/A6 旧证据、`reset --hard`、`force push` 或为了获得 PASS 弱化断言。未得到用户明确授权不得 `git push`、改写阶段门状态、自动执行 M3/M3.5/M4。

---

## A. 本轮立即可执行：A7 独立静态/本地证据复核（无需推送授权）

### A0 — 真实状态与提交链核验

1. 阅读 `AGENTS.md`、两份 `docs/plans/*v2.1.md`、`docs/reviews/M2-a6-strict-proof-review.md`、A7 任务书 `Shutu_AI_Trading_Lab_M2_A7_Targeted_Proof_Codex_Task.md` 以及用户已提交的 A7 报告。以仓库当前真实文件为准，不凭文本推测文件必然存在。
2. 执行并记录：
   ```bash
   git status --porcelain=v1
   git rev-parse HEAD
   git fetch origin main
   git rev-parse origin/main
   git log --oneline --decorate -8
   git show --stat --oneline 8a5f9c5
   git show --stat --oneline ea259c0
   git diff --stat origin/main...HEAD
   git diff --check origin/main...HEAD
   ```
3. 验证 `8a5f9c5` 是否为 docs-only，`ea259c0` 是否为 A7 测试/证据/报告，且前后 ancestry 连续。若提交不在本地、存在冲突、脏工作区、HEAD 指向其他提交或远端分叉，**STOP 并报告**；不能覆盖操作者工作。
4. 逐个检查 A7 代码和新增证据的事实与报告一致。明确列出实际改动的所有生产源码文件；若有生产变更，标记原因、对应 RED/回归测试和审计范围。

### A1 — 四项核心证明逐行核查（任一关键缺口未补齐即不得送审）

1. **CLAIM_HOLDER_CRASH（≥5轮）**：每轮确实由独立子进程自己成功领取同一个 COID 的 claim，SQLite 持久成为 `SEND_CLAIMED` 后由**成功领取者** `os._exit(37)`/真实强制终止，父进程不抢先 claim；逐轮核对 pid、coid、明确的已提交事实、退出码 `37`、重启后二次 claim `None`、0 Port entry。`exit=37` 自身不是领取成功的证据，要与 durable DB 状态及 worker 因果顺序对应。
2. **RECOVERY_AUTO_HALT（≥5轮）**：每轮从全新 KillSwitch 对象确认 `is_halted()==False`，无预置 `set()`，调用实际 `OmsEngine.recover()` 后 `still_unknown` 包含原意图；再次新建 KillSwitch 验证仍 HALT，保留来自 `recover()` 的审计事件/调用证据，避免复用上一轮状态产生假阳性。
3. **RISK 与 OMS 两层独立拒绝**：分别有明确的 RiskEngine DENY 和 `OMS_DENY_PREAPPROVED_AFTER_HALT`；后一测试必须在 HALT 前创建合法 HMAC 已密封且当时有效的批准决策，在 HALT 后 **无条件**实际调用 `oms.submit()`，断言 `HALT_NEW_RISK`、Port 入口数为 0、没有新发送 claim、没有替代 COID；不得用 `if decision.allow:` 跳过。
4. **PROCESS RACE（≥50轮）与证据**：原 `spawn + Barrier` 并发竞争不得回退。每轮两个不同 PID、READY/GO、两个 attempt 与结果、`errors=[]`、恰 1 winner、持久态 `SEND_CLAIMED`、二次领取拒绝的硬断言必须与报告一致；日志为可解析 JSONL（如果命名 `.jsonl`）；所有测试超时/异常按失败计数。仅能声称跨进程 Journal claim，不是 BrokerPort E2E。

### A2 — 证据完整性/幂等检查

1. 检查 `artifacts/evidence/M2/a7-targeted-proof/` 实际存在 `baseline.md`、claim-holder crash/恢复、Risk-vs-OMS、进程竞争、完整检查、manifest、证据缺口记录等已承诺文件，按**真实文件**出具清单，不得写不存在文件。
2. `evidence-manifest.sha256` 的 2 条非空记录只是数量描述，不等于内容通过：重新计算每条 SHA-256 与相对路径，确保所列文件存在、哈希相等；解释未纳入的文件以及 manifest 自身如何通过 Git 提交保护。不得将空文件 hash 作为自身校验。
3. 校验 JSONL 每一非空行均为独立 JSON 对象；核对至少 5 crash + 5 recovery + 50 race 的原始轮次、不重复、COID 唯一性、执行系统/版本、代码 SHA、分母及失败情况。不能仅采信 summary 行。
4. 查 `git diff origin/main...HEAD -- artifacts/evidence/M2/`，确认本轮未再次覆盖先前提交的 A2/A5/A6 历史证据；发现旧日志改写要清楚记录且 STOP 进入人工裁决。
5. 用 `pytest --collect-only` 核实 **340 → 347 = +7** 的用例构成与 A7 增量；如 `338 + 9` 其实含 A6 两例，报告需修正统计口径而非凭空增加测试。
6. 将 A7 的**独立审查结论**输出到 `docs/reviews/M2-a7-remote-readiness.md`（可另附精简矩阵）；即便本地全绿也只能标 `A7_LOCAL_EVIDENCE_REVIEWED / CI_REMOTE_PENDING`。

### A3 — 本地命令核验（允许在新临时目录运行；不改旧证据）

```bash
python -m pytest -q tests/fault_injection/test_a7_targeted_proof.py   # 如果真实文件名不同，先发现后使用实际路径；不能凭猜测宣称运行
python -m pytest -q
python scripts/check_environment.py
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
```

再单独验证原 100 轮线程 Port-entry、50 轮严格进程 claim、1,080 故障矩阵仍通过；各项记录真实 EXIT code、平台、Python、HEAD、用例总数、重试/skip/xfail、证据路径。不要为了新跑测试改写 tracked 的旧日志；如旧测试仍写固定跟踪路径，应先在安全隔离的临时副本/工作树运行，或先提交可复现的最小测试输出路径修正，再按新 SHA 重新做 CI。失败不得隐藏。

**若 A0–A3 已充分通过**，结论仅可为：`M2_A7_LOCAL_REVIEW_PASS / CI_REMOTE_PENDING / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`。若有 P0 实际失败，使用 `M2_A7_REMEDIATION_REQUIRED`，列精确缺陷，不以新的大范围重构替代直接证明。

---

## B. 条件任务：远端双平台 CI（必须先获得用户单独 Push 授权）

**当前消息没有授予 push 权限。** 只有用户在随后的消息明确批准范围为 `8a5f9c5` → `ea259c0` 及必要的非产品证据修正提交，且 A0–A3 PASS 后，才能执行 B。

1. Push 前核对 `origin/main` 为本地 HEAD 的祖先、无意外提交、工作树 clean、无秘密；**仅正常 fast-forward push，不 force push**。出现远端新提交则 STOP，不能直接覆盖或自行合并风险边界变化。
2. 执行授权范围内的 push 后，记录**实际远端 HEAD**、所有推送 SHA、GitHub Actions run URL、workflow run 的 `head_sha`、Ubuntu/Windows 两个 Job 的 `conclusion`。
3. 两平台必须在**最终 A7 测试代码 SHA**（或包含 A7 的后续只增补文档 SHA）上运行且成功；不能复用旧的 A6 run `44900846467`。必须核对 CI 所运行脚本是否实际包含 A7 新测试，而非仅依赖总量；如仓库 CI 配置只执行 pytest，应确认本次 pytest 收集到 A7 用例。
4. 远端 CI 的作业 SUCCESS 与“保留了双平台每轮原始日志”是两件事：没有 CI 上传 artifact 时写 `CI_JOB_PASS / REMOTE_PER_ROUND_LOG_NOT_ARCHIVED`，不得冒称已留存完整远端轮次数据。
5. 如果 Ubuntu/Windows 任何一平台失败，状态为 `M2_A7_REMOTE_REMEDIATION_REQUIRED`，只做针对性 RED→GREEN，不先关闭 M2。
6. 如补充 `docs/reviews/M2-a7-ci-verification.md` 等文档，本地可生成并提交；**再次 push 仍需遵守用户授予的具体 push 范围**；文档补录的 SHA 不应冒充先前 CI 运行 SHA。保留原测试 SHA 与报告 SHA 的对应。

双平台真实绿且 A7 证据可核对后，最多宣布：

`M2_A7_TARGETED_PROOF_REMOTE_VERIFIED / M2_CLOSE_REVIEW_READY / E=PASS_WITH_SCOPE(MOCK_ONLY) / BLOCKED_DATA / U-1 UNRESOLVED / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

**B 结束强制 STOP：不得自动关闭 M2，不得启动 M3。**

---

## C. 仅供用户审议：M2 关闭阶段门（另需明确的人类签批）

整理 `docs/reviews/M2-closure-decision-package.md`，包括：M2 原始 Gate 与 A2/A5/A6/A7 各自“真正证明了什么、未证明什么”、双平台 CI SHA/run/job、340→347 的用例统计、1,080 故障矩阵及失败记录、架构变更、风险残余及独立边界。未获取远端 A7 CI PASS 不能出具“建议已可关闭”决策。

建议**通过与限制并存**：M2 工程范围仅 mock/fake broker 的 OMS/Risk/Journal 安全不变量完成；Broker 侧真实幂等和跨宿主执行仍未验证，全市场研究数据仍 BLOCKED，M2 关闭不等于上线准入。`E=PASS_WITH_SCOPE(MOCK_ONLY)` 与 Gate 互相独立。

只有用户亲自明确发布 **`M2_GATE=CLOSED`** 时，才可在阶段门记录中记载用户审批的真实来源、时间及范围；不得生成虚假签名、代签或以 Codex/CI 结果代替。若用户选择 HOLD，维持 `M2_GATE=USER_PENDING` 并停止。

---

## D. 仅供未来单独授权：M3 合成数据离线回测（不得同次自动进入）

**必要前置条件同时满足**：①真实记录的用户 `M2_GATE=CLOSED`；②后续另一项用户明确授权 `M3_START=APPROVED`。A7 CI 绿、M2 决策包、阅读此任务文件都不等于 M3 启动授权。

启动后的范围应严格遵守两份 v2.1 计划 M3：

- 预先冻结 `configs/evaluation_protocol.yaml` 与 `docs/adr/ADR-004-evaluation.md`，包含数据/协议/code/seed hash、PIT 边界、研究/验证/滚动 OOS/最终 Sealed Holdout/前向 cohort 角色、Purge/Embargo、唯一候选未来选择规则、PASS/FAILED/INCONCLUSIVE/INVALIDATED、研究预算及成本 ×1/×2/×3。
- 仅用合成/离线 fixture 建 `src/trading_lab/backtest/`、`validation/` 的最小可重算回测与验证门；Decimal 现金/持仓/交收/费用守恒，模拟延迟、价差、滑点、部分成交、退市/企业行为、可成交时间，禁止未来信息泄漏。
- 在 M3 只**实际运行** B0 现金、B1 宽基 ETF 买入持有和 B2 透明规则；按 Architecture §4.3 原义**登记冻结** B3–B8 定义，不提前开发 Regime/AI/Portfolio 空架构。
- 将 B2 单规则候选（如趋势/动量/均值回归）仅作为**合成 fixture 上的工程对照**，不得宣称策略 alpha。凯利、波动率目标、风险平价、CVaR 只能登记为后续受控研究目标，不突破 v2.1 阶段范围。
- 保留全量安全回归、1,080 矩阵、无真实 Broker/Live 凭证、Holdout 未解封、`BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED` 不变，S/R 证据不得错误晋级。
- 完成后输出 M3 三轨报告，`M3_GATE=USER_PENDING / M3.5_START_APPROVAL_PENDING`，STOP。

如果用户同时明确给出两个授权，也应按**阶段门实际顺序**执行并分别留存证据；默认本任务只授权 A 的只读/本地检查部分，不得将其解释为对 B/C/D 的自动授权。

---

## 直接粘贴给 Codex 的启动提示词（**当前允许范围：A0–A3**）

> 阅读本任务书、`AGENTS.md`、两份 v2.1 权威计划、A6/A7 任务与报告。仅执行 A0–A3：核对本地 `8a5f9c5`、`ea259c0` 和远端 `5c3c5cb` 的 SHA/父子关系，逐行验收成功 claim 的 worker `os._exit(37)`、无预置 HALT 的 `recover()`、RiskEngine 与 OMS 独立硬拒、50 轮 spawn Barrier 逐轮断言，并验证 A7 JSONL / manifest 和测试总量 340→347 的真实归因。运行不覆盖历史证据的完整本地回归，生成 M2 阶段门送审材料。未经用户**另行明示 push 授权**不得执行 B，未经用户独立审批 `M2_GATE=CLOSED` 不得进行 C 的状态变更，未经 `M3_START=APPROVED` 不得执行 D。保留 `BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED` 与 Live 禁止。完成后 STOP，明确报告远端 CI、阶段门和待审批事项。
