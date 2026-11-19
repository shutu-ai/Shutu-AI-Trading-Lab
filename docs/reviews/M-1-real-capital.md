# M-1 真实资金验收报告（R-Gate）

| 字段 | 值 |
|---|---|
| stage_id | M-1 |
| commit | `ea894ec2`（主证据提交，见 engineering 报告头部） |
| protocol_hash | NOT_APPLICABLE |
| environment | 本地沙箱；无任何券商账户连接 |
| test_commands | NOT_APPLICABLE |
| evidence_paths | `artifacts/evidence/M-1/` |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED |
| forward_window_status | NOT_APPLICABLE |
| next_gate | R-Gate 在 M9 之后才会进入 OBSERVING（且需全部前置门通过 + 人工签批） |
| approver | 待用户审查 |

## R-Gate 结论：**NOT_STARTED**

依据（基线 §0.4 / §9）：M-1 阶段 `R=NOT_STARTED`。

## 明确声明

1. 本阶段**未开立、未连接、未触碰任何券商账户**；未获取任何 API 密钥（环境中不存在 Alpaca 密钥，已记录于环境证据）。
2. 未发生任何真实资金操作：无入金、无出金、无下单、无自动交易。
3. Alpaca Paper API 属可选验证，本阶段未运行（无密钥）→ 如实标注 **`BROKER_BEHAVIOR_UNVERIFIED`**（engineering 报告 §Alpaca Paper）；按基线 §9，这**不等于** `BLOCKED_ENV`（属"非必测而未做"）。
4. Fake broker / mock 的全部通过只证明本地契约，不构成任何真实券商行为验证。
5. 未产生任何 TWR/MWR/成本/回撤数据（无资金参与，天然无此数据）。
