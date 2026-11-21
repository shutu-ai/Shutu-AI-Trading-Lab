# A4 基线（M2-A2-CONCURRENCY-EVIDENCE-CLOSE-AND-M3-GATED-002）

- 远端审查基线：`b7d11aa`（run `44878925093` 双矩阵 334 passed——旧测试范围）
- 本地 HEAD：`29ecf54`（领先 1 提交；**已核实 docs-only**：仅整改报告 CI 状态 2 行更新；保留未覆盖）
- 回归分母：334 用例；故障矩阵 1,080 独立实例（seed=20261120）
- 上一任务书 A2 量化门槛核对：
  - 双线程同 COID ≥100 轮受控竞争：**NOT_MET**（仅有单轮确定性竞争 + 本地 5 次稳定性重跑）
  - 双真实进程 ≥50 轮竞争：**NOT_MET**（仅有单轮）
  - 本轮补齐（新增分母单列，不改写历史）
- 工程基线：`b7d11aa` 的 `OrderJournal.claim_send_attempt` / `_transaction` / `BrokerEgress` 唯一实现；**优先补测试与证据，不改生产组件**（若竞争暴露真实缺陷才最小修复）
