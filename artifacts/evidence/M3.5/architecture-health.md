# M3.5 架构健康审查（S6）— Architecture Health

> Task ID: `M3.5-SHADOW-FORWARD-ENGINEERING-001` · 2026-11-22
> 复查命令（全部可复现，EXIT CODE 见 `verification.log`）:
>
> ```powershell
> .\.venv-m35-review\Scripts\python.exe scripts\check_architecture.py
> .\.venv-m35-review\Scripts\python.exe -m pytest tests\architecture -q
> .\.venv-m35-review\Scripts\python.exe -m pytest tests\forward_smoke -q
> ```

## 1. 七分类终版

| 分类 | 内容 | 健康 |
|---|---|---|
| REUSE | `security.canonical`、`security.audit.AuditLog`（journal 骨干）、`validation.cohorts`（ForwardCohort 机械校验 + 语义）、`data.calendar.MarketCalendar`（时钟判定）、`contracts`（envelope 语义对齐）、B2 冻结定义（MA(2,4)）、M0/M2 KillSwitch 隔离语义（概念对齐，不借用 PAPER/LIVE 标签）、`research-code-identity-v1` 方案模式 | ✓ 全部直接导入，无复制 |
| MODIFY | `scripts/check_architecture.py`（新增 daemon 平面规则 + `DAEMON_FORBIDDEN_ROOTS` + main 扫描扩展）；`pyproject.toml`（pytest `pythonpath += "."`） | ✓ 唯一架构检查器不变，规则有正反用例 |
| ADD | `apps/trading_daemon/{__init__,envelope,rule,prereg,journal,session,clock,engine,driver,fixture,identity,report,eligibility,__main__}.py`；`configs/forward_observation.yaml`；`scripts/run_m35_shadow_replay.py`；`tests/forward_smoke/`（13 文件，90 项） | ✓ 全部在 M3 身份范围之外 |
| REPLACE | 无 | ✓ |
| REMOVE | 无（无遗弃代码；安全控制零触碰） | ✓ |
| POC-ISOLATE | daemon 与测试零 POC/artifacts 导入；检查器 `artifacts`/`poc` 片段规则覆盖 daemon 平面；负例用例（`import poc_tools`、`from artifacts.evidence import …`）被拒 | ✓ |
| DEPENDENCIES | 零新增（pydantic/pyyaml/pytest 既有；无新框架、无后台服务、无 SQLite 新使用——journal 是 JSONL 审计链） | ✓ |

## 2. 唯一权威职责（无第二实现）

| 职责 | 唯一正式实现 | M3.5 关系 |
|---|---|---|
| 规范化/哈希 | `trading_lab.security.canonical` | daemon 只导入 |
| 追加式审计链 | `trading_lab.security.audit.AuditLog` | daemon journal 骨干（复用，非复制） |
| 研究批次账本/预算 | `trading_lab.validation.ledger.ExperimentLedger` | 未触碰；journal 不复制预算语义（理由见 baseline.md §2） |
| 历史模拟成交引擎 | `trading_lab.backtest.engine.BacktestEngine` | daemon 核心零导入（仅等价性测试在 tests 层使用 arms 的 `_run_ma_cross`） |
| B2 历史臂 | `backtest.arms` | 前向决策函数独立职责（增量、无成交模拟），**决策等价性回归测试绑定**（`test_equivalence_backtest.py`，翻转序列逐点一致） |
| 日历/时钟 | `trading_lab.data.calendar.MarketCalendar` | daemon ReplayClock 只导入 |
| 前向事件状态机/锁/身份 | `apps/trading_daemon`（新职责） | 消费者：官方 runner + 测试；S8 授权后扩展 |
| OMS/KillSwitch 券商写停机 | `trading_lab.oms` / `security.kill_switch` | 未触碰；daemon 无券商写路径（静态 + 运行时 0 调用证明） |
| 单写者锁 | daemon `session.SessionLock`（新增最小租约原语） | 理由：oms FenceCoordinator 绑定 PAPER/LIVE 环境枚举，借用即伪造 account_environment（baseline.md §2） |

## 3. 模块依赖图（终版）

```
scripts/run_m35_shadow_replay.py ─► apps.trading_daemon.{driver,fixture,identity,prereg,report,journal}
                                  └► trading_lab.backtest（仅合成夹具等价层；daemon 核心不导入）
apps.trading_daemon.engine ─► {envelope,rule,journal,clock} + trading_lab.{security.canonical,validation.cohorts}
apps.trading_daemon.journal ─► trading_lab.security.audit.AuditLog
apps.trading_daemon.clock ─► trading_lab.data.calendar
禁止（检查器强制）: trading_lab.brokers / oms / risk / socket / ssl / urllib / http /
                   ftplib / smtplib / telnetlib / xmlrpc / requests / websockets /
                   aiohttp / alpaca / artifacts / poc 片段
```

无调用代码与旧兼容层：无。daemon 内无 deprecation shim、无 `*_legacy` 文件；
M3 侧未为 daemon 添加任何兼容代码（M3 身份范围逐字节未变，见 §5）。

## 4. 风险分层

| 层 | 控制 | 残余风险 |
|---|---|---|
| 事件准入 | envelope fail-closed + 预注册准入 + 市场钟 | 静态检查不拦计算性动态导入（已声明边界，与 M1/M2 相同） |
| 时间纪律 | 锁先于观察（journal 顺序）、ForwardCohort 机械校验、PIT 过滤 | 锚可信度 = 锚文件存储（ADR-002 单机边界，已声明） |
| 恰好一次 | SCORED 链条目 + 重建一致性规则 | 无（构造性保证 + 负例覆盖） |
| 券商隔离 | 导入禁令 + AST 环境取值禁令 + 运行时 0 调用 + 凭证只记可见性 | S8 接入真实源时需重新评审（本阶段范围外） |
| 证据分层 | SYNTHETIC_REPLAY 全程标注；资格状态机拒绝合成冒充 PASS/PENDING_FORWARD_WINDOW | 无新增 |

## 5. 身份与漂移证明

- `forward-daemon-identity-v1`：13+ 文件清单（daemon 包 + runner + 预注册 + 4 个库包 + `__init__`），父身份显式链接 M3-R2 `af7ff10c…`；同树跨进程重算一致（测试）。
- **M3 身份零漂移**：`test_m3_r2_identity_recomputes_unchanged_at_current_head` 在当前 HEAD 重算 `research-code-identity-v1` = `af7ff10c…`（与 `artifacts/evidence/M3/r2/code-identity-manifest.json` 一致）。本阶段对 `src/trading_lab/{backtest,contracts,security,validation}`、`src/trading_lab/__init__.py`、`scripts/run_m3_r2_baselines.py` 零字节修改。

## 6. 已知边界（诚实声明，与 baseline.md §6 一致）

1. 静态检查不覆盖计算性动态导入 / exec / C-extension（平台既有边界）。
2. 锚文件防整文件替换，但锚自身存储可信度即边界（与 M3 账本锚相同）。
3. journal 重建从链推导一切状态；若未来加入新的链上事件类型，必须同步扩展
   `ForwardJournal._rebuild` 一致性规则（当前未知的 kind 只计数，不参与状态机）。
