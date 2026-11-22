# 离线预演与退出码实测（offline-rehearsal — T9.4，LOCAL_ONLY，2026-11-22）

> 全部在一次性临时目录 + 净化进程环境执行：剥离 `APCA_API_KEY_ID` /
> `APCA_API_SECRET_KEY` / `APCA_API_KEY_SECRET` / `S8_OPERATOR_AUTHORIZATION`，
> 清空 `HTTP(S)_PROXY`/`http(s)_proxy`。零真实 API 访问、零凭证读取、零网络
> 请求（所跑三个子命令本身无网络路径）。未触碰既有或未来真实 state dir
> （`artifacts/state/` 不存在）。原始输出见本目录 `*-rehearsal-*.log`。

## 1. 命令级预演（净化环境）

| 命令 | 退出码 | 关键结果（原始日志） |
|---|---|---|
| `check-config` | **0** | `bars_endpoint: ranged_daily_bars`、`feed: iex`、`plan: basic_free`、`min_trading_days: 5`、`paper_write: NOT_AUTHORIZED`、协议 `m35-s8-real-shadow-readonly-v2`（schema v3） |
| `selftest --state-dir <tmp> --no-evidence` | **0** | `outcome: OFFLINE_HARNESS_PASS_WITH_SCOPE`、`events_synthetic: true`、`problems: []`、honesty 原句："fixture events are never real trading days; they can never mint PENDING_FORWARD_WINDOW or PASS" —— 结果标 `SIMULATED_REAL_SHAPE_TEST_ONLY` 语义，零真实日数、零 PASS |
| `status --state-dir <tmp>` | **0** | `forward_window_status: NOT_STARTED`（空状态合法查询，exit 0） |

临时目录已销毁（`TEMP-CLEANED`）；`--no-evidence` 保证 selftest 不写任何
evidence 文件。

## 2. 契约回归（unit/integration，mock/哨兵，不执行 collect）

全量 pytest（`full-regression.log`，本轮实跑）：

- 结果：**960 passed, exit 0**（= 944 基线零删减 + 16 T8 测试；无 skip/xfail）
- 覆盖核对（与 T9.4 要求逐项对应）：
  - 收据故障 6/7、快照/链绑定完整性：`tests/s8_gateway/test_completion_integrity.py`（T7，18 用例）
  - 终态 8、凭证/网络隔离哨兵、离线 `repair-completion`：`tests/s8_gateway/test_terminal_collection_fence.py`（T8，16 用例）
  - 凭证门/无凭证 BLOCKED_ENV（exit 3/4）：`tests/s8_gateway/test_runner_cli.py`
  - E-Gate 不变量（synthetic 拒 PASS、5 全覆盖日、断连/重复恢复、0 订单）：`tests/s8_gateway/test_forward_gate_persistence.py` 等
- 均为进程内 mock/哨兵（dummy feed 返回空传输应答、`socket.socket` 密封、
  preflight 记录型哑元），不发起任何真实连接，不执行 `collect`。

## 3. 历史证据污染检查（T7/T8 事故路径的显式复检）

T7/T8 RED 期间的污染模式：未修复代码经 `cmd_collect(evidence_dir=EVIDENCE_DIR)`
向 `s8-contract-r1/` 写入未跟踪模拟 `real-forward-window-status.json`。
本轮显式复检：

- 本轮全部预演/回归**未调用任何带 evidence_dir 的成功完成路径**
  （selftest 用 `--no-evidence`；回归为 mock/哨兵；预演三命令不产生快照）；
- 预演与回归后检查：`artifacts/evidence/M3.5/s8-contract-r1/` 无
  `real-forward-window-status.json`；`git status --short` 中无任何历史证据
  目录的未跟踪/修改条目（唯一历史改动为回归自改写的 M2 三份日志——按既有
  协议从 HEAD 恢复，新鲜输出仅存本目录 archive，见 verification 记录）；
- 结论：本轮零历史证据污染。

## 4. 不在本轮范围（如实标注 NOT_RUN / 未执行）

- `collect` / `collect --complete` / `repair-completion` CLI 实跑：**NOT_RUN**
  （任务书明令禁止执行 collect；repair/completion 的退出码契约由 16+18 个
  单元/集成用例覆盖，本轮不重复实跑）；
- 任何网络出口探针：**未执行**（属操作者 §C，模板见
  `operator-attestation-template.md`）；
- 真实凭证注入/校验：**未执行**（零接触）。
