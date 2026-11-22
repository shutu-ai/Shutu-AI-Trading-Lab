# Shutu AI Trading Lab — M3-R1 独立复核摘要

日期：2026-11-21  
仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
受测提交：`dde7a8bc1d1a435ecd3a3108f86677be71eb55c5`  
远端 main：`4ae119fe17ab7118075adb2899def69eafe2cd78`（文档与证据补录）  
Actions：https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44938095081

## 复核通过的事实

- GitHub Actions Ubuntu、Windows 均成功，各 **522 passed**（原始 job 日志已核对）。
- `check_architecture`：5 包、26 文件、0 违规；`scan_secrets`：369 tracked files、0 findings；`verify_live_blocked` 通过。
- A7 五轮 crash-holder 真实 `os._exit(37)` 证明已恢复，新测试位于 `tests/fault_injection/test_a7_targeted_proof.py`；M3 新增专属 `tests/backtest/`、`tests/validation/`、研究包架构测试。
- M3-R1 包括 B0/B1/B2、风险/成本敏感性、Decimal 账本、cohort 与 synthetic Holdout 演练；策略报告明确不将合成数据当作真实 OOS 或 Alpha。
- 旧 1,080 故障矩阵的零违例主张有仓库专项记录；不得把其当作 1,080 个 pytest 用例。

## 源码级待补强点

### R2-P0-1：code_hash 未包含核心执行源码

`scripts/run_m3_baselines.py` 约第71–72行用 `sha256_hex((.../run_m3_baselines.py).read_bytes())` 计算所谓 `code_hash`，但真正影响计算的 `src/trading_lab/backtest/engine.py`、`arms.py`、`validation` 实现不在计算范围；故不同的研究行为可能沿用相同 code_hash。需要完整且稳定的研究执行代码身份，并保留原有实验身份不篡改。

### R2-P1-1：冻结 min_bars 与官方数据矛盾

`configs/evaluation_protocol.yaml` 定义 `validation.min_bars: 100`；`scripts/run_m3_baselines.py` 的 `PRICES` 仅20条。代码没有在“官方运行”路径阻断此不符合工程门槛的样本。应将20根数据降级为 smoke-only，同时使用新冻结批次/协议和100+ bar 完全合成数据验证真正样本门，不得擦除旧实验预算。

### R2-P1-2：账本恢复前缺验链，尾截断缺独立锚

`src/trading_lab/validation/ledger.py::_load_existing()` 直接逐行 `_apply()` 并更新 `_prev`；`verify_chain()` 虽验证保留链的链接和 digest，但无已知外部 head/entry_count 的条件下，尾部截断后剩余记录仍可自洽。应验证后恢复并明确锚点信任边界；若不能做到，不可声称“全部删除/截断均可检测”。

## 裁决

`M3_R1_REMOTE_VERIFIED` 成立于既有522项测试和合成工程范围；但在 M3 最终关闭前建议完成**最小 M3-R2 研究完整性补证**。M2 已闭的 MOCK_ONLY 工程门不因上述研究缺口自动撤销。

保持：`M3_GATE=USER_PENDING`、`S=INCONCLUSIVE/N_A`、`R=NOT_STARTED`、`BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`SEALED_NOT_MATERIALIZED`。不自动批准 M3.5/M4、真实数据或真实券商访问。
