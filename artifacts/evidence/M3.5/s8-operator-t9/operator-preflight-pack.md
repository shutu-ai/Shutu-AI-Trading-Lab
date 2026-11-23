# 操作者 A/B/C 验证包（operator-preflight-pack — T9.3，LOCAL_ONLY，准备不签署）

> 本包整合 r1 `operator-preflight.md` 与 r2 `operator-readiness.md` 的现行
> 要求，供**账户所有者本人**逐项本地执行。Codex 不签署、不读取凭证、不代跑
> 网络负例。签署结果只保存在操作者本地（空白模板见
> `operator-attestation-template.md`；仓库内永远是空白）。

## 状态定义与客观转换条件（三种状态，无第四种）

| 状态 | 客观含义 |
|---|---|
| `PENDING_OPERATOR` | 清单就绪但操作者尚未执行/签署对应项（**当前全部处于此状态**） |
| `VERIFIED_BY_OPERATOR` | 操作者本人已完成该项全部子项、留有本地证据（命令+时间戳+输出摘要）、并在本地模板上签署；A 项还需账户实际状态与条款核对一致 |
| `BLOCKED` | 某必需子项客观无法满足（例如：只有 Live 账户无 Paper、条款禁止个人只读用途、隔离负例无法在网络层拒绝）——不得推进，如实记录 |

规则：`B=PREPARED`（方案/模板就绪）**不是** `B=VERIFIED_BY_OPERATOR`；
`operator_confirmed: true` 配置声明**不是**签署事实；`API_VERIFIED` 只能由
未来真实采集的**可审计回执**升级，与 A/B/C 签署无关。

## §A 账户与许可核对（PENDING_OPERATOR）

**目的**：区分"官方公开条款允许什么"与"我的账户实际是什么状态"——两者都要
本人核对，缺一不可。

1. 官方公开条款核对（操作者本人阅读当期页面，记录页面版本/日期到本地签署
   记录；以下 URL 由操作者访问，本轮 Codex 未访问网络）：
   - 市场数据 API 总览：`https://docs.alpaca.markets/us/docs/about-market-data-api`
   - 单标的日线 bars 契约：`https://docs.alpaca.markets/us/reference/stockbarsingle-1`
   - 市场数据 FAQ：`https://docs.alpaca.markets/us/docs/market-data-faq`
   核对点：免费 Basic 计划 + IEX feed 的**当前**条款；个人工程/只读用途是否
   允许；付费计划（SIP / Algo Trader Plus）边界。
2. 账户实际状态核对（本人登录确认，**不向任何人展示**）：
   - 账户为 Paper Only（未开通 Live、未入金）；
   - 未订阅任何付费数据计划；
   - 市场数据权限确为 IEX/Basic（以控制台显示为准）。
3. 与冻结预注册一致性：`configs/forward_observation_s8_real_v2.yaml` 的
   `source_authorization`（ALPACA_IEX_BASIC_READ_ONLY / provider alpaca /
   feed iex / plan basic_free / broker_credentials FORBIDDEN）与上述事实一致。
4. `license_attestation.approval_record` 指向的签批记录存在且为本人签发。

## §B 凭证操作方案（PENDING_OPERATOR；`PREPARED` ≠ `VERIFIED`）

**边界**：凭证值只存在于 Alpaca 控制台 → 操作者本人 → 采集子进程环境。
不进仓库、日志、回执、CI、AI 会话、剪贴板同步工具、截图、`.env`。

操作方案（**2026-11-22 T9.7 修订**：注入时点改为"**授权 1（B-only 无网络
凭证注入核验）获用户明确批准之后**"——与"首次真实采集授权"完全独立，
消解原"采集授权之后"表述与 A/B/C 前置条件构成的依赖环，见
`../s8-operator-t9-7/operator-gate-reconciliation.md` §1–§3；本轮不注入、
不校验）：
1. 在受控采集环境（见 `operator-environment-plan.md`）内，由操作者本人以
   进程级方式注入 `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`（环境变量或
   secret mount；采集器只在构建请求头时读取值，从不打印/落盘）。
2. 注入前确认：环境内无仓库外副本；shell 历史不回显值（`read -s` 类方式）；
   注入后**不**运行任何会把 env 打印出来的命令。
3. 注入后的有效性判定**只能**来自真实采集的审计回执链；`APCA_API_KEY_ID`
   非空本身**不是**市场数据授权成功的证明（权限错误、401/403 都可能出现，
   见 approval-request §4 的预期）。
4. 会话结束：终止进程树、销毁环境（方案 A）或清空子进程环境；本地签署
   记录中只记"已注入/已清除"事实，不记任何值。

## §C 无凭证出口负例（PENDING_OPERATOR；模板供日后本人执行，本轮严禁执行）

完整可证伪条件见 `operator-environment-plan.md` §7（F-1～F-8）；
`operator-attestation-template.md` §C 附命令模板（PowerShell / curl 形态，
全部无凭证）。要点重申：

- 允许域：`data.alpaca.markets:443` 应用层收到**任意**HTTP 响应即算通
  （401/403/4xx 均可，不强求 401）；
- 禁行域：`api.alpaca.markets`、`paper-api.alpaca.markets`、任选非白名单域
  ——必须**网络层失败**（超时/拒绝/DNS 失败），HTTP 401/403 反而是**失败**
  （说明请求到达了对端应用 = 隔离没生效）；
- 覆盖：IPv4+IPv6、直连+代理/CONNECT、交互 shell + 采集器同型子进程；
- 部分通过就部分声明：只能证明的路径写 `VERIFIED`，其余写 `BLOCKED` /
  `UNVERIFIED`；`HOST_EGRESS_ISOLATION_UNVERIFIED` 只要有任一必需路径
  未证实就保持。

## 签署（账户所有者本人，本地保存，不入仓库）

- 模板：`operator-attestation-template.md`（空白）。
- 签署后本地保存完整模板 + 证据摘要；仓库内该模板**永远保持空白**——
  仓库中出现签署副本即视为违规入库（应立即本地删除该副本并报告）。
- A/B/C 三项相互独立：可以单独 VERIFIED；`FIRST_REAL_ONCE_READY` 只在三
  项全部 `VERIFIED_BY_OPERATOR` **且**用户另行单独授权后才可能升级。

> **2026-11-23 T9.8 修订（直连受限试点例外——上一行门槛不删除，新增可
> 验证替代分支）**：经用户批示（根目录
> `Shutu_M35_S8_T9_8_Windows_Direct_Limited_Pilot_Approval.md`；审批记录
> `../s8-operator-t9-8/windows-direct-pilot-approval-record.md`），在批示
> 定义的直连受限只读试点范围内，"C 全部 VERIFIED"一腿可由替代条件满足：
>
> `A_verified AND ((C_verified AND environment_frozen) OR
>  (direct_pilot_exception_approved AND local_risk_acceptance_signed AND
>   environment_frozen))`
>
> 事实基线不变：2026-11-23 直连主机实测 F-2 失败，C 保持实测原值
> `BLOCKED`（§C 判据与 `HOST_EGRESS_ISOLATION_UNVERIFIED` 规则照旧）；
> 例外不写成 C `VERIFIED`、不虚构 F-1～F-8 证据、不要求修改 Windows 全局
> 防火墙。A 与 B 的核验/签署要求**零降低**；§C 的负例矩阵仍是全矩阵路径
> 与环境切换重验的判据。
