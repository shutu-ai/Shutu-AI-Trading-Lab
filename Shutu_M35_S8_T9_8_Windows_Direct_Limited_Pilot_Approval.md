# Shutu AI Trading Lab — M3.5-S8 T9.8 Windows 直连受限只读试点正式批示

> 文件类型：Codex/操作者执行与验收批示；日期：2026-11-23
> 用户批示原话：**「对于当前个人开发的 Alpaca Paper/Shadow 阶段，不必过度建设隔离环境。可以在保留程序级安全、凭证保护和审计的前提下，正式批准一个风险范围明确的 Windows 直连试点。」**
> 基准：`b38d0c4da5202b3b3d55c5faa7e3bff0e2a26ff3`（T9.7 已远端验证；run `45042155239`，Ubuntu/Windows 各 960 passed）
> 作用域：个人开发、单人操作、单台 Windows 11 主机、单次人工触发的只读市场数据试点。**此文件不是任何真实交易/Paper 下单授权，也不等于 B-only 或首次 collect 的执行授权。**

## 0. 决议与状态词表

**批准：** `S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE`、`HOST_EGRESS_ISOLATION_EXCEPTION=APPROVED_WITH_SCOPE(WINDOWS_DIRECT_READ_ONLY_PILOT)`。

**保留真实事实：** `OPERATOR_PREFLIGHT_C=BLOCKED`（实际 F-2 失败）；`HOST_EGRESS_ISOLATION_UNVERIFIED`。不得把例外批准写成 `C=VERIFIED_BY_OPERATOR`、`F-2=PASS` 或“交易端点在网络层不可达”。

**本批准不变更的门：** `OPERATOR_PREFLIGHT_A=PENDING_OPERATOR`（直至账户所有者本人完成核验及签字）；`OPERATOR_PREFLIGHT_B=PENDING_OPERATOR`；`B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED`；`FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED`；`API_VERIFIED=NONE`；`REAL_FORWARD_DAYS=0`；`M3.5_GATE=USER_PENDING`；`PAPER_WRITE=NOT_AUTHORIZED`；`S=INCONCLUSIVE`；`R=NOT_STARTED`；`BROKER_BEHAVIOR_UNVERIFIED`；`BLOCKED_DATA=FULL_MARKET_HISTORY`；`M4=NOT_STARTED`。以上只在客观完成对应动作或获得另一份明确授权后变更。

## 1. 为什么允许例外、例外承担什么风险

以前 T9.7 的 C 项要求网络层 default-deny，且 F-1～F-8 全部通过。2026-11-23 用户实际 Windows WLAN 直连实测：`Get-NetFirewallProfile -PolicyStore ActiveStore` 三档 `DefaultOutboundAction=Allow`；`data.alpaca.markets:443=True`；`api.alpaca.markets:443=True`；`paper-api.alpaca.markets:443=True`。因此网络层的 F-2 **确实不成立**。这份批准接受这个缺口，仅针对单用户、非资金、只读 Shadow 试点，不宣称风险消失。

保留的核心威胁模型：Paper API Key 可能具有模拟交易权限；宿主其他进程、错误脚本、恶意软件或泄露的凭证仍可能访问交易端点。程序中的 `GuardedGetClient` GET-only/host allowlist/redirect forbid/无 broker 导入等机制是重要的纵深防御，但**不等于**宿主网络拦截或凭证只读。不得把试点结果扩展成生产部署、真实资金或 Paper 写能力证明。

**停止与升级原则：** 任何泄露迹象、交易域访问、意外 broker 订单、凭证异常、非预期出站、审计链失败、环境改变、程序版本漂移都必须停止试点；立即由账户所有者撤销/轮换可能泄露的 Key，进行本地取证。不得自动清除历史证据，也不得自动续采。

## 2. 明确许可范围（权限最小化）

| 维度 | 仅允许 | 明确禁止 |
|---|---|---|
| 账户 | 账户所有者亲自确认的 Paper Only、免费 Basic/IEX、个人只读工程用途 | 付费订阅、SIP、Live 账户、资金操作 |
| 主机 | 已检查的单台 Windows 11，WLAN 直连，单操作者、前台人工操作 | 共享服务/无人值守后台定时任务/远程 Agent 代操作 |
| 源 | `data.alpaca.markets:443`，预注册的只读日线 `GET /v2/stocks/{symbol}/bars?timeframe=1Day`，feed=`iex` | `api.alpaca.markets`、`paper-api.alpaca.markets`、HTTP POST/PUT/DELETE、交易 SDK/MCP |
| 标的 | 当前冻结版本中 `SPY`、`QQQ`，最多原批准的 3 个 | 扩大股票池、自动选股、策略参数自适应变更 |
| 执行 | 可准备环境、运行离线自测，未来在单独授权后执行一次 `collect --once` | 立即 collect；连续自动采集；`collect --complete`；Paper/Live 下单 |
| 凭证 | 账户所有者独自保管、短寿命独立进程级注入，结束立即清理 | 发往 ChatGPT/Codex/连接器/CI、终端历史、Git、日志、截图；打印值或派生值 |
| 证据 | 本地只读验证、journal/receipt/hash/失败事件、手动签署 | 抹除失败记录、合成冒充真实、在未实测前写 `API_VERIFIED` |

本机使用免费 Alpaca Basic/IEX，并不解除 Sharadar/全市场历史证券池 `BLOCKED_DATA`。最多只能证明指定 IEX 来源上的工程前向链，不应宣称全美股票真实市场价格完整性或统计盈利。

## 3. 操作者本地必要步骤（**不含真实 API 或凭证注入**）

### A. 账户与许可人工签署

本人登录 Alpaca 控制台并逐项核对：确实为 Paper Only 而不是 Live；API Key 对应 Paper；免费 Basic + IEX 权限；没有正在启用的付费订阅或自动扣费；当期条款允许个人非商业工程 Shadow 只读用途；不把 API Key 提供给其他程序或 Agent。以当前官方条款和账户实际页面为准，不能用 YAML 中 `operator_confirmed: true` 代替本人核验。

按仓库 `artifacts/evidence/M3.5/s8-operator-t9/operator-attestation-template.md` 在本机**仓库外**保存签署副本：只写非敏感账户类型、免费计划与权限判定、条款页面标题/核验日期、本人签名和非敏感证据索引。**不写账户号、Key ID、Secret、交易余额、截图原始内容到公开库。** A 全部通过才标 `A=VERIFIED_BY_OPERATOR`；否则 `A=BLOCKED/PENDING_OPERATOR`。

### C. 风险接受而非 C 项伪通过

将下面事实写入本地「风险接受记录」，本人签署，且与 A 独立：

- `ActiveStore` 出站 `Allow` 三档；实际 WLAN 互联网出口；WinHTTP 直连、用户 ProxyEnable=0、当前 PowerShell 无 HTTP(S)/ALL_PROXY 环境变量；仅未发现 IPv6 默认路由，不能声称全 IPv6 隔离。
- 三个 Alpaca TCP 443 域名当前均为 True；F-2 测试失败，传统 C 全矩阵不通过。选择**仅对此次受限 Windows 直连试点接受该风险**，而非 C `VERIFIED`。
- 记录仅非敏感的机器/网络环境标识、当前 commit、冻结预注册协议/身份 hash、时间、风险接受人；任何切换网络/VPN/代理或新启动方式触发暂停与再审。
- 原 C 项 F-1～F-8 测试证据不得虚构，原始 FAIL/UNVERIFIED 保留。

**不要求修改 Windows 全局防火墙**。不要为了通过 C 而把通用主机出站全部设置为 Block，免得影响工作环境。

### 状态卷与预注册确认

即使简化 C，也不简化历史完整性：指定**唯一**本地状态目录，权限仅给采集账户，加密（已有 BitLocker 或受控加密卷均可），跨日保留原始 receipts/journal/head/anchor；采集前后验证哈希和链；每日做独立离线备份；不得因关机/重建丢失 ≥5 日真实前向连续性。

由 Codex **只读**核对存在的冻结 S8 v2 实际文件、日线 REST 契约、IEX 限定、`GET` 守卫、身份/协议 hash，避免使用旧版 `bars/latest` 入口。检查与当期真实时钟的日历/半日表，不在盘中使用未完成日线。任何协议变更需新版本新证据，不在原证据上覆盖。

## 4. 后续两个授权点继续独立

**授权点 B-only：** A 人工签署与直连例外风险接受记录就绪，操作者将本批示与非敏感环境摘要一起提交单独 B-only 申请。只有用户再次明确授权后，操作者方可在不触网的受控子进程里验证两项凭证变量的**名称级可见性**、立即清除；不打印、不计算散列、不上传；B=`VERIFIED_BY_OPERATOR` 只表明安全注入流程被执行，不表明权限有效。

**授权点 First Real Once：** A 完成、直连风险接受已签、B-only 执行并本地签署、代码/CI 基线与运行环境未漂移、唯一持久状态卷已就绪后，另行提交一次性 `collect --once` 申请。只有用户明确批准**指定环境/日期/代码 SHA/只读源**，账户所有者才在本机手工执行一次。退出码 0 只证明运行程序完成，`API_VERIFIED` 必须由真实 API 回执与 journal 交叉绑定证明；若无完整日线，0 交易日亦可为诚实结果。`--complete`、自动重复采集及 Paper 写继续禁止。

**特别声明：** 本批示可作为旧 T9.7 中「必须 C=VERIFIED 才能申请 B-only / 首次 collect」之**特定范围政策例外**；门的语义应改成 `C_VERIFIED OR (DIRECT_PILOT_EXCEPTION_APPROVED AND local_risk_acceptance_signed AND A_verified)`，但绝不能修改 C 原值、跳过 B-only 独立授权、首次 once 独立授权或改写已冻结历史记录。

## 5. 给 Codex 的唯一工作范围：T9.8-GOVERNANCE-ONLY

基于 `b38d0c4` 与 T9/T9.7 既有文档，**只执行文档治理变更**，不修改生产交易代码、回测或行情网关，不增依赖、不跑网络探针、不触凭证、不执行 `collect`、不推送。

1. 先核验现有 `operator-action-card.md`、`operator-gate-reconciliation.md`、`b-only-authorization-request.md`、`first-real-once-approval-request.md`、`operator-preflight-pack.md` 的依赖规则和当前历史事实；只做必要的 T9.8 dated addendum，保留旧原文与原始 FAIL/UNVERIFIED，不伪造人工签署或原始 F-2 PASS。
2. 新增受限例外的明确审批记录：用户上述原话、批准范围、实际 F-2 失败证据、风险接受边界、终止/撤销机制、独立 B-only 与 First Once 两门。记录中任何签署栏应保留为操作者待填，用户原话不代替 A 核验。
3. 把 B-only / First Once 前置条件变成**可验证的替代条件**而不是删除它们：`A_verified AND ((C_verified AND environment_frozen) OR (direct_pilot_exception_approved AND local_risk_acceptance_signed AND environment_frozen))`。B-only 成功后才可申请 First Once。
4. 只运行无网络的静态交叉引用一致性、`check_architecture.py`、`scan_secrets.py`、`verify_live_blocked.py`、`git diff --check`。若运行全量测试将自改写既有证据，应先确认并如实记录；本 docs-only 轮可标 `NOT_RUN`。把结果及待人工动作写在新证据目录 `artifacts/evidence/M3.5/s8-operator-t9-8/`。
5. 本地提交后停门；不自动推送。新 docs-only 提交需单独 push 授权；不能把 T9.8 政策例外作为首次真实 collect 的授权。

## 6. 验收退出条件

- 批示已登记；与原始 T9.7 文档不冲突；无权限“悄悄升级”。
- 仍然真实记录 `C=BLOCKED` / F-2 失败、`HOST_EGRESS_ISOLATION_UNVERIFIED`；例外审批是独立字段，不替换 C 验收事实。
- 没有凭证值/派生标识被记录；没有真实 Alpaca 网络调用，`REAL_API_CALLS=0`。
- B-only、first collect、Paper/Live 写、M4 均未授权/未执行；`API_VERIFIED=NONE`、`REAL_FORWARD_DAYS=0`。
- 本人后续 A 核验、直连残余风险签署、环境与状态卷准备完成后，才申请 B-only。

**强制停止：** `T9_8_GOVERNANCE_LOCAL_READY_FOR_REVIEW / M3.5_GATE=USER_PENDING`。不得自动关闭 M3.5；不得启动实采或下单。
