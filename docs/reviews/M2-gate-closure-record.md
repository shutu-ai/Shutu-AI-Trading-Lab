# M2 阶段门正式关闭记录

| 字段 | 值 |
|---|---|
| decision | **M2_GATE=CLOSED** |
| approved_scope | **E=PASS_WITH_SCOPE(MOCK_ONLY)** |
| 审批日期 | 2026-11-21 |
| 审批来源 | 用户在当前会话中经 AskUserQuestion 审批核查点明确确认（选择"批准 M2 关闭 + M3 启动"） |
| 最终被测代码 SHA | `379bd72`（CI run `44912904901` 双矩阵 347 passed） |
| CI 补录后 SHA | `f27892d`（CI run `44925761010` 双矩阵 347 passed） |
| docs-only 后记 | `1988cab`（无独立 CI run；`0ebae0d`/`29ecf54`/`a4f1413` 均为此前 CI 补录） |

## 审批范围限定

- 仅关闭 **M2 工程阶段**（E=PASS_WITH_SCOPE(MOCK_ONLY)）
- **BLOCKED_DATA(全市场研究)不变**、U-1 UNRESOLVED 不变、BROKER_BEHAVIOR_UNVERIFIED 不变
- **不授权 M3 启动**（M3 启动须另行确认，见下方第二项审批）
- 不授权任何真实券商交易、Paper/Live 连接、真实资金操作

## 第二项审批记录

| 字段 | 值 |
|---|---|
| decision | **M3_START=APPROVED** |
| approved_scope | **SYNTHETIC_ENGINEERING_ONLY**（仅合成数据+纯离线回测工程） |
| 审批日期 | 2026-11-21（与 M2 关闭同一审批核查点确认） |
| 限定 | 不含 M3.5/M4/Paper/Live/真实数据/真实资金 |

## 审计披露

- 历史 A2/A5/A6 部分日志曾重生成（`process_concurrent_50.log` 为覆盖式写入等）；原始版本可由 Git 历史追溯
- `M2-final-gate-recommendation.md` 残余风险清单实际 9 行（原称 8 项不准确）
- CI `smoke_mock` 非独立 CI 步骤（本地 EXIT=0 但 CI 未单独执行该脚本）

## M2 残余风险（不变，归后续阶段）

| 风险 | 归属 |
|---|---|
| R6 TOCTOU 窗口 | Paper 专项 |
| R7 六字段 MOCK_ONLY | Paper/实盘阶段 |
| R3 订单级对账 MOCK_ONLY | Paper/实盘阶段 |
| ApprovalSecrets 跨进程分发 | 真实部署阶段 |
| U-1 VendorFacts 词表 | 真实数据解封前置阻断 |
