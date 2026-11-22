# T8 CI 证据回填（remote-ci-backfill — T9.1，LOCAL_ONLY，2026-11-22）

> 数据来源：T9 会话内经 GitHub 官方 CLI（`gh run view` / `gh run view --job
> --log`）对 run 45035699101 的**新鲜再核验**（基线核对同场执行，见
> `baseline.md`），非复用 T8 会话旧输出。

## Run 标识

- Run：[`45035699101`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45035699101)
- Event：`push`（`0b1f3b7..ca74989 main`，用户单独授权的推送）
- Head：`ca749890521ce0d16f31b0984a3f4f0518176369`（= origin/main，父链
  `ca74989 → 0b1f3b7` 现场核对一致）
- Conclusion：`success`

## Job 与测试矩阵（原始日志核对）

| Job | ID | 结论 | 耗时 | pytest（原始日志行） |
|---|---|---|---|---|
| test (windows-latest) | `137248862025` | ✓ success | 6m6s | `960 passed in 331.30s (0:05:31)` |
| test (ubuntu-latest) | `137248862171` | ✓ success | 1m30s | `960 passed in 75.73s (0:01:15)` |

960 = 既有 944（零删减）+ 16 个 T8 契约测试
（`tests/s8_gateway/test_terminal_collection_fence.py`）。

## 静态门步骤（双平台全部 success）

- Environment check ✓
- Architecture boundary check（0 violation）✓
- Secret leak scan ✓ —— 官方日志原句：
  `scan_secrets: scanned 551 tracked files, 0 findings`
- Paper runtime live-artifact gate ✓ —— 官方日志原句：
  `paper config ok: configs/paper/runtime.example.yaml (PAPER/PAPER_TEST_ACCOUNT)`、
  `verify_live_blocked: paper runtime contains no live artifacts — PASS`

## 警告（不影响判断）

GitHub Actions 平台层 annotation：Node.js 20 deprecation
（`actions/checkout@v4`、`actions/setup-python@v5` 被强制运行于 Node 24）——
与本项目代码、测试结果、门判定无关。

## Scratch 日志处置（T9.1.2）

未跟踪文件 `r3/ci-run-45035699101.log`（T8 会话的 `gh run watch` 原始输出 +
追加的核验摘要，无凭证/无敏感环境信息）经**只读**检查后：本文件已覆盖其全部
核验事实（run/job/计数/门/警告），scratch 全文不入库，工作区移除以保持整洁；
不覆盖任何旧证据。

## 范围声明（诚实性）

- 本 run 只证明 **T8 代码**：不证明 T9 及之后的文档/代码，不证明真实 Alpaca
  API 行为、行情最终性或主机级出口隔离；
- **此回填不意味着 `API_VERIFIED`**——`API_VERIFIED=NONE` 不变；
- 状态索引以追加式说明：`r3/review.md` 成文时的
  `T8_CI=REMOTE_PENDING` 是**提交当时**的真实状态，其文末追加节注明推送后
  升级为 `T8_CI=REMOTE_VERIFIED`（本文件为完整核验依据）；
- `T9` 本轮无代码变更，`T9` 文档本身的"CI"概念不适用（纯文档提交不触发
  双矩阵语义变化；若随未来 docs 推送触发 CI，仅证明文档提交不破坏测试）。
