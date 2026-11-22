# T8 独立验收审阅（review — LOCAL_ONLY，2026-11-22）

## 判定

**`T8_AUDIT_VERDICT = LOCAL_PASS_WITH_SCOPE`**（`TERMINAL_FENCE=PASS`、
`OFFLINE_REPAIR=PASS`）

范围：本地离线整改（终态围栏 + 纯离线 repair-completion + 16 契约测试 +
CI 回填归档 + 本地提交）。本轮代码未经远端 CI 验证
（`T8_CI=REMOTE_PENDING`）；不证明真实市场、供应商行为或主机出口隔离。

## 已验证（本轮实测）

1. P1-A 终态围栏：封存窗口上 `collect --once`/`--complete` 在任何凭证读取/
   网络客户端/feed 访问/链写入之前拒绝（exit 8，零磁盘写入，哨兵 + socket
   密封证明）；链损坏 → exit 6；合法路径双向 guard 不变；cycle 前二次复核。
2. P1-B 离线修复：`repair-completion` 9 项拒绝/成功矩阵全绿
   （`fault-injection.log` §D）；成功修复零收据/journal 变更、原子写入、
   三重资格匹配；写失败 → exit 7 无假 COMPLETE。
3. RED→GREEN：14 failed / 2 passed → 16 passed（`red-run-full.log` / 套件）。
4. 全量回归 **960 passed**，exit 0（944 既有零删减 + 16 新增，240.11s，
   本地 Windows Python 3.13.15）。
5. 工具链 exit 0：check_environment / check_architecture / scan_secrets /
   verify_live_blocked / audit_t6_m2_provenance / smoke_mock；
   `git diff --check` 干净。
6. CI 回填：run 45031453603 经官方日志新鲜再核验（`remote-ci-backfill.md`）；
   `r2/review.md` 追加式补记；未跟踪 gh-watch 工作文件经只读迁移后移除，
   未入库任何敏感环境信息。

## 未验证 / 残余风险

1. **TOCTOU 跨进程窗口未从机制上消除**：围栏读取与 cycle 之间无单一跨进程
   锁（`SessionLock` 只租约保护 journal 会话，不覆盖收据追加与围栏本身）。
   缓解：入口 + cycle 前双重只读复核把竞态窗口缩到单 cycle 内部；单操作者
   主机"一次一个 CLI"操作纪律下实际风险极低。**如实记录，不声称检查一次
   即跨进程原子。**若未来出现并发采集的真实需求，需在此处补最小锁/租约复用。
2. **内部 API 面未硬围栏**：`run_collection_cycle()` 保持无守卫（测试/引擎
   内部面；T7 漂移拒绝测试依赖其构造拒绝状态）。唯一用户入口（CLI）已围栏；
   若未来新增第二采集入口，必须复用 `_terminal_gate()`。已记录为边界而非缺陷。
3. **T8_CI=REMOTE_PENDING**：新增 16 测试与围栏改动仅本地 Windows 验证；
   Linux 矩阵（`os.replace`/路径/换行语义）待未来授权推送后的双平台 CI。
4. **对外契约变化**：`repair-completion` 子命令与 exit 8 为新语义；把
   "collect 对任何状态都会尝试采集"当作前提的自动化必须更新。
   已文档化（runner docstring、`operator-readiness.md` §D 修订）。
5. **RED 期间事故（已披露）**：未修复代码经测试路径向 r1 写入过一个未跟踪
   模拟 evidence 文件，已删除恢复原状；GREEN 围栏结构性防复发（三轮套件 +
   二分定位验证零再污染）。详见 `red-green.md` 附注。

## 状态出口（逐字）

```text
T8_AUDIT_VERDICT=LOCAL_PASS_WITH_SCOPE
T7_CI=REMOTE_VERIFIED (run 45031453603, head 0b1f3b7900b9fe385bf4579e8126f1641f15d5ca)
T8_CI=REMOTE_PENDING
BASELINE_HEAD=0b1f3b7900b9fe385bf4579e8126f1641f15d5ca
REMOTE_HEAD=0b1f3b7900b9fe385bf4579e8126f1641f15d5ca
LOCAL_HEAD=<见提交记录>
TERMINAL_FENCE=PASS
OFFLINE_REPAIR=PASS
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
HOST_EGRESS_ISOLATION_UNVERIFIED
FIRST_REAL_ONCE_READY=NO
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
PUSH=NOT_AUTHORIZED
REAL_API_CALLS=0
BROKER_ORDERS=0
M4=NOT_STARTED
NEXT_APPROVAL_REQUIRED=separate push approval, then operator A-C and later one-cycle real read-only collection approval
```

**停止点：本地提交后停止（`PUSH_AUTHORIZATION_REQUIRED`），等待下一次人工授权。**
