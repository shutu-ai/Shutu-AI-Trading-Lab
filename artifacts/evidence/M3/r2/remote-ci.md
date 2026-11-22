# M3-R2 — 远端 CI 验证记录（REMOTE_VERIFIED）

- 推送授权：用户 2026-11-22 明确指示"提交推送"
- 推送 1：`4ae119f..9e640bd → origin/main`（EXIT=0，2026-11-22）
- 推送 2：`9e640bd..906bf6f → origin/main`（EXIT=0，CI 缺陷修复）
- **受测代码 SHA：`906bf6f`**（= R2 全部代码 + 证据 + CI 缺陷修复；docs-only
  后续提交除外，见文末）
- CI run：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44998829308

## 一手日志证据（gh run view --job --log 提取，2026-11-22，经代理 192.168.1.2:8080）

| Job | 结论 | 原始日志行 |
|---|---|---|
| test (ubuntu-latest)（id 137135622818） | success | `572 passed in 64.78s (0:01:04)` |
| test (windows-latest)（id 137135622437） | success | `572 passed in 482.39s (0:08:02)` |

- 远端 572 = 本地 572（分母一致，无 skip/xfail 差异）。
- **REMOTE_VERIFIED 成立**：`M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED /
  E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)`；范围不变（S=INCONCLUSIVE/N_A、
  R=NOT_STARTED、BLOCKED_DATA、BROKER_BEHAVIOR_UNVERIFIED、SEALED_NOT_MATERIALIZED、
  M3_GATE=USER_PENDING 均不变；本记录不构成 M3 关闭签批）。

## 完整尝试历史（如实，含失败）

### run 44996858265（SHA `9e640bd`，R2 代码+证据提交）

| attempt | job | 结论 | 一手日志 | 失败归因 |
|---|---|---|---|---|
| 1 | ubuntu `137129641102` | **failure** | `1 failed, 571 passed in 56.11s` | **既有 M2 A6** `test_a6_strict_process_proof.py::TestA6ConcurrentClaimRace::test_50_rounds_concurrent_claim_race`（`assert all(r["type"]=="ready")`，真实进程 spawn 竞争的握手时序异常）。R2 diff 零触碰 fault_injection/oms；本轮 50 项新测试全部通过 |
| 1 | windows `137129641246` | cancelled | — | matrix fail-fast 连带取消 |
| 2 | ubuntu `137131749629` | success | `572 passed in 43.07s` | A6 复跑即绿（flake 行为坐实） |
| 2 | windows `137131749396` | **failure** | `1 failed, 571 passed in 604.69s` | **R2 自身测试缺陷**：`test_code_identity.py` 的 CRLF/LF 确定性测试前置断言假设工作树为 LF，Windows runner（autocrlf 检出 CRLF）即炸。已在 `906bf6f` 修复（fixture 自构造 LF 基线再派生 CRLF，不依赖检出模式；测试目的不变）。该失败同时实证：真 CRLF 检出上其余 571 项（含全部身份归一化测试）通过 |

### run 44998829308（SHA `906bf6f`，修复提交）— VERIFIED 基准

双 job 全 success，`572 passed` ×2（上表）。

## A6 flake 记录（观察项，不弱化、不擅自处置）

跨 5 次 A6 实际执行（attempt1-ubuntu FAIL、attempt2-ubuntu PASS、
attempt2-windows PASS、final-ubuntu PASS、final-windows PASS）出现 1 次握手
时序失败——共享 CI runner 负载敏感类的既有风险，与本轮 diff 无因果证据。
处置留待用户决定（可在后续轮次单独加固 A6 的 ready 握手鲁棒性；本轮未改其
断言与超时）。

## 文档提交说明

本文件所在的 docs 提交为 docs-only（不触碰 src/tests/configs）；受测代码 SHA
即 `906bf6f`。与 r1 先例一致（受测 `dde7a8b`，记录提交 `4ae119f` 跟随）。
