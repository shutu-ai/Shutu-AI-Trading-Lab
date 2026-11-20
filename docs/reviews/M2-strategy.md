# M2 — 策略验收报告（strategy）

| 字段 | 值 |
|---|---|
| stage_id | M2 |
| commit | `b3a3feed109c7ad5a9ad9febc647d38f1162d749` |
| code_hash | git tree at `b3a3fee` |
| protocol_hash | NOT_APPLICABLE（M3 冻结） |
| environment | 与 M2-engineering 相同 |
| test_commands | NOT_APPLICABLE —— M2 无策略行为可测 |
| evidence_paths | `artifacts/evidence/M2/` |
| findings | M2 为风控/OMS 工程里程碑：合成数据 + Fake Broker，无策略、无回测、无任何 Alpha/OOS 统计证据；故障注入证明的是工程崩溃一致性，不是策略能力 |
| status | **S = N_A** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |
| next_gate | 策略证据自 M3（冻结协议）起；合成交易不产生 Alpha 证据 |
| approver | USER_PENDING |
