# 前向验收门的持久事实来源（forward-gate-proof，T2）

> 测试：`tests/s8_gateway/test_forward_gate_persistence.py`。**全部窗口均为 `SIMULATED_REAL_SHAPE_TEST_ONLY`**（夹具形状事件走真实管线），只证明机制；不是真实交易日，不计入任何实际窗口。

## PASS 判据现在来自链计算事实（不来自自报）

`window_facts_from_journal()`（唯一事实源，无第二评估机）从 receipt 链 + ForwardJournal 计算全部资格字段：

| 字段 | 来源（可重放、可审计） |
|---|---|
| `disconnect_recoveries` | receipt 链时间线：`disconnect_eligible=true` 的 FEED_ERROR（仅 TRANSPORT/429/5xx；**400/401/403/404 是操作者侧错误，永不算断连**）之后出现成功 RECEIPT = 一次恢复 episode |
| `duplicate_recoveries` | journal `DUPLICATE` 条目数——引擎对重复投递的**审计过的拒绝二次消费/评分**记录 |
| `audits_passed` | `receipt_evidence_ok`（双链 verify + receipt↔journal 绑定）**且** `protocol_binding_ok`（每个 SESSION_STARTED 的 protocol_hash/environment 与当前预注册一致）——**默认 False，缺失即 False** |
| `trading_days_observed` | 全覆盖日（每个预注册标的当日均有有效 bar）计数；部分日披露不计数 |

## 机器行为证明（正例 = 机制；全部标注 SIMULATED）

- 5 全覆盖夹具日 + 断连 episode（.TRANSPORT 失败 → 下一周期恢复回执）+ 重复投递 → `claim='PASS'` 评得 **PASS / COMPLETE**，且 `S=INCONCLUSIVE / PAPER_NOT_RUN / broker_writes=0` 不变。
- 同一事实窗口打 `events_synthetic=True`（自测/夹具来源）→ PASS 仍拒绝：**字段是必要条件，真实到达记录才是充分条件**。

## 负例（全部拒绝，无一通过）

| 负例 | 拒绝原因 |
|---|---|
| 断连无恢复（最后周期失败） | `disconnect_recoveries == 0` |
| 无重复投递 | `duplicate_recoveries == 0` |
| 4 全覆盖日 + 1 部分日 | `trading_days_observed == 4 < 5`（部分日不计数） |
| 跨协议污染（新协议窗口用 legacy 预注册评估） | `protocol_binding_ok=False → audits_passed=False` |
| 篡改回执链 | 链校验失败 → `receipts_verified=False → audits=False` |
| 合成旗标 | `events_synthetic=True` → 永不 PASS |

## 持久化（完成时落盘）

`--complete` / 窗口完成时：

1. receipt 链追加 `WINDOW_COMPLETED` 记录（`facts_digest`、eligibility、协议哈希、环境）；
2. `forward-window-evaluation.json`（schema `s8-forward-window-evaluation-v1`）写盘：facts + digest + eligibility；
3. 任何后续 `status` **重算** facts 并比对 digest——测试证明：完成评估与重算一致；篡改快照 digest 即被检出。

真实窗口的 PASS 因此具备**可重放、链绑定、篡改可检**的持久事实来源；不存在 `setdefault(True)`、硬编码布尔或"模拟成功充当真实恢复"的路径。
