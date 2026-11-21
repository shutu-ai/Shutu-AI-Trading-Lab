# M2 A5 真正跨进程竞争补证记录（M2-A5-TRUE-PROCESS-RACE-AND-M3-GATED-001）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `1c6d7b7`（run `44885002933` 双矩阵 336 passed——旧测试范围） |
| 本地基线 | `0ebae0d`（领先 1 提交；**已核实 docs-only**：仅 A2 报告 CI 状态 2 行更新；保留未覆盖） |
| 整改提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-21 |
| 方法 | A5-T0 盘点 → A5-T1/T2 新测试（先确认上一轮缺陷真实存在）→ A5-T3 线程质量 → A5-T4 全量回归 |
| 生产代码变更 | **零**（仅新增测试与证据——现有 claim_send_attempt 原子事务在 50 轮跨进程同步竞争下未暴露任何双发） |
| approver | **USER_PENDING** |

## A5-T0 — 上一轮缺陷确认

| 上轮 A2 声称 | A5 审查结论 |
|---|---|
| 50 轮跨进程竞争 | **不成立**——顺序重放（A 先完成再发 B），非同步竞争 |
| 5 轮 crash = `sys.exit(0)` | 非异常终止；且缺少显式 `recover()` 调用与持久 HALT 断言 |
| Windows 3% 瞬态 vs Ubuntu 0% | 日志差异为不同运行环境，如实区分（A5-T3 处理） |

## A5-T1 — 双进程同步竞争 ≥50 轮 → **PASS**

- **核心修正**：Worker 类拆分 `send_claim()`（写 stdin 不等结果）与 `read_result()`（阻塞读 stdout），父进程**先向两个 worker 的 stdin 同时写 claim 命令**，再分别读结果——两个 worker 因阻塞在 `stdin.readline()` 上，同时收到命令后各自调用 `claim_send_attempt()`。
- **50 个独立 COID**，每轮 setup 先持久化 SUBMITTING 意图 + 尝试（两名真实 OS 进程有资格对同一 COID 争夺 claim）。
- **每轮验证**：`two_distinct_pids=true`（workerA pid≠workerB pid）、`claimed` 合计恰为 1、0 errors、50/50 通过。
- **诚实标注**：证明跨进程 journal claim 仲裁（BEGIN IMMEDIATE 原子性），不证明跨进程 BrokerPort E2E（worker 仅调 journal，不调 port）。

## A5-T2 — 异常终止及持久恢复 ≥5 轮 → **PASS**

- **异常终止**：claimer 子进程 `proc.terminate()`（非 `sys.exit(0)`）。
- **持久验证**：SEND_CLAIMED 状态在 DB 中持久存在；二次 claim 拒绝（None）。
- **恢复**：重建 OMS/Journal/Fence/KillSwitch → 显式调用 `recover()` → `still_unknown` 包含该意图、KillSwitch 全局 HALT 持久存在；操作人未解锁前新增风险发送为 0。5 轮全部通过。

## A5-T3 — 线程测试质量（100 轮保留）→ **PASS**

- 原 100 轮 Barrier 双线程测试原样保留并通过（每轮恰 1 port entry）。
- 重试计数如实记录（本轮 0 retries——隔离运行确定性同步稳定；全量套件负载下曾观察到 3% Windows 瞬态，已由轮级重试覆盖）。
- 本地 Windows 与远端 CI Ubuntu/Windows 日志独立保存，不混淆。

## 验证与证据

| 项 | 结果 |
|---|---|
| 全量回归 | 338 passed（336 基线 + 2 A5 新测试）；分项 140/71/19/14/26/20/48 |
| 1,080 故障矩阵 | 重跑全绿 |
| 架构检查器 | EXIT=0（3 包 0 违规） |
| 生产代码变更 | **零** |
| CI | **CI_REMOTE_PENDING**（无推送授权） |

## 状态

**（2026-11-21 更新）`M2_A5_TRUE_PROCESS_RACE_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(MOCK_ONLY) / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
整改提交经用户明确授权推送（`1c6d7b7..4a327b4`）后，远端 CI **双矩阵实际 PASS 于最终 SHA**：run `44891635260`——ubuntu ✓（50s）+ windows ✓（10m24s），URL `https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44891635260`；338 用例（含 50 轮跨进程同步竞争、5 轮 abrupt crash recovery、1,080 故障矩阵）双平台实际执行。
