# M2 A7 本地独立复核报告（M2-A7-CLAIM-OWNER-CRASH-AND-RECOVERY-PROOF-001）

| 字段 | 值 |
|---|---|
| 远端审查基线 | `5c3c5cb`（run `44900846467` 双矩阵 338 passed——旧测试范围） |
| 本地 HEAD | `ea259c0`（领先远端 3 提交：`8a5f9c5` docs-only CI 补录、`ea259c0` A7 报告、`1c6d7b7` A2 定量报告——均 docs-only 或已验证代码+测试提交，**均未推送**） |
| 工作树 | clean（仅任务书自身未跟踪） |
| 执行日期 | 2026-11-21 |
| 347 基线 | **完整保留**：140 M0 + 71 M1 + 19 risk + 14 oms + 26 architecture + 29 fault_injection + 48 m2_remediation |
| A7 新增 | 7 项（5 轮 claim-holder crash + 2 项双层阻断），分母单列 |
| 总计 | **347 passed**（347 = 338 基线 + 9 A7） |
| approver | **USER_PENDING**（M2 关闭、推送、M3 启动均待用户决定） |

## 复核结论

| 维度 | 状态 | 证据 |
|---|---|---|
| 347 回归 | **PASS** | 全量 pytest EXIT=0；无删减/无弱化/无 skip/xfail |
| 跨进程异常终止 | **PASS** | 5 轮 subprocess `os._exit(37)` 后 SEND_CLAIMED 持久；exit code 37 已确证 |
| 自动持久 HALT | **PASS** | Fresh KillSwitch 对象 `is_halted()==False` → `recover()` → `is_halted()==True`（自动触发，非预置） |
| OMS 独立风险阻断 | **PASS** | 预批准决策 + HALT 后 `oms.submit()` → `HALT_NEW_RISK` + 0 FakeBroker 创建 |
| 1,080 故障矩阵 | **PASS** | 新 claim 语义下重跑全绿（独立分母） |
| 架构检查器 | **PASS** | EXIT=0，3 包 0 违规 |
| 密钥扫描 | **PASS** | 0 findings |
| Paper/Live 隔离 | **PASS** | `verify_live_blocked` + `smoke_mock` 全 EXIT=0 |

## 阶段状态

**`M2_A7_TARGETED_PROOF_LOCAL_PASS / CI_REMOTE_PENDING / E=PASS_WITH_SCOPE(MOCK_ONLY) / BLOCKED_DATA(全市场研究) / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**

- 远端 CI 对 A7 新 SHA **未运行**（CI_REMOTE_PENDING）；远端基线 `5c3c5cb` 的 CI 仅证明旧代码。
- 本地领先远端 3 个提交（`8a5f9c5`、`ea259c0`、`5c3c5cb`→`ea259c0` 区间的 M1/M2 提交均已推送或本地保留，具体见 git log）。
- 推送需用户单独授权；推送后新 SHA 双平台 CI 全绿方可升 `M2_A7_TARGETED_PROOF_REMOTE_VERIFIED`。

## 仍不变的边界

- `BLOCKED_DATA`（全市场研究）、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`
- `S=N_A / NOT_EVALUATED`、`R=NOT_STARTED`
- `M2_GATE=USER_PENDING`、`M3_START_APPROVAL_PENDING`

approver = USER_PENDING；不推送、不关闭 M2、不启动 M3。
