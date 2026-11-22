# Shutu AI Trading Lab — M3.5 S8 T9.7 操作者阶段门消歧与准入交接（Codex 执行任务）

**任务 ID**：`M35-S8-T9-7-OPERATOR-GATE-RECONCILIATION-R1-20261122`  
**代码基线**：`19ac01430823c07c94066547a45c6c56f8beff48`  
**验收依据**：GitHub Actions run [`45038488439`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45038488439)，head 与基线一致，ubuntu/windows **960/960 passed**；T9 仅文档/证据变更。  
**授权范围**：**本地、离线、文档级消歧与核对**。若按既有任务模式进行本地提交，仅提交本轮新增/必要修改的说明文件，**禁止 push**。  
**任务出口**：`T9_7_DOC_GATE=LOCAL_READY_FOR_REVIEW` 或 `HOLD`；`M3.5_GATE=USER_PENDING` 不变。

> **最高优先级禁令**：Codex 不得读取、索要、显示、复制或注入任何真实凭证；不得向 Alpaca 或其他外网服务发起请求，**包括无凭证网络探针**；不得修改防火墙/代理/DNS/证书/路由；不得调用 `collect` / `collect --complete`；不得下 Paper 或 Live 订单；不得启动 M4；不得推送、关闭 M3.5 或替账户所有者签署。操作者未来的 A/C 实测以及 B 凭证操作为**人工独立行动**，不是本任务的一部分。

## T9.7.0 — STOP/GO 基线与范围

1. 仅读仓库：`git status --short`、`git rev-parse HEAD`、`git rev-parse origin/main`、相关 `git log`；记录提交指向、待处理未跟踪文件。仅当 `HEAD=origin/main=19ac014...` 且异常改动可解释时继续。
2. 阅读并引用：
   - `artifacts/evidence/M3.5/s8-operator-t9/operator-environment-plan.md`
   - `artifacts/evidence/M3.5/s8-operator-t9/operator-preflight-pack.md`
   - `artifacts/evidence/M3.5/s8-operator-t9/operator-attestation-template.md`
   - `artifacts/evidence/M3.5/s8-operator-t9/first-real-once-approval-request.md`
   - `artifacts/evidence/M3.5/s8-contract-r2/operator-readiness.md`
   - `configs/forward_observation_s8_real_v2.yaml`（**只读**）
3. 若 `origin/main` 已漂移，或任何真实证据、冻结协议及生产代码出现未预期变化：停止并报告 `HOLD`；不覆盖、不清理未知文件。

## T9.7.1 — 修正 B 项阶段门死锁（P1，纯文档）

**问题**：现有文档一方面把 **B=VERIFIED_BY_OPERATOR** 绑定到“实际进程级注入”，另一方面把“注入”限定于“未来单周期采集获得授权之后”；但单周期授权又以前置 **A/B/C 全 VERIFIED** 为条件。这是流程依赖环。

**修正方法：严格分离两个独立授权，不降低任何门槛**：

- `B_PLAN_READY`：操作者已理解、核对并签署凭证进程级注入与清理方案；这是**准备状态**，**不是** `B=VERIFIED_BY_OPERATOR`。如旧状态枚举只支持三态，B 仍记录 `PENDING_OPERATOR`，`B_PLAN_READY` 仅作为独立准备事实，绝不把 `PREPARED` 冒充 VERIFIED。
- **独立授权 1 — B-only 无网络凭证注入验证**：在 A 本人验证通过、C 目标环境全部验证通过、环境身份固定后，单独向用户申请“仅在受控子进程执行一次凭证注入/可见性检查、立即销毁，不访问任何网络/API/下单”的明确批准。**未批准前禁止执行**。实际执行及签署只由账户所有者本人完成，输出只能包含无敏感信息的检查结果、时间、环境标识、清理结果，**绝不能包含凭证值、长度、前后缀、散列或可回推标识**。
- B-only 本人核验后，B 才可以按本地签署结果标为 `VERIFIED_BY_OPERATOR`。即使已确认环境变量存在，也**不得**认定 Alpaca 授权有效、`API_VERIFIED` 已升级或任何 API 成功。
- **独立授权 2 — 首次真实行情单周期**：仅当 A/B/C 的**人工签署记录实际成立**、安全环境未变化、CI 基线一致时，再发出另一次明确申请；范围仅 `collect --once` **一次**、指定环境、指定日期、指定只读数据端点。B-only 批准**绝不**自动授权此步骤。

交付一个简洁的决策图或顺序表，确保所有文档对依赖条件的描述不互相矛盾。修订旧文件时采用最小改动和标注补充日期；不抹除 T9 历史成文事实。

## T9.7.2 — 环境、出口和状态持久性检查表（不执行网络）

1. 固定**一个**候选采集环境（仅方案，不自动选定）：独立 VM/容器或严格 ACL 的独立代理。明确 `target_environment_id`、`network_mode`、`proxy_mode`、DNS、IPv4/IPv6、网络层 default-deny 策略以及单实例使用承诺的**待填空白字段**。
2. 指出 **VM/容器销毁与多交易日 receipt/journal 链持续存在**之间的冲突。要求操作者设计安全的持久状态卷：独占、权限最小化、加密/受保护、避免与模拟状态共用、跨日原始字节不被覆盖，保留备份/校验摘要；所有操作须保持既有协议身份与状态目录连续性。环境复建必须保留并验证两条链、状态快照及其路径绑定；不得凭复制的摘要冒充验证通过。
3. C 项 F-1～F-8 继续只由操作者本人**无凭证**执行；严格区分：
   - 允许域 HTTPS 确实到达 `data.alpaca.markets`，应核实证书/目标，不能把代理 407、劫持页、DNS 错配或重定向错误当成成功；
   - `api.alpaca.markets`、`paper-api.alpaca.markets` 和非白名单域必须**网络层失败**；收到 401/403 不是通过；
   - 代理/CONNECT、WinINET/WinHTTP、DNS、IPv4/IPv6、同型子进程适用路径必须有真实证据。仅对实际**将用于采集的网络环境**验收，切换后重验；
   - 无法证明任一必需项就维持 `HOST_EGRESS_ISOLATION_UNVERIFIED`。
4. 不把应用层 `GuardedGetClient` 的 GET-only 与禁止交易 host，等同于凭证原生只读或主机级安全隔离；Alpaca 账户/市场数据权限以操作者核验的实际条款与控制台状态为准。
5. T8 残余 TOCTOU 为**运行规程缓解**（单操作者、单实例、唯一状态目录），不声称跨进程原子互斥。任何疑似并发执行、状态链漂移或采集进程异常均停止进一步采集，人工复核。

## T9.7.3 — 人工交接资料（全部空白，不代签）

输出（可为附录或新文件）：

- `operator-action-card.md`：操作者依次完成 A→C→申请 B-only→人工验证 B→申请首次 collect-once 的步骤，每步记录状态、时间和非敏感证据索引；**不写任何可自动执行真实调用的脚本**。
- `b-only-authorization-request.md`：**草案**，只申请本机子进程级注入可见性、清除与证据记录，无网络/API/采集/订单，签批栏空白；不得含凭证值或要求操作者复制给 AI。
- `first-real-once-approval-request.md`：必要时修订现有草案，增加 B-only 前置签批、环境身份及跨日状态连续性检查。草案不是授权；仍要未来再次明确审批。

以上为资料准备，**不意味着 A/B/C 验证通过**；正式签署副本只能由本人放在仓库外的私有存储中，不得由 Agent 收取。

## T9.7.4 — 离线核对，不制造新历史证据

1. 对文档交叉引用、已冻结协议名称、符号 `SPY/QQQ`、`feed=iex`、`timeframe=1Day`、`poll_window_et=[16:05,17:30] ET`、状态枚举和出口代码做静态一致性检查。
2. `python scripts/check_architecture.py`、`python scripts/scan_secrets.py`、`python scripts/verify_live_blocked.py`、`git diff --check`；如只是文档改动，不强制重跑 960 项完整测试和 M2 故障矩阵，避免自重写旧证据。确有代码修改才需 STOP 并申请新的代码整改范围，而不是擅自扩大授权。
3. 所有新资料只存本轮独立证据目录；**禁止覆盖/修改** `r1/r2/r3` 旧验收日志、现有冻结预注册、真实状态目录。既有 T9 未跟踪 `ci-run-45038488439.log` 仅可只读核对来源，除明确获得文件处置授权外**不删除、不移动、不入库**。

## T9.7.5 — 交付、状态、停止

本轮在**允许文档本地提交**的前提下，生成新的最小 docs-only 本地提交，逐项列出 changed files、`git diff --check`、工具退出码、实际 SHA。**不 push**；若存在未知修改，停止并报告 HOLD。

必须输出以下状态（不得因准备文件或 CI 全绿而擅自升级）：

```text
T9_CI=REMOTE_VERIFIED_WITH_SCOPE (run 45038488439, head 19ac014; 960/960)
T9_7_DOC_GATE=LOCAL_READY_FOR_REVIEW or HOLD
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
B_PLAN_READY=UNVERIFIED_OR_PENDING_OPERATOR
B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED
HOST_EGRESS_ISOLATION_UNVERIFIED
FIRST_REAL_ONCE_READY=NO
FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
REAL_API_CALLS=0
BROKER_ORDERS=0
M4=NOT_STARTED
PUSH=NOT_AUTHORIZED
```

**最终停门**：

- 下一次决定 A：是否批准**仅文档**的本地提交推送（如产生提交，需单独批准）；
- 下一次决定 B：由账户所有者在选定的安全环境中亲自完成 A、C（禁止 Codex 代做）；
- 下一次决定 C：获得单独 B-only 注入核验授权，再由操作者本人完成并私下签署；
- 下一次决定 D：A/B/C 均真实通过后，**再单独申请**首次 `collect --once`，不自动执行。

这不是 T10 工程整改；除非本轮产生实证性阻塞缺陷，否则结束离线开发阶段。
