# M2 A5 True Process Race — T0 基线（2026-11-21）

- 远端审查基线：`1c6d7b7`（run `44885002933` 双矩阵 336 passed——旧测试范围）
- 本地 HEAD：`0ebae0d`（领先 1 提交；**已核实 docs-only**：仅 A2 整改报告状态 2 行 CI 补录；保留未覆盖）
- 工作树：clean（仅本任务书未跟踪，随整改提交留档）
- 回归分母：336 用例（contract+security 140 / no_lookahead 71 / risk 19 / oms 14 / architecture 26 / fault_injection 12+2 send_claim / m2_remediation 48+2 residual）；故障矩阵 1,080 独立实例

## 审查确认的缺陷（A5-T0）

上一轮 `test_process_50_rounds_long_lived_workers` 中：

```python
res_a = worker_a.race(...)   # 写 stdin → 等待 stdout 结果
res_b = worker_b.race(...)   # A 完成后才发 stdin → B
```

这是**顺序重放**而非并发竞争——worker A 已完整执行并 commit claim 后 worker B 才开始。50 轮 `[True, False]` 只证明"后到者被拒"，不证明"两者同时到达时恰一人成功"。

## 修复计划

核心改动在 Worker 类：拆分 `send()` 与 `read()` 方法，使父进程可**先向两个 worker 的 stdin 同时写命令**，再分别读 stdout。两个 worker 因阻塞在 `stdin.readline()` 上，同时收到命令后各自调用 `claim_send_attempt()`——BEGIN IMMEDIATE 在 SQLite 层仲裁恰好一个 UPDATE 成功。竞争是真实的（两条独立 OS 进程 + 两条独立 SQLite 连接同时进入），且诊断不依赖 sleep。

## 诚实边界

- 本测试证明**跨进程 journal claim 仲裁**（SQLite BEGIN IMMEDIATE 原子性），不证明跨进程 BrokerPort E2E（worker 仅调用 journal，不调用 port——per A5-T1 item 5）。
- 崩溃测试使用 `proc.terminate()`（Windows SIGTERM 等价），不是 `sys.exit(0)`。
