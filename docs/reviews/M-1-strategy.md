# M-1 策略验收报告（S-Gate）

| 字段 | 值 |
|---|---|
| stage_id | M-1 |
| commit | `ea894ec2`（主证据提交，见 engineering 报告头部） |
| code_hash | 本阶段工件由 git 跟踪；POC 代码哈希随提交可重算 |
| protocol_hash | NOT_APPLICABLE — 本阶段未运行任何策略验证，无研究协议 |
| environment | Windows 11 / Python 3.13.15 / 本地沙箱，无券商连接 |
| test_commands | NOT_APPLICABLE — 无策略测试（工程测试见 engineering 报告） |
| evidence_paths | `artifacts/evidence/M-1/` |
| evidence_state | **NOT_EVALUATED** |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED（未解封；本阶段未触及任何 Holdout） |
| forward_window_status | NOT_APPLICABLE — 未启动任何前向采集 |
| next_gate | M0（部署隔离与签批契约），等待用户审查 M-1 后另行授权 |
| approver | 待用户审查（本报告不含任何自批） |

## S-Gate 结论：**N_A**

依据（基线 §9 M-1）：`S=N_A，evidence_state=NOT_EVALUATED，R=NOT_STARTED`。
M-1 是开源底座工程 POC，**不运行任何策略、不产生任何 Alpha 证据**。

## 明确声明

1. 本阶段没有评估任何交易策略的有效性；任何收益字样均不适用。
2. 数据 POC 中的价格数据仅验证管道形状（UTC、时间可得性、复权字段），不用于任何信号研究。
3. qlib 样本数据上的任何模型运行（如候选评估中的工作流）只是**库能力验证**，其指标不是本项目策略证据，不得被引用为 Alpha 支持。
4. 未修改任何验收标准；S 门在后续阶段（M3 起）按冻结协议独立执行。
