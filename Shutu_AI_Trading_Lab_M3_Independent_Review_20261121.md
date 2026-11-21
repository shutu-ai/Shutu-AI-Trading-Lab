# Shutu AI Trading Lab — M3 起步阶段独立验收报告

审查时间：2026-11-21；公开 GitHub 仓库 `shutu-ai/Shutu-AI-Trading-Lab`。

## 证据与状态

- 当前 main：`3505799f844c0a8cfa410df269b6afdd907f38f0`。
- CI：run `44929797426`，Ubuntu/Windows 作业 success；原始 Job logs 均为 **343 passed**，而非项目总结的 347。前一工程基线 `f27892d` 为 347 passed。
- 3505799 相对 f27892d：提交 `5c020b0` 记录仓库声称的 `M2_GATE=CLOSED` 与 `M3_START=APPROVED`；提交 `3505799` 增加 `configs/evaluation_protocol.yaml`、`backtest/engine.py`、`validation/__init__.py`，也修改已验收 A7 测试及 A2/A5/A6 历史日志。仓库审批记录存在，但原始审批交互不在本审查可见材料中，审查不独立认证签批的真实性。
- 本轮无真实券商/资金验证证据；保持 `BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`。

## 不通过原因

**P0：旧 M2 A7 安全回归被弱化。** `tests/fault_injection/test_a7_targeted_proof.py` 删除了曾经执行 5 轮真实子进程 `claim → os._exit(37) → fresh recover() → automatic HALT` 的参数化测试。新文件只有顺序 CAS 一次性领取、Risk/OMS 单层拒绝等测试。343 passed 与旧 347 的净差 4 项相符。CI 全绿不证明原证明保持。

**P0：M3 缺少专属验证。** 仓库树中没有 `tests/backtest/`、`tests/validation/`；`validation` 仅初始化文件；没有 M3 三轨报告或 ADR-004。M3 E-Gate 关键要求未被执行证据证明。

**P1：回测核心不足。** `backtest/engine.py` 只有简化 `Bar` / `BacktestAccount`；购买未检查现金余额、数量价格/类型无完整检查，标记权益缺价时默认为零；无可复算时间/执行/费用/交收/分红/拆股/退市模型，且可能重复现有 `contracts.MarketBar`。

**P1：协议只是配置声明。** `evaluation_protocol.yaml` 没有完成规范化 hash 与冻结状态机/全试验账本、OOS/Holdout/Forward 独立分割、一次性封存与污染、真实可执行的两套预算与检验阈值。`equal_*_budget: true` 不是公平性证明，`max_drawdown_pct: 100` 不是有约束力的风险准入门。

**P1：静态架构检查未覆盖新增包。** CI 显示 3 packages/18 files，`backtest`、`validation` 不在扫描范围。

## 结论

- `M2_GATE=CLOSED`：仓库中有审批记录，保持其状态，不以 M3 新问题自动撤销。
- `M3_START=APPROVED`：仓库记录仅授权合成离线研究。
- `M3_GATE=USER_PENDING`：不能关闭；不得进入 M3.5。
- 下一步：执行 `M3-R1-RESTORE-M2-PROOF-AND-COMPLETE-SYNTHETIC-RESEARCH-20261121-001`，首先恢复 M2 A7 不可退化回归，再完成并验证 M3 的实际工程范围。工程结果与真实策略证据继续分离。

链接：<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44929797426>；<https://github.com/shutu-ai/Shutu-AI-Trading-Lab/commit/3505799f844c0a8cfa410df269b6afdd907f38f0>。
