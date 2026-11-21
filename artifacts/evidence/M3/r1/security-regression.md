# M3-R1 T1 — P0：M2 A7 安全回归恢复记录（STOP/GO 门）

- 任务: R1-T1（第一 STOP/GO 门）
- 日期: 2026-11-21
- 基线退化: `3505799` 相对 `f27892d` 删除 A7-T1 五轮 claim-holder crash proof（见
  `baseline.md` §2，CI 347→343 与删除的 4 项参数化实例精确吻合）

## 1. RED（退化证据，恢复前采集）

- `t1-red-collection.txt`：在 HEAD=3505799 上
  `pytest tests/fault_injection/test_a7_targeted_proof.py --collect-only` 仅收集 **3** 项
  （`TestClaimCasOneShot` 1 + `TestA7T2DualLayerBlock` 2），
  **无任何 `TestA7T1ClaimHolderCrash` 参数化实例**。
- 删除断言清单 A1–A8 见 `baseline.md` §2.2。

## 2. 恢复内容（merge，非回滚文件整体替换）

| 项 | 处置 |
|---|---|
| `TestA7T1ClaimHolderCrash`（5 轮，`@pytest.mark.parametrize("round_no", range(1, 6))`） | **从 f27892d 逐字恢复**（A1–A8 全部断言），并按任务书强化：删除旧版 `if new_decision.allow:` 逃逸分支；恢复后双层阻断改为**无条件**断言 |
| 强化点 1（Layer 1） | recover() 自动 HALT 后，RiskEngine.evaluate() 必须 `not allow` 且 `KILL_SWITCH_ENGAGED` ∈ reason_codes（无条件，不再依赖 allow 才提交） |
| 强化点 2（Layer 2） | HALT **之前**合法密封的 pre-approved decision（Phase 1 中 evaluate 得 allow=True 并断言），HALT 后提交 `oms.submit()` → **无条件** `HALT_NEW_RISK` + FakeBroker created_orders==0 |
| `TestClaimCasOneShot`（3505799 新增） | **保留**（进程内 CAS 一次性领取有独立价值），不替代五轮 crash proof |
| `TestA7T2DualLayerBlock`（2 项） | 逐字保留 |
| 父进程/子进程职责 | 保持原设计：子进程自己原子领取 claim 并 `os._exit(37)`；父进程只做编排、fact 文件校验、全新栈 recover() |
| 风险面 | 零新增端口/零生产代码变更（仅测试文件）；不盲重发、不替代意图 |

## 3. GREEN（恢复证据，本地实测）

- `t1-green-run.txt`：`pytest tests/fault_injection/test_a7_targeted_proof.py -v`
  → **8 passed in 3.08s**（win32, Python 3.13.15, pytest 9.2.0）
- `t1-green-ids.txt`（`-vv` 逐 ID）：
  - `TestA7T1ClaimHolderCrash::test_claim_holder_crash_auto_halt[1..5]` **5/5 PASSED**
    （每轮：真实子进程 exit 37 → SEND_CLAIMED 全新连接可见 → recover() →
    still_unknown → 自动 HALT → RiskEngine 拒绝 → pre-approved 提交 HALT_NEW_RISK →
    broker 0 单）
  - `TestClaimCasOneShot::test_second_claim_returns_none` PASSED
  - `TestA7T2DualLayerBlock::{test_risk_deny_after_halt,test_oms_deny_preapproved_after_halt}` PASSED
- `t1-fault-inj-regression.txt`：`pytest tests/fault_injection` 全目录
  **30 passed**（恢复前 25；含 1,080 实例故障矩阵切片），EXIT=0
- 收集总量：**348**（343 − 3 + 8 = 348 ≥ 旧 347；新增 1 项为 3505799 引入的 CAS 测试）

## 4. 测试身份完整性（对照旧 347 验收意图）

- 旧 A7 的 7 项 collection ID：5 项 crash 恢复、2 项 T2 保留；断言无删除或弱化
  （T1 新增 2 条无条件断言为净强化）。
- 其余 344 项既有测试（contracts/security/no_lookahead/oms/risk/m2_remediation/
  fault_matrix 等）本轮未改动；全量回归在 T7 记录。
- 1,080 故障矩阵：未触碰（9 类切片计数不变），本轮 fault_injection 目录回归中随跑通过；
  T7 仍按任务书单独执行并记录。

## 5. 裁决

**R1-T1 STOP/GO 门：GO。** M2 A7 不可退化安全回归已恢复并取得本地真实 GREEN 证据；
测试总数 348 ≥ 347。允许继续 T2–T7。远端 CI 复验（REMOTE_VERIFIED）需用户另行授权 push。
