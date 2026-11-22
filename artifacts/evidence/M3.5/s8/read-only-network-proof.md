# S8 只读网络证明（read-only network proof）

> 签批边界：`S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE`；`PAPER_WRITE=NOT_AUTHORIZED`。

## 断言

S8 采集平面（`apps/market_gateway/`）对真实行情的访问是**结构只读**的：不存在任何下单/撤单/账户/持仓路径，且交易 API 主机不可达。证明分三层，全部为可执行负例（非约定）。

## 1. 运行时守卫（每请求，先于任何网络 I/O）

`apps/market_gateway/http_client.py` `GuardedGetClient`：

- **仅 GET**：无其他动词 API 面（`test_get_only_surface_no_body_support` 断言公共面无 post/put/delete/request/send；守卫常量 `METHOD == "GET"`）；
- **主机白名单**：非白名单主机 `HOST_NOT_ALLOWED`（`test_rejects_host_outside_allowlist`）；
- **交易主机双重拒绝**：`api.alpaca.markets` / `paper-api.alpaca.markets` — 构造期拒绝（`test_construction_refuses_trading_allowlist`）+ 每请求再拒（`test_request_time_guard_refuses_trading_hosts`，模拟"配置损坏后仍不可达"）；
- **路径白名单**：非 `/v2/stocks/{SYM}/bars/latest` 一律 `PATH_NOT_ALLOWED`（orders/positions/account/quotes/小写标的等负例 `test_rejects_paths_outside_whitelist`）；
- **头白名单**：仅 `APCA-*` 凭证头与 `accept`（`test_rejects_non_apca_headers`）；
- **禁重定向**：3xx 是错误不是跳转（`test_redirect_status_is_refused_not_followed` 断言第二次请求从未发生）；
- **禁请求体**：客户端无携带 body 的路径；
- **密钥卫生**：凭证仅构建请求头时在采集进程内使用；错误/回执/日志不含凭证值（`test_credential_headers_never_appear_in_errors`、回执字段测试断言无 `APCA`/凭证串）。

所有拒绝类测试使用"爆炸传输"：若守卫漏放，测试传输会以 AssertionError 炸出——**证明拒绝发生在任何网络 I/O 之前**。

## 2. 静态平面规则（架构检查器，防止网络面扩散）

`scripts/check_architecture.py` gateway 规则（`tests/architecture/test_gateway_plane_rules.py`，19 拒绝 + 11 合法 + 实包扫描）：

- 禁 brokers/oms/risk 导入（无任何 broker 写机制可达）；
- 禁第三方 SDK：requests/websockets/aiohttp/httpx/alpaca；
- 禁 stdlib 原语：socket/ssl/http.*/ftplib/smtplib/telnetlib/xmlrpc —— **全部流量只能经 `GuardedGetClient`**；
- 仅允许 `urllib`（guarded client 的底层）与常规库；
- `apps/trading_daemon` 的禁网规则**原样保留**（`test_daemon_plane_stays_network_free_after_s8`）——S8 不得弱化离线核心的安全论证。

## 3. 预注册侧（配置面收口）

`configs/forward_observation_s8_real.yaml` 加载器（`tests/s8_gateway/test_prereg_real.py`）拒绝：交易主机白名单（live/paper/both）、POST 方法、follow 重定向、orders/positions 路径、空主机、付费计划（`algo_trader_plus`）、SIP feed、`broker_credentials != FORBIDDEN`。加载器 + 守卫 + 平面规则三层独立，单层失效不破坏只读性。

## 4. 诚实边界（记录，不隐藏）

- 守卫是**采集进程内**的应用级控制；主机级隔离（出口防火墙白名单、Data-only 凭证、独立采集进程）属签批条款 3 划给账户所有者的本机安全配置，不在本模块冒充；
- 静态检查不拦计算性动态导入/exec（与 M1/M2/M3.5 相同的已声明边界）；
- Paper/Live 写从未实现——`PAPER_WRITE=NOT_AUTHORIZED` 由**不存在写路径**保证，而非开关。
