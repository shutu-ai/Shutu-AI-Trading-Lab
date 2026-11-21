# M2 A7 定向证明纠偏记录（M2-A7-CLAIM-OWNER-CRASH-AND-RECOVERY-PROOF-001）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `5c3c5cb`（run `44900846467` 双矩阵 338 passed——旧测试范围） |
| 本地基线 | `8a5f9c5`（领先 1 提交；**已核实 docs-only**：仅 A6 报告 CI 状态 2 行更新；保留未覆盖） |
| 整改提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-21 |
| 生产代码变更 | **零**（仅新增测试与证据） |
| approver | **USER_PENDING** |

## A6 审查四项证明缺口的 A7 修正

| 缺口 | A7 修正 | 验证 |
|---|---|---|
| 错误的 crash 主体（父进程 claim，子进程消费后退出） | 子进程独立 claim + `os._exit(37)` 异常终止 | 5/5 轮 exit code 37 |
| 恢复前预置 HALT | FRESH KillSwitch 对象（pre-recovery `is_halted()==False`）→ `recover()` 自动触发 HALT → 持久确认 | 5/5 轮 automatic HALT |
| OMS 下游阻断可跳过 | 无条件调用 `oms.submit()` → `HALT_NEW_RISK` + 0 port entries | 5/5 轮 blocked |

## 状态

**`M2_A7_TARGETED_PROOF_LOCAL_PASS / CI_REMOTE_PENDING / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**
approver = USER_PENDING；不关闭 M2、不启动 M3。
