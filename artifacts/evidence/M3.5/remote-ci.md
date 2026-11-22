# M3.5 远端 CI 记录

## 状态

**`CI_REMOTE_PENDING`** — 本阶段未推送（任务书 §0.2：默认仅本地 commit，push 需单独用户授权）。

## 事实

- 本地验证（Python 3.13.15，Windows 11）：见 `verification.log`——全量回归、M2 故障矩阵、架构检查、密钥扫描、live-blocked、smoke、官方回放，全部通过（EXIT CODE 如实记录）。
- **未验证**：Ubuntu 平台、Windows 远端 runner、远端双矩阵。在用户授权 push 且双平台 CI 全绿之前，任何 `REMOTE_VERIFIED` 表述都不成立。
- 受测代码 SHA：以推送时刻 `git rev-parse HEAD` 为准（本阶段完成后记录于最终 commit）。
- 已知观察项：M2 A6 ready 握手进程竞争 flake（历史失败 run 见 `docs/reviews/M3-engineering.md`）。若远端重现，按任务书 S0.5 处理（确定性 READY 同步小范围 RED→GREEN，50 轮竞争数量不减，单独报告），不得以 skip/xfail 掩盖。

## 解除条件（按任务书 S7）

1. 用户单独授权 push；
2. 远端 CI 双平台（Ubuntu + Windows）全绿；
3. 在此记录 run ID、受测 SHA、双矩阵通过数，方可将状态写为
   `M3.5_OFFLINE_HARNESS_REMOTE_VERIFIED`——但仍不得升级为完整真实前向 E=PASS
   （真实窗口未开始，`S=INCONCLUSIVE` 不变）。
