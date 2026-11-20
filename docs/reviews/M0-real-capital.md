# M0 — 真实资金验收报告（real-capital）

| 字段 | 值 |
|---|---|
| stage_id | M0 |
| commit | `59ef4698a6f6fe8ee4c4c1e4d96fd92c1230e1e8` |
| code_hash | git tree `c2152d7f472ee6c8fff185111f71077c0554079c` |
| protocol_hash | NOT_APPLICABLE |
| environment | 与 M0-engineering 相同 |
| test_commands | NOT_APPLICABLE |
| evidence_paths | `artifacts/evidence/M0/` |
| findings | M0 期间：无真实账户、无真实密钥、无 Paper/Live 连接、无任何订单或资金操作。全部签批/账户均为 mock 测试密钥与虚构账户（架构 §6.5 规定），Live 相关只做 mock 干运行 |
| status | **R = NOT_STARTED** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED（未创建） |
| forward_window_status | NOT_APPLICABLE |
| next_gate | R 自真实 Live Pilot 起计（M9 之后，需 `E=PASS ∧ S=SUPPORTED ∧ FORWARD_SUPPORTED ∧ M9 Holdout=PASS ∧ 人工签批` 全链满足）；本报告不构成任何实盘许可 |
| approver | USER_PENDING |
