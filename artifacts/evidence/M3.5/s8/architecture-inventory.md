# S8-T0 范围与架构盘点（Scope & Architecture Inventory）

> 审批依据：`artifacts/evidence/M3.5/s8/authorization-check.md`（2026-11-22 签批）
> 基线：`d85d105`（本地 = 远端）；受测代码族 `906bf6f → de39b40 → a06e0dc → d85d105`

## REUSE（原样复用，零修改消费者）

| 机制 | 来源 | 唯一权威职责 |
|---|---|---|
| `ForwardJournal` + 外部锚 | `apps/trading_daemon/journal.py` | 前向事件持久链（锁→观察→评分恰好一次） |
| `SessionLock` | `apps/trading_daemon/session.py` | 单写者租约（陈旧接管审计） |
| `ShadowForwardEngine` / `ForwardEvent` | `apps/trading_daemon/engine.py` / `envelope.py` | 预测锁定/PIT 门/幂等/异常拒绝的唯一状态机 |
| `B2ForwardRule`（MA 2,4） | `apps/trading_daemon/rule.py` | 冻结透明规则（等价性测试绑定回测 B2） |
| `AuditLog` | `src/trading_lab/security/audit.py` | 追加式哈希链（journal 与**新 receipt 链**共用同一机制） |
| `MarketCalendar` / ET / DST | `src/trading_lab/data/calendar.py` | 唯一日历权威（真实假日表为声明输入，非推断） |
| `canonical_digest` | `src/trading_lab/security/canonical.py` | 唯一规范化摘要 |
| `ForwardCohort` | `src/trading_lab/validation/cohorts.py` | 锁先于可得的一次性评分纪律（机械强制） |
| M1 数据准入 | `src/trading_lab/data/acceptance.py` | U-1 修复后语义不变（见 MODIFY） |

## MODIFY（最小修改，行为经测试锁定）

1. `data/acceptance.py` — **M1 U-1 最小修复**（签批条件 2）：`VendorFacts` 四个能力字段改为封闭词表（`{yes,no,unknown}` / `{event_level,eod_only,none,unknown}`），非法值构造即 fail-closed（`VendorFactsError`，`DataAcceptanceConfigError` 子类）。修复前 RED 复现见 `u1-red-reproduction.txt`；`evaluate_purpose` 冻结语义不变。**不解除全市场历史 `BLOCKED_DATA`**。
2. `trading_daemon/engine.py` — 准入分支：`dataset_admission == "pinned"`（v1，行为逐字节不变）走原 fixture-hash 门；`receipt_content_hash`（仅 v2 真实预注册类暴露）跳过 pin 门。`EVENT_CONSUMED` 载荷新增 `dataset_hash` 字段（receipt 链交叉核验的绑定键）。
3. `trading_daemon/prereg.py` — 新增 `dataset_admission` 属性（v1 恒为 `pinned`）；加载器拒绝范围不变。
4. `trading_daemon/eligibility.py` — 移除阶段性 `or True` 守卫，改为 fail-closed 默认（facts 默认 synthetic、receipt 证据默认未证）；`PASS` 需 ≥ preregistered `min_trading_days`、断线与重复恢复、0 订单、审计通过。合成范围行为不变（既有 6 项测试全绿）。
5. `trading_daemon/report.py` — `mode/account_environment/source_evidence_level` 自预注册派生（v1 输出不变）；`trading_days_observed` 自 eligibility 读取（v1 为 0）。
6. `trading_daemon/identity.py` — 身份清单支持 `extra_files/extra_packages`（默认调用范围不变）；新增 `build_s8_forward_identity`（S8 范围：daemon + gateway + v2 配置 + 自测夹具 + S8 runner；父身份仍链接 M3-R2）。
7. `scripts/check_architecture.py` — 新增 gateway 平面规则（见 ADD-3）。

## ADD（新增，含唯一消费者）

1. **`apps/market_gateway/`** — S8 只读采集平面（唯一消费者：`scripts/run_m35_s8_shadow_real.py` 与测试）：
   - `http_client.py` — `GuardedGetClient`：GET-only、https、主机白名单、路径白名单、禁重定向、禁请求体、`parse_float=Decimal` + 拒绝 NaN/Infinity 常量、凭证值不入日志/回执。交易主机（api/paper-api.alpaca.markets）在构造与每请求双重拒绝。
   - `prereg_real.py` — v2 真实预注册加载器（fail-closed：feed=iex、plan=basic_free、≤3 标的、窗口启用、≥5 日、许可签批、GET-only、禁交易主机、日历表校验）。
   - `alpaca_feed.py` — IEX 日线适配器：确定性 event_id、session-close 归一化（DST/半日市）、保守 PIT（ts_available=接收时刻）、回执记录、质量问题/断网均入回执链。
   - `quality.py` — 原始载荷校验（schema/有限正值/OHLC 关系/成交量/符号回显/当日 vs 陈旧 vs 未来）。
   - `feed_session.py` — 采集循环（feed → 回执链 → `run_replay`；会话跨周期开放）+ 窗口事实（journal↔receipt 链交叉绑定）+ 预检双门（授权标记 + 凭证可见性）+ 离线自测编排。
   - `offline_fixtures.py` + `fixtures/selftest_bars.json` — 自测脚本化传输（同样过 GuardedGetClient）+ 文档化形状夹具（合成数值，非网络录制）。
2. **`configs/forward_observation_s8_real.yaml`** — 真实前向预注册 v2（`m35-s8-real-shadow-readonly-v1`，首次真实观测前冻结）。**`configs/forward_observation.yaml` 逐字节未动**（签批条件 4）。
3. `check_architecture.py` gateway 规则 — 唯一允许网络的平面：禁 brokers/oms/risk、禁 socket/ssl/http.* 原语与全部第三方 SDK、仅允许 urllib（经 guarded client）；`apps/trading_daemon` 禁网规则不变。
4. `scripts/run_m35_s8_shadow_real.py` — 官方 S8 runner（check-config/selftest/collect/status；collect 双门：授权标记 → 凭证；无凭证 = `BLOCKED_ENV` exit 3，标记缺失 = `AUTHORIZATION_REFUSED` exit 4）。

## REPLACE / REMOVE

无。未删除任何旧实现、旧测试、旧证据；无迁移。

## POC-ISOLATE

本阶段未引入任何 POC/`artifacts/poc` 依赖（架构检查器碎片规则继续覆盖 gateway）。

## DEPENDENCIES

**零新增依赖**。采集传输使用 stdlib `urllib`（guarded client 的唯一网络根，架构规则固化）；JSON 解析 stdlib `json`（`parse_float=Decimal`）；时区沿用既有 `tzdata`（Windows）。无第三方 SDK（alpaca/requests/websockets 等在 gateway 平面被静态禁止）。pyproject.toml 零改动。

## 唯一职责声明（防第二实现）

- 第二 Shadow 引擎 / 第二 PIT 规则 / 第二 OMS：**未创建**（真实事件走同一 `ShadowForwardEngine`）。
- 第二 journal：**未创建**；receipt 链是新职责（传输到达证据），明确不复制 `ExperimentLedger` 预算语义，复用 `AuditLog` 机制。
- 真实日历：**未硬编码推断**；预注册声明表 + `MarketCalendar` 权威。
