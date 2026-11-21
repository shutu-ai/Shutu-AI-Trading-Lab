# M2 A6 严格跨进程同步与恢复证据补强记录（M2-A6-STRICT-PROCESS-BARRIER-AND-EVIDENCE-001）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `ca29f9f`（CI run `44891635260` 双矩阵 338 passed——旧测试范围） |
| 本地基线 | `ca29f9f`（clean，无未推送提交——`0ebae0d`/`29ecf54`/`a4f1413` 均已推送） |
| A6 新提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-21 |
| 生产代码变更 | **零** |
| approver | **USER_PENDING** |

## 提交-证据矩阵（A6-T0）

| SHA | 类型 | CI run | 说明 |
|---|---|---|---|
| `4a327b4` | 产品代码（fence.py read lock） | `44891635260` ✓ | CI 稳定化——**A5 首轮声称零产品变更，此后 4a327b4 有产品代码变更**（动机：跨线程 sqlite 安全；回归风险：读锁性能；独立验证：双平台 CI 绿） |
| `ca29f9f` | docs-only | 无独立 run | CI 补录（前一 run 的后记提交） |
| A6 新 SHA | 测试+证据 | PENDING | 本轮新增 |

## A6-T1 — 50 轮跨进程同步竞争（P0）→ **PASS**

- **方法**：multiprocessing spawn context + 共享 Barrier(2) + Queue IPC。父进程先 seed 意图，再向两个 worker 的 Queue 同时放入相同命令。Worker 收到命令后信号 READY、进入 Barrier、放行后调用 `claim_send_attempt`。父进程确认 `ready_count==2`、`distinct_pids=true` 后才由 Barrier 放行 GO。
- **结果**：50/50 轮——每轮 `attempted_count=2, claim_winner_count=1, errors=[]`, `SEND_CLAIMED=true`。
- **诚实标注**：证明跨进程 journal claim 仲裁（BEGIN IMMEDIATE 原子性），不证明跨进程 BrokerPort E2E。

## A6-T2 — crash/restart 与真实风险阻断（P0/P1）→ **PASS**

- **方法**：subprocess `os._exit()` 模拟 crash（非 `sys.exit(0)`），确证 `SEND_CLAIMED` 持久化；二次 claim 全拒；新 KillSwitch 对象持久 HALT 确认；重建 OMS → `recover()` → `still_unknown`；新增风险请求 → `HALT_NEW_RISK` 且 FakeBroker 0 创建。
- **5 轮全部通过**。

## A6-T3 — 证据自洽（P1）→ **PASS**

- 证据目录 `a6-strict-process-proof/`：`baseline.md`、`barrier_50_rounds.jsonl`、`crash_recovery_5_rounds.jsonl`、`full_checks.log`、`evidence-manifest.sha256`
- A5 缺失文件（`abrupt_crash_recovery_5.log`、`thread_retry_accounting.md`）如实标注为未留存，使用 A6 新证据替代
- `fence._read_lock` 跨线程回归：无退化（`ARCH_EXIT=0`）

## A6-T4 — 不可缩减验证矩阵 → **PASS**

- 全量：340 passed（338 基线 + 2 A6 新测试）；分项 140/71/19/14/26/22/48
- 1,080 fault matrix：重跑全绿
- 全门禁 EXIT=0

## 状态

**（2026-11-21 更新）`M2_A6_STRICT_PROCESS_PROOF_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
整改提交经用户明确授权推送（`ca29f9f..5c3c5cb`）后，远端 CI **双矩阵实际 PASS 于最终 SHA**：run `44900846467`——ubuntu ✓（54s）+ windows ✓（7m14s），URL `https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44900846467`；340 用例（含 50 轮 spawn 跨进程同步竞争、5 轮 abrupt crash recovery、1,080 故障矩阵）双平台实际执行。
