# S8-T4 架构健康（architecture health — S8 后）

> 前置文档：`architecture-inventory.md`（T0 盘点，本文件为其执行后终版确认）
> 检查命令与退出码见 `verification.log`。

## 检查器状态

`scripts/check_architecture.py`：扫描 6 个平面包（src 五包 + `apps/trading_daemon` + `apps/market_gateway`），**0 违规**。

| 平面 | 规则要点 | 测试 |
|---|---|---|
| `trading_lab.data` | 禁 risk/oms/brokers/研究平面（不变） | 既有 |
| `trading_lab.{risk,oms,backtest,validation}` | 平面单向规则（不变） | 既有 |
| `apps.trading_daemon` | 禁 brokers/oms/risk + 13 类网络模块 + artifacts/poc 片段（**S8 后原样保留**） | 既有 14+9 + 实包 |
| `apps.market_gateway`（新） | 禁 brokers/oms/risk + 第三方 SDK（requests/websockets/aiohttp/httpx/alpaca）+ stdlib 原语（socket/ssl/http.*/ftp/smtp/telnet/xmlrpc）；**仅允许 urllib**；artifacts/poc 片段禁用 | 新增 19 拒绝 + 11 合法 + 实包扫描 |

## 身份健康

- `forward-daemon-identity-v1`（S8 范围）：daemon 核心 + gateway 包 + `configs/forward_observation_s8_real.yaml` + `fixtures/selftest_bars.json` + `scripts/run_m35_s8_shadow_real.py` + 四个运行时库包；父身份显式链接 M3-R2 `af7ff10c…`；同树跨进程确定性（测试）。
- **M3 身份零漂移**：U-1 修复仅触及 `src/trading_lab/data/`，不在 M3-R2 身份范围（backtest/contracts/security/validation）；`test_m3_r2_identity_recomputes_unchanged_at_current_head` 在本 HEAD 重算 = `af7ff10c…` 与 `artifacts/evidence/M3/r2/code-identity-manifest.json` 一致（测试绿）。
- 合成身份（默认 `build_forward_identity`）与 S8 身份哈希不同、父链接相同（测试锁定）。

## REUSE/MODIFY/ADD/REPLACE/REMOVE/POC-ISOLATE/DEPENDENCIES 终版

- **REUSE**：见 inventory（全部原样）。
- **MODIFY**：inventory §MODIFY 七项；全部由既有 + 新增测试锁定（含"v1 行为不变"回归：forward_smoke 90 项全绿、eligibility/report 语义测试、`event_id`/admission 的 pinned 路径逐字节语义）。
- **ADD**：gateway 六模块 + 夹具 + v2 预注册 + S8 runner + 架构规则 + 测试（`tests/s8_gateway/` 116 项 + 架构 35 项 + U-1 26 项）。
- **REPLACE / REMOVE**：无。
- **POC-ISOLATE**：无 POC 依赖。
- **DEPENDENCIES**：**零新增**（stdlib urllib/json/decimal；pyproject.toml 未改动）。

## 无第二实现声明

未创建第二 Shadow 引擎/第二 PIT 规则/第二 OMS/第二 journal 语义。receipt 链是唯一新增持久记录（职责：传输到达证据；机制复用 `AuditLog`；不复制 `ExperimentLedger` 预算语义；理由与替代方案见 inventory ADD-1/`feed_session` 模块头）。

## 可复现命令

```
.venv\Scripts\python.exe -I scripts\check_architecture.py   # 0 violations
.venv\Scripts\python.exe -m pytest tests/architecture tests/s8_gateway -q
.venv\Scripts\python.exe -m pytest -q                        # full suite
```
