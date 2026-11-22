# M3.5 远端 CI 记录

## 状态

**`M3.5_OFFLINE_HARNESS_REMOTE_VERIFIED`**（2026-11-22 用户授权 push；双平台 CI 全绿）
完整真实前向 E=PASS 仍不成立：真实窗口未开始，`S=INCONCLUSIVE` 等状态不变（见下）。

## 授权与推送

- **push 授权**: 2026-11-22，用户在本会话明确指令"推送"（对应执行报告列出的待签批项 ①）。
- **推送范围**: `e1301c5..a06e0dc` → `origin/main`，三个本地 commit：
  - `de39b40` feat(M3.5-S1-S6) — daemon/预注册/runner/测试/检查器
  - `4d7acfb` chore(M3.5) — M2 自再生日志（披露谱系）
  - `a06e0dc` docs(M3.5) — 授权/基线/证据/三轨报告

## CI 结果（一手 job 日志核对）

| 项 | 值 |
|---|---|
| Run | [`45006808270`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45006808270)（push 触发，2026-11-22T09:17:22Z） |
| 受测 HEAD | `a06e0dc`（daemon 代码在 `de39b40`，docs-only 差异至 `a06e0dc`） |
| ubuntu-latest | ✓ **686 passed** in 55.70s（job 137160108678） |
| windows-latest | ✓ **686 passed** in 355.44s（job 137160108361） |
| 本地对照 | 同为 686 passed（Python 3.13.15，见 `verification.log`） |
| 注解 | 仅 Node.js 20 deprecation 提示（actions 基建噪音，非测试失败） |
| A6 flake | 本 run 未重现（windows 6m24s 全绿，一次通过） |

## 状态升级（严格限定）

- `CI_REMOTE_PENDING` → `M3.5_OFFLINE_HARNESS_REMOTE_VERIFIED`
- **不升级项（保持原样）**：`E=PASS_WITH_SCOPE(SYNTHETIC_REPLAY_ONLY)`（远端绿 ≠ 真实前向窗口）、
  `REAL_FORWARD=NOT_STARTED_OR_BLOCKED_ENV`、`S=INCONCLUSIVE`、`R=NOT_STARTED`、
  `BLOCKED_DATA`、`BROKER_BEHAVIOR_UNVERIFIED`、`M1 U-1 UNRESOLVED`、
  `PAPER_NOT_RUN`、`M3.5_GATE=USER_PENDING`。
- REMOTE_VERIFIED 的语义：离线合成 Shadow 工程夹具在双平台可复现——仅此而已。

## 后续门（各自需单独签批）

S8 真实行情来源 / Alpaca Paper 写 / M4 启动 —— 本记录不构成其中任何一项的授权。
