# M2 A6 独立验收复核（2026-11-21）

- 仓库：`shutu-ai/Shutu-AI-Trading-Lab`
- 检验 SHA：`5c3c5cbd3980a02637de1511f6e908dcc2b922db`
- GitHub Actions：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44900846467
- CI：Ubuntu 和 Windows 均 SUCCESS，同一实际 SHA。
- 本地 docs-only 补录 `8a5f9c5`：用户报告存在，远端查询未找到，不能算远端已验证。

## 结论

`M2_A6_CI_VERIFIED / A7_TARGETED_EVIDENCE_REMEDIATION_REQUIRED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`

工程既有 mock-only 结果不因本次发现自动作废，但严格 claim-holder crash、recover 触发 HALT 和 OMS 下游独立拒绝仍未得到充分直接证据。**不能据此断言生产 OMS 存在双发漏洞**；也不宜在证据未齐时关闭 M2。

## 已核实的正面证据

- A6 采用 `multiprocessing.get_context('spawn')` 与两进程共享 `Barrier(2)`；此机制需要两个参与者都到达才可继续，因此不是 A5 的顺序重放。
- 50 轮测试的 `winner_count=1` 被断言；GitHub CI 两平台通过，报告载明共 340 tests。
- A6 `full_checks.log` 载有本地 340 passed、架构、密钥、Live 隔离与 smoke_mock EXIT=0；该本地记录并非双平台每轮原始日志。

## 需整改发现

| 严重性 | 发现 | 直接依据 | 缺口 |
|---|---|---|---|
| P0 | 成功 claim 在父进程完成，失败的第二 claimer 执行 `os._exit(1)` | `tests/fault_injection/test_a6_strict_process_proof.py` | 不能称为成功 claimer crash 后恢复 |
| P0 | 测试在 `recover()` 之前手动 `ks1.set()` | 同上 | 不能证明恢复主动触发 HALT |
| P0 | `if new_decision.allow: oms2.submit(...)` | 同上 | RiskEngine 拒绝时下游 OMS 不执行仍能 PASS |
| P1 | race 测试只硬断言恰一 winner，缺逐轮 error/round/PID/DB final state 校验 | 同上 | 报告的多个字段没有逐轮硬验证 |
| P1 | `barrier_50_rounds.jsonl` 是文本而非 JSONL | A6 远端证据文件 | 机器可解析性不足 |
| P1 | manifest 自身条目用空文件 SHA256；报告提及 baseline.md 但远端目录缺失 | A6 远端证据目录 | 清单与文档不一致 |
| P1 | A6 提交修改 A2/A5 历史日志 | GitHub 5c3c5cb commit files | 应停止测试运行覆盖历史证据 |

## 边界和建议

不执行更多大范围产品安全重构；安排 M2 A7 定向修补测试和证据，保留现有已验证事实。通过后重新提请用户独立决定 `M2_GATE=CLOSED`，然后再单独决定 `M3_START=APPROVED`。全市场数据仍 BLOCKED_DATA、真实 Broker 行为仍 UNVERIFIED，不允许 Paper/Live 凭证或实盘操作。
