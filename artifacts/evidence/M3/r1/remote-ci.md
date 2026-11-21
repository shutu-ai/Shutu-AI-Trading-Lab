# M3-R1 — 远端 CI 验证记录（REMOTE_VERIFIED）

- 推送授权：用户在 2026-11-21 会话中明确指示"推送"
- 推送：`3505799..dde7a8b → origin/main`（EXIT=0）
- 被测 SHA：`dde7a8bc1d1a435ecd3a3108f86677be71eb55c5`
- CI run：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44938095081

## 一手日志证据（gh run view --job --log 提取）

| Job | 结论 | 原始日志行 |
|---|---|---|
| test (ubuntu-latest)（id 136949069626） | success | `522 passed in 19.94s` |
| test (windows-latest)（id 136949069758） | success | `522 passed in 350.85s (0:05:50)` |

- 远端 522 = 本地 522（分母一致，无 skip/xfail 差异）。
- CI 绿 + 本轮全部工程硬门（T1 恢复 GO / T2 冻结 / T3–T6 负例与检查器 / T7 全清单
  EXIT=0）→ `E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)` 之 **REMOTE_VERIFIED**
  成立；范围不变（S=INCONCLUSIVE/N_A、R=NOT_STARTED、BLOCKED_DATA、
  BROKER_BEHAVIOR_UNVERIFIED、M3_GATE=USER_PENDING 均不变）。
