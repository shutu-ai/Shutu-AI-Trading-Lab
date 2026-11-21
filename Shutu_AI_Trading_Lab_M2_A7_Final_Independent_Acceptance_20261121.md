# Shutu AI Trading Lab — M2 A7 最终独立验收复核

**复核日期**：2026-11-21  
**仓库**：https://github.com/shutu-ai/Shutu-AI-Trading-Lab  
**审核对象**：M2/A5/A6/A7 累计 Mock 安全工程证据；非真实 Broker 认证、非 Live 准入。  
**建议裁决**：`M2_ENGINEERING_ACCEPTABLE_FOR_USER_CLOSURE / E=PASS_WITH_SCOPE(MOCK_ONLY)`；阶段门当前仍 `M2_GATE=USER_PENDING`。

## 1. 已通过远端核对的事实

| 项目 | 证据 | 结果 |
|---|---|---|
| main HEAD | `1988cab264e6f76ee280eb245e3ce16378be9ba2` | 已在远端 |
| 最后实际运行的代码 SHA | `379bd72b19a6ee416e48444c4e4bab6e1eb8f120` | 通过 |
| GitHub Actions | https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44912904901 | success |
| Ubuntu pytest | 同次 Run 的 `test (ubuntu-latest)` 原始 Job 日志 | **347 passed in 31.20s** |
| Windows pytest | 同次 Run 的 `test (windows-latest)` 原始 Job 日志 | **347 passed in 340.06s** |
| 架构检查 | 两 Job 日志 | 3 packages / 18 files / 0 violations |
| SHA 关联 | `1988cab` 的 parent 是 `379bd72`，仅更新 `docs/reviews/M2-a7-independent-closure.md` | 后记 docs-only；不宣称 CI 在 `1988cab` 上运行 |

CI 中的秘密扫描、Paper runtime live-artifact gate 和环境检查步骤为 success；`smoke_mock`、`git diff --check` 和单独故障矩阵本地检查结果来自提交的日志，不是同一个 GitHub 工作流的独立步骤。1,080 是故障实例分母，而不是 1,080 个独立的 pytest 测试用例。

## 2. 源码核对摘要

- `tests/fault_injection/test_a7_targeted_proof.py` 中 5 轮 `test_claim_holder_crash_auto_halt` 的真实子进程调用 `claim_send_attempt`，将领取结果写至 fact 文件，随后 `os._exit(37)`；父进程验证退出码、claimed=True 和新 SQLite 连接中的 `SEND_CLAIMED`。这是正确的 claim-holder crash 主体。
- 在重建 OMS 前，fresh `KillSwitch` 的 `is_halted()` 为 False；执行 `recover()` 后为 True，且 `still_unknown` 包含对应意图。`src/trading_lab/oms/engine.py::recover()` 源码先获得新 fence 并调用 `_ks.set(...)`，符合自动 HALT 设计。
- A7-T1 仍使用 `if new_decision.allow:` 的分支，**不应以它单独声称 OMS 强制拒绝**；A7-T2 的 `test_oms_deny_preapproved_after_halt` 使用 HALT 前真实批准决策、HALT 后无条件调用 `oms.submit()`，验证 `HALT_NEW_RISK` 及 FakeBroker 零新增订单，补齐独立 OMS 拒绝证据。
- A7-T1 本身没有再执行“第二次 claim”断言，也没有在 `recover()` 之后新建第三个 KillSwitch 对象断言持久 HALT。此两项如需写为累计证明，应引用 A5/A6 或其他现存测试，不得归因于 A7-T1 单项测试。
- A6 用 spawn + `Barrier(2)` 并发取 claim；A5/A6/A7 累积支撑 Mock 范围内的原子性与恢复不变量；不等价于真实经纪商出口/跨宿主 E2E 证明。

## 3. 文档与证据质量说明（非新一轮安全阻断）

1. `docs/reviews/M2-a7-independent-closure.md` 存在历史基线描述与当前远端已推送状态不一致的字段；新任务只补遗，不回写原历史结果。
2. A7 本地报告存在“347 = 338 + 9”以及“新增 7 项”并列描述。准确拆分：A5 338 基线 + A6 新增 2 + A7 新增 7 = **347**。注意将 A6 340 作为 A7 的直接基线。
3. A7 evidence-manifest 仅列 `baseline.md` 与 `full_checks.log`，不能说其覆盖全部证据；如需整体验证，建立单独目录的清单，避免更改旧结果。
4. `379bd72` 及其祖先提交修改过 A2/A5/A6 历史日志。保持可审计提交历史、标注重生成的路径和原因，不将这些日志作为不可变文件的直接证明。
5. `created_orders_by_intent()==0` 是 FakeBroker 最终创建数，不自动等于独立 Port-entry 计数。OMS HALT 提前返回从静态逻辑支持未调用出口，若报告涉及“0 port entries”，应引用专门的 Port-entry 计数测试。

上列问题未构成已复现的生产安全漏洞；建议在 M2 关闭补遗中诚实注明，而非无新故障证据继续扩大安全整改。

## 4. 建议人工关闭范围

`M2_GATE=CLOSED` **仅在用户明确签批后生效**，并固定：

- `E=PASS_WITH_SCOPE(MOCK_ONLY)`；风控、OMS、SQLite Journal、同宿主并发 claim、FakeBroker 故障恢复的工程验收完成。
- `S=N_A`，`evidence_state=NOT_EVALUATED`，`R=NOT_STARTED`；不得声称已证明真实 Alpha 或实盘安全。
- `BLOCKED_DATA(全市场研究)`、`U-1=UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、真实 BrokerPort E2E / 跨宿主 fencing 未验证，继续列为后续阶段独立阻断项。
- `M3_START_APPROVAL_PENDING` 与 `M2_GATE` 是两个不同权限：关闭 M2 不自动授权 M3；尤其不授权真实券商 API、Paper 前向或 Live。

**最终建议：接受 M2 Mock 范围工程阶段的人工关闭申请；在用户签批前状态继续 USER_PENDING。**
