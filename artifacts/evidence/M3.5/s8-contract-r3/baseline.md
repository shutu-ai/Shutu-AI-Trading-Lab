# T8 基线记录（baseline — LOCAL_ONLY，2026-11-22）

## STOP/GO 核对（T8.0）

- `HEAD` = `origin/main` = `0b1f3b7900b9fe385bf4579e8126f1641f15d5ca`（任务书基线一致）
- `git log -3 --oneline`：
  - `0b1f3b7` fix(M3.5-S8 T7): fail-closed window completion + status integrity exit codes
  - `a0b1f58` docs(M3.5-S8 T6): remote-acceptance audit + M2 provenance verification
  - `94019e9` docs(M3.5-S8 R1): record remote CI verification — run 45023566557
- `git diff --check`：干净。
- 开工时未跟踪文件（均为已知、可追溯）：
  1. T8 任务书本身（用户输入文档）；
  2. `artifacts/evidence/M3.5/s8-contract-r2/ci-run-45031453603.log`（T7 会话
     遗留的 gh watch 原始输出——T8.4 预见并指示只读引用、不入库；其事实已由
     `r3/remote-ci-backfill.md` 的官方日志新鲜再核验覆盖，该工作文件已移除）。
  → **GO**。
- T7 远端验证（本轮新鲜再核验，`remote-ci-backfill.md`）：run `45031453603`
  head `0b1f3b7`，双平台 944/944，全门绿。**它只证明 T7 代码，不证明本轮
  T8 改动**（`T8_CI=REMOTE_PENDING`）。

## 已读输入（T8.0 阅读清单）

- 根/父级 `AGENTS.md`；T7 任务书（T7 会话全文已读）；
  `docs/reviews/M3.5-s8-completion-integrity-r2.md`；
  `artifacts/evidence/M3.5/s8-contract-r2/{baseline,red-green,operator-readiness,review}.md`；
  `scripts/run_m35_s8_shadow_real.py`（cmd_collect / _complete_window /
  cmd_status / main 全文）；`apps/market_gateway/feed_session.py`
  （run_collection_cycle / read_completion_records / window_facts_from_journal）；
  `tests/s8_gateway/test_completion_integrity.py`（T7 全部 18 用例）；
  ranged 预注册 v3（`configs/forward_observation_s8_real_v2.yaml`，经
  `prereg_real.py` 验证逻辑通读）与 eligibility 契约
  （`apps/trading_daemon/eligibility.py`）。

## 发现的 P1 家族（静态可复现路径，测试证实于 RED 阶段）

1. **P1-A 终态写入隔离缺失**：`cmd_collect` 在两种路径（`--once`、
   `--complete`）上都在任何终态审查之前执行凭证可见性审计 → 网络客户端/
   feed 构建 → `run_collection_cycle()`；`run_collection_cycle()` 先
   `collect_once()` + 追加收据，再 `run_replay(complete=False)`；已提交
   `WINDOW_COMPLETED` 的窗口可经普通采集入口继续追加链/会话（RED 实测：
   dummy feed 被调用、journal 变更、exit 0）。
2. **P1-B 纯离线恢复入口缺失**：`CHAIN_COMMITTED_SNAPSHOT_MISSING` 的修复
   只能经 `collect --complete` ——该入口要求 operator token + 凭证可见
   （无凭证时 exit 3 BLOCKED_ENV），且语义上可能"补采再修复"；
   `operator-readiness.md`（T7 版）对崩溃窗口的指引恰是"重跑
   `collect --complete`"——需要纯本地、零采集、零凭证的显式修复入口。

## 测试隔离设计（T8.0.5）

- 全部状态在 `tmp_path`；fixture 数据驱动（`selftest_daily_bars_v2.json`）；
- feed 哨兵：`AlpacaIexDailyBarFeed.collect_once` 被替换为记录型哑元
  （返回空传输应答，绝不产生网络字节），并在窗口构建**之后**才应用
  （避免污染窗口构建本身——T7 会话已验证此顺序）；
- 网络哨兵：对"零执行"断言的用例密封 `socket.socket`（`GuardedGetClient`
  构造器不建 socket，密封不影响合法路径）；
- 凭证哨兵：`preflight` 被记录型哑元替换——围栏断言它在 feed 之前**未被调用**；
- 不读取真实环境密钥；不改动默认真实配置；`REAL_API_CALLS=0`。

## 本轮改动范围（可归因清单）

- `scripts/run_m35_s8_shadow_real.py`：
  (a) `cmd_collect` 终态围栏（legacy 检查后、一切凭证/网络/写入之前；
      cycle 前二次复核缩小 TOCTOU 窗口）；新增退出码 `8 TERMINAL_WINDOW`；
  (b) 新增 `repair-completion` 子命令（纯离线快照修复，严格资格门）；
  (c) 抽取共享 `_snapshot_text`（完成/幂等修复/离线修复单一写入形状）；
  (d) docstring 退出码契约表与子命令文档更新。
- `tests/s8_gateway/test_terminal_collection_fence.py`：新增 16 契约测试。
- `artifacts/evidence/M3.5/s8-contract-r2/operator-readiness.md`：按 T8 语义
  修订 §D（最小修订 + 修订说明，T8.3 明确授权）。
- `artifacts/evidence/M3.5/s8-contract-r2/review.md`：追加式 CI 回填说明
  （T8.4，历史原文不动）。
- `artifacts/evidence/M3.5/s8-contract-r3/`：本轮新证据（只追加）。
- 未改动：`feed_session.py`（T7 已有 `read_completion_records` 直接复用）、
  冻结 v1/legacy 协议、r1/r2 原始证据、M2 历史、既有 944 测试零删改。
- 无新依赖；无密钥；无订单/经纪商模块导入；无未授权主机调用。
