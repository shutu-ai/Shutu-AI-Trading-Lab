# 操作者就绪手册草案（operator-readiness，T7.4 — LOCAL_ONLY，未签署）

> 任务：`M35-S8-T7-COMPLETION-INTEGRITY-AND-OPERATOR-PREFLIGHT-R1-20261122`。
> 本文件是 T7.4 的**资料准备**：把 `s8-contract-r1/operator-preflight.md` 的 A–C
> 核验项整理为可执行的操作手册草案。它**不代替**账户所有者的本人核验，不构成签署，
> 不升级任何状态。所有 A/B/C 状态保持 **`PENDING_OPERATOR`**。
> 本文件不含任何凭证值；Codex 在本轮（含本文件撰写）**零接触**任何真实凭证，
> 未发起任何对 `data.alpaca.markets` / `api.alpaca.markets` / `paper-api.alpaca.markets`
> 的网络请求（`REAL_API_CALLS=0`）。

## 状态总表（签署前不得变动）

| 项 | 状态 | 升级条件（由操作者本人完成） |
|---|---|---|
| A 账户与许可 | `PENDING_OPERATOR` | 本人核对 Paper-only + Basic/IEX 条款并在本地签署记录 |
| B 凭证注入 | `PENDING_OPERATOR` | 操作者本人在受控主机进程级注入（Codex 永不代办） |
| C 主机出口隔离 | `PENDING_OPERATOR`（`HOST_EGRESS_ISOLATION_UNVERIFIED`） | 操作者本人执行 §C 无凭证负例并留档 |
| `FIRST_REAL_ONCE_READY` | **NO** | A–C 全部签署 **且** 用户另行单独授权首次 `collect --once` |

> 配置中 `license_attestation.operator_confirmed: true` 是**配置声明**，不是已验证
> 事实；只有操作者本地签署后才转为本地确认记录（与 T6 审计口径一致）。

## §A 账户与授权（操作者本人逐项核对）

1. 登录 Alpaca 账户，确认：Paper Only、未开通 Live、未入金。
2. 打开当期市场数据条款页，确认免费 **Basic 计划 + IEX feed** 允许个人工程观察用途；
   记录条款页 URL 与当日日期到本地签署记录（不入仓库）。
3. 确认未订阅、也不会订阅任何付费计划（SIP / Algo Trader Plus 永不授权，
   预注册 `plan: basic_free` 钉死）。
4. 核对 `configs/forward_observation_s8_real_v2.yaml` 中
   `license_attestation.approval_record` 指向的签批记录路径确实存在且为本人签发。
5. 全部核对后，在本地（不入仓库）签署 A 项。

## §B 凭证边界（操作者本人执行；Codex 零接触）

- 凭证只存在于：Alpaca 控制台 → 操作者本人 → 采集子进程环境。中间任何一步都
  不经过 AI 会话、剪贴板同步工具、截图、`.env`、git、CI。
- 注入方式由操作者本人选择（secret mount / 进程级环境注入），注入动作用户本人完成；
  ~~**只有未来单独授权真实采集时**才需要执行注入，本轮不注入。~~
  **（2026-11-22 T9.7 修订）**：上一句构成 B 项审批死锁（注入被绑在采集授权
  上，而采集授权又要求 B 已签署）——已废止。现行模型：注入时点改为
  **独立的"授权 1：B-only 无网络凭证注入核验"获用户批准之后**（A/C 已签署
  + 环境固定为前置）；B 本人核验签署后才可 VERIFIED；"授权 2：首次真实
  `collect --once`"仍另行单独申请，B-only 批准绝不预授权它。
  见 `../s8-operator-t9-7/operator-gate-reconciliation.md` §1–§3。本轮不注入。
- Codex 不得读取、请求、打印、转录、搬运任何密钥值；本轮未发生（`scan_secrets`
  0 发现佐证仓库侧干净）。
- 注入后的离线自检序列（无网络请求，可在任何主机执行）：
  1. `python scripts/run_m35_s8_shadow_real.py check-config` —— 应输出 ranged v2
     协议事实（`bars_endpoint: ranged_daily_bars`，`paper_write: NOT_AUTHORIZED`）。
  2. `python scripts/run_m35_s8_shadow_real.py selftest --state-dir <临时目录> --no-evidence`
     —— 应离线通过（`OFFLINE_HARNESS_PASS_WITH_SCOPE`），fixture 事实永不计入真实窗口。
  3. `python scripts/run_m35_s8_shadow_real.py status --state-dir <状态目录>`
     —— 未开始窗口应 `exit 0` + `completion_state: NOT_STARTED`；**完整性失败时
     自 T7 起为非零退出码（6/7），零退出码不再等价于"一切正常"**（见 §D）。
- 以上三条命令不读凭证值、不发网络请求；B 项的"注入成功"判定**只能**由
  未来真实 `collect --once` 的可审计回执给出，不由任何离线命令判定。

## §C 主机出口隔离负例核验（操作者本人在其受控主机执行；本轮未执行）

> 以下步骤设计为**无凭证**网络层负例，仅为操作者未来的操作说明；
> Codex 本轮未执行任何外连探针。GET-only 进程级校验 ≠ 主机级出口隔离。

1. **应用层白名单已由代码强制**（`GuardedGetClient`：仅 `data.alpaca.markets`、
   仅 GET、仅预注册路径、禁止重定向）——但这不是主机隔离证据。
2. 主机层负例（全部应**在网络层失败**，不是 401/403）：
   - `GET https://api.alpaca.markets/v1/clock`（无凭证）→ 应被防火墙/容器策略阻断；
   - `GET https://paper-api.alpaca.markets/v2/account`（无凭证）→ 同上；
   - 泛互联网对照（任一非白名单主机）→ 同上；
   - `GET https://data.alpaca.markets/v2/stocks/SPY/bars?...`（无凭证）→
     应到达 401（证明白名单路径在**主机层**可达，应用层守卫与主机策略一致）。
3. 覆盖维度，每项留档命令与结果：
   - `urllib.request` 直连 vs 环境 `HTTP(S)_PROXY` 显式设置（本机办公代理
     `192.168.1.2:8080`）vs 系统代理（Windows WinINET 设置）vs CONNECT 隧道行为；
   - DNS 解析（A/AAAA）：白名单主机与被拒主机各自的解析是否被策略拦截；
   - IPv4 与 IPv6 分别验证（只放行 v4 时 v6 必须同样被阻断）；
   - 子进程出口：从采集器同型子进程（`python -c "import urllib.request;..."`）
     发起上述负例，证明策略覆盖子进程而不只是交互 shell；
   - 代理机（办公网）与家庭直连两种网络环境分别执行——**不为通网放宽白名单**。
4. 任何一项无法证明 → 如实保持 `HOST_EGRESS_ISOLATION_UNVERIFIED`，
   禁止在任何报告中声称"网络层完全只读"。

## §D 首次真实采集纪律（未来单独授权后；本轮禁止执行）

1. 每次授权只允许**一个**受控真实周期：`collect --once`。
2. `MARKET_CLOSED` / `OUTSIDE_POLL_WINDOW` / `EXIT_OK` **不能**自动认定
   `API_VERIFIED`——真实事件资格只能由可审计回执链证明。
3. 不因 5 个日历日过去而认定窗口完成：计数只认**全覆盖真实交易日**
   （`day_counting_rule: full_coverage`）；断连恢复、重复事件恢复必须真实发生
   并留链证，**不准故意制造线上断连、不准向真实链混入合成证据**。
4. 真实采集期间 `status` 的退出码语义（T7 起；T8 修订）：
   - `0` = 命令完成且完整性核验通过（**不是**资格 PASS；资格看 JSON 字段）；
   - `6` = 完整性失败（快照篡改/未绑定/链损坏/重复完成）→ 停止采集并人工复核；
   - `7` = 完成流程未收尾（崩溃窗口）；
   - `8` = 窗口已被 `WINDOW_COMPLETED` 收据封存（T8 起）→ 普通 `collect --once` /
     `collect --complete` 在任何凭证读取、网络客户端、feed 访问**之前**拒绝，
     零磁盘写入。
5. **快照修复（T8 修订）**：`CHAIN_COMMITTED_SNAPSHOT_MISSING` 只用纯离线的
   `repair-completion --state-dir <dir>` 修复——不读凭证、不建网络客户端、不采集、
   不新增收据/会话/事件；只接受"恰一条可验证已提交完成收据 + 快照缺失 + 摘要/
   协议/eligibility 独立重算匹配"。`collect --complete` **只**服务尚未封存窗口的
   首次受控完成，**不是**离线修复入口（T8 起对已封存窗口直接拒绝，exit 8）。
   （T7 版本曾写"`7` → 重跑 `collect --complete` 幂等修复"——按 T8 终态语义
   废止该指引，修订依据见 `s8-contract-r3/red-green.md` 与
   `docs/reviews/M3.5-s8-terminal-collection-fence-r3.md`。）
6. Paper 下单是完全独立的未来签批（`PAPER_WRITE=NOT_AUTHORIZED` 保持）；M4 不自动启动。

## 本轮已离线核验（LOCAL_ONLY，全部在临时目录/合成数据上）

- `check-config`（默认 ranged v2 + legacy 钉死文件）✅ exit 0
- `selftest`（`--no-evidence`，临时状态目录）✅ exit 0，fixture 事实、claim 全拒绝
- `status`（空状态 → `NOT_STARTED` exit 0；各完整性故障 → exit 6/7）✅
  证据：`red-green.md`、`fault-injection.log`、`full-regression.log`
- 本轮 `REAL_API_CALLS=0`；未打开真实采集状态目录（`artifacts/state/` 本机不存在）。
