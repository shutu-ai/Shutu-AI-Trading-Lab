# M3-R2 T0 — 只读基线、一手证据与 RED 计划

- 日期: 2026-11-21
- 任务书: `Shutu_AI_Trading_Lab_M3_R2_Research_Evidence_Integrity_Codex_Task.md`（Task ID `M3-R2-RESEARCH-EVIDENCE-INTEGRITY-20261121-001`）
- 本目录 `artifacts/evidence/M3/r2/` 为本轮新建；`M2/a2|a5|a6` 与 `M3/r1` 历史证据零写入。

## 1. 仓库基线（命令实跑记录）

| 命令 | 结果 |
|---|---|
| `git rev-parse HEAD` | `4ae119fe17ab7118075adb2899def69eafe2cd78` |
| `git rev-parse origin/main` | `4ae119fe17ab7118075adb2899def69eafe2cd78`（本地=远端） |
| `git status --porcelain` | 仅 2 个未跟踪文件：`Shutu_AI_Trading_Lab_M3_R1_Independent_Review_20261121.md`、`Shutu_AI_Trading_Lab_M3_R2_Research_Evidence_Integrity_Codex_Task.md`（用户的本地审查/任务文档，本轮保留不提交、不改动） |
| `git diff dde7a8b..HEAD --stat` | 3 个文件、+26/−2，全部为文档/证据补录（`remote-ci.md`、`verification.log`、`M3-engineering.md`），零源码差异 |
| `git diff 4ae119f..HEAD` | 空（HEAD 即 4ae119f） |

未执行 `reset --hard` / `force push`；历史全部保留。

## 2. CI 一手核验（本轮实跑 gh，非转抄）

- run `44938095081`：`headSha = dde7a8bc1d1a435ecd3a3108f86677be71eb55c5`，conclusion `success`。
- Job `test (ubuntu-latest)`，**id `136949069626`**，success，原始日志行：`522 passed in 19.94s`。
- Job `test (windows-latest)`，**id `136949069758`**，success，原始日志行：`522 passed in 350.85s (0:05:50)`。
- **文档 SHA 声明**：当前 `main` HEAD `4ae119f` 不是该 CI 的受测 SHA（CI 受测 `dde7a8b`）；`4ae119f` 仅在 `dde7a8b` 之上追加了文档/证据补录（git diff --stat 可复核），源码零变化。

## 3. 三个缺口在本 HEAD 的现场确认（源码级）

### R2-P0-1（P0）code_hash 仅覆盖 runner

- `scripts/run_m3_baselines.py:71-72`：`code_hash = sha256_hex((REPO_ROOT/"scripts"/"run_m3_baselines.py").read_bytes())` —— 单文件字节哈希。
- r1 官方账本 13 条 entry 全部绑定该值 `c0a9ede5bf4dea02e5a4141f3a494c29291039d678ed3aae2380619d510a8d0f`。
- 真正影响回测结果的 `src/trading_lab/backtest/engine.py`、`arms.py`、`validation/*` 及 import 期依赖（contracts、security 包、顶层 `__init__`）均不在范围内 → 改算法不改 runner，身份不变。
- 失败模式 RED 计划：隔离副本中改 `engine.py` 字节 → legacy 单文件哈希不变（可证明），新身份契约必须改变。

### R2-P1-1（P1）min_bars=100 vs 官方 20 根

- `configs/evaluation_protocol.yaml`（v1.1，hash `48dee8...`）`validation.min_bars: 100`、`min_trades_for_stats: 10`。
- `run_m3_baselines.py` PRICES 恰 20 根；`r1/experiment-ledger.jsonl` 每条 TRIAL `calendar_span_days: 20`、`effective_observations: 21`。
- 运行路径无任何样本门检查（协议加载器/arms/runner 均无 min_bars 引用；grep 证实引用仅存在于协议 YAML 与其探针测试）。
- r1 三轨报告均未声称 100 根门 PASS（如实），但代码层缺"不足即拒正式结论"的机制性防线 → RED：sample-gate API 不存在；20 根数据在现路径可出"官方工程运行"结果而无门判定。

### R2-P1-2（P1）账本恢复前未验链、尾截断无锚

- `src/trading_lab/validation/ledger.py:69-79 _load_existing()`：逐行 `json.loads` 后直接 `_apply()` 并前移 `_prev`，**先重放后无校验**；链断裂/中间篡改的账本可加载并继续追加。
- `verify_chain()`（:243-262）只验证保留部分的 prev/digest 自洽——对**尾部截断、整文件替换、清空**（不保留尾锚）不可检测；无外部 head/entry_count 锚。
- 无并发写保护：两个进程可同时以同一 `prev` 追加（无锁文件、无单写者判定）。
- RED 计划：中间篡改/删尾/清空/半行截断 ×（无锚/有锚）×（重启加载/继续追加）矩阵；双进程并发写。

## 4. 不变量核对（本轮必须保持）

| 不变量 | 基线状态 |
|---|---|
| M2 A7 五轮真实 crash（`os._exit(37)`）+ HALT 负例 | 在 `tests/fault_injection/`，本轮只增不减 |
| 522 项回归目标 | r1 CI 逐 job 一手核验如上；本轮全套件目标 ≥522 |
| 1,080 故障矩阵（9 类） | 专项独立于 pytest 计数，r1 `fault-matrix-r1.txt` 留证，本轮重跑 |
| `SYNTHETIC_ENGINEERING_ONLY` / `BLOCKED_DATA` / `U-1 UNRESOLVED` / `BROKER_BEHAVIOR_UNVERIFIED` / `SEALED_NOT_MATERIALIZED` | 不触碰任何解封路径 |
| r1 官方账本/summary/证据 | 只读；r2 一律新目录新文件 |

## 5. RED 清单（先于任何实现编写）

| 文件 | 覆盖 |
|---|---|
| `tests/validation/test_code_identity.py` | T1：新身份契约（scope/排序/归一化/缺失文件/缓存排除/跨进程一致/legacy 对比） |
| `tests/validation/test_sample_gate.py` | T2：sample gate API、99/100/101 边界、sessions≠曲线点、trade-stats N_A、v2 批次治理 |
| `tests/validation/test_ledger_integrity_r2.py` | T3：加载前验链、身份/计数一致性 fail-closed、外部锚、锁与并发写、BATCH_INIT、崩溃半行 |

RED 结果记入 `red-tests.log`；GREEN 后同一文件零弱化复跑。
