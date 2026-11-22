# s8-contract-r1 基线（T0.1）

> Task ID: `M35-S8-REAL-FEED-CONTRACT-AND-FORWARD-GATE-R1-20261122`
> 授权：用户 2026-11-22 会话指令（逐字要点：本轮仅执行 T0–T5；只提交本地代码和证据，**不自动推送**；禁止读取真实 Alpaca 凭证、调用真实行情 API、执行任何 Paper/Live 下单、购买数据服务或启动 M4；完成后停在 `M3.5_GATE=USER_PENDING`，等待单独授权推送及首次真实采集）。

## 仓库基线（实查）

| 项 | 值 |
|---|---|
| 本地 HEAD | `1b3460ee41cfd712e07b97398e1707b11318ab25`（docs-only：`remote-ci.md`、`s8/verification.log`、`docs/reviews/M3.5-s8-readonly.md` 状态行回填，3 文件 +33/−3） |
| origin/main | `2e189eb499bfb1cd5c9e73a266c93c0f3008ad18`（`1b3460e` **未推送**，已确认无覆盖/无冲突——本轮新增内容不触及该 3 文件） |
| 远端 CI | run `45013402697`：`completed success`，head=`2e189eb`，ubuntu-latest ✓ / windows-latest ✓（`gh run view --json` 实查 2026-11-22） |
| 历史结论 | `S8_OFFLINE_ENGINEERING_REMOTE_VERIFIED`（887+887 passed）——**只证明旧代码**，本轮整改后新 SHA 不复用该结论 |

## 冻结协议与身份（整改前）

| 文件 | SHA-256（整文件） | 说明 |
|---|---|---|
| `configs/forward_observation.yaml`（合成 v1） | `ad287c600e2be1223aaf0f4b70f6f811eedb145f0ccabe900c1b818b9d622a01` | 本轮零改动 |
| `configs/forward_observation_s8_real.yaml`（真实 v1，含伪造 latest 形状） | `c1a65ffb926169504aeae755452f0490bf79490d2508a228a4e9aa58bcfcf54e` | **冻结为 `LEGACY_INVALID_VENDOR_CONTRACT`**，零改动；新协议另起文件 |

协议 hash（canonical，loader 计得）：合成 `m35-shadow-synthetic-replay-v1`、真实 legacy `m35-s8-real-shadow-readonly-v1`（`d3446826…`）；本轮新增 `m35-s8-real-shadow-readonly-v2`。旧协议在其存在期内 **0 API_VERIFIED、0 real forward day**，不允许产生真实 PASS。

## 测试分母（整改前）

- 全量回归 **887 passed**（run 45013402697 双矩阵）＝ M3.5 基线 686 + S8 新增 201；
- 本轮新测试**单列分母**，不删减/skip/xfail/软化任何既有断言；M2 1,080 故障矩阵原样保留重跑。

## 历史证据

`artifacts/evidence/M3.5/`（含 `s8/`）与全部 M2/M3 证据**只读**，本轮零改写。
