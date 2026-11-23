# Shutu AI Trading Lab — M3.5-S8 操作者实机核验 A/C 行动书

**目标环境**：日常 Windows 11 主机；直连互联网（无授权代理出口）；**本次只核验 A 与 C**。
**基线**：`b38d0c4da5202b3b3d55c5faa7e3bff0e2a26ff3`，GitHub Actions `45042155239`，Ubuntu/Windows 各 `960 passed`。
**状态**：`A=PENDING_OPERATOR / C=PENDING_OPERATOR / HOST_EGRESS_ISOLATION_UNVERIFIED / B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED / FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED`。

> **禁止事项**：本行动书不授权凭证注入、网络 API 身份验证、真实 `collect`、Paper/Live 下单、自动提交/推送。不要向 Codex、ChatGPT、终端历史、日志或仓库提供 API Key ID/Secret Key。只操作非敏感环境数据。

## 0. Windows 共用主机的关键限制

Windows Defender Firewall 默认允许普通出站连接。仅创建一条允许 `data.alpaca.markets` 的规则，不会自动阻止其它域名。仅对 Python 加入“封锁全部”规则，可能连本应允许的主机也封锁，无法靠普通的 `Allow` 规则覆盖 `Block`。Windows 的 FQDN dynamic keyword 规则是 DNS 解析后的 IP 条件，不是天然的 TLS SNI/Host 访问控制；共享 IP、DoH、代理、IPv6 等情况须另证。

在日常主机上，符合 T9.7 的 C 项需要**实际落实并证明** `default deny`、只放行市场数据域 `data.alpaca.markets:443`、其它域/交易域在网络层失败、绕行路径同样被拒。若无法在不影响日常应用的条件下做到，**C=BLOCKED/UNVERIFIED；不得继续 B-only**。优先考虑用户实际操作环境下的隔离 Windows 用户/沙箱/VM 或经严格 ACL 的独立安全出口（改变所选环境意味着重新核验），不要擅自更改整个主机的默认出站策略。

## 1. A：账户与许可（本人、浏览器、不要拷贝凭证）

1. **Paper Only**：本人登录 Alpaca Dashboard，确认 API Key 来自 **Paper 账户**，而非 Live；无实盘账户资金操作授权；记录非敏感的账户类型（不要记录账户 ID、Key ID、Secret）。
2. **套餐**：确认当前免费 **Basic**、股票行情来源 **IEX**，没有 SIP/付费升级或自动续费；记录查看日期及本地截图索引（截图必须遮蔽账户/个人敏感信息）。
3. **用途**：本人阅读当前 Alpaca 官方数据/API 条款，确认个人、只读、非再分发、非商用或本项目实际用途可被条款许可。官网：`https://docs.alpaca.markets/us/docs/about-market-data-api`、`https://docs.alpaca.markets/us/docs/paper-trading`、`https://docs.alpaca.markets/us/docs/market-data-faq`。如条款不明确，A 保留 PENDING 或 BLOCKED，不擅自认定许可。
4. **凭证安全认识**：即使 API Key 来自 Paper 账户，也可能具备模拟交易操作权；绝不能因程序仅使用 GET 就把密钥标成“原生只读”。只核对 **Key ID 和 Secret Key 均已安全留存**这一事实，不打印/复制/注入其值。若存在额外的权限管理选项，仅以实际账户显示为准，不能将 Broker API 产品的 Access Controls 当作个人 Trading API 的已证能力。
5. **签署**：按仓库 `artifacts/evidence/M3.5/s8-operator-t9/operator-attestation-template.md` 的 §A1–A5，在**本地私有副本**填写 `A=VERIFIED_BY_OPERATOR` / `BLOCKED` / `PENDING_OPERATOR`、核验日期、条款版本/URL、非敏感本地证据索引并本人签名。仓库内空白模板不得被覆盖。

## 2. C：准备与只读盘点（不得改变网络配置）

操作者先固定“唯一目标主机/网络”候选身份：Windows 版本、网络适配器、网关、DNS 来源、IPv4/IPv6 状态、是否 VPN/代理、采集用 Python 可执行文件路径、独立 state dir 位置、持久卷与备份计划。命令均不读取 Alpaca 凭证。

在**自己的非仓库目录**创建证据文件夹，例如 `%LOCALAPPDATA%\Shutu-S8-Operator-Audit\<date>\`（先人工确认该目录为私有目录）。在 PowerShell 7 或 Windows PowerShell 5.1 中只读运行：

```powershell
[Environment]::OSVersion.Version.ToString()
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
Get-NetIPInterface | Select-Object InterfaceAlias, AddressFamily, ConnectionState
Get-NetRoute -AddressFamily IPv6 -DestinationPrefix '::/0' -ErrorAction SilentlyContinue
Get-DnsClientServerAddress | Select-Object InterfaceAlias, AddressFamily, ServerAddresses
Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultOutboundAction
netsh winhttp show proxy
# 只列变量名，不输出值（代理地址里可能包含用户名/密码）
Get-ChildItem Env: | Where-Object Name -Match '^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$' | Select-Object -ExpandProperty Name
# 仅读取系统代理配置是否启用/是否存在 PAC，不输出任何代理 URL 或账户信息
$p = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
[pscustomobject]@{ProxyEnabled=$p.ProxyEnable; PACConfigured=[bool]$p.AutoConfigURL}
```

**注意**：这些命令只能盘点。`DefaultOutboundAction=Allow` 不能让 C 通过。禁止在日常工作主机直接执行未经单独计划与回滚验证的 `Set-NetFirewallProfile -DefaultOutboundAction Block`；此类全局变更会切断办公/家庭网络及其它进程，且凭此仍不能证明 SNI/DNS/代理等出口边界。

## 3. C：F-1～F-8 可证伪实测矩阵（全部无凭证）

**先决条件**：操作者先独立落实目标网络的 **default-deny**、目标主机定向 allowlist 和安全回滚；在配置尚未实现时，下面的测试只能用来报告缺口（例如禁行域可达），不能写成通过。命令中的 `curl.exe` 必须使用 Windows 原生可执行文件；`--noproxy "*"` 强制直接连接以检验直连路径；不要使用 `-k`（忽略证书）或 `-L`（跟随重定向）。建议避免将整段 curl 输出上传至任何聊天/仓库，仅保留经过脱敏的本地结果摘要。

### F-1：允许域真实 TLS 响应

```powershell
curl.exe --noproxy "*" --proto "=https" --max-redirs 0 -v --connect-timeout 5 --max-time 15 --output NUL 'https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day&feed=iex'
```

**PASS**：对正确 `data.alpaca.markets` 完成 TLS 主机名/证书链校验并得到目标端 HTTP 响应；无凭证时 401/403/其它正常 HTTP 错误码也可，**只用于证明网络链路**，不证明行情授权。**FAIL**：407 代理认证、登录门户、错误证书、重定向、DNS 劫持/错误主机、超时。不能只看 curl 退出码。若允许域直接返回 200 也不等于 API_VERIFIED（缺签批/回执链）。

### F-2：两个交易域在网络层无法连接

```powershell
curl.exe --noproxy "*" -v --connect-timeout 5 --max-time 12 --output NUL https://api.alpaca.markets/v2/account
curl.exe --noproxy "*" -v --connect-timeout 5 --max-time 12 --output NUL https://paper-api.alpaca.markets/v2/account
```

**PASS**：连接超时、网络层拒绝或 DNS 策略拒绝，目标 API 无 HTTP 回应。**FAIL**：收到任何 HTTP 响应，**包括 401/403**。这些测试不带凭证也不发订单。

### F-3：非白名单域在网络层拒绝

```powershell
curl.exe --noproxy "*" -v --connect-timeout 5 --max-time 12 --output NUL https://example.com/
curl.exe --noproxy "*" -v --connect-timeout 5 --max-time 12 --output NUL https://www.wikipedia.org/
```

**PASS**：两者网络层不可达（没有任何 HTTP 响应）。**FAIL**：任一站点能回复 HTTP，无论 200/403/404，均说明网络出口过宽。

### F-4：IPv6 无旁路

```powershell
Get-NetIPInterface -AddressFamily IPv6 | Select-Object InterfaceAlias, ConnectionState
Get-NetRoute -AddressFamily IPv6 -DestinationPrefix '::/0' -ErrorAction SilentlyContinue
Resolve-DnsName api.alpaca.markets -Type AAAA -ErrorAction SilentlyContinue
curl.exe -6 --noproxy "*" -v --connect-timeout 5 --max-time 12 --output NUL https://api.alpaca.markets/v2/account
```

**PASS**：如具有 IPv6 外联路径，必须实测交易域的 IPv6 网络层拒绝；如**无可用 IPv6 默认路由/外联**，记录无 IPv6 路径的路由与接口证据。**不能**只凭目标没有 AAAA 记录或一次 curl DNS 失败就判定 IPv6 已被阻断。

### F-5：直连与代理/CONNECT 绕行路径

检查 §2 的 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY` **变量名是否存在**、WinHTTP、WinINET/PAC、VPN/透明代理可能性；在固定的“直连”环境中，必须证明采集进程与所有会被它采用的代理路径均被禁用或受同等级 ACL 限制。未经授权，不可把“自动代理可绕过规则”标为已核验。若实际经过代理或 PAC，则该环境不再是“直连”，应冻结新的环境标识并按代理方案重验 F-1～F-8。

### F-6：采集器同型子进程复验

在**不注入任何 Alpaca 凭证**的 `powershell.exe -NoProfile` / `pwsh -NoProfile` 子进程内，从相同用户/解释器/网络上下文分别复跑 F-1～F-4（可以直接把上面的单行 curl 命令放进新开子进程交互窗口）；记录子进程的进程号和脱敏结果摘要。**PASS**：与父进程同样允许/拒绝；任一子进程穿透则 FAIL。必要时还要覆盖 Python 的 urllib 子进程，排除其自动读取系统代理设置造成的绕行。

### F-7：DNS 路径受控

```powershell
Get-DnsClientServerAddress | Select-Object InterfaceAlias, AddressFamily, ServerAddresses
Resolve-DnsName data.alpaca.markets -Type A -ErrorAction SilentlyContinue
Resolve-DnsName data.alpaca.markets -Type AAAA -ErrorAction SilentlyContinue
Resolve-DnsName api.alpaca.markets -Type A -ErrorAction SilentlyContinue
```

**PASS**：实际 DNS 服务器与网络政策一致、IPv4/IPv6 地址族与出口规则一致，且非白名单域即便被解析也不能通过连接；如要求“DNS 查询本身白名单限制”，须另提供可证实的 DNS ACL 证据。**FAIL**：DNS/DoH/代理可绕过已签策略、错误/劫持解析、非白名单域能够建立网络连接。

### F-8：独立、本地、非敏感、可审计的签署

每项 F-1～F-7 记录 `UTC 日期时间 | 命令或检查类型 | 环境标识 | 可否实际连通 | 证书/域名验证结果 | 拒绝层级（DNS/TCP/TLS/HTTP） | PASS/FAIL/UNVERIFIED | 本地证据索引`。汇总页由账户所有者按 `operator-attestation-template.md` 的 §C-1～C-8 手工签署；**签署版永久留在本地、禁止入库或发给 Agent**。

## 4. 固定环境与五日状态卷（C 的必要补充）

只有 F-1～F-8 全满足之后才能固定目标环境：唯一 `target_environment_id`、无混用的私有状态目录、文件权限最小化、BitLocker 等磁盘加密、跨日不覆盖 receipt/journal/head/anchor、每日独立备份与 SHA-256 摘要、重启先链校验再采集、单操作者单实例、禁止同时执行另一个 CLI。环境/代理/网卡/策略变更则 C 失效并重验。

## 5. 停止门与授权分界

- 仅 **A 与 C 在本地均人工签署为 VERIFIED_BY_OPERATOR** 且固定环境身份/状态卷满足要求之后，才能**提出申请** `B_ONLY_INJECTION_AUTHORIZATION`；不能直接执行 B。
- B-only 必须另获用户明确一次性批准，才可由账户所有者本人在无网络子进程中做“注入→变量名存在性→立即清除”，且绝不触网。拥有 Key ID/Secret Key 不等于 B 已完成。
- B 完成人工签署后，才可另行申请 `FIRST_REAL_ONCE_AUTHORIZATION`；无授权前禁止 `collect --once`。任何通过结果都不能自动转 `API_VERIFIED`、`REAL_FORWARD_DAYS>0` 或 `PAPER_WRITE=AUTHORIZED`。
- 如果因为日常 Windows 主机共享网络需求而不能取得 C=VERIFIED_BY_OPERATOR，请如实记录 `HOST_EGRESS_ISOLATION_UNVERIFIED`，停止在 C，后续再决定是否更换更适合的独立运行环境；**不可降低 F-1～F-8 判据**。

**官方依据**：
- Alpaca Paper Trading：https://docs.alpaca.markets/us/docs/paper-trading
- Alpaca Market Data：https://docs.alpaca.markets/us/docs/about-market-data-api
- Windows Firewall default outbound：https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/configure
- Windows Firewall FQDN dynamic keywords：https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/dynamic-keywords
- 项目 T9.7 操作卡：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/blob/main/artifacts/evidence/M3.5/s8-operator-t9-7/operator-action-card.md

## 6. T9.8 附录：直连受限试点例外的门协调（2026-11-23，§0–§5 原文保持不变）

> 依据：用户批示（`Shutu_M35_S8_T9_8_Windows_Direct_Limited_Pilot_Approval.md`，
> 同日入库）；例外审批记录
> `artifacts/evidence/M3.5/s8-operator-t9-8/windows-direct-pilot-approval-record.md`。
> 批准：`S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE`、
> `HOST_EGRESS_ISOLATION_EXCEPTION=APPROVED_WITH_SCOPE(WINDOWS_DIRECT_READ_ONLY_PILOT)`。

1. **实测事实更新（2026-11-23）**：本行动书头部"C=PENDING_OPERATOR"为
   成文时点记录；当日直连主机实测 F-2 **失败**（三个 Alpaca 域名 443 可达、
   ActiveStore 三档出站 Allow），现势状态
   `OPERATOR_PREFLIGHT_C=BLOCKED`（全矩阵路径）、
   `HOST_EGRESS_ISOLATION_UNVERIFIED` 保持。
2. **§5"停止在 C"的例外分支**：§5 第 5 条（不能取得 C=VERIFIED 即停止、
   不可降低 F-1～F-8 判据）对**全矩阵路径**继续成立、判据零降低；经
   T9.8 批示，**仅限批示定义的直连受限只读试点**新增可验证替代分支：
   `A_verified AND ((C_verified AND environment_frozen) OR
   (direct_pilot_exception_approved AND local_risk_acceptance_signed AND
   environment_frozen))`。例外分支下 B-only 申请以"本人签署的本地直连
   残余风险接受记录"替代 C 腿（approval-record §8.2 模板），不写成
   `C=VERIFIED`、不虚构 F-1～F-8 证据、不要求修改 Windows 全局防火墙。
3. **本行动书 §1–§4 的角色**：§1（A 项核验）与 §3/§4（F-1～F-8 矩阵、
   环境与状态卷）保持有效——§3/§4 仍是全矩阵路径与环境切换重验的判据；
   直连试点依批示 §3 执行状态卷与预注册确认（即使简化 C，不简化历史
   完整性）。F-2 在直连主机的实测结果按 FAIL 如实记录，不得改判。
4. **顺序与独立性不变**：A 核验签署 + 风险接受签署 + 环境固定/状态卷就绪
   之后才可申请 B-only；B-only 成功签署后才可申请 First Once；两授权
   互相独立，任何批准不自动延伸。停止/升级与例外撤销条款见
   approval-record §6。
