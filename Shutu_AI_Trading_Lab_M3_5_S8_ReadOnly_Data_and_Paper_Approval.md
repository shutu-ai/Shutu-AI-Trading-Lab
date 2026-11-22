# Shutu AI Trading Lab — M3.5 S8 真实行情 Shadow 与 Alpaca Paper 分离审批任务书

> Task ID: `M3.5-S8-READONLY-MARKET-DATA-GATE-20261122-001`  
> 编制日期：2026-11-22  
> 项目：`shutu-ai/Shutu-AI-Trading-Lab`  
> 编制依据：两份 v2.1 计划、`AGENTS.md`、M3.5 S0–S7 三轨验收及远端 GitHub Actions。  
> **此文件是待用户签发的审批草案，不是用户已经签批或执行授权的证据。**  
> 参照代码：`de39b40`（daemon 功能）→ `a06e0dc`（686 tests 双平台 CI run `45006808270`）→ `d85d105`（docs-only 后续提交）。  
> 执行前仍须检查 `origin/main`、本地 HEAD、最新 CI 与真实授权记录；绝不把文件存在当作签批。

## 0. 先讲清楚两种授权

| 审批项 | 实际行为 | 需要什么 | 资金/权限边界 | 本草案建议 |
|---|---|---|---|---|
| **② S8 真实行情来源** | 从第三方实时接收美国股票/ETF 的真实价格、时间戳、成交量等；用于不发单的 Shadow 观察 | 来源账户、条款/用途许可、真实可用的行情凭证、精确 Feed、数据质量/时钟与审计 | **只读数据**，不发任何 Paper/Live 订单；不解封全市场历史研究 | **优先单独批准，限定免费 IEX + 极小样本** |
| **③ Alpaca Paper 写** | 通过 `paper-api.alpaca.markets` 的模拟券商 API 下达/撤销模拟订单，读取订单、持仓、现金，验证 broker 回执与崩溃恢复 | Paper 账户及独立 Paper 凭证、Broker 适配器、OMS/风控审核及专门测试 | 不动真实资金，但有**模拟交易写权限**；与 ② 的只读目的不同 | **暂不批准**；先证明 ② 安全稳定 |

**重要**：Alpaca Paper API 的账户凭证与 Market Data API 的访问方式可能有关联；不能仅因代码只调用 GET/WS 就把一个本来具备 Paper 下单权的密钥称为“技术上只读”。若账户产品不能提供真正 Data-only scope，必须通过独立采集进程、目的地主机网络白名单、权限与进程隔离确保数据路径无法调用 Trading API；不得伪称密钥自身已被降权。

**区别历史数据**：Alpaca 免费 IEX Feed 的某几个 ETF 前向观察，不是 Sharadar 历史证券池/退市/PIT/企业行为完整数据源，不能用于取消 `BLOCKED_DATA(全市场研究)`；`M1 U-1`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=INCONCLUSIVE`、`R=NOT_STARTED`、`SEALED_NOT_MATERIALIZED` 均保持。

## 1. 建议本次用户签批文本（待用户明确发送，未发送则不生效）

> **我批准 M3.5-S8 的第一子阶段：只读真实行情 Shadow 验证（`S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE`）。** 仅允许在我亲自完成 Alpaca 账户创建、确认许可条款与本机安全配置凭证后，使用免费 Basic/IEX Feed，对最多 3 个美国股票或 ETF 代码进行只读实时到达事件采集、预注册 Shadow 预测锁定、后验评分与工程观测。初期仅用于工程前向窗口，不用于真实 Alpha 或全市场回测。费用预算为 **0 美元**，禁止任何自动订阅或付费升级。
>
> 同时批准先修复 M1 数据准入的 `VendorFacts U-1` 非法词表可误放行缺陷，并补充 fail-closed 测试；这项修复**不构成**对全市场历史研究 `BLOCKED_DATA` 的解除。
>
> **我不批准 Alpaca Paper 写、不批准任何 Live、不批准购买 Sharadar/付费行情、不批准 M4。** 禁止调用 `paper-api.alpaca.markets` 与 `api.alpaca.markets` 的下单/撤单接口；不得从自动化任务或 Codex 会话读取、打印、提交或上传密钥。不得在没有人工确认真实凭证已安全提供、许可和 Feed 可用之前尝试联网。M3.5 S8 完成后停在 `M3.5_GATE=USER_PENDING`，推送另行授权。

> **用户未发送以上（或等价）明确签批前：`S8_DATA_READ_ONLY=USER_PENDING`，Codex 只能审查/制定实现计划，不得连接真实数据源。**

## 2. 用户需要做的事（不交给 Codex 自动代办）

1. 使用官方 Alpaca 入口创建/登录账户：<https://app.alpaca.markets/account/login>；若无账户可从 <https://app.alpaca.markets/signup> 注册。选择 **Paper Trading / Paper Only**；不要因此开通 Live 或入金。
2. 在账户 Dashboard 查看 **Paper API Keys**，确认当前能合法获取 **IEX** 行情；官方文档表明 Paper Only 对 IEX 有访问资格。账号/功能是否适用于你，以你的账户界面及当期服务条款为准。
3. 首次只考虑 **Basic 免费 Feed**，`feed=iex`，不要选择付费 `sip`/Algo Trader Plus。可用 `SPY` 等 1–3 个高流动性 ETF 作**数据管道测试标的**，不代表投资建议。若不具备 IEX 读取权或许可条件不满足，记录 `BLOCKED_ACCESS`，不猜测、不绕过。
4. 凭证由用户在本机用安全凭证库、仅对采集子进程生效的 secret mount/注入方式配置；不要发送到 ChatGPT/Codex、不要写入 `.env` 进 Git 或 CI、不要出现在截图/日志里。若没有可限定为 Data-only 的令牌，绝不能把 Paper API key 当成天生只读；必须启用独立主机/进程级网络出口封锁交易域名。
5. 用户只告知执行代理**非秘密元信息**：`账户已就绪/未就绪`、`IEX Feed 可用/不可用`、`凭证已安全注入/未注入`、`许可个人研究使用是否确认`；不要复制真实 key 值。

## 3. Codex 开工前的硬门（S8-T0）

- 读取 `AGENTS.md`、两份 v2.1、`docs/reviews/M3.5-*`、`artifacts/evidence/M3.5/authorization.md`、`remote-ci.md`，验证最新 SHA 与 CI；确认 **S8 独立人工签批**真实存在。原 S0–S7 授权不继承到 S8。
- 核实 `S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE`，且人类已确认 Alpaca 个人研究用途许可、Feed、凭证安全存放。任一缺失：`AUTHORIZATION_PENDING/BLOCKED_ACCESS`，STOP，不尝试真实联网。
- 拒绝把账户可登录当作数据许可证全文验证；证据逐项标 `DOCUMENTED / API_VERIFIED / UNVERIFIED / BLOCKED_ACCESS`。
- 提交短 `T0 scope + architecture inventory`，列清 REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES 与每一新模块的唯一消费者；优先复用 M3.5 `ForwardJournal`、`SessionLock`、`Preregistration`、`AuditLog`、`B2ForwardRule` 和现有 M1 数据准入。

## 4. 先修 M1 U-1（S8-T1，必须 RED→GREEN）

- 在现有 `src/trading_lab/data/acceptance.py` 上最小修改 `VendorFacts` 非法枚举：`pit_availability` 仅允许 `{event_level,eod_only,none,unknown}`，历史成分/退市/CA 覆盖字段仅允许 `{yes,no,unknown}`；非法值**fail-closed**，不允许回退到“具备能力”。
- 必测已登记真实负例：`"PIT-ready (marketing claim)"`、`"partially"`、未知/大小写拼错、空字符串、None、缺字段；正例保持。测试不得弱化既有 M1 准入规则。
- 明确 S8 的**有限、实时前向只读**数据用途准入独立于全市场历史研究；新用途需要许可、Feed 品类、可得时间/接收时间、完整性、质量阈值，不可以直接调用 `historical_research_daily` 的 ACCEPT 或将其门禁禁用。
- `U-1 FIXED` 可以申请单独代码验收，但全市场研究继续 `BLOCKED_DATA`，Sharadar/PIT/退市缺口仍在。

## 5. S8-T2：真实源最小只读适配（不得混入离线核心）

- 首选官方 `wss://stream.data.alpaca.markets/v2/iex`，仅订阅 `bars` 或合法可用的 `trades`；允许必要的只读数据认证/协议请求，**网络出口白名单仅包含数据主机**；任何 Trading API 域名/IP、POST/DELETE 下单/撤单、账户订单端点均 fail-closed。
- 实时源适配器放在**单独采集进程/明确隔离模块**。当前 `apps/trading_daemon/` 的离线引擎坚持不 import 网络库、不读取 API key；采集进程只输出经验证的、来源可追踪的不可变数据事件。禁止以“让测试能通过”为由直接删除原有离线禁止网络规则。
- 原配置 `configs/forward_observation.yaml` 必须维持 `SYNTHETIC_REPLAY_ONLY` 不动。另建版本化 **真实前向预注册**（new `forward_protocol_id/hash`），在首次真实观测前冻结：供应商/Feed/IEX 单交易所限制、代码列表、数据使用权、样本期、交易日历/半日市、时间戳定义、B2 参数/代码身份、数据质量与丢包/回补策略、5 天门槛、成本/预算及其不可变审计。
- 对每条消息至少保留：`provider`,`feed`,`symbol`,`event_id`,`exchange_ts/event_time`,`received_at_utc`,`available_at_utc`,`payload_hash`,`protocol_hash`,`collector_code_hash`。严格先写入并锁预测，再让后续可得结果进入评分；禁止把回补旧 bar 当成当时已知。完整性/可得时间、断线重连、乱序/重复、DST、迟到 `updatedBars` 都须可复现负例；不可把当天已经发生的结果回填成“前向”。
- 凭证只由采集进程的最小权限入口读取，禁止记录 secret 内容。若服务对 Data-only scope 不支持，**网络与进程隔离必须有实际负例证明**，不能只依赖开发约定或 UI 下拉框。
- 不引入第二套 Shadow Journal、第二套 PIT 规则、OMS/Risk/BrokerPort 的依赖；不要提前开发 Paper 订单适配器、策略搜索、通用 Event Bus。

## 6. S8-T3：可观测真实前向窗口（至少 5 个市场会话）

- 真实首个市场会话开始采集前，必须完成预注册和代码身份冻结；记录行情真实到达时间而非单纯历史事件时间。每个会话的开始/结束、休市/半日市、事件数量、缺失量、延迟分位数、时钟偏差、重连次数、重复/修订拒绝数分母如实记录。
- 若真实数据合法到达、完整工程检查通过，但不足 5 个真实美股交易日，标 `E=PENDING_FORWARD_WINDOW / forward_window_status=ACCUMULATING`；若尚无合法行情/授权/有效时钟/环境则 `BLOCKED_ENV` 或 `BLOCKED_DATA`。绝不将 synthetic replay、历史补录、节假日计入真实观察天数。
- 至少 1 次受控断网/重启恢复与 1 次重复事件恢复；持久预测/评分不得改变。异常、断开与漏采要保留原始证据，不能删除失败事件制造完美窗口。
- 只允许 Shadow：**0 Paper orders，0 Live orders**；有真实到达观察不等于统计 Alpha，`S=INCONCLUSIVE / R=NOT_STARTED / BROKER_BEHAVIOR_UNVERIFIED` 始终保留。

## 7. S8-T4：工程验收和停止条件

- 保留当前 **686** 项基线和所有 M2/M3 1,080 故障注入、架构检查、密钥扫描、Paper/Live 纯度门；新增无授权/无许可/密钥泄漏/数据 Feed 不符/错账/迟到修订/真假时间混淆/中断重复/错误凭证/非法域名等 RED→GREEN 负例。Windows/Ubuntu 双平台 CI，且**CI 中不使用真实密钥**。
- 提供 `artifacts/evidence/M3.5/s8/{authorization-check.md,source-license-and-feed.md,u1-red-green.md,architecture-health.md,negative-tests.log,verification.log,real-forward-window-status.json,read-only-network-proof.md}` 和 `docs/reviews/M3.5-s8-readonly.md`；真实行情凭证和原始授权个人信息不得进入仓库。
- 无用户单独 push 批准不得 push；报告本地/远端真实状态，不能用离线 686 PASS 替代新 S8 代码的 CI。至少完成真正真实到达数据的前向观察后，才讨论完整 `E=PASS`。
- **S8 只读任务结束时 STOP**：`M3.5_S8_READONLY_GATED / PAPER_WRITE=NOT_AUTHORIZED / M4_START_APPROVAL_PENDING`，实际 E 由真实观察事实决定。不能代签 `M3.5_GATE=CLOSED` 或启动 M4。

## 8. ③ Alpaca Paper 写授权 — **未来草案，不在本次批准范围**

只有用户在 ② 真实行情已核实、数据侧隔离通过、独立审批后才允许启用。**下列文字仅供未来再次人工决定，当前没有效力。**

> 我另行批准 `ALPACA_PAPER_WRITE=APPROVED_LIMITED_TEST`，仅限 Paper 环境、指定模拟账户和 `https://paper-api.alpaca.markets`；必须使用独立 Paper keys，拒绝 Live keys/endpoint。由 OMS→BrokerEgress 唯一出口执行，不允许绕过已批准 RiskDecision、持久化意图、单次 Claim、全局 Kill Switch 和恢复对账；首轮只允许手动确认的极少量模拟订单（如每单模拟名义金额不超过 100 美元，最多 1 笔提交，须检查订单/成交/撤单/查询/持仓/现金的一致性），没有单独批准不得扩量、无人值守、重复发送。真实资金 0；任何 UNKNOWN 立即 HALT、先查单/对账再由操作人解锁；保留完整审计。禁止 `api.alpaca.markets` Live 及真实资金调用。完成专项后 STOP，等待新阶段门。

Paper 验证步骤（**未来才做**）：先 Paper credentials/account 只读验证 → Paper BrokerAdapter 的 API 语义对照（422/429/5xx/断线/重复 COID/部分成交/取消/回报乱序）→ 风控与账本一致性 → 限定一次模拟订单人工放行 → 回执/持仓/现金真实 Paper 对账 → 报告 `BROKER_BEHAVIOR_UNVERIFIED` 可解除的精确子集及仍未证明的行为。Paper 模拟成交不证明真实市场滑点/冲击、也绝不授权 Live。

## 9. 完成验收与用户决策表

| 事项 | 本文件默认 | 后续触发条件 |
|---|---|---|
| M3.5 S0–S7 | `REMOTE_VERIFIED` | 已有 CI `45006808270` 通过 |
| docs-only `d85d105` | 独立核验其 CI | 不能借原受测 SHA 代替新运行 |
| ② S8 数据只读 | `USER_PENDING`（建议批准） | 用户发送 §1 明确签批 + 自行配置账户/许可/密钥 |
| U-1 数据词表修复 | `USER_PENDING`（建议与 ② 一起批准） | 仅修复漏洞，不解除历史研究封锁 |
| ③ Paper 写 | **NOT_AUTHORIZED** | 另行签批 §8 且完成 Paper 真实工程前置 |
| 全市场历史研究 | **BLOCKED_DATA** | 另行订阅/许可证/API_VERIFIED + PIT/退市/质量准入 |
| M4 | **NOT_AUTHORIZED** | 新阶段单独批准 |
| Live | **PROHIBITED** | 未来满足 M9 Holdout、独立前向和独立审批链才可讨论 |

## 10. 给 Codex 的最小启动指令（仅用户正式签批后）

> 请先读本任务书和 M3.5 既有授权、三轨报告、代码、两份 v2.1 计划。校验 `S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE` 真实来自用户签批；未找到就停在 `AUTHORIZATION_PENDING`，不连真实网络。获批后先修复 U-1 且不解除 `BLOCKED_DATA`；再开展免费 Alpaca IEX **只读**前向 Shadow 源的预注册、隔离采集、身份/时间戳/许可/负例、真实到达窗口积累。用户自行完成账号和凭证安全注入，代理不得接触凭证明文。整个任务禁止任何 BrokerPort/Paper/Live 写、付费订阅、M4 和未经授权 push。达到授权范围后停人工门，提交按证据分层的三轨报告和验证日志。

---

**官方核对参考（2026-11-22 查询）：**

- Alpaca Paper Only：<https://docs.alpaca.markets/us/docs/paper-trading>
- Market Data 基础/付费限制：<https://docs.alpaca.markets/us/docs/about-market-data-api>
- 实时 IEX WebSocket：<https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data>
- Paper 与 Live Key/Host 隔离：<https://docs.alpaca.markets/us/v1.1/docs/authentication-1>
- Alpaca Dashboard：<https://app.alpaca.markets/account/login>
