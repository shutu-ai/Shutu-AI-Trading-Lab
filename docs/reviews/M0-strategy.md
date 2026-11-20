# M0 — 策略验收报告（strategy）

| 字段 | 值 |
|---|---|
| stage_id | M0 |
| commit | `59ef4698a6f6fe8ee4c4c1e4d96fd92c1230e1e8` |
| code_hash | git tree `c2152d7f472ee6c8fff185111f71077c0554079c` |
| protocol_hash | NOT_APPLICABLE（研究协议在 M3 冻结） |
| environment | 与 M0-engineering 相同（离线，无数据接入） |
| test_commands | NOT_APPLICABLE —— M0 无策略行为可测 |
| evidence_paths | `artifacts/evidence/M0/`（无策略证据工件） |
| findings | M0 为纯安全/契约里程碑：无策略、无回测、无数据，不产生任何 Alpha 或统计证据 |
| status | **S = N_A** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED（未创建） |
| forward_window_status | NOT_APPLICABLE |
| next_gate | 策略证据自 M3（冻结协议）起；M3.5/M8 才可能产生 `FORWARD_*`；不得以任何 mock/契约结果充当策略证据 |
| approver | USER_PENDING |

`N_A` 说明：M0 计划范围即为部署隔离与签批契约，不含任何策略要素；此结论为忠实记录，不代替任何 PASS。
