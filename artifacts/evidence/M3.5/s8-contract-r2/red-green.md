# T7 RED → GREEN 对照记录（red-green — LOCAL_ONLY，2026-11-22）

> 两个 P0 均为代码审查静态发现的可疑故障通路，先以精确 RED 用例复现旧行为，
> 再以最小修复转 GREEN。全部用例使用临时目录 + 合成 fixture 数据
> （`SIMULATED_REAL_SHAPE_TEST_ONLY`），不触碰真实采集状态与已提交证据集。

## P0-A：完成收据落盘失败仍产出成功形态快照

**旧路径（RED 复现，`red-run-full.log`）**：
`_complete_window()` 对 `append_receipts(WINDOW_COMPLETED)` 捕获异常后仅把
`window_completed_receipt` 置为 `"FAILED: …"`，随后**无条件**写入
`forward-window-evaluation.json` 与 evidence 副本；`cmd_collect --complete`
不检查该字段，恒 `return EXIT_OK`。

RED 断言（修复前全部失败）：

| 用例 | 旧行为实测 | 期望（新契约） |
|---|---|---|
| `test_receipt_write_failure_leaves_no_success_snapshot` | 注入 OSError 后快照仍被写入 | 无快照、无 evidence 副本、诊断保留 |
| `test_collect_complete_returns_nonzero_on_receipt_failure` | `collect --complete` 退出码 0 | 退出码 **7**（`RECEIPT_WRITE_FAILED`） |
| `test_receipt_failure_with_evidence_dir_writes_no_evidence_copy` | evidence 副本照写 | 不写 |
| `test_recompletion_with_unchanged_facts_is_idempotent` | 二次完成追加第 2 条收据 | 恰 1 条，幂等修复快照 |
| `test_recompletion_after_window_drift_is_refused` | 窗口漂移后仍二次完成 | `REFUSED_ALREADY_COMPLETED`，零变更 |
| `test_snapshot_write_failure_is_reported_and_recoverable` | 快照写入无隔离、抛未处理异常 | `SNAPSHOT_WRITE_FAILED`，可幂等修复 |

**修复（GREEN，`green-run.log`）**：`_complete_window` 改为终态、幂等、可恢复的
完成状态机——(1) 先 fail-closed 读取已提交 `WINDOW_COMPLETED` 记录（链损坏即
`REFUSED_CHAIN_CORRUPT`，零变更）；(2) 新完成：先提交收据，**仅当收据已持久化**
才原子写入快照（临时文件 + `os.replace`，双平台原子、强制 LF）；收据失败 →
`RECEIPT_WRITE_FAILED`（退出 7），**不写快照、不写 evidence 副本**；快照失败 →
`SNAPSHOT_WRITE_FAILED`（退出 7，收据已提交，重跑幂等修复）；(3) 已完成窗口：
facts 未漂移 → 仅修复快照（不追加收据）；漂移 → `REFUSED_ALREADY_COMPLETED`
（退出 6），不覆盖快照、不改 journal。

**附注（诚实披露）**：RED 阶段旧代码经 `cmd_collect(evidence_dir=EVIDENCE_DIR)`
测试路径向 `artifacts/evidence/M3.5/s8-contract-r1/` 写入过一个未跟踪的模拟
`real-forward-window-status.json`（15:41 本机时间）——这正是 P0-A 故障模式本身。
该文件为未跟踪本地文件，已删除恢复原状；GREEN 路径结构性地防止复发
（evidence 副本仅在完成全部提交后写入）。既有测试
`test_completion_persists_chain_bound_evaluation` 的防污染断言继续通过。

## P0-B：状态完整性失败不反映在 CLI 退出码

**旧路径（RED 复现）**：`cmd_status()` 计算 `digest_match` 后恒 `return EXIT_OK`；
且只比较 `facts_digest` 字符串相等，**不核对快照与已提交 WINDOW_COMPLETED
链记录的绑定关系**——"重算摘要相等但无对应已提交记录"会被当作正常。

RED 注入矩阵（6 类，独立临时状态；修复前全部 exit 0）：

| 注入 | 期望问题码 | 期望退出码 |
|---|---|---|
| 快照 `facts_digest` 篡改 | `DIGEST_MISMATCH` | **6** |
| 快照 `protocol_hash` 不匹配 | `PROTOCOL_MISMATCH` | **6** |
| 快照存在但无合法完成链记录（P0-A 残留形态） | `UNBOUND_SNAPSHOT` | **6** |
| 链记录存在但快照缺失（崩溃窗口） | `CHAIN_COMMITTED_SNAPSHOT_MISSING` | **7** |
| 重复完成：digest 冲突 / 完全重复 | `CONFLICTING_COMPLETIONS` / `DUPLICATE_COMPLETION` | **6** |
| receipt/journal 损坏 | `RECEIPT_CHAIN_CORRUPT` / `JOURNAL_CORRUPT` | **6** |

**修复（GREEN）**：`cmd_status` 复用 `_verify_completion_evidence()`
（共享实现，`status` 与完成路径同源）：digest + 协议哈希 + **链绑定**
（快照须绑定到一条 `facts_digest`/`protocol_hash`/`eligibility` 全部一致的
已提交记录）+ 重复/冲突 + 三链完整性（journal/receipt/snapshot 可解析），
输出 `completion_state ∈ {NOT_STARTED, NOT_COMPLETED, COMPLETE_VERIFIED,
CHAIN_COMMITTED_SNAPSHOT_MISSING, INTEGRITY_FAILURE}` + `completion_problems[]`，
按状态返回 **0 / 6 / 7**（可区分、稳定、文档化于 runner docstring）。
可用性与完整性分开陈述：`exit 0` 只表示"命令完成且无完整性异常"，
**永远不等于资格 PASS**（资格只看 JSON 字段）；未开始/进行中的合法查询行为
保持 exit 0（两个守卫用例修复前后语义一致）。

## 跨进程崩溃恢复（`os._exit`，全新进程读取）

| 故障点 | 注入 | 全新进程观察（GREEN） |
|---|---|---|
| 收据写入前 | 子进程 patch `append_receipts` → `os._exit(9)` | 无收据无快照；status exit 0 `NOT_COMPLETED`；修复运行后恰 1 条收据 |
| 收据写入后/快照前 | 子进程 patch `AuditLog.append` 于 WINDOW_COMPLETED 提交后 `os._exit(9)` | 收据已提交、无快照；status exit **7** `CHAIN_COMMITTED_SNAPSHOT_MISSING`；修复运行不产生第 2 条收据 |
| 快照写入时 | 快照路径被目录占位（双平台可复现写失败） | `SNAPSHOT_WRITE_FAILED`；解除后修复运行恢复快照、仍 1 条收据 |
| 快照写入后 | 正常完成 | status exit 0 `COMPLETE_VERIFIED` |

无任何故障点产生假 COMPLETE 或二次完成收据。原始 pytest 输出：
`red-run-full.log`（18 failed）/ `green-run.log`（18 passed）；
全量回归见 `full-regression.log`。
