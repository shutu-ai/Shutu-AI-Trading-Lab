# M3-R1 T0 — 源码/证据基线审计

- 任务: `M3-R1-RESTORE-M2-PROOF-AND-COMPLETE-SYNTHETIC-RESEARCH-20261121-001`
- 审计时间: 2026-11-21 (UTC)
- 审计人: Claude Code（本地独立复核，含远端 CI 一手日志取证）

## 1. SHA 与 CI 事实（一手证据）

| 项 | 值 | 证据来源 |
|---|---|---|
| 本地 HEAD = origin/main | `3505799f844c0a8cfa410df269b6afdd907f38f0` | `git rev-parse HEAD` / `git rev-parse origin/main`（fetch 后一致） |
| 远端 CI run（当前 HEAD） | `44929797426`，双 job success | `gh run view 44929797426` |
| Ubuntu job 原始日志 | **`343 passed in 30.09s`** | job 136923694611 日志（gh run view --job --log） |
| Windows job 原始日志 | **`343 passed in 377.65s (0:06:17)`** | job 136923694422 日志（gh run view --job --log） |
| 提交信息声称 | "347 tests PASS" | commit 3505799 message —— **与实际 343 不符** |
| 旧工程基线 `f27892d` CI | run `44925761010`，Windows job 日志 `347 passed in 341.29s` | gh run view --job=136911368311 --log |
| 提交链 | `f27892d → 5c020b0 → 3505799` | `git log --oneline` |

**结论（已验证）**：3505799 的真实测试数是 343，比 f27892d 净少 4；净差全部来自
`tests/fault_injection/test_a7_targeted_proof.py`（151 删 / 54 增）。CI 双绿不代表 M3 完成，
也不代表 A7 证明仍然存在。

工作树状态：本轮开始时仅两份未跟踪新文档（M3 独立审查 + 本任务书），无未提交代码改动。

## 2. A7 测试退化明细（`git diff f27892d..3505799 -- tests/fault_injection/test_a7_targeted_proof.py`）

### 2.1 Collection ID 变化

| 旧（f27892d，共 7 项） | 新（3505799，共 3 项） | 状态 |
|---|---|---|
| `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[1]` | （不存在） | **删除** |
| `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[2]` | （不存在） | **删除** |
| `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[3]` | （不存在） | **删除** |
| `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[4]` | （不存在） | （不存在） **删除** |
| `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[5]` | （不存在） | **删除** |
| `TestA7T2DualLayerBlock::test_risk_deny_after_halt` | 同名保留 | 保留 |
| `TestA7T2DualLayerBlock::test_oms_deny_preapproved_after_halt` | 同名保留（docstring 被删） | 保留（弱化注释） |
| （不存在） | `TestClaimCasOneShot::test_second_claim_returns_none` | 新增（弱验证） |

净变化 7 → 3（**-4**），与 CI 347 → 343 精确吻合。

### 2.2 被删除断言逐项清单（A7-T1 五轮 crash proof）

| # | 断言 | 状态 |
|---|---|---|
| A1 | 独立子进程以自身 PID 原子领取 claim（`claim_send_attempt` 返回非 None） | **删除** |
| A2 | 子进程持久提交后 `os._exit(37)`，父进程验证 exit code == 37 | **删除** |
| A3 | 崩溃后从**全新** Journal 连接读取 `attempt_state_for_coid == "SEND_CLAIMED"`（持久性） | **删除** |
| A4 | 全新 KillSwitch 在 recover() 之前**未** HALT（排除预设 HALT 冒充自动恢复） | **删除** |
| A5 | `oms.recover()` 报告 `still_unknown` 包含崩溃 intent | **删除** |
| A6 | recover() **自动**触发全局 HALT（`ks.is_halted()` 事后为真） | **删除** |
| A7 | 恢复后新风险经真实 OMS `submit()` 路径被拒（`HALT_NEW_RISK`） | **删除** |
| A8 | 被拒提交在 FakeBroker 的 created_orders == 0（零端口副作用） | **删除** |

保留项：CAS 一次性领取（新增，进程内、无崩溃/恢复语义——独立价值但**不能替代** A1–A8）；
A7-T2 双层阻断 2 项（完整保留）。

**裁决**：这是测试覆盖退化，不是已证明的生产代码缺陷；但 M2 验收证据链已断，
必须恢复（R1-T1，第一 STOP/GO 门）。

## 3. 3505799 提交完整变更面

| 文件 | 变更 | 性质 |
|---|---|---|
| `tests/fault_injection/test_a7_targeted_proof.py` | -151/+54 | A7 crash proof 删除（§2） |
| `artifacts/evidence/M2/a5-true-process-race/process_concurrent_50.log` | 重生成 | 历史日志覆盖（gate record 审计披露已知） |
| `artifacts/evidence/M2/a5-true-process-race/barrier_50_rounds.jsonl` | 重生成 | 同上 |
| `artifacts/evidence/M2/a2-quantitative-close/process_50_rounds.log` | 重生成 | 同上 |
| `configs/evaluation_protocol.yaml` | +92 | M3 协议声明（仅配置，无 hash/冻结执行，见 §4） |
| `src/trading_lab/backtest/__init__.py` + `engine.py` | +43 | M3 回测桩（42 行，无校验，见 §4） |
| `src/trading_lab/validation/__init__.py` | +1 | 空壳 |
| `src/trading_lab/oms/engine.py` 等生产代码 | 无变更 | 生产安全代码未被改动（退化仅在测试层） |

1,080 故障矩阵（`tests/fault_injection/test_fault_matrix.py`，9 类 × 切片 = 1,080 实例）：
**未被动过**，完整保留。Paper/Live 隔离相关测试（`tests/security/` 等）未被改动。

## 4. M3 现有文件与缺口清单

| 要求工件（任务书 T7 清单） | 当前状态 | 缺口 |
|---|---|---|
| `docs/adr/ADR-004-evaluation.md` | 不存在 | 新建 |
| `src/trading_lab/backtest/` | 仅 `Bar`+`BacktestAccount` 42 行桩 | 重写（R1-T3） |
| `src/trading_lab/validation/` | 仅 `__init__.py` | 新建 protocol/cohorts/holdout/ledger（R1-T2/T5） |
| `configs/evaluation_protocol.yaml` | 存在但不可执行 | 无 protocol_hash/冻结状态机；`max_drawdown_pct: 100` 无约束；`equal_*_budget: true` 两个布尔冒充公平；无 M9 选择规则（R1-T2 修复） |
| `tests/backtest/` | 目录不存在 | 新建（R1-T3/T4） |
| `tests/validation/` | 目录不存在 | 新建（R1-T5） |
| `artifacts/evidence/M3/r1/*` | 不存在 | 本轮新建 |
| `docs/reviews/M3-{engineering,strategy,real-capital}.md` | 不存在 | T7 新建 |
| `scripts/check_architecture.py` | 仅扫 3 包（data/risk/oms，18 文件） | 扩到 5 包 + 负例（R1-T6） |

## 5. M3 依赖图（计划）

```
tests/validation ──────────► trading_lab.validation ──┐
tests/backtest ────────────► trading_lab.backtest ────┤──► trading_lab.contracts (MarketBar 复用)
                                                      └──► trading_lab.security (canonical 唯一规范化)
trading_lab.validation ──(允许)──► trading_lab.security   （protocol hash / 审计 digest）
trading_lab.backtest / validation ──(禁止)──► oms / risk / brokers / data / poc / artifacts
trading_lab.data ──(禁止)──► backtest / validation （既有方向规则扩展，R1-T6）
```

复用裁决：`Bar`（backtest 桩）与 `contracts.MarketBar` 重复 → **REPLACE**（回测直接消费
MarketBar，不保留第二套 bar 类型）；canonical 化**只**用 `security.canonical`，不建第二套。

## 6. REUSE / MODIFY / ADD / REPLACE / REMOVE / POC-ISOLATE / DEPENDENCIES

| 类别 | 项 | 唯一使用者 |
|---|---|---|
| REUSE | `contracts.MarketBar`（bar 语义）、`security.canonical.canonical_digest`（协议/数据 hash）、`helpers_m2` stack fixture、故障矩阵 1,080 实例、既有 Paper/Live 隔离测试 | 回测/验证测试、协议冻结 |
| MODIFY | `scripts/check_architecture.py`（3 包 → 5 包平面规则）、`configs/evaluation_protocol.yaml`（补治理能力）、`tests/fault_injection/test_a7_targeted_proof.py`（恢复 T1，保留新 CAS 测试） | 架构检查器、协议加载器、A7 回归 |
| ADD | `src/trading_lab/validation/protocol.py`（协议注册+hash）、`validation/cohorts.py`（WF/Purge/Embargo/重叠）、`validation/holdout.py`（封存/解封/污染）、`validation/ledger.py`（全试验账本）、`backtest/engine.py` 重写（事件驱动执行内核）、`backtest/arms.py`（B0/B1/B2）、`tests/backtest/*`、`tests/validation/*`、`docs/adr/ADR-004-evaluation.md`、三轨报告、R1 证据 | 见 §5 依赖图 |
| REPLACE | backtest 桩 `Bar` 数据类 → `contracts.MarketBar` 消费 | 回测内核 |
| REMOVE | 无（不删任何既有安全断言；A7 恢复为净增加） | — |
| POC-ISOLATE | 无新 POC；`artifacts/poc/` 继续不进生产依赖 | — |
| DEPENDENCIES | **零新第三方依赖**（stdlib + 既有 pydantic/pytest） | — |

## 7. 证据完整性规则

- 旧 A2/A5/A6/A7 证据路径（`artifacts/evidence/M2/**`）本轮**零覆盖**；全部新证据写入
  `artifacts/evidence/M3/r1/`。
- 旧 M2 审计结论（`M2_GATE=CLOSED`，基于 379bd72/f27892d 的 347）与新分支（3505799，343）
  的回归证据分开记账：M2 关闭记录保持原样不改写；本轮恢复回归后另行记录。
- 本文档记录的 CI 数字全部来自 `gh run view --log` 原始日志（见 §1 来源列），非提交信息转述。
