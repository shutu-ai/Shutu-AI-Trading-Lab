# M3-H1A — T0 现状盘点与变更边界（只读核对记录）

Task ID: `M3-H1A-OFFLINE-HISTORICAL-DATA-PIPELINE-20261126-R1`
核对时刻: 2026-11-26（本地执行轮）

## 基线核对（全部实测）

| 项 | 实际值 |
|---|---|
| `git rev-parse HEAD` | `a604fa77734df9df864d4bdc209403d3f85dd067` |
| `git rev-parse origin/main` | `a604fa77734df9df864d4bdc209403d3f85dd067`（== HEAD） |
| branch | `main` |
| CI run `45816148658`（H1 文档整改） | status=completed, conclusion=success, headSha=`a604fa7…`（gh 实测） |
| CI run `45357179029`（H0 治理提交） | status=completed, conclusion=success, headSha=`1a06f81…`（gh 实测） |
| Python | 3.14.7（仓库要求 >=3.13） |

## 既有脏文件（仅路径名登记，正文未读取、未修改、未暂存）

Modified（M2 保护日志，禁止触碰）:
- `artifacts/evidence/M2/a5-true-process-race/process_concurrent_50.log`
- `artifacts/evidence/M2/a6-strict-process-proof/barrier_50_rounds.jsonl`
- `artifacts/evidence/M2/final-send-claim/a2-quantitative-close/process_50_rounds.log`

Untracked（既有，原位保护）:
- `M35-S8-T9-10-Forward-Window-Readiness-20261124.md`
- `Shutu_AI_Trading_Lab_Cross_Conversation_Reconciliation_Baseline_20261124.md`
- `Shutu_AI_Trading_Lab_M35_S8_T9_9_First_Real_ReadOnly_Once_Codex_Task.md`
- `Shutu_AI_Trading_Lab_M3_H0_Remote_CI_Gate_Reconciliation_20261124.md`
- `Shutu_AI_Trading_Lab_M3_H1_Contract_Preflight_Remediation_20261124.md`
- `Shutu_AI_Trading_Lab_M3_H1_Contract_Preflight_Resume_20261125.md`
- `Shutu_AI_Trading_Lab_M3_H1A_Offline_Historical_Data_Pipeline_Codex_Task_20261126.md`（本轮任务书本身）
- `p1.png`、`p3.png`

本轮新增临时目录（不进提交路径）: `.superpowers/sdd/Shutu_AI_Trading_Lab_M3_H1A_…/`（执行 ledger，git status 将新增 `?? .superpowers/` 条目——属本轮工作痕迹，不暂存）。

## 权威文件交叉核对记录（实际 HEAD）

已全文阅读: `AGENTS.md`（会话上下文）；`docs/plans/M3-historical-research-workstream-20261124.md`；`docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md`（含 2026-11-26 四项勘误 P0-1/P0-2/P1-3/P1-4）；`docs/reviews/M3-historical-data-blocker-register-20261124.md`；`docs/adr/ADR-003-data-contract.md`；`docs/reviews/M3.5-S8-T9.9-First-Real-ReadOnly-Once.md`；`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`（全文 320 行）+ 附录 A3-H；`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`（数据/历史/M3-H 相关节定向核对，935 行）。

源码核对（实测源）: `src/trading_lab/data/{acceptance,calendar,quality,records,snapshot,__init__}.py`；`apps/market_gateway/{http_client,alpaca_feed,quality,prereg_real,offline_fixtures,__init__}.py`；`scripts/check_architecture.py`；`tests/no_lookahead/{conftest,test_calendar}.py`；`tests/helpers_no_lookahead.py`；`tests/s8_gateway/test_http_guard.py`；`configs/data_acceptance.yaml`；`pyproject.toml`。

## T0 检查项结论

1. `AVAILABLE_AT_RULES` 闭集 = {bar_ts_plus_0, bar_ts_plus_15min, announced_or_published_before_use}（acceptance.py:105）；`_EVENT_LEVEL_RULES` 仅 announced_or_published_before_use；新规则受控加入 frozenset 后自然落入 bar-level else 分支，判定顺序零改动。
2. `PurposeRequirements` 全阈值强制（`…` defaults + extra=forbid）；min_coverage ≥ 1−max_missing 一致性校验在位。
3. `evaluate_purpose` 七步冻结判定序与 ADR-003 D5 一致；零分母→INCONCLUSIVE；license 未确认→BLOCKED_DATA。
4. `MarketCalendar` 假日/半日由构造参数供应（frozenset，拒绝周末假日/重复/重叠）；`session()` 对窗口外日期按"周一到周五"分类——**这正是本轮要包一层版本化供应 + 覆盖窗口 fail-closed 的原因**（禁止静默 weekday 推演）。
5. `quality.latency_stats` 语义 = `ts_available_utc − ts_event_utc`（quality.py:115-139），与逐行日历截止校验明确分离实现。
6. `snapshot.research_admissible` = 完整性 + KNOWN availability + available_at ≤ cutoff（snapshot.py:135-165）——不证明供应商历史 PIT 真实验证（勘误 P1-4），本轮以 availability_basis + PIT 分级使其不可冒充。
7. 仓库**无既有 H1 代码**（`src` 全树 grep historical/history_bars 无历史数据管线命中；`apps/market_gateway` 仅有 S8 前向采集面）→ 无第二套实现风险，按最小新增执行。

## 本轮允许变更路径（任务书 T0）

- `src/trading_lab/data/`（新增 historical_calendar.py、historical.py；records.py/snapshot.py/acceptance.py/__init__.py 最小扩展）
- `apps/market_gateway/historical_bars.py`（最小复用接口，复用 GuardedGetClient）
- `tests/m3_h/`（新增 H1 定向测试）+ `tests/no_lookahead/`（如需回归保护，本轮预期零改动）
- `configs/data_acceptance.yaml`：**本轮不改**（新用途行 PURPOSE_ROW_PENDING_CALENDAR_FREEZE——max_latency_seconds 推导依赖尚未冻结的 2017–2025 研究日历；勘误 P0-1 明确禁止在该规则实现并冻结阈值前提交用途行；候选行以可自动验证模板形式存在于测试）
- `artifacts/evidence/M3-H/h1a/`（RED/GREEN 证据、推导记录、请求审计）
- `docs/reviews/M3-H1A-offline-implementation-20261126.md`（唯一验收报告）
