# M2 A7 基线（M2-A7-CLAIM-OWNER-CRASH-AND-RECOVERY-PROOF-001）

- 远端审查基线：`5c3c5cb`（run `44900846467` 双矩阵 338 passed——旧测试范围）
- 本地 HEAD：`8a5f9c5`（领先 1 提交；**已核实 docs-only**：仅 A6 报告状态 2 行更新；保留未覆盖）
- 回归分母：338 用例；故障矩阵 1,080 独立实例
- A5 原报告"零产品代码变更"：**需修正**——后续 `4a327b4` 修改了 `fence.py`（read lock），属产品代码变更

## A6 审查确认的四项证明缺口

| 缺口 | 源码位置 | 原始行为 |
|---|---|---|
| 1. 错误的 crash 主体 | `test_a6_strict_process_proof.py` 先由父进程 claim，再由子进程尝试已消费的 claim | 子进程 `os._exit(1)` 证明的是"失败的第二 claimer 退出"，非"成功 claimer 崩溃后恢复" |
| 2. 恢复前预置 HALT | `test_a6_strict_process_proof.py` 在 `recover()` 之前 `ks1.set(...)` 再用新 KillSwitch 检查 | 未隔离证明 `recover()` 自动触发 HALT |
| 3. OMS 下游阻断可跳过 | `if new_decision.allow: oms2.submit(...)` | HALT 下 RiskEngine 直接拒绝则 `oms2.submit` 未被调用 |
| 4. 证据/断言不符 | `barrier_50_rounds.jsonl` 纯文本非 JSONL；无 `baseline.md`；manifest 空文件哈希 | 需修复证据格式 |

## 预声明验收门槛

| 门 | 要求 |
|---|---|
| CLAIM_HOLDER_CRASH | ≥5 轮真实 OS 子进程 claim 后 `os._exit(37)`；SEND_CLAIMED 持久；二次 claim 拒绝 |
| RECOVERY_HALT_ASSERTION | 无预置 HALT → `recover()` 自动触发全局 HALT；新 KillSwitch 对象确认持久 |
| OMS_DENY_PREAPPROVED | HALT 前生成的有效密封决策 + HALT 后 `oms.submit()` → `HALT_NEW_RISK` + 0 port |
| RISK_DENY_AFTER_HALT | HALT 后 RiskEngine 拒绝新意图 |
| 0 新增风险 | 0 port entries / 0 盲重发 / 0 替代 COID |
