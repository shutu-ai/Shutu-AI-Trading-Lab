# T9 基线记录（baseline — LOCAL_ONLY，2026-11-22）

## STOP/GO 核对（T9.0）

- `HEAD` = `origin/main` = `ca749890521ce0d16f31b0984a3f4f0518176369`
  （任务书基线一致）
- 父链核对：`ca74989` parent = `0b1f3b7900b9fe385bf4579e8126f1641f15d5ca`
  （T8→T7→T6 链完整）
- `git log -3 --format='%h %s'`：
  - `ca74989` feat(M3.5-S8 T8): terminal collection fence + pure-offline repair-completion
  - `0b1f3b7` fix(M3.5-S8 T7): fail-closed window completion + status integrity exit codes
  - `a0b1f58` docs(M3.5-S8 T6): remote-acceptance audit + M2 provenance verification
- `git diff --check`：干净。
- 开工时未跟踪文件（均为任务书预见、如实记录，未删除他人文件）：
  1. T9 任务书本身（用户输入文档）；
  2. `artifacts/evidence/M3.5/s8-contract-r3/ci-run-45035699101.log`
     （T8 会话遗留的 gh watch scratch 日志——T9.1 预见；经只读检查、敏感信息
     核对后仅摘录事实入 `remote-ci-backfill.md`，全文不入库，随后移除）。
  → **GO**。

## T8 远端验收再核验（T9.0.3，本轮新鲜执行，非复用旧记录）

工具在线，经 `gh run view` / `gh run view --job --log` 实时再核验：

- run [`45035699101`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45035699101)
  head `ca749890521ce0d16f31b0984a3f4f0518176369`，conclusion=success；
- test (windows-latest) job `137248862025`：✓ 6m6s，**960 passed in 331.30s**；
- test (ubuntu-latest) job `137248862171`：✓ 1m30s，**960 passed in 75.73s**；
- 门步骤（双平台）：Environment check / Architecture boundary check（0 violation）/
  Secret leak scan（551 tracked files, 0 findings）/ Paper runtime live-artifact
  gate（`verify_live_blocked: paper runtime contains no live artifacts — PASS`）
  全部 success；
- 960 = 既有 944（零删减）+ 16 个 T8 契约测试；annotation 仅有 Node.js 20
  平台层弃用告警（不影响判定）。
- **范围**：该 run 只证明 T8 代码（`ca74989`），不证明真实 Alpaca API 行为、
  行情最终性、主机出口隔离，不构成操作者 A–C 签署或首次真实采集授权。

## 已读输入（T9.0.1）

`AGENTS.md`（根/父级，T7/T8 会话已全文在案）；T8 任务书；
`artifacts/evidence/M3.5/s8-contract-r3/review.md`；
`docs/reviews/M3.5-s8-terminal-collection-fence-r3.md`；
`artifacts/evidence/M3.5/s8-contract-r2/operator-readiness.md`（含 T8 修订）；
`artifacts/evidence/M3.5/s8-contract-r1/operator-preflight.md`；
`configs/forward_observation_s8_real_v2.yaml`（本轮从冻结文件直接核实：
`schema: forward-observation-preregistration-v3`、
`forward_protocol_id: m35-s8-real-shadow-readonly-v2`、
`poll_window_et: ["16:05","17:30"]`、`poll_interval_seconds: 60`、
`poll_timeout_seconds: 20`、`transport.scheme: https`）。

## 冻结对账基线与目标输出（T9.0.4）

- 对账基线：`ca749890521ce0d16f31b0984a3f4f0518176369`（= origin/main）。
- 本轮输出目录：`artifacts/evidence/M3.5/s8-operator-t9/`（新建，只追加）；
  `docs/reviews/` 可附 T9 审阅报告；全部为文档与离线测试输出，**零生产代码
  变更**（如审查发现需要代码变更，按 T9.6.2 单独提交缺陷报告，本轮不修）。
- 状态冻结：`M3.5_GATE=USER_PENDING`；`API_VERIFIED=NONE`；
  `REAL_FORWARD_DAYS=0`；`FIRST_REAL_ONCE_READY=NO`；
  `OPERATOR_PREFLIGHT_A/B/C=PENDING_OPERATOR`；
  `HOST_EGRESS_ISOLATION_UNVERIFIED`；`PAPER_WRITE=NOT_AUTHORIZED`；
  `S=INCONCLUSIVE`；`R=NOT_STARTED`；`BROKER_BEHAVIOR_UNVERIFIED`；
  `BLOCKED_DATA=FULL_MARKET_HISTORY`；`M4=NOT_STARTED`。
