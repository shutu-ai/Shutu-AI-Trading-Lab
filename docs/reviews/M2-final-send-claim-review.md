# M2 并发 Send Claim 收口审查记录（M2-FINAL-SEND-CLAIM-AND-M3-GATED-001 A 段）

| 字段 | 值 |
|---|---|
| 审查基线 | 远端 `fc9c3d4`（run `44823606397` 双矩阵 330 passed——旧测试范围） |
| 本地基线 | `a4f1413`（领先 1 提交；**已核实 docs-only**：仅整改报告状态 2 行更新；保留） |
| 整改提交 | 见文末（本地，未推送） |
| 执行日期 | 2026-11-21 |
| 范围 | 仅 A 段（并发 Send Claim 原子性收口）；B 段（M3）未获授权未执行 |
| approver | **USER_PENDING**（M2 关闭、推送、M3 启动均待用户决定） |

## A0 — RED 结论（受控竞争，非 sleep/随机）

| 用例 | 整改前行为 | 判定 |
|---|---|---|
| A-RED1 双线程 Barrier 竞争 | **REPRODUCED**：2 次真实 port 进入/单意图（errors=[]，cross-thread sqlite 修复了首版空过） | 竞争窗口真实存在 |
| A-RED2 双进程竞争 | **REPRODUCED**：SELECT-only 模式下 `[True, True]` 双双通过资格检查 | 跨进程窗口真实存在 |
| A-RED3 claim 后崩溃 | spec 测试（claim API 缺席 AttributeError——如实标注为 API 缺席，非缺陷证明） | 待 GREEN 提供 |
| A-RED4 非 SUBMITTING 状态/过期 fence | 已被上一轮 R2 拒绝（`ALREADY_SAFE`，本轮回归锁定） | 无新缺陷 |
| A-RED5 弱断言 | 宽泛 `except Exception: pass` 与 `or True` 残迹 | 已修复 |

## A1/GREEN — 修复内容

1. `journal.claim_send_attempt()`：**单 BEGIN IMMEDIATE 事务**完成 绑定匹配 + `attempts SUBMITTING→SEND_CLAIMED` CAS——并发竞争恰好一人成功（rowcount 仲裁），其余 None 且**绝不重发**；claim 先于 port durable commit；claim 后崩溃 = 保守 UNKNOWN（恢复对账），claim 永不回滚为可重发。
2. journal 全部写事务收口到 `_transaction()` 上下文管理器（进程内锁 + BEGIN IMMEDIATE + finally 释放）——**修复了一个真实原子性缺陷**：`isolation_level=None` 下 `with conn` 不启动事务，多条 INSERT 各自立即提交（与 R4 同根因，全部 6 个写方法统一）。
3. egress 迁移至 claim 入口；SELECT-only 的 `get_send_eligibility` 删除（无消费者残留，无后门）。
4. `FakeBroker` 保持无去重语义（竞争测试用真实 port 入口计数，不靠 mock 掩盖）。

## 验证

| 门 | 结果 |
|---|---|
| 竞争修复 | A-RED1 连续 5 次全绿（修复前确定性复现 2 entries）；A-RED2 atomic_claim 模式恰一 winner；claim 后崩溃保守 UNKNOWN 且 claim 不再授予 |
| 回归 | **334 passed**（330 基线零删减 + 4 竞争测试单列）；分项 140/71/19/14/26/16/48 |
| 故障矩阵 | 原 1,080 实例在新 claim 语义下重跑全绿（`fault_matrix_final.log`，独立分母） |
| 门禁 | environment/architecture（3 包 0 违规）/scan_secrets/verify_live_blocked/smoke_mock/diff --check 全 EXIT=0（`checks.log`） |
| CI | **CI_REMOTE_PENDING**（本任务无推送授权；新 SHA 需独立双平台 PASS） |

## 状态

**`M2_FINAL_SEND_CLAIM_LOCAL_PASS / CI_REMOTE_PENDING / BLOCKED_DATA / BROKER_BEHAVIOR_UNVERIFIED / M2_GATE=USER_PENDING / M3_START_APPROVAL_PENDING`**

B 段（M3）未获授权未执行：M2 正式关闭与 M3 启动需用户分别明确批准。approver = USER_PENDING；不推送、不代签、不越界。
