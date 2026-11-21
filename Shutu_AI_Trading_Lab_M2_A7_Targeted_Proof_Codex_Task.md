# Shutu AI Trading Lab — M2 A7 定向证明纠偏与阶段门复核任务

> Task ID: `M2-A7-CLAIM-OWNER-CRASH-AND-RECOVERY-PROOF-001`  
> 日期：2026-11-21  
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
> 审查基线：远端 `5c3c5cbd3980a02637de1511f6e908dcc2b922db`  
> GitHub Actions：`44900846467`，Ubuntu/Windows `SUCCESS`，执行的 SHA 为 `5c3c5cb`。  
> 本地 `8a5f9c5` 据用户报告为后补验证记录；**远端尚未核实该提交**，只能由本机复核。  
> 决议：**A7 为 M2 小范围证据补强，非 M3 启动授权**。

## 0. 独立审查结论与禁止事项

截至当前审查，A6 的跨进程 `spawn + Barrier(2)` 为实质上的双方同步到达，足以避免 A5 那种父进程等待 A 完成再启动 B 的顺序重放；该机制应保留。但是，A6 测试对关键结果和日志的硬断言不足。A6 的 crash/recovery 测试另有两个实质性证明缺口：

1. **错误的 crash 主体**：`tests/fault_injection/test_a6_strict_process_proof.py` 中先在父进程直接 `journal.claim_send_attempt()`，再启动子进程尝试已消费的 claim；子进程 `os._exit(1)` 只说明“失败的第二 claimer 退出”，没有证明“成功 claimer 崩溃后恢复”。
2. **恢复前预置 HALT**：A6 在 `recover()` 之前通过 `ks1.set(...)` 主动写入 HALT，再通过新 KillSwitch 对象检查持久性；并未隔离证明 `recover()` 对未知发送状态产生并持久化 HALT。要分开验证“手动 HALT 持久化”与“恢复逻辑自动 HALT”。
3. **OMS 下游阻断断言可跳过**：`if new_decision.allow: oms2.submit(...)`。在 HALT 下若 RiskEngine 直接拒绝，`oms2.submit()` 没有被调用，仍然写出 `new_risk_blocked=True`。这不是 OMS 独立拒绝能力的证明。
4. **证据/断言不符**：A6 并发测试没有逐轮 assert 结果 PID、轮次、errors、已消耗的持久 claim 状态；`barrier_50_rounds.jsonl` 实际是纯文本而非 JSONL，也没有报告中的 `ready_count/attempted_count/errors/db_state`。目录没有报告列出的 `baseline.md`；manifest 自身条目为 SHA256(empty file) 不能自校验；A6 提交修改了 A2/A5 旧日志，须停止未来覆盖行为。

注意：**这些是测试覆盖与证据问题，不代表生产 OMS 已被证明存在重复发单漏洞。** 只有新的可重现 RED 才能授权最小产品修复。当前有效范围仍为 `E=PASS_WITH_SCOPE(MOCK_ONLY)`、`BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED`，`M2_GATE=USER_PENDING`、`M3_START_APPROVAL_PENDING`。

**绝对禁止**：未经授权 push、代签人工阶段门、运行 M3/M3.5、实连 Alpaca Paper/Live、获取账户凭证、真实订单/资金操作、解封真实最终 Holdout、修改真实数据准入结论、削弱风险控制。不得 force push / reset --hard / 覆盖旧审计证据；不新增平行 OMS 或风险引擎。

## A7-T0：环境与基线核实

1. 阅读 `AGENTS.md`、两份 `docs/plans/*v2.1.md`、`docs/reviews/M2-a5-independent-closure.md`、`docs/reviews/M2-a6-strict-proof-review.md`、现有 `tests/fault_injection/test_a6_strict_process_proof.py` 与 M2 三轨报告。
2. 记录 `git status --porcelain=v1`、`git rev-parse HEAD`、`git rev-parse origin/main`、最新远端 SHA、CI run 与差异；独立核实本地 `8a5f9c5` 的存在、父提交、是否 docs-only、是否仍未推送。保留所有未提交工作；不臆断本地 SHA 已通过远端 CI。
3. 写 `artifacts/evidence/M2/a7-targeted-proof/baseline.md`（此文件必须实际存在），记录上述四项审查发现所对应源码行/行为、原始证据与预声明的验收门槛。

## A7-T1：真正的 claim-holder 崩溃和重启（P0，至少 5 轮）

每轮必须由**真实 OS 子进程自己**使用独立 SQLite 连接领取 claim、完成持久提交，然后子进程在 `SEND_CLAIMED` 后、任何 BrokerPort 调用之前被**非正常终止**。父进程不能预先领取 claim，也不能以“第二个失败 claimer 退出”代替。建议：

- 父进程仅创建合法持久意图/attempt，启动唯一领取者 worker；worker 读取 journal 并执行 `claim_send_attempt()`。
- worker 提供不可混淆的 `CLAIM_COMMITTED` 事实（包含 COID、PID、成功、commit 后 DB state 和审计事件），在受控阻塞点等待；由父进程在确认 commit 后调用 `terminate()/kill()`，或 worker 定点 `os._exit(37)`。记录实际 exit code / signal、PID、进程已退出的证明。不能用 `sys.exit(0)`。
- 另一个新进程重开 Journal 后重新领取同一 COID，必须拒绝；状态仍 `SEND_CLAIMED`，不得执行端口调用、自动重置 claim 或生成替代 COID。
- **独立无预置 HALT 场景**：新进程/新对象重建 Journal、Fence、KillSwitch、OMS；恢复前持久 KillSwitch 必须处于“未人为 HALT”状态（不允许先 `ks.set()`）。调用真实 `oms.recover()`；确证 `still_unknown` 包含原始意图、恢复动作引发全局 HALT，随后**再次重建** KillSwitch 后仍 `is_halted()==True`。记录审计事件来源。若实际设计要求其他系统组件负责 HALT，必须通过完整的正式恢复入口证明，不得改写验收语义。
- 每轮独立数据库/账户或严格隔离，避免其他未知意图触发 HALT 造成假阳性；至少 5/5 轮成立。
- 要求 0 新增风险端口调用、0 未经授权解锁、0 盲重发。每轮明确区分 `CLAIM_HOLDER_CRASH` 与 `RECOVERY_HALT_ASSERTION` 两项证明。

## A7-T2：RiskEngine 与 OMS 双层阻断（P0）

必须设计**两条分开的、不可条件跳过的测试**：

1. `RISK_DENY_AFTER_HALT`：在 HALT 后创建新意图，实际调用 RiskEngine，显式 assert `allow=False`（或系统预定义拒绝值），验证正确原因、零端口调用。
2. `OMS_DENY_PREAPPROVED_AFTER_HALT`：在 HALT **之前**生成可信、有效、HMAC 密封且未过期的批准决策及新意图，并确认其最初满足准入；随后激活/恢复产生的 HALT；**必须实际调用** `oms.submit(...)`（用 spy 计数证明调用了 1 次），断言真实 OMS 接口按契约返回 `HALT_NEW_RISK` 或其精确类型的拒绝（先从现有代码/契约确认，不许吞异常），并确认 Journal 无不应存在的可发送 claim、BrokerPort entry=0、FakeBroker created=0。

不允许 `if approved: submit`、`except Exception: pass`、`or True`、宽泛异常吞断言、只看最终 FakeBroker 创建数；若无法获得真实有效的前置批准应当 **FAIL/INCONCLUSIVE**，不能报通过。单独验证超时、HMAC 错误等其它条件不能替代 HALT 触发的拒绝。

## A7-T3：保留并强化真实跨进程竞争（P1，至少 50 轮）

保留 `multiprocessing.get_context('spawn')` 两个不同 PID 的共享 Barrier 并发路径。建议采用 parent 参与 `Barrier(3)` 的 `READY -> PARENT_GO -> CLAIM -> RESULT`，使父进程确实在收齐两名 READY（带 round_no、PID）后才放行；如选择其它等价设计，必须提供父进程放行和双方尝试的证据。

每轮都执行**硬断言**：

- 两个独立 PID，两个 READY 且均属于本轮；父进程发出 GO；两个不同 PID 的 RESULT 且 round_no 匹配本轮、`attempted_count=2`；
- `error is None` 对两者必须成立，不允许将异常当成合法输家；exactly one `claimed=True`，另一条 `claimed=False`；
- DB reopen 后确认该 COID 持久 `SEND_CLAIMED`，无法第二次领取；不依赖 FakeBroker 去重掩盖双发；
- 任何 timeout、queue 异常、错误轮次、缺失 READY/RESULT、worker 非零退出、双胜/双败、DB state 不匹配都必须硬失败；禁止把失败轮次重试成 PASS 后隐藏首次故障。

保留原 100 轮双线程 Port-entry 测试和 1,080 fault matrix，不得降分母。此项仍只证明跨进程 **Journal claim 仲裁**；没有真正多进程 BrokerPort 共享入口计数之前，不称为跨进程 Port E2E。

## A7-T4：审计证据、一致性及日志完整性（P1）

新增独立目录（不得覆盖 A2/A5/A6 已提交的证据）：

```text
artifacts/evidence/M2/a7-targeted-proof/
  baseline.md
  claim_holder_crash_5.jsonl
  recovery_halt_5.jsonl
  risk_vs_oms_block.jsonl
  process_race_50.jsonl
  full_checks.log
  evidence-manifest.sha256
  ci-verification.md
  evidence-gaps.md

docs/reviews/M2-a7-independent-proof-review.md
```

- `.jsonl` 必须逐行是可解析 JSON object（不能以文本行冒充）；字段包括 `run_id/test_id/round_no/pid/phase/coid/ready/go/attempted/claimed/error/db_state/port_entries/exitcode` 的适用子集，必要字段缺失即证据失败。
- 证据生成必须区分本地和 CI 的 OS/版本/运行 SHA；CI 在 A7 SHA 上真实执行后才能标 `CI_REMOTE_VERIFIED`；若没有可下载 CI 原始证据，必须注明仅有 CI 作业成功记录，不能冒称已留存每轮远端日志。
- `evidence-manifest.sha256` 在所有文件生成后构建，**不得在自身清单中给自己写虚假的空文件哈希**；提供可复现、跨平台的清单验证命令与结果。可仅列子文件并由 Git commit 保护 manifest。
- 如旧 A2/A5/A6 测试运行会改写已跟踪日志，修复**测试输出路径/证据保存机制**（测试临时目录、CI artifacts 或独立 append-only 目录），不重写已提交的历史证据；承认既有 A6 提交的修改事实，不做静默回滚或掩盖。
- 填补 A6 报告中 `baseline.md` 缺失、以及 READY/GO/错误计数未落盘的历史不一致说明；可以新建 A7 证据，不回填并冒充 A6 当时真实生成的数据。
- 复核生产变更统计；`4a327b4` 的 `fence.py` 属前期产品代码修改，A6 新 SHA 未修改产品模块。按提交分别叙述，不混淆。

## A7-T5：全量质量门与阶段停止

执行并真实记录 Python 版本、平台、HEAD/工作树、退出码与测试覆盖：

```bash
python -m pytest -q tests/fault_injection/test_a6_strict_process_proof.py
python -m pytest -q
python scripts/check_environment.py
python scripts/check_architecture.py
python scripts/scan_secrets.py
python scripts/verify_live_blocked.py
python scripts/smoke_mock.py
git diff --check
```

附加核查 1,080 fault matrix、原 100 轮 Port-entry 和 50 轮 spawn claim（不得 skip/xfail），架构依赖方向、密钥泄露、Paper/Live 强隔离、真实 Broker 未调用、无新增生产依赖。

**通过门槛（全部必须成立）**：≥5 轮真实 claim-holder 退出；≥5 轮新进程恢复自动持久 HALT；独立 Risk 拒绝与 OMS submit 拒绝均有实际调用及 0 Port entries；≥50 轮 Barrier 真实同步并逐轮所有硬断言通过；所有证据格式/哈希/缺口说明可复核；全部原测试+新测试和 1,080 矩阵全绿。发现实际产品缺陷时先 RED 再最小 GREEN，且只改必要的正式模块。

本地 PASS 后：

`M2_A7_TARGETED_PROOF_LOCAL_PASS / CI_REMOTE_PENDING / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

未经用户**另行推送授权**不得 push；推送后 Ubuntu/Windows 在新的实际测试 SHA 均 PASS 且证据充分，方可：

`M2_A7_TARGETED_PROOF_REMOTE_VERIFIED / M2_CLOSE_REVIEW_READY / E=PASS_WITH_SCOPE(MOCK_ONLY) / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

失败：`M2_A7_REMEDIATION_REQUIRED`，绝不为了关门放松断言。

**A7 完成强制 STOP**：不自行关闭 M2、不代签、不自动开始 M3。后续必须由用户分别明确签批 `M2_GATE=CLOSED`、`M3_START=APPROVED`，并保留 `BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=N_A/NOT_EVALUATED`、`R=NOT_STARTED`。获批后的 M3 只在两份 v2.1 原计划范围内执行合成数据/离线回测与 B0–B2，不得提前启动 M3.5、M4、Paper 或 Live。

## 可直接粘贴给 Codex 的启动提示词

请阅读 `Shutu_AI_Trading_Lab_M2_A7_Targeted_Proof_Codex_Task.md`、`AGENTS.md`、M2 A6 独立审查发现及两份 v2.1 权威计划。**本次仅执行 A7-T0～A7-T5。** 首先核查当前本地 HEAD、`8a5f9c5` 未推送提交、工作树；不得覆盖历史工作。纠正 A6 的三项 P0 证据问题：真正成功领取 claim 的 OS 进程在 commit 后异常退出、无预置 HALT 的 recover 自动全局 HALT、以及实际调用 OMS.submit 且被独立拒绝。保留并强化 spawn Barrier 50 轮双进程同步竞争。修复 JSONL、manifest、日志覆盖与报告自洽性。严格遵守测试 RED→GREEN、全量回归、1,080 fault matrix，优先只动测试/证据。完成后生成 M2 A7 独立验收报告并 STOP；无用户单独授权不得 push、关闭 M2 或启动 M3。
