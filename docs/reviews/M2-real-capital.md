# M2 — 真实资金验收报告（real-capital）

| 字段 | 值 |
|---|---|
| stage_id | M2 |
| commit | `b3a3feed109c7ad5a9ad9febc647d38f1162d749` |
| code_hash | git tree at `b3a3fee` |
| protocol_hash | NOT_APPLICABLE |
| environment | 与 M2-engineering 相同 |
| test_commands | NOT_APPLICABLE |
| evidence_paths | `artifacts/evidence/M2/` |
| findings | M2 期间：无真实账户、无券商凭证申请、无 Paper/Live 连接、无任何订单或资金操作；全部经纪行为为本地 FakeBroker（零网络，smoke 扫描证明） |
| status | **R = NOT_STARTED** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |
| next_gate | R 自真实 Live Pilot 起计（M9 之后，全链条件满足且人工签批）；本报告不构成任何实盘许可 |
| approver | USER_PENDING |
