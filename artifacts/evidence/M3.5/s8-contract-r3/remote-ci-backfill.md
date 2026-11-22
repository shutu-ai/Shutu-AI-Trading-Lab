# T7 CI 回填归档（remote-ci-backfill — T8.4，LOCAL_ONLY，2026-11-22）

> 数据来源：本轮（T8 会话内）通过 GitHub 官方 CLI（`gh run view` / `gh run list` /
> `gh run view --job=<id> --log`）对 run 45031453603 的**新鲜再核验**，
> 非复用 T7 会话中的旧输出。

## Run 标识

- Run：[`45031453603`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45031453603)
- Event：`push`（`a0b1f58..0b1f3b7 main`，用户单独授权的推送）
- Head：`0b1f3b7900b9fe385bf4579e8126f1641f15d5ca`（与 origin/main 一致）
- Conclusion：`success`（总耗时 9m13s，触发于 2026-11-22T14:11:25Z）

## Job 与测试矩阵

| Job | ID | 结论 | 耗时 | pytest |
|---|---|---|---|---|
| test (ubuntu-latest) | `137235738944` | ✓ success | 1m16s | **944 passed in 63.26s** |
| test (windows-latest) | `137235739166` | ✓ success | 9m9s | **944 passed in 517.75s** |

944 = 既有 926（零删改）+ 18 个 T7 新契约测试
（`tests/s8_gateway/test_completion_integrity.py`）。

## 静态门步骤（双平台全部 success）

- Environment check ✓
- Architecture boundary check（`python scripts/check_architecture.py`）✓
- Secret scan ✓
- Paper runtime live-artifact gate ✓ —— 官方日志原句：
  `paper config ok: configs/paper/runtime.example.yaml (PAPER/PAPER_TEST_ACCOUNT)`、
  `verify_live_blocked: paper runtime contains no live artifacts — PASS`

## 警告（不影响判断）

GitHub Actions 平台层 annotation：Node.js 20 deprecation
（`actions/checkout@v4`、`actions/setup-python@v5` 被强制运行于 Node 24）——
属于 runner 平台弃用告警，与本项目代码、测试结果和门判定无关。

## 范围声明（诚实性）

- 本 run 只证明 **T7 代码**（`0b1f3b7` 的 926+18 测试在双平台通过）：
  **不证明本轮 T8 代码**（终态围栏 + `repair-completion` 为 T8 新改动，
  `T8_CI=REMOTE_PENDING`，需未来授权推送后的新 run）；
  不证明真实 Alpaca API 行为、行情最终性或主机级出口隔离；
  不证明操作者 A–C（仍 `PENDING_OPERATOR`）。
- 未跟踪工作文件 `r2/ci-run-45031453603.log`（T7 会话留下的 gh watch 原始输出，
  无敏感环境信息）经只读检查后**不入库**；其全部事实已由本文件的官方日志
  再核验覆盖，该工作文件已从工作区移除以保持整洁。
- `r2/review.md` 的历史 `LOCAL_ONLY` 结论保持原文不动，仅以追加式回填说明
  T7_CI 状态升级（见该文件末尾追加节）。
