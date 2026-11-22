# 操作者行动卡（operator-action-card — T9.7.3，全部人工步骤，本轮未执行）

> 顺序硬约束：A → C → 固定环境 → 申请 B-only → 本人核验 B → 申请首次
> collect --once。每步只记录**状态、时间、非敏感证据索引**（签署副本与全部
> 证据永远留在操作者本地，不入仓库、不交 Agent）。本卡不含任何可自动执行
> 真实调用的脚本。

| # | 步骤 | 谁执行 | 前置 | 记录栏（执行时填） | 状态 |
|---|---|---|---|---|---|
| 1 | A 账户与许可核对（attestation §A1–A5；官方条款页本人阅读当期版本） | 账户所有者 | — | 状态：＿＿ 时间：＿＿ 证据索引：＿＿ | PENDING_OPERATOR |
| 2 | C 出口隔离负例全矩阵（environment-plan §7 F-1～F-8 + reconciliation §7 精化判据；attestation §C-1～C-8 模板） | 账户所有者 | 已固定候选环境 | 状态：＿＿ 时间：＿＿ 证据索引：＿＿ | PENDING_OPERATOR |
| 3 | 固定目标环境身份（reconciliation §5 登记表全部空白字段 + §6 持久状态卷落实：独占/权限/加密/备份摘要/重建程序） | 账户所有者 | 步骤 2 通过 | 登记表副本索引：＿＿ 时间：＿＿ | 未固定 |
| 4 | 申请【授权 1：B-only 注入核验】（`b-only-authorization-request.md` 草案 → 用户审批） | 操作者发起 / 用户批准 | 步骤 1+2+3 完成；A=VERIFIED、C=VERIFIED | 申请日期：＿＿ 批复：＿＿ | `B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED` |
| 5 | 本人执行 B-only：子进程注入 → 可见性检查（名称级）→ 立即清除 → 无敏感记录 | 账户所有者（仅本人） | 步骤 4 明确批准；**未批准禁止执行** | 时间：＿＿ 结果（无敏感）：＿＿ 清除确认：＿＿ | `B_PLAN_READY=UNVERIFIED_OR_PENDING_OPERATOR` |
| 6 | B 本地签署 → B=VERIFIED_BY_OPERATOR（attestation §B） | 账户所有者 | 步骤 5 完成 | 签署副本索引（本地）：＿＿ | PENDING_OPERATOR |
| 7 | 申请【授权 2：首次 collect --once】（`first-real-once-approval-request.md` 修订草案；前置核验：A/B/C 签署成立 + 环境身份未变 + CI 基线一致 + 状态卷就绪） | 操作者发起 / 用户批准 | 步骤 1–6 全部成立 | 申请日期：＿＿ 批复：＿＿ | `FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED` |
| 8 | 执行一次 `collect --once`（指定环境/日期/只读端点），按预期结果集判读（request §4） | 账户所有者 | 步骤 7 明确批准；异常即停（reconciliation §8） | 时间：＿＿ 退出码：＿＿ 状态输出摘要：＿＿ | — |

**铁律**：
- 步骤 4/7 的批准彼此独立，任何批准不自动延伸到下一步；
- 全程 Codex/Agent 零接触凭证、零代签、零代执行；
- 任何一步 BLOCKED/UNVERIFIED → 停在下门口，不得为推进而放宽判据；
- 状态枚举只有三态（PENDING_OPERATOR / VERIFIED_BY_OPERATOR / BLOCKED），
  `B_PLAN_READY`、`PREPARED` 永远只是准备事实，不冒充签署。
