# 首次真实只读单周期采集授权申请（first-real-once-approval-request — 草案，本轮不执行）

> **本文件是一份"未来授权申请"的草案**：它本身不是许可，不构成执行授权，
> 不附带任何执行动作。`FIRST_REAL_ONCE_READY=NO`。只有在"操作者 A/B/C 本人
> 签署全部 VERIFIED_BY_OPERATOR + 账户所有者/用户再给出一次**独立、范围限
> 一次**的明确授权"之后，才可能按本草案执行**一个**只读采集周期
> （`collect --once`）。

## 1. 操作者前提状态（申请时点如实填写；当前全为 PENDING_OPERATOR）

| 项 | 状态 | 签署依据（操作者本地 attestation，不入仓库） |
|---|---|---|
| A 账户与许可 | **PENDING_OPERATOR** | ＿＿（签署后填本地模板版本/日期） |
| B 凭证操作 | **PENDING_OPERATOR** | ＿＿（PREPARED 不算签署事实） |
| C 出口隔离 | **PENDING_OPERATOR**（`HOST_EGRESS_ISOLATION_UNVERIFIED`） | ＿＿（须 §C 全矩阵 VERIFIED） |

## 2. 执行环境标识（预填工程事实；操作者执行时补环境标识与 hash）

- 受控主机/环境：＿＿＿＿（方案 A/B 见 operator-environment-plan.md；唯一
  已验证环境，切换即全矩阵重验）
- 唯一网络环境：＿＿＿＿（直连 / 经代理 + CONNECT ACL）
- 独占进程承诺：观察窗口内单操作者、单实例、零并发 CLI
  （TOCTOU 机制残余未消除，操作纪律见 environment-plan §8）
- 只读出口验证摘要：＿＿＿＿（C 项 §C-1～C-8 结果摘要；任何未证实路径须
  如实标注）
- 私有 state dir：＿＿＿＿（路径或非敏感 hash；专用新建，不复用任何旧目录）
- 采集环境标识 hash（检出 commit + 环境）：＿＿＿＿

## 3. 目标协议（冻结配置事实，工程预填——不替操作者检查实际时钟）

- 预注册：`configs/forward_observation_s8_real_v2.yaml`
  （schema `forward-observation-preregistration-v3`）
- 协议 ID：`m35-s8-real-shadow-readonly-v2`
- 数据契约：ranged `GET /v2/stocks/{symbol}/bars?timeframe=1Day`，
  adjustment=raw，window_bounds=session_midnight_et_to_received_at，
  GET-only、redirects forbidden、page_cap≤20
- 数据源：Alpaca **IEX / Basic（$0）**；符号：**SPY, QQQ**（预注册，不可扩）
- 轮询窗口（**配置值**，操作者须自行确认真实时钟在窗口内）：
  `poll_window_et: ["16:05", "17:30"]`，间隔 60s，超时 20s；
  交易日历：操作者声明表（calendar_valid_from/until、holidays、half_days
  以配置为准）
- 授权 token 名称：`S8_OPERATOR_AUTHORIZATION`（值由签批记录定义；
  **token 名称出现在文档中不构成执行授权**）
- 退出码契约（T7/T8 冻结）：0 / 1 / 3 / 4 / 5 / 6 / 7 / 8（runner docstring）

## 4. 正确预期（申请人与执行人必须先读；任何单周期都可能出现以下任一结果）

- `MARKET_CLOSED` / `OUTSIDE_POLL_WINDOW`：合法拒绝采集，**不是错误**；
- 权限错误（401/403）：凭证或数据权限问题，如实入 FEED_ERROR 回执；
- 空 bars 页：当日无数据的合法厂商应答（MISSING_BAR 语义），不是崩溃；
- `NOT_A_DAILY_BAR`：盘中分钟戳防御，日线契约纵深防御——**未经实证不得放宽**；
- 429/5xx：disconnect-ELIGIBLE 传输错误（回执链留证）；重试与恢复以回执链
  为准，**不准人为制造断连**；
- `CONFLICT` / `AUTHORIZATION_REFUSED` / `BLOCKED_ENV`：门语义，如实记录；
- `EXIT_OK`（0）**不能**自动赋予 `API_VERIFIED` 或真实交易日——真实资格只能
  由 receipt↔journal 绑定的可审计回执链证明；合成/模拟事件**永不**入真实链；
- 状态查询用 `status`（exit 0=无完整性异常 ≠ 资格 PASS；6=完整性失败；
  7=完成未收尾；8=窗口已封存）。

## 5. 窗口完成条件与诚实边界

- E=PASS 最低门槛：**≥5 个全覆盖真实交易日**（`day_counting_rule:
  full_coverage`）+ ≥1 真实断连恢复 + ≥1 真实重复事件恢复 + 审计全过 +
  0 broker 订单——在此之前**不得声称 PASS**；
- 每个合法交易日一个只读会话；不回填、不冒充前向；
- 完成 ≥5 天后另行走 `collect --complete` + 独立复核流程（与本次单周期
  授权无关）；
- Paper 下单、M4、付费升级与本申请完全无关，永不附带。

## 6. 授权请求（明确、独立、范围限一次）

申请人（账户所有者）请求：**仅一次** `collect --once` 真实只读采集周期，
在上述已签署环境内执行；该授权不覆盖第二个周期、不覆盖 `--complete`、
不覆盖任何 Paper/Live 写路径、不关闭 `M3.5_GATE`。

批复栏（由授权人填写）：
- [ ] 批准（范围：一次 `collect --once`；环境：＿＿＿＿；日期：＿＿＿＿）
- [ ] 拒绝 / 补充条件：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿

**当前状态：`FIRST_REAL_ONCE_READY=NO`。本草案不是许可。**
