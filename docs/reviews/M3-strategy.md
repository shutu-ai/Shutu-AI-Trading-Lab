# M3-R1 — 策略验收报告（strategy）

| 字段 | 值 |
|---|---|
| stage_id | M3-R1（SYNTHETIC_ENGINEERING_ONLY） |
| status | **S = INCONCLUSIVE / N_A** |
| evidence_state | NOT_EVALUATED（合成结果最高可声称 ENGINEERING_ONLY，协议字段 `max_claimable_evidence` 冻结此项） |
| strategy_role | NONE |
| final_holdout_status | SEALED_NOT_MATERIALIZED（真实数据 BLOCKED_DATA：无样本、无 ID、无 hash，不作伪） |
| forward_window_status | NOT_APPLICABLE（M3.5 前不适用） |

## 1. 本轮合成了什么（工程证明，非策略证据）

官方合成实验（`scripts/run_m3_baselines.py`，账本 `experiment-ledger.jsonl`）：

| 臂 | 定义 | 官方运行 | 合成净收益（×1 成本） |
|---|---|---|---|
| B0_cash | 现金，无交易（协议未登记现金收益→如实 0.0） | 3（×1/×2/×3） | 0.0000 |
| B1_buy_hold | 合成 ETF 买入持有，含分红/拆股/成本 | 3（×1/×2/×3） | +0.0033 |
| B2_single_rule | 预声明 MA 交叉 (2,4)，仅 Train/Validation 选参后冻结 | 3（×1/×2/×3） | +0.0032 |

- 全部 9 runs 0 失败 0 重试；成本倍数下单调退化（×1 ≥ ×2 ≥ ×3）与费用账目一致。
- 数据集为 20 根手写合成价格（dataset_hash 绑定）；PRICES 本身带上升趋势 →
  **B1/B2 的正净值是数据形状的产物，不构成任何市场判断**。
- 多重比较口径：MA 网格 4 次查询 + 9 次试验全部登记；无校正后 PASS 声称
  （statistical_alpha 门 NOT_SETTABLE → 恒 INCONCLUSIVE）。

## 2. 为什么 S 不可给正结论（守门声明）

1. 合成数据无真实市场微观结构、无公司行动不确定性、无容量/流动性现实。
2. 无独立样本外：HIST_OOS 区域仍是同一合成分段；协议禁止将合成结果标为
   `HIST_OOS_SUPPORTED`，更不可能触发 Live 资格。
3. M9 Sealed Holdout 未物质化（无伪造 sample ID/dataset hash）；候选选择规则已
   预注册但唯一候选要到 M8 末按冻结规则选出。
4. AI vs 规则公平对照（B6/B7）未启动；等试验预算为 B0–B2 官方矩阵已执行
   （per-arm 3/3/3），等经济预算如实 NOT_APPLICABLE_YET。

## 3. S 线后续路径（不自动执行）

真实数据解封（M1 准入 + U-1 解决）→ 真实历史滚动 OOS → M4 激活 AI 臂与美元预算对等
→ M8 末按预注册规则冻结唯一候选 → M9 一次性解封判定
（PASS/FAILED/INCONCLUSIVE/INVALIDATED）。任何一步缺失都维持 S=INCONCLUSIVE。
