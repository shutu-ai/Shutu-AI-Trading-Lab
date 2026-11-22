# T7 独立验收审阅（review — LOCAL_ONLY，2026-11-22）

## 判定

**`T7_COMPLETION_INTEGRITY = LOCAL_PASS_WITH_SCOPE`**

范围声明：本轮仅完成本地离线整改（P0-A/P0-B fail-closed 修复 + 18 个契约测试
+ 操作者资料准备 + 证据入档 + 本地提交）。新代码**未经过任何远端 CI 验证**
（`T7_CI=REMOTE_PENDING`）；不证明真实市场、供应商行为或主机级出口隔离。

## 已验证（本轮实测）

1. P0-A 修复：收据未持久化 ⇒ 无快照、无 evidence 副本、`collect --complete`
   退出 7；快照写入失败 ⇒ `SNAPSHOT_WRITE_FAILED`、可幂等修复、不重复收据
   （`fault-injection.log` §B/§E）。
2. P0-B 修复：6 类完整性注入全部非零、可区分、稳定退出（6/7），共享校验实现
   `_verify_completion_evidence`（含**链绑定**，不接受"摘要相等但无已提交记录"）。
3. 崩溃恢复：四个故障点 × 全新进程读取，无假 COMPLETE、无二次完成收据。
4. 既有安全不变量复测通过：`events_synthetic` 门、receipt↔journal 绑定、协议
   身份、断连/重复恢复、≥5 全覆盖日、0 订单（s8_gateway 173 测试全绿，
   含既有 926 套件的全部用例）。
5. 工具链：check_environment / check_architecture / scan_secrets /
   verify_live_blocked / audit_t6_m2_provenance / smoke_mock 全部 exit 0；
   `git diff --check` 干净。

## 未验证 / 残余风险

1. **`T7_CI=REMOTE_PENDING`**：新增 18 测试与两文件生产改动只在本地 Windows
   （Python 3.13.15）验证；Linux 矩阵（含 `os.replace`/LF/路径语义差异）待
   下轮授权推送后的双平台 CI。代码中已按平台文档化（docstring：POSIX 原子；
   Windows `MOVEFILE_REPLACE_EXISTING`）。
2. **AuditLog.append 的崩溃原子性是检测级而非预防级**（M0 既有设计，ADR-002）：
   记录已写、head 未写之间崩溃 → 下次 verify 报链不匹配 → 本轮状态机一律
   fail-closed 拒绝（`REFUSED_CHAIN_CORRUPT` / `INTEGRITY_FAILURE`）。这是
   如实拒绝而非数据修复，属可接受工程取舍，未在本轮扩大改造。
3. **自重写 M2 证据日志（a2/a5/a6）**：全量 pytest 会按既有设计重写这三份已
   提交日志（T6 已披露机制）。本轮协议：跑完后从 HEAD 恢复已提交字节，新鲜
   输出另存 `r2/full-regression-rewritten-logs/` 存档；已提交历史保持不变。
4. **`collect` 真实路径仍仅可由未来授权运行触达**：本轮用模拟 feed 在进程内
   驱动 cmd_collect 全分支（含 preflight READY 门），真实供应商行为
   `BROKER_BEHAVIOR_UNVERIFIED`、`API_VERIFIED=NONE` 维持。
5. **status 退出码契约是新增对外语义**：任何把 `status exit 0` 当作
   "一切正常/资格通过"的外部自动化必须改为读取 JSON 字段；已文档化于
   runner docstring 与 `operator-readiness.md` §D。
6. **本轮 RED 期间的事故披露**：旧代码经测试路径向 r1 写入过一个未跟踪模拟
   evidence 文件，已删除并恢复原状（详见 `red-green.md` 附注）；GREEN 路径
   结构性防止复发。

## 状态出口（逐字）

```text
T7_COMPLETION_INTEGRITY=LOCAL_PASS_WITH_SCOPE
T7_CI=REMOTE_PENDING
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
HOST_EGRESS_ISOLATION_UNVERIFIED
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
FIRST_REAL_ONCE_READY=NO
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
```

**停止点：本地提交后停止（`PUSH_AUTHORIZATION_REQUIRED`），等待下一次人工审批。**

---

## 追加回填（T8.4，2026-11-22，追加式——上文成文时的事实保持不变）

上文 "T7_CI=REMOTE_PENDING" 为成文时（本地提交 `0b1f3b7` 之前）的事实。
其后经用户单独授权推送 `a0b1f58..0b1f3b7`，GitHub Actions run
[`45031453603`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45031453603)
（head `0b1f3b7900b9fe385bf4579e8126f1641f15d5ca`，完整 SHA 与 job 细节见
`r3/remote-ci-backfill.md`）双平台 **944 passed**（ubuntu 63.26s /
windows 517.75s），静态门全绿 → **`T7_CI=REMOTE_VERIFIED`**。
该 run 只证明 T7 代码（既有 926 + 18 个 T7 测试），不证明 T8 及之后的代码，
也不证明真实 API 行为。T8 之后的验证状态见
`artifacts/evidence/M3.5/s8-contract-r3/`（`T8_CI=REMOTE_PENDING`）。
