# Shutu AI Trading Lab — M3.5-S8 真实日线契约与前向验收门定向整改（Codex 任务书）

> Task ID: `M35-S8-REAL-FEED-CONTRACT-AND-FORWARD-GATE-R1-20261122`  
> 编制日期：2026-11-22  
> 远端仓库：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> 独立审查远端 `main`：`2e189eb499bfb1cd5c9e73a266c93c0f3008ad18`  
> 真实 CI：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45013402697`，Ubuntu / Windows 均 **887 passed**。  
> **验收结论：`S8_OFFLINE_ENGINEERING_REMOTE_VERIFIED`，但 `S8_REAL_DATA_READY=BLOCKED_BY_CONTRACT`，真实前向为 `NOT_STARTED`（0 天）。**  
> **本轮只允许 S8 定向工程整改、离线协议验证；不得自动 push、读取真实凭证、连接真实 Alpaca、启动 Paper 或 M4。**

## 0. 停止门、范围与基线（强制执行）

1. 先阅读仓库的 `AGENTS.md`、两份 v2.1 计划、`configs/forward_observation_s8_real.yaml`、`artifacts/evidence/M3.5/s8/authorization-check.md`、`docs/reviews/M3.5-s8-readonly.md` 和 M3.5 S8 原始任务书。任务书的存在不构成额外授权；原用户授权 `S8_DATA_READ_ONLY=APPROVED_WITH_SCOPE` 仅覆盖有限、无付费、无券商写的工程范围。
2. 执行前核实 `git status --short`、`git rev-parse HEAD`、`git rev-parse origin/main`、远端 CI 的 `head_sha` 和双平台 job log。用户称本地 docs-only 提交 `1b3460e` 未推送：**先验证它是否存在、触及何文件、是否与当前变更冲突；绝不能覆盖、丢弃、reset --hard 或未经明确批准推送。**
3. 既有 887 项测试是整改前基线，不可删减、skip、xfail、软化断言或降低五日门槛；M2 1,080 故障矩阵、M3/M3.5 旧研究协议与历史证据原文保留。新测试单列分母；先 RED 后 GREEN，记录每个真实退出码。
4. **最高优先级：不要运行真实 `collect`。** 当前生产代码将 `/v2/stocks/{symbol}/bars/latest` 的分钟 bar 误当作日 bar，并期待不符合该接口的 `bars` 数组；修复并独立验证前，任何 API 凭证都不得注入该进程。当前真实采集 0 天绝不补录、回填或宣称已开始。
5. 本轮不接触真实行情凭证、不联网调用 Alpaca、不创建付费订阅、不发 Alpaca Paper/Live 订单、不执行 M4、不解封 Holdout、不作 Alpha/收益主张。`PAPER_WRITE=NOT_AUTHORIZED / BLOCKED_DATA(full_market) / BROKER_BEHAVIOR_UNVERIFIED / S=INCONCLUSIVE / R=NOT_STARTED / SEALED_NOT_MATERIALIZED` 保持。
6. 本轮以**单一 `apps/market_gateway/` 只读适配器**和既有 `apps/trading_daemon/` 唯一评分引擎为基础；不新建 OMS、第二条行情管线、第二个评估机、通用 SDK/消息总线/兼容层。只有确有消费者需要的新模块才可加入。

## 1. P0 源码事实与官方契约（先核实，不凭假设）

### P0-1 日线接口错配

当前：

- `apps/market_gateway/alpaca_feed.py::collect_once()` 请求 `GET https://data.alpaca.markets/v2/stocks/{symbol}/bars/latest?feed=iex`，每个响应被作为当日完整日线。
- `apps/market_gateway/quality.py` 预期 `payload["bars"]` 为 `len==1` 的数组、`bar.t` 为该日午夜 ET；测试夹具 `apps/market_gateway/fixtures/selftest_bars.json` 也自称这是该 latest 接口的“documented shape”。
- **Alpaca 官方 API 文档**明确指出：`/v2/stocks/{symbol}/bars/latest` 返回 **latest minute bar**；其单标的响应采用 `bar` 对象，而非本仓库伪造的 `bars` 数组。见：
  - https://docs.alpaca.markets/us/reference/stocklatestbarsingle-1
  - https://docs.alpaca.markets/us/reference/stocklatestbars-1
- 官方完整日线可走 `GET /v2/stocks/{symbol}/bars` 或 `GET /v2/stocks/bars`，明确 `timeframe=1Day`、`feed=iex`、`adjustment=raw`、有界 start/end、核实返回的日期与分页，见：
  - https://docs.alpaca.markets/us/reference/stockbarsingle-1
  - https://docs.alpaca.markets/us/reference/stockbars
- **两类证据不得混用**：分钟 close ≠ 日线 close，分钟 volume ≠ 全天成交量，改个 `interval` 标签不能修复。

### P0-2 最终 E=PASS 判据缺少事实来源

- `apps/trading_daemon/eligibility.py::evaluate_eligibility(claim='PASS')` 要求 `disconnect_recoveries>=1`、`duplicate_recoveries>=1`、`audits_passed=True`、足额 `trading_days_observed`、零非法/重复订单。
- `apps/market_gateway/feed_session.py::window_facts_from_journal()` 当前返回 `cycles_after_feed_error` / `duplicate_events` / `journal_verified` / `receipts_verified` 等，但**没有生成**上述三项资格字段；最终 `_complete_window()` 会尝试 PASS 后退化，无法据完整真实证据正当地满足 E=PASS。
- 真实前向的 `PASS` 必须依赖**可重放持久事实**，不得通过 `setdefault(True)`、临时硬编码布尔量或将“模拟测试成功”充当真实恢复。

## 2. T0 — 基线、RED 复现与证据隔离

1. 建立 `artifacts/evidence/M3.5/s8-contract-r1/` 新目录，写 `baseline.md`（远端 SHA / 本地 `1b3460e` 差异 / 原 CI / 现有协议 hash / 身份 hash / 旧 887 测试分母）。历史证据只读。
2. 在离线、注入的假 HTTP 响应环境写**行为 RED**：
   - `bars/latest` 的真实文档形状 `{"symbol":"SPY","bar":{"t":"...","o":...,"h":...,"l":...,"c":...,"v":...}}` 被误判为不是完整日线/或者错误接入；精确说明原行为。不要用缺失新模块的 `ImportError` 冒充漏洞实证。
   - 对 `claim='PASS'` 构造满足全部**真实且持久**五日事实时，当前 `window_facts_from_journal()` 不能提供所需三字段；说明已写/未写事实差异。不要预先假设已存在真实网络事件。
3. 保存 `red-tests.log`、`red-contract-probe.md`（官方 URL、检索日期、原始字段差异、实际输出/退出码）；只用人工构造的 API 文档形状离线夹具，**绝不能写成“真实 API 返回”**。

## 3. T1 — 最小修复正确的完整日线契约（P0，先 GREEN）

1. 优先修改已有 `alpaca_feed.py`、`quality.py`、`offline_fixtures.py`、`http_client.py` 和已有测试。**唯一权威为官方有显式 `timeframe=1Day` 的 bars API**，且继续限定 `feed=iex`、`adjustment=raw`、<=3 预注册标的、GET-only、交易主机硬拒、重定向硬拒、超限/超时 fail-closed。
2. 针对所请求的**当前 NYSE 交易会话日**构造显式 UTC/ET 时间边界，严禁宽窗口抓历史数据补齐“前向日数”；处理 API 日期语义、返回 bars 数组、缺 bar、额外 bar、空 bar、分页、无行情、429/401/403/5xx 和文档规定的可能字段。每一条拒绝必须写入回执审计，不计作完整日。
3. 时间约束：既有 `ts_event` 为当日真实会话收盘（含半日、DST），`ts_available` 为真实接收时刻；实际 bar 必须能证明是该会话 **已完成日线**，不得用还在形成中的日线或最新分钟 bar 代替。若供应商对收盘后某时段的完成性/延迟不能保证，标 `NOT_FINALIZED`、等待后续合法轮询；不能默默修改日线结束时间/日线 timestamp。明确 IEX 单一场所，不得冒充 SIP 全市场。
4. 保留并重新验证 `event_id` 确定性、provider/source/feed、raw payload digest/normalized bar digest、receipt↔journal 绑定、跨重启幂等、迟到修订冲突；供应商后补修订不得静默篡改已锁定预测。
5. **旧夹具不得改写后声称“原来就正确”。** 保留旧夹具原样作为历史缺陷证据，标记 `LEGACY_INVALID_VENDOR_CONTRACT`；新建或版本化**正确日线 API 形状**的合成夹具和负例，清晰记录迁移及兼容测试。不得留两套生产适配流程。
6. 源码与测试必须证明：即便误传最新分钟 bar 响应，也**零日线事件、零前向日数**；正确日线 shape 才可能生成候选事件；尚无真实 API_VERIFIED。

## 4. T2 — 完整接通五日 E-Gate 的持久证据（P0）

1. 继续复用 `window_facts_from_journal()` 和唯一 `evaluate_eligibility()`；不要创建第二个决策引擎。由**回执链 + ForwardJournal + 恢复事件日志**计算所需字段：
   - `disconnect_recoveries`：真实采集发生可审计的 transport 断连/失败之后，合法、完整、同窗口的后续接收恢复，必要时还必须包括独立重启恢复证明；不能把普通 401/403 或假设性网络故障算作“断连”证据。
   - `duplicate_recoveries`：真实到达事件的重复投递经 engine `DUPLICATE` 拒二次消费/评分并可审计（不等于仅有两个相同日志）。
   - `audits_passed`：真实执行了双链完整性 + 头/外锚 + 身份/协议一致性 + 持久重放/窗口资格 + 数据质量检查的验证。失败、缺失或未完成 => False，而非默认 True。
2. 增强恰好一次、五日完整覆盖的负例：4/5/6 日、单标的缺失、交易所休市/半日、同日重复、跨阶段合成污染、无 receipt/receipt 哈希错、重启后重复、仅断连无恢复、仅重复无持久去重、缺审计锚、篡改锁定时点、回填过去日期，都不得 `PASS`。
3. 真实前向日数只能在**先验冻结预测时间先于供应商事实真实到达/可得时间**且每个预注册标的同日完整可得时计数；历史补拉（即使成功 GET）不得伪装成实时前向观察。恢复状态来自持久事实，不接受自报整数。
4. `cmd_status` 和 `cmd_collect --complete` 必须在同一持久事实下给出一致状态：没有合法到达记录 => `BLOCKED_ENV`/`NOT_STARTED`；合法但不足 5 日 => `PENDING_FORWARD_WINDOW`/`ACCUMULATING`；真实 ≥5 全覆盖且恢复/重复/审计门全通过才可 `PASS`；证据缺陷必须拒绝升级。**不要为了取 PASS 而伪造真实记录**——所有 PASS 负例/正例均明确标 `SIMULATED_REAL_SHAPE_TEST_ONLY`，不影响实际 Stage E。
5. 继续 `S=INCONCLUSIVE / R=NOT_STARTED`，E 的真实 PASS 永不等于策略有效、Paper 或 Live 资格。

## 5. T3 — 新版预注册、许可与凭证边界

1. **不要原地改写**已冻结 `configs/forward_observation_s8_real.yaml` 和旧 S8 证据。新增受控协议版本（新 `forward_protocol_id/hash` 与新的合法日线 endpoint/查询/时钟/事件契约），明确从旧版迁移的理由、受测代码身份、回执链版本以及旧协议此前 **0 API_VERIFIED、0 real forward day**；不允许旧协议生成真实 `PASS`。
2. 新协议沿用唯一 v2 加载器并加硬约束（仅必要时增量修改）；Runner 选择新协议需显式参数或经人工确认的明确入口，避免静默切换。任何不兼容旧状态库必须显式拒绝跨协议续写，旧 JSONL 不迁移伪造前向证据。
3. 当前旧版 `license_attestation.operator_confirmed: true` 只是配置声明，不等于已经验证用户账户真实许可。编写单独、由账户所有者签名/确认的本地许可与数据权限核对清单（凭证不写入仓库）；未确认则 `BLOCKED_ENV`。勿记录任何 API key 内容、hash 或可识别值。
4. 凭证可能具备 Paper 写能力：**进程内 GET-only 守卫不等同于凭证原生只读权限**。明确操作者的主机/容器独立网络策略：只有 `data.alpaca.markets:443` 可出站；阻断 `api.alpaca.markets`、`paper-api.alpaca.markets` 与泛互联网外联。若本机无法证明网络策略，则标 `HOST_EGRESS_ISOLATION_UNVERIFIED`，禁止声称网络层完全只读。应用层不绕过系统代理；检查 Windows 办公网代理/家庭直连差异，但禁止为通网而放宽主机白名单。
5. `$0`、`iex`、最多 3 标的、Paper 写禁止、Live 禁止不可放宽；无凭证时所有单测/自测不得连接真实 API。首次真实采集仍属于后续**单独操作者动作**，本轮只准备就绪报告。

## 6. T4 — 测试、架构、证据与回归硬门

必须做到：

- 新增正反例覆盖最新一分钟 bar 与完整日 bar 的**本质不同**；官方文档响应 shape 与 repo 旧 fixture 的差异；分页/错误码/分钟错用/未完结日线/半日/DST/过期行情/合法不同 feed 误入；双链回执不可伪造的已声明范围。
- 两平台执行完整 `python -m pytest -q`，基线至少 **887** 且原测试 0 删减/跳过/xfail；另跑原 M2 1,080 故障矩阵及 M3/M3.5 前向/身份回归。**如果旧 fixture 测试需要迁移，必须保留原行为的负证据并逐项解释改动不是放松检测。**
- `python scripts/check_environment.py`、`python scripts/check_architecture.py`、`python scripts/scan_secrets.py`、`python scripts/verify_live_blocked.py`、`python scripts/smoke_mock.py`、`git diff --check` 全 PASS，退出码入库。只读平面继续唯一允许 `urllib` 的网络入口，daemon/backtest/validation 禁网络及 broker/risk/oms 写入口。
- Architecture Health 记录 `REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES/DEBT`，记录精确职责消费者；如无必要不加运行依赖，不堆叠兼容模块或平行实现。
- 历史受测 CI `45013402697` 只证明旧 S8 工程 887 项通过；新 SHA 任何本地绿 **不等于 REMOTE_VERIFIED**。需用户**单独批准推送**后才能执行并核实 Ubuntu + Windows 新 CI。不要复用旧 SHA 冒充新代码绿。

## 7. T5 — 必须生成的文档与状态

建议工件（可按仓库既有命名略作调整，但不得覆盖旧证据）：

```text
artifacts/evidence/M3.5/s8-contract-r1/
  baseline.md
  official-api-contract.md
  red-tests.log
  negative-tests.log
  verification.log
  architecture-health.md
  protocol-migration.md
  forward-gate-proof.md
  operator-preflight.md
  remote-ci.md                    # 未获 push / 远端未跑：写 PENDING，不得写 PASS

docs/reviews/M3.5-s8-contract-remediation.md
```

报告应分别标注：

- `S8_OFFLINE_ENGINEERING_REMOTE_VERIFIED` = **历史 887 旧代码结果**，仍是真实事实；
- 本轮整改在未 push 时 `S8_CONTRACT_REMEDIATION_LOCAL_PASS / CI_REMOTE_PENDING`，不可升级；
- 真实行情 `API_VERIFIED=NONE`（未操作用户账户），`REAL_FORWARD_DAYS=0`，`S8_REAL_DATA_READY=OPERATOR_AND_CI_PENDING`；
- 全市场 `BLOCKED_DATA` 不解除，M1 U-1 为已修词表，不再误写 UNRESOLVED，但不能推论供应商已授权；
- `PAPER_WRITE=NOT_AUTHORIZED / S=INCONCLUSIVE / R=NOT_STARTED / BROKER_BEHAVIOR_UNVERIFIED / M3.5_GATE=USER_PENDING`。

## 8. 强制 STOP 与未来单独的真实采集门（禁止本轮自动执行）

**完成 T0–T5 后强制 STOP。** 未获用户单独授权不得 push；即使新 SHA 的 CI 双平台通过，也不得自动用本人账号运行真实 collect。

首次真实采集由**用户本人**完成账户注册/合法使用条款核对/凭证本机安全注入/网络出口隔离，并在收到新协议 + 远端 CI 验收后显式选择执行。正确操作序列是：

1. 无凭证：`python scripts/run_m35_s8_shadow_real.py check-config`、离线 `selftest`、`status`；不得以此计真实窗口。
2. 授权与权限确认完成后，先完成应用/系统出口阻断（不能连接任何 trading host），验证新配置检查、原始 shape、限额与查询日是否正确；**首次仅采集一个真实周期**，把状态从 `BLOCKED_ENV` 升级到实际取证后的 `API_VERIFIED` 或继续 BLOCKED，不能猜测。
3. 每个合法真实交易日继续只读采集（不回填冒充前向），完整五日并涵盖断连/重启、重复投递的真实运行证据后，独立复核再申请 `M3.5_GATE=CLOSED_WITH_REAL_FORWARD_SCOPE`；若环境不足则 `PENDING_FORWARD_WINDOW`/`BLOCKED_ENV`，不冒称 E PASS。
4. **Alpaca Paper 模拟下单仍需完全不同的独立签批**。不因 read-only 通过而自动开放 Paper，禁止 M4 自动启动。

---

## 直接交给 Codex 的执行提示词

> 读取 `Shutu_AI_Trading_Lab_M3_5_S8_Real_Feed_Contract_Remediation_Codex_Task.md`、`AGENTS.md`、两份 v2.1 计划和 S8 原始授权记录。**仅执行 T0–T5**：先 RED 实证官方 `bars/latest` 是分钟线而仓库误作日线、以及五日 PASS 所需证据字段未接通，再在已有唯一 market_gateway/daemon 上最小 GREEN 修复。独立新建预注册版本，保护旧配置/身份/历史证据，保留 >=887 回归及 1,080 故障矩阵并进行架构安全验收。只用官方文档加人工合成响应进行离线验证；禁止读用户凭证、调用真实 Alpaca、购买订阅、提交模拟/真实订单、进入 M4 或自动推送。所有证据写入新目录，完成后停在 `M3.5_GATE=USER_PENDING`，报告本地与远端状态、真实剩余阻断项，等待我单独审批推送和首次真实采集。
