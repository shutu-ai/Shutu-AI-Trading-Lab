# Windows 直连受限只读试点例外审批记录（windows-direct-pilot-approval-record — T9.8.2，LOCAL_ONLY，2026-11-23）

> 本文件登记 2026-11-23 用户对 Windows 直连受限试点的**政策例外批准**，并把它
> 与 T9.7 既有 A/B/C 阶段门协调一致。它**不是**任何真实交易/Paper 下单授权，
> 不等于 B-only 或首次 `collect` 的执行授权；签署栏全部留空，由操作者/账户
> 所有者本人日后在本地填写（签署副本不入仓库）。用户批示原话**不代替** A 项
> 的人工核验。
> 批示原件：仓库根 `Shutu_M35_S8_T9_8_Windows_Direct_Limited_Pilot_Approval.md`
> （2026-11-23，随本记录同一提交入库）；基线 `b38d0c4`（T9.7 已远端验证：
> GitHub Actions run `45042155239`，Ubuntu/Windows 各 960 passed）。

## 1. 决议状态词表（T9.8 §0 逐字）

**批准：**

```text
S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE
HOST_EGRESS_ISOLATION_EXCEPTION=APPROVED_WITH_SCOPE(WINDOWS_DIRECT_READ_ONLY_PILOT)
```

**保留的真实事实（不得改写）：**

- `OPERATOR_PREFLIGHT_C=BLOCKED`（2026-11-23 直连主机实测 F-2 失败——见 §3；
  C 三态枚举语义不变，仅状态按实测更新）；
- `HOST_EGRESS_ISOLATION_UNVERIFIED` 保持；
- **例外批准是独立字段，不替换 C 的验收事实**：不得把例外写成
  `C=VERIFIED_BY_OPERATOR`、`F-2=PASS` 或"交易端点在网络层不可达"。

**本批准不变更的门（仅在客观完成对应动作或获得另一份明确授权后变更）：**

```text
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED
FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
M4=NOT_STARTED
```

## 2. 用户批示原话（逐字，2026-11-23）

> 「对于当前个人开发的 Alpaca Paper/Shadow 阶段，不必过度建设隔离环境。
> 可以在保留程序级安全、凭证保护和审计的前提下，正式批准一个风险范围明确
> 的 Windows 直连试点。」

原话是**政策例外批准**：它批准的是"允许存在一个范围受限的直连试点"这一
政策，不是 A 项账户核验的事实声明，也不是任何执行动作的授权。

## 3. 实测 F-2 失败事实（2026-11-23，操作者本机；原始输出留在操作者本地）

- `Get-NetFirewallProfile -PolicyStore ActiveStore`：三档防火墙 Profile
  `DefaultOutboundAction=Allow`（域/专用/公用三档均允许出站）；
- 实际出口为 Windows WLAN 直连互联网；WinHTTP 直连、用户 `ProxyEnable=0`、
  当前 PowerShell 会话无 `HTTP(S)_PROXY`/`ALL_PROXY` 环境变量；
  仅未发现 IPv6 默认路由，**不能声称全 IPv6 隔离**；
- 三个 Alpaca 域名 TCP 443 实测可达（`True`）：
  `data.alpaca.markets`、`api.alpaca.markets`、`paper-api.alpaca.markets`；
- 因此网络层 **F-2 确实不成立**（交易域收到对端应答而非网络层失败），
  传统 C 全矩阵（F-1～F-8）在该直连主机上**不通过**；
- 以上为操作者本机只读盘点/连通性事实的**摘要**；命令原始输出、时间戳等
  完整证据由操作者在本地私有目录留档（依据 T9.7 action-card 的记录纪律），
  不入仓库。本记录不虚构任何未实测项。

**残余威胁模型（批准接受、不宣称消失）：** Paper API Key 可能具有模拟交易
权限；宿主其他进程、错误脚本、恶意软件或泄露的凭证仍可能访问交易端点。
`GuardedGetClient`（GET-only/host allowlist/redirect forbid/无 broker 导入）
是重要的**纵深防御**，但不等于宿主网络拦截，也不等于凭证只读。

## 4. 批准范围（权限最小化；细表见批示原件 §2）

仅允许：个人开发、单人操作、单台已检查 Windows 11 主机、WLAN 直连、
前台人工触发、**只读**市场数据试点——源限 `data.alpaca.markets:443` 的
预注册只读日线 `GET /v2/stocks/{symbol}/bars?timeframe=1Day`（feed=`iex`），
标的限冻结预注册 `SPY`、`QQQ`（最多原批准的 3 个），凭证由账户所有者独自
保管并短寿命进程级注入、用毕即清。

明确禁止：`api.alpaca.markets` / `paper-api.alpaca.markets` 访问、
HTTP POST/PUT/DELETE、交易 SDK/MCP、扩大股票池、连续自动采集、
`collect --complete`、Paper/Live 下单、付费订阅/SIP、共享主机无人值守/
远程代操作、凭证进入 ChatGPT/Codex/连接器/CI/终端历史/Git/日志/截图。

本机使用免费 Alpaca Basic/IEX **不解除** Sharadar/全市场历史证券池
`BLOCKED_DATA`；试点结果不得扩展为生产部署、真实资金或 Paper 写能力证明，
不应宣称全美股票真实市场价格完整性或统计盈利。

## 5. 风险接受边界（与 A 项独立；由账户所有者本人签署）

选择本例外 = 操作者**仅对此次受限 Windows 直连试点**接受 §3 残余风险，
而非 C `VERIFIED`。本地「风险接受记录」须包含（全部非敏感）：

- §3 的环境事实（ActiveStore 三档 Allow、WLAN 直连、无代理环境变量、
  IPv6 路径未证全隔离、三域名 443 可达、F-2 失败）；
- 接受范围声明：仅限本次直连受限试点，非 C `VERIFIED`；
- 仅非敏感的机器/网络环境标识、当前 commit、冻结预注册协议/身份 hash、
  时间、风险接受人；
- 原 C 项 F-1～F-8 测试证据不得虚构，原始 FAIL/UNVERIFIED 保留；
- **不要求也不进行** Windows 全局防火墙修改（不为通过 C 把通用出站改为
  Block）。

本地风险接受记录模板（空白，签署副本仅存本地）见本文件 §8。

## 6. 停止、暂停与撤销机制

**强制停止试点并升级的触发条件（任一即触发）：** 凭证泄露迹象、任何交易域
访问、意外 broker 订单、凭证异常、非预期出站、审计链失败、环境改变
（切换网络/VPN/代理/新启动方式）、程序版本漂移（代码/协议/预注册 hash
变化）。

**触发后的动作：** 立即停止试点；由账户所有者本人撤销/轮换可能泄露的
Key；本地取证；如实记录失败/异常事件（不自动清除历史证据、不自动续采）。

**例外本身的撤销：** 用户可随时以明示声明撤销本例外；撤销后 B-only /
First Once 的准入立即回落到 T9.7 原全矩阵路径（C=VERIFIED 才可申请），
已产生的诚实证据链保留原样。

## 7. 两个授权点继续独立（T9.8 §4；前置条件变为可验证的替代条件，不删除）

**门语义（T9.8 §5.3 逐字，两处申请通用）：**

```text
A_verified AND (
    (C_verified AND environment_frozen)
    OR (direct_pilot_exception_approved
        AND local_risk_acceptance_signed
        AND environment_frozen)
)
```

- `A_verified`：账户所有者本人完成 §A1–A5 核验并本地签署
  （attestation 模板 §A）；
- `environment_frozen`：`operator-gate-reconciliation.md` §5 登记表填写
  完成 + §6 持久状态卷落实（独占/权限最小化/加密/跨日字节不覆盖/备份
  摘要/重建先验证再采集）；
- `direct_pilot_exception_approved`：本记录（`APPROVED_WITH_SCOPE`）；
- `local_risk_acceptance_signed`：§8 模板的本人签署副本（本地）；
- `C_verified`：F-1～F-8 全矩阵 `VERIFIED_BY_OPERATOR`（原路径，保持
  可用，不被废除）。

**授权点 1（B-only 无网络注入核验）：** 前置门满足后，操作者将本批示与
非敏感环境摘要一起提交**单独** B-only 申请；仅用户再次明确授权后，账户
所有者才可在不触网受控子进程中验证两项凭证变量的**名称级可见性**、立即
清除；不打印、不计算散列、不上传。`B=VERIFIED_BY_OPERATOR` 只表明安全
注入流程被执行，不表明凭证权限有效。

**授权点 2（First Real Once）：** A 完成、直连风险接受已签、B-only 执行
并本地签署、代码/CI 基线与运行环境未漂移、唯一持久状态卷就绪后，**另行**
提交一次性 `collect --once` 申请；仅用户明确批准**指定环境/日期/代码 SHA/
只读源**后由账户所有者本机手工执行一次。退出码 0 只证明运行程序完成；
`API_VERIFIED` 必须由真实 API 回执与 journal 交叉绑定证明；无完整日线时
0 交易日亦可为诚实结果。`--complete`、自动重复采集、Paper 写继续禁止。

**顺序硬约束不变：** B-only 成功（本人签署）后才可申请 First Once；两个
授权互相独立，任一批准不自动延伸到下一步。

## 8. 操作者待办与本地签署栏（全部空白，执行时由本人填写）

### 8.1 A 项账户与许可核验（依据 attestation §A1–A5，本例外不降低任何子项）

- [ ] A1 Paper Only；A2 当期条款允许个人只读工程用途；A3 无付费订阅；
      A4 控制台权限与 IEX/Basic 一致；A5 与冻结预注册一致
- A 判定：＿＿＿＿（VERIFIED_BY_OPERATOR / BLOCKED / PENDING_OPERATOR）
- 核验日期：＿＿＿＿-＿＿＿-＿＿＿＿　本地签署副本索引：＿＿＿＿

### 8.2 直连残余风险接受记录（模板——复制到仓库外本地填写签署，不入仓库）

```text
直连受限试点残余风险接受记录（本地私有副本）
接受人（账户所有者）：＿＿＿＿＿＿＿＿
接受日期(UTC)：＿＿＿＿-＿＿＿-＿＿＿＿ ＿＿＿:＿＿＿
机器/网络非敏感标识：Windows 版本 ＿＿＿＿；网络适配器 ＿＿＿＿；
  网关/DNS 来源 ＿＿＿＿；WLAN 直连（无授权代理）；IPv6 默认路由：未发现
代码基线 commit：b38d0c4da5202b3b3d55c5faa7e3bff0e2a26ff3
冻结预注册协议/身份 hash：＿＿＿＿＿＿＿＿（非敏感摘要）
已阅读并接受的事实：
  [ ] ActiveStore 三档 DefaultOutboundAction=Allow；F-2 实测失败
      （data/api/paper-api.alpaca.markets:443 均 True）
  [ ] HOST_EGRESS_ISOLATION_UNVERIFIED 保持；本接受仅限本次直连受限试点
  [ ] 触发 §6 任一停止条件即停；Key 撤销/轮换由本人执行
例外引用：S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE（2026-11-23）
签署：＿＿＿＿＿＿＿＿
```

### 8.3 后续待办（顺序，全部人工）

1. 本人完成 §8.1 A 核验并本地签署；
2. 本人完成 §8.2 风险接受记录并本地签署；
3. 固定环境身份（reconciliation §5 登记表）+ 落实持久状态卷（§6 要求，
   含 BitLocker/受控加密、跨日 receipts/journal/head/anchor、每日离线
   备份与哈希校验）；
4. 之后才可提交 B-only 申请（随附本批示 + 非敏感环境摘要）；
5. B-only 批准、执行、签署完成后，才可另行提交 First Once 申请。

## 9. 本轮边界重申（T9.8 治理轮）

本轮（T9.8-GOVERNANCE-ONLY）零生产代码变更、零依赖新增、零网络探针、
零 `collect`、零推送：`REAL_API_CALLS=0`、`BROKER_ORDERS=0`；未注入、
未校验、未使用任何凭证。**披露一处偏差**：治理会话在盘点未跟踪文件时，
接触到仓库根本地笔记文件（内含 Alpaca Paper Key ID/Secret 明文）的头部
内容——未转录、未入库、未外发；按本记录 §6 停止原则，该 Key 的轮换已
列入操作者待办（详见同目录 `consistency-check.md` §安全卫生发现）。
本记录全部为文档；任何"已批准"字样均指**政策例外批准**，不构成执行授权。
