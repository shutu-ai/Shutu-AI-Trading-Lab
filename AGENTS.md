# Shutu AI Trading Lab — 工程与验收守则（仓库内简版）

> 完整阶段定义以 `docs/plans/` 两份 v2.1 为唯一权威；本文件只固化跨阶段工程纪律，不复制规划内容。

## 阶段门

1. 每个阶段（M-1～M11 含 M3.5）只能由用户**明确批准**启动；任务书的存在、CI 绿、报告存在均不构成授权。
2. 阶段结束停在阶段门（`{STAGE}_GATE=USER_PENDING`）；不自动进入下一阶段、不代签审批、不 push 除非单独授权。
3. 真实券商/资金操作在所有阶段被禁止，直到 M9 之后由账户所有者另行签批。

## 架构完整性

4. 一个职责只有一个正式实现；`artifacts/poc/` 永不成为生产运行时依赖。
5. 数据层不导入 oms/brokers/risk/研究执行模块（`scripts/check_architecture.py` 强制）；新增依赖必须记录用途/许可证/替代方案，拒绝无理由基础设施。
6. 安全控制、审计与不可变契约的回归测试不可削弱；删除旧代码必须迁移必要行为测试。

## 证据与诚实性

7. 不伪称测试：`DOCUMENTED / API_VERIFIED / UNVERIFIED / BLOCKED_ACCESS`（数据）与 `BLOCKED_ENV / PENDING_FORWARD_WINDOW / PASS_WITH_SCOPE`（阶段）如实标注；零分母报 INCONCLUSIVE 而非 100%。
8. 阈值与验收判据先声明后执行，失败后不得降低。
9. 供应商证据标注来源 URL 与检索日期；营销描述 ≠ 实测结论。
