# M1 — 策略验收报告（strategy）

| 字段 | 值 |
|---|---|
| stage_id | M1 |
| commit | `c2505becb8beb0f722162059b25c5156f2ecf46f` |
| code_hash | git tree at `c2505be` |
| protocol_hash | NOT_APPLICABLE（研究协议在 M3 冻结） |
| environment | 与 M1-engineering 相同 |
| test_commands | NOT_APPLICABLE —— M1 无策略行为可测 |
| evidence_paths | `artifacts/evidence/M1/`（无策略证据工件） |
| findings | M1 为数据供应里程碑：无策略、无回测、无任何统计或 Alpha 证据；合成 fixture 仅证明数据管道逻辑，不构成策略证据 |
| status | **S = N_A** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |
| next_gate | 策略证据自 M3（冻结协议）起；不得以数据准入状态或工程 PASS_WITH_SCOPE 充当策略证据 |
| approver | USER_PENDING |
