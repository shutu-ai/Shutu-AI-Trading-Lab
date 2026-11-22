# 协议迁移记录（protocol-migration，T3）

## 迁移事实

| 项 | 旧（pinned legacy） | 新（生产） |
|---|---|---|
| 文件 | `configs/forward_observation_s8_real.yaml` | `configs/forward_observation_s8_real_v2.yaml` |
| schema | `forward-observation-preregistration-v2` | `forward-observation-preregistration-v3` |
| forward_protocol_id | `m35-s8-real-shadow-readonly-v1` | `m35-s8-real-shadow-readonly-v2` |
| 数据端点 | `/v2/stocks/{sym}/bars/latest`（官方语义=分钟线） | `/v2/stocks/{sym}/bars?timeframe=1Day&feed=iex&adjustment=raw`（官方区间日线） |
| 响应形状 | 伪造的 `bars` 数组（无真实端点返回） | 官方 `stock_bars_resp_single`：`bars` 数组 + 恒存在的 `next_page_token` + 必填 `symbol` 回显 |
| 窗口 | 无界（仅轮询窗） | 有界：start=会话 00:00 ET（含，覆盖盘前戳约定）、end=真实接收时刻；`page_cap=5` 封顶 |
| 日/分钟判别 | 无（分钟戳可冒充日线，RED-2 实证） | 请求契约（timeframe+有界窗）+ 形状（`bar` 对象进 ranged 路径即 CONTRACT_SHAPE）+ 盘中戳拒绝（NOT_A_DAILY_BAR 纵深防御） |
| 完成性 | 未声明 | 预注册完成边际（收盘后轮询窗）；同 id 异载荷修订 → CONFLICT 保守挂起，静默改写被禁 |
| 存在期真实产出 | **0 API_VERIFIED、0 real forward day** | 未开始（`API_VERIFIED=NONE`） |

## 不变项

- 合成预注册 `configs/forward_observation.yaml` **逐字节不变**（sha256 `ad287c60…`，测试钉住）；legacy 文件**逐字节不变**（sha256 `c1a65ff…`，测试钉住）。
- 唯一引擎（`ShadowForwardEngine`）、唯一事件契约、唯一 eligibility 机器、唯一 receipt 链机制全部复用；gateway 内**无第二管线**（contract switch 在同一适配器内，legacy 分支冻结为证据复现专用，真实采集在 runner 层结构性拒绝 legacy，exit 5）。
- 5 日门槛、$0、iex-only、≤3 标的、Paper/Live 禁止、交易主机硬拒全部沿用。

## 兼容与状态隔离

- 旧 JSONL **不迁移、不伪造**：receipt 链记录携带 `protocol_hash`，journal 的 `SESSION_STARTED` 亦然——跨协议续写会在 `protocol_binding_ok` 处失败（测试：新协议窗口用 legacy 预注册评估 → binding False → audits False → PASS 拒绝）。
- Runner 显式选择：默认 `--config` = 新 v2 协议文件；legacy 仅可显式传参加载（证据复现），`check-config --config legacy` 可读、`collect --config legacy` 结构性拒绝（exit 5 `LEGACY_CONTRACT_INVALID`）。
- 新默认状态目录 `artifacts/state/s8-shadow-r2` 与 legacy `s8-shadow` 分离；回执记录新增 `receipt_schema: s8-receipts-v2`（`disconnect_eligible` 分类）。

## 许可与凭证边界（T3.3/T3.4）

- `license_attestation.operator_confirmed` 是**配置声明**，不是已验证账户事实；新增操作者本地核对清单（`operator-preflight.md`，凭证不写入仓库）；未确认 → 预检保持 `BLOCKED_ENV`。
- 进程内 GET-only 守卫 ≠ 凭证原生只读：操作者需在主机/容器层独立实施仅 `data.alpaca.markets:443` 出站、阻断两个交易主机与泛互联网；无法证明则如实标 `HOST_EGRESS_ISOLATION_UNVERIFIED`。应用层不绕过系统代理（urllib 沿用 getproxies；办公代理 192.168.1.2:8080 差异由操作者环境自证）；不为通网放宽主机白名单。
