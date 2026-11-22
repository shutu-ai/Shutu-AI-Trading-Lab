# M3.5-S8 远端 CI 验证记录（remote-ci.md）

| 字段 | 值 |
|---|---|
| 状态 | **`REMOTE_VERIFIED`**（2026-11-22 用户授权推送后，双矩阵一次通过） |
| CI run | [`45013402697`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45013402697)（push 触发，branch `main`） |
| 受测 HEAD | `2e189eb`（docs 提交，含 feat `b7353c4` 全部代码） |
| 推送 | `d85d105..2e189eb`（用户签批"推送"，2026-11-22；签批记录 `authorization-check.md`） |
| ubuntu-latest | **887 passed** in 54.50s（job 137180438950，✓ 1m09s） |
| windows-latest | **887 passed** in 306.72s ≈ 5m07s 测试（job 137180439148，✓ 5m41s） |
| 基线对照 | M3.5 基线 686 + S8 新增 201 = 887；无 skip / 无 xfail / 无阈值下调 |
| 注解 | 仅既有的 Node.js 20 → 24 deprecation 警告（checkout@v4/setup-python@v5，历史 run 同样存在，非本阶段引入） |
| A6 flake | 本 run 未重现（ready 握手一次通过），观察项保持 |

## 一手日志摘要（`gh run view --job --log` 实取）

```
job 137180438950: 887 passed in 54.50s   (ubuntu-latest)
job 137180439148: 887 passed in 306.72s  (windows-latest)
```

## 边界（不变）

- `REMOTE_VERIFIED` 只证明**工程与测试**在双平台绿；不改变任何证据分层：真实前向窗口仍 `NOT_STARTED`（`BLOCKED_ENV`），`S=INCONCLUSIVE`、`R=NOT_STARTED`、`PAPER_WRITE=NOT_AUTHORIZED`、`BROKER_BEHAVIOR_UNVERIFIED`、全市场历史 `BLOCKED_DATA` 保持。
- CI 不使用任何真实密钥（无凭证可用，负例路径照常走通）。
- 本记录提交（docs-only）按 M3.5 `d85d105` 惯例在 CI 绿后回填推送。
