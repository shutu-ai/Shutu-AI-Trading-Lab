# 操作者签署模板（operator-attestation-template — 空白，不入库签署副本）

> 使用方式：账户所有者本人**复制本文件到本地**（仓库外），逐项执行、填写、
> 签署后仅在本地保存。仓库内本模板永远保持空白；任何签署副本进入仓库即视为
> 违规。Codex 不填写、不签署、不收集本文件。

签署人（账户所有者）：＿＿＿＿＿＿＿＿
签署日期：＿＿＿＿-＿＿＿-＿＿＿＿
目标环境标识（主机类型/虚拟化方式/网络类型/是否经代理，不含任何密钥）：
＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿
专用 state dir 标识（路径或其非敏感 hash）：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿

## §A 账户与许可（逐项勾选，全部为本人登录/阅读确认）

- [ ] A1 账户为 Paper Only（未开通 Live、未入金）
- [ ] A2 已阅读当期官方市场数据条款并确认免费 Basic + IEX 允许个人工程只读
      用途（已记录条款页面版本/日期于本地：＿＿＿＿）
      参考：docs.alpaca.markets `/docs/about-market-data-api`、
      `/reference/stockbarsingle-1`、`/docs/market-data-faq`
- [ ] A3 未订阅且不会订阅付费数据计划（SIP / Algo Trader Plus）
- [ ] A4 控制台显示的市场数据权限与 IEX/Basic 一致
- [ ] A5 与冻结预注册 `forward_observation_s8_real_v2.yaml` 的
      source_authorization 一致；`approval_record` 指向的签批记录存在且为本人签发

A 判定：＿＿＿＿（VERIFIED_BY_OPERATOR / BLOCKED）
不通过原因（如有）：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿

## §B 凭证操作（本节在未来的真实采集授权之后才执行；现在只登记方案确认）

- [ ] B1 我确认凭证只经我本人注入采集子进程，不进仓库/日志/回执/CI/AI 会话/
      截图/`.env`
- [ ] B2 我确认注入与清除操作方案已理解（operator-preflight-pack.md §B）
- [ ] B3（实际执行时填写）注入日期/时间：＿＿＿＿；清除日期/时间：＿＿＿＿
      （只记事实，不记任何值）
- [ ] B4 我理解 key 非空 ≠ 市场数据授权成功；有效性只能由审计回执链证明

B 判定：＿＿＿＿（PENDING_OPERATOR / PREPARED / VERIFIED_BY_OPERATOR / BLOCKED）
说明：`PREPARED` 仅表示方案就绪，不是签署事实。

## §C 无凭证出口隔离负例（本人执行的实测记录；每行一条证据摘要）

> 命令模板见下；执行环境 = 目标采集环境本体。全部无凭证。
> 判定要点：允许域收到任意 HTTP 响应=通；禁行域必须网络层失败
> （HTTP 401/403 = 隔离失败）。

| # | 路径 | 命令（模板） | 预期 | 实测（摘要+时间） | 判定 |
|---|---|---|---|---|---|
| C-1 | 直连 IPv4 | `curl -4 -sS -o /dev/null -w "%{http_code}" --max-time 15 https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day` | 任意 HTTP 码（401/403/4xx） | ＿＿＿＿ | ＿＿＿ |
| C-2 | 直连 IPv6 | 同上 `-6`（或环境无 v6 时记录"v6 已禁用"证据） | 任意 HTTP 码 / v6 禁用证据 | ＿＿＿＿ | ＿＿＿ |
| C-3 | 交易域① | `curl -4 -sS -o /dev/null -w "%{http_code}" --max-time 15 https://api.alpaca.markets/v1/clock` | 网络层失败（非 HTTP 码） | ＿＿＿＿ | ＿＿＿ |
| C-4 | 交易域② | 同上 `https://paper-api.alpaca.markets/v2/account` | 网络层失败（非 HTTP 码） | ＿＿＿＿ | ＿＿＿ |
| C-5 | 非白名单域×2 | 同上形态，任选两个公网站点 | 网络层失败 | ＿＿＿＿ | ＿＿＿ |
| C-6 | 代理/CONNECT 路径 | 显式代理变量下重跑 C-1～C-5（`HTTPS_PROXY=<代理>`） | 与直连同向（允许域通、禁行域网络层失败） | ＿＿＿＿ | ＿＿＿ |
| C-7 | 子进程同边界 | `python -c "import urllib.request;print(urllib.request.urlopen('https://api.alpaca.markets/v1/clock', timeout=15).status)"` 及允许域同型命令 | 采集器同型子进程结果与 C-1～C-6 一致 | ＿＿＿＿ | ＿＿＿ |
| C-8 | DNS 受控 | 固定 DNS 记录说明 + 白名单外域名解析/连接失败证据 | 解析路径受控 | ＿＿＿＿ | ＿＿＿ |

说明：Windows 下可将 `curl` 换为 `Invoke-WebRequest`/`Test-NetConnection`
（`Test-NetConnection api.alpaca.markets -Port 443` 应 TcpTestSucceeded=False）；
模板仅示范"无凭证 + 判定要点"，操作者可用等效工具，但**不得修改 allowlist
以凑成功**。任何一条无法证明 → 该项 `BLOCKED`/`UNVERIFIED`。

C 判定：＿＿＿＿（VERIFIED_BY_OPERATOR / BLOCKED / 部分通过则逐行如实标注）
未证实路径（如有）：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿
`HOST_EGRESS_ISOLATION`：＿＿＿＿（仅当 C 全部 VERIFIED 才可去掉
UNVERIFIED 标注；否则保持 `HOST_EGRESS_ISOLATION_UNVERIFIED`）

## 签署

- [ ] A 全部 / 判定：＿＿＿＿
- [ ] B 判定：＿＿＿＿
- [ ] C 判定：＿＿＿＿

签署人：＿＿＿＿＿＿＿＿　日期：＿＿＿＿-＿＿＿-＿＿＿＿
（本签署仅保存于操作者本地；不回传仓库、CI 或任何 AI 会话。）
