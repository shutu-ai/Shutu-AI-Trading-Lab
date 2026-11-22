# T7 基线记录（baseline — LOCAL_ONLY，2026-11-22）

## STOP/GO 核对（T7.0）

- `HEAD` = `a0b1f58d29ecb4bf25646ac22a5791ea04ca6cdb`
- `origin/main` = `a0b1f58d29ecb4bf25646ac22a5791ea04ca6cdb`（与任务书远端基线一致）
- `git log -3 --oneline`：
  - `a0b1f58` docs(M3.5-S8 T6): remote-acceptance audit + M2 provenance verification
  - `94019e9` docs(M3.5-S8 R1): record remote CI verification — run 45023566557
  - `2a60864` chore(M3.5-S8 R1): regenerate A2/A5/A6 self-rewriting evidence logs
- `git diff --check`：干净。
- 开工时工作区未跟踪文件：仅任务书本身
  `Shutu_AI_Trading_Lab_M35_S8_T7_Completion_Integrity_and_Preflight_Codex_Task.md`
  （用户输入文档，预期内）→ **GO**。
- 远端 CI 参照：run [`45026250819`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45026250819)
  head `a0b1f58`，双平台 926 passed（任务书转述，本轮未重新访问远端）。
  **本文件及本轮所有证据均为 LOCAL_ONLY：该 CI 属于修复前代码，不证明本轮新代码。**
  `T7_CI=REMOTE_PENDING`。

## 已读输入（T7.0 阅读清单）

- 仓库 `AGENTS.md`（两份：`D:/dev-projects/AGENTS.md`、项目根）——阶段门、证据诚实性纪律。
- `artifacts/evidence/M3.5/s8-contract-r1/t6-audit.md`（T6 复核结论）。
- `artifacts/evidence/M3.5/s8-contract-r1/operator-preflight.md`（A–C 清单，T7.4 输入）。
- ranged 预注册 v3 契约：`configs/forward_observation_s8_real_v2.yaml`（经
  `apps/market_gateway/prereg_real.py` 全部验证逻辑通读：ranged_daily_bars、
  1Day/raw、page_cap≤20、GET-only、`broker_credentials: FORBIDDEN`、
  `paper_orders: PAPER_NOT_RUN`、`day_counting_rule: full_coverage`）。
- 生产代码：`scripts/run_m35_s8_shadow_real.py`（`_complete_window`、`cmd_status`、
  `cmd_collect`、`main`）、`apps/market_gateway/feed_session.py`（`append_receipts`、
  `window_facts_from_journal`、`evaluate_window`）、`apps/trading_daemon/engine.py`
  （`complete_session`）、`apps/trading_daemon/driver.py`（`run_replay`）、
  `apps/trading_daemon/eligibility.py`（输出契约：`eligibility` /
  `forward_window_status` / `s=INCONCLUSIVE` / `paper_orders=PAPER_NOT_RUN`）、
  `src/trading_lab/security/audit.py`（AuditLog 哈希链 + head）、
  `src/trading_lab/security/canonical.py`（`canonical_digest`）。
- 既有测试：`tests/s8_gateway/test_forward_gate_persistence.py`、
  `test_runner_cli.py`、`tests/s8_gateway/conftest.py`。

## 基线不变量（修复前记录，修复不得削弱）

1. **收据链格式**：`receipts.jsonl`（AuditLog JSONL 哈希链 + `.head` 尾记录），
   记录 `payload.event_type ∈ {RECEIPT, FEED_ERROR, QUALITY_REJECT,
   WINDOW_COMPLETED}`；`WINDOW_COMPLETED` 记录字段：`facts_digest`、`eligibility`、
   `forward_window_status`、`trading_days_observed`、`protocol_hash`、
   `environment`、`received_at`、`receipt_schema="s8-receipts-v2"`。
2. **快照**：`<state>/forward-window-evaluation.json`，schema
   `s8-forward-window-evaluation-v1`，键：`facts_digest`、`facts`、`eligibility`、
   `claim_attempt`、`claim_error`、`protocol_hash`（T7 修复保持键集不变，
   仅改为原子写入并强制 LF）。
3. **失败码语义（修复前）**：0 OK / 1 FAILURE / 3 BLOCKED_ENV /
   4 AUTHORIZATION_REFUSED / 5 LEGACY_CONTRACT。T7 新增（文档化于 runner docstring
   与 `red-green.md`）：6 INTEGRITY_FAILURE / 7 COMPLETION_INCOMPLETE。
4. **合法查询行为边界**（保持不变）：空状态目录 → `status` exit 0 +
   `forward_window_status=NOT_STARTED`；有链无完成记录 → exit 0（进行中）。
   既有测试 `test_status_on_empty_state_is_honest_not_started` 修复前后均通过。
5. **E-Gate 不变量（全部保持）**：`events_synthetic` 门、receipt↔journal 绑定、
   协议身份（SESSION_STARTED protocol_hash/environment）、
   `disconnect_recoveries`/`duplicate_recoveries`/`audits_passed`、
   ≥5 全覆盖交易日、0 订单；synthetic PASS 永远只能是
   `SIMULATED_REAL_SHAPE_TEST_ONLY`，不升 `API_VERIFIED`。

## 本轮改动范围（可归因清单）

- `scripts/run_m35_s8_shadow_real.py` —— P0-A/P0-B 修复（完成状态机、
  fail-closed status、退出码 6/7、原子快照写入）。
- `apps/market_gateway/feed_session.py` —— 新增只读助手
  `read_completion_records()`（fail-closed 读取 WINDOW_COMPLETED 记录）。
- `tests/s8_gateway/test_completion_integrity.py` —— 新增 18 个契约测试。
- `artifacts/evidence/M3.5/s8-contract-r2/` —— 本目录新证据。
- 未改动：冻结 v1/legacy 协议、事实/原始历史日志、OMS/风控/Paper/Live 边界、
  基础研究策略、`s8-contract-r1/` 及全部既有证据、既有 926 测试零删改。
- 无新依赖；无密钥；无订单/经纪商模块导入；无未授权主机调用。
