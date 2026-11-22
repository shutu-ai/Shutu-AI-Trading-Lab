# Shutu AI Trading Lab — M3-R2 研究证据完整性定向补强（Codex 任务书）

> Task ID: `M3-R2-RESEARCH-EVIDENCE-INTEGRITY-20261121-001`  
> 评审日期：2026-11-21  
> 仓库：`shutu-ai/Shutu-AI-Trading-Lab`  
> 已核实代码 CI SHA：`dde7a8bc1d1a435ecd3a3108f86677be71eb55c5`，Actions [44938095081](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44938095081)，Ubuntu/Windows 均 **522 passed**。  
> 当前远端 `main`：`4ae119fe17ab7118075adb2899def69eafe2cd78`（上一 CI 后的文档/证据补录）。  
> **任务不是 M3_GATE=CLOSED 的签批，也不是 M3.5/M4 的启动授权。执行结束必须 STOP。**

## 0. 审查裁决与范围

M3-R1 的 A7 五轮异常退出安全回归已恢复，回测、研究协议、B0/B1/B2、Holdout 演练、实验账本、5 包架构门及 522 项回归在双平台通过；保持 `E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY) — REMOTE_VERIFIED` 的*既有测试范围*。但源码中存在三项需要在 **M3 最终阶段门关闭前**证明/修正的研究证据完整性问题：

| ID | 级别 | 可复核事实 | 必须验证的失败模式 |
|---|---|---|---|
| R2-P0-1 | P0 | `scripts/run_m3_baselines.py` 的 `code_hash` 当前只取该脚本的字节哈希；`src/trading_lab/backtest/engine.py`、`arms.py`、验证核心与真实策略实现未进入该哈希 | 修改执行/策略计算逻辑但不改 runner，实验记录仍有相同 `code_hash`，导致结果版本无法追责 |
| R2-P1-1 | P1 | `configs/evaluation_protocol.yaml` 声明绑定工程门 `validation.min_bars: 100`；官方运行 `PRICES` 仅 20 根，运行路径未拒绝/降级不足样本 | 不满足预注册样本门，却被报告成完成正式工程样本检验 |
| R2-P1-2 | P1 | `ExperimentLedger._load_existing()` 直接重放 JSONL 而不先校验链；`verify_chain()` 在无外部已知 head/计数锚的情形下无法发现尾部截断 | 被篡改/截断的旧账本可能重新加载、少计试验预算或继续追加研究 |

**拒绝扩大范围**：不重写整个 backtest/OMS，不新增数据库/消息队列/通用事件系统；不把 M3 变成 M3.5、M4 或真实研究项目。只有独立可复现 RED 发现进一步安全问题时才提出最小修正。以上结论是对“某些尚未证明的性质”的审查，不等于已出现真实资金损失或 Broker 安全缺陷。

**绝对不变量**：
- 保留 M2 A7 全 5 轮真实 claim-holder `os._exit(37)` + `recover()` + Risk/OMS 独立 HALT 负例，不准改弱、不准删。
- 保留现有 522 项验收目标、1,080 故障实例、SYNTHETIC_ENGINEERING_ONLY、`BLOCKED_DATA`、`U-1 UNRESOLVED`、`BROKER_BEHAVIOR_UNVERIFIED`、`S=INCONCLUSIVE/N_A`、`R=NOT_STARTED`、`evidence_state=NOT_EVALUATED`、`final_holdout_status=SEALED_NOT_MATERIALIZED`。
- 禁止真实数据供应商/Alpaca Paper 或 Live API、凭证、真实 Holdout、真实账户/资金、启动 M3.5/M4 或自动 push。
- 仅在**已获得 M3 的 SYNTHETIC_ENGINEERING_ONLY 实现授权**范围内操作；不把任务书/聊天建议看成额外授权。M3 关闭和 M3.5 启动仍需分别由用户审批。

## 1. R2-T0：只读基线、真实证据与 RED 计划

1. 阅读 `AGENTS.md`、两份 v2.1 权威计划（Architecture §4.2–4.5、Execution M3）、`docs/adr/ADR-004-evaluation.md`、`docs/reviews/M3-{engineering,strategy,real-capital}.md`、`artifacts/evidence/M3/r1/{protocol-freeze.md,remote-ci.md,verification.log}` 和本任务书。
2. 记录 `git rev-parse HEAD`、`git status --porcelain`、`origin/main`、相对 `dde7a8b` / `4ae119f` 的差异。保留用户其他本地改动；禁止 `reset --hard`、`force push`。
3. 核对 CI 原始 job 日志：run `44938095081`、实际代码 SHA=`dde7a8b`、各 522 passed；文档 SHA `4ae119f` 非该 CI 实际受测 SHA。查收集 ID，不仅只比总数量。
4. 对以下每个缺口先编写**最小独立 RED**（可证明失败/未覆盖，不得模拟日志或降低断言）：
   - 修改 `engine.py` / `arms.py` 的控制字节，runner 不改，当前 code_hash 不变；仅在隔离副本/临时目录做探针，**不得篡改正式历史工件**。
   - 20 bars 的官方样本，在 `min_bars=100` 的约束下，现有执行不能判定为满足该门。
   - JSONL 链中间篡改、最后一条删除/末尾截断（配合事先固定的外部 head/entry_count），重启加载不能继续写研究记录。
5. 证据输出至独立新目录 `artifacts/evidence/M3/r2/`；禁止再覆盖 `M2/a2`、`a5`、`a6` 或 M3/r1 的历史日志。旧测试若会自写历史路径，考虑以临时目录/环境注入隔离，先保存完整证据再修正，不能修改测试目的。

## 2. R2-T1（P0）：真正绑定整个可执行研究实现的 code_hash

目标：**不改 runner 的情况下，改变真正会影响交易结果的代码，必须导致 `code_hash` 改变。**

- 复用 `security.canonical` 或现有 SHA-256 工具，构建**最小、确定性、排序的源码清单**：至少包含 `scripts/run_m3_baselines.py`、`src/trading_lab/backtest/*.py`、`src/trading_lab/validation/*.py`，并检查被执行的 `contracts`/`data`/`security.canonical` 相关语义依赖；实现范围必须可解释且避免排除实际算法依赖。仅保留必要的一处计算权威，不做新的研究版本框架。
- 明确区分 `protocol_hash`、`dataset_hash`、`code_hash`、`git_commit`；研究实验、结果摘要、账本和复算记录必须引用**同一 code_hash**。源代码版本与输入版本有差异时不能悄悄复用旧结果。
- 对源码集合、相对路径、内容 SHA、排序、缺失文件、临时文件/缓存及代码构建来源给出固定契约；必要时记录 Git tree SHA 用于独立复核，但不把含生成日志的整个工作树内容作为不稳定唯一依据。
- **硬测试**：分别变更 engine/arms/validation 的参与源码字节（在隔离样本或临时副本），确认 code_hash 改变；无变更跨进程/Windows/Linux 结果一致；旧 `code_hash` 与新源码组合被拒绝或显式标为无法重现；结果 digest 的实际业务计算也需保持独立确定性。
- 若新的身份规范改变既有实验身份，**不改写/重签 M3/r1 的9个旧记录**；旧版标记 legacy code_hash scope limited，并在新批次使用新身份。

## 3. R2-T2（P1）：100 根样本门与正式/冒烟实验的语义对齐

- 保留原始 **20-bar** 合成数据和其结果作为 `SYNTHETIC_SMOKE_ONLY` 功能冒烟证据；明确它**不满足** `min_bars=100`，不能用于宣称该样本门 PASS。不要删除旧实验历史或调整数据让既有 hash 失真。
- 研究协议/运行路径必须在运行或出具工程结论前检查样本门：不足时拒绝“正式验收 PASS”，或明确报告 `INSUFFICIENT_SAMPLE/INCONCLUSIVE`；0 笔或不足 `min_trades_for_stats` 的臂（例如 B0 现金）只能将交易统计标为 N/A，不得错误地判其全部工程无效。
- 建立**100+ bars 且完全合成**的最小官方独立 fixture，保留现有 B0/B1/B2、成本 ×1/×2/×3、PIT、守恒、决定时点规则；添加 99/100/101 bars 正反门槛测试，验证样本统计与独立事件数量不能混淆。
- **关键治理**：M3/r1 旧账本已经按 v1.1 每臂消费 3/3/3 trial；新的 100+ bar 实验不能通过清空账本、换名字或另造 ledger 绕过已消耗预算。先登记旧运行的受限地位、预声明新实验批次及预算/费用，按 v2.1 的协议变更规则提交**新协议版本与新 hash**，使 v1.0→v1.1→新版本审计链清晰；不得事后更改旧阈值或把旧 9 trials 冒充新数据运行。
- 所有结果仍标记 `SYNTHETIC_ENGINEERING_ONLY`；即使满足100根样本，也不能据此申报真实 Alpha、`HIST_OOS_SUPPORTED` 或真实数据准入。

## 4. R2-T3（P1）：账本复核与不可抵赖边界

- **加载前先验证再重放**：链断裂、digest 错误、协议/code hash 不匹配、计数/预算自相矛盾时 fail closed，不得先更新计数再继续写入。不能因新 batch 合法版本更替误判正常版本迁移，应显式绑定 batch/版本。
- 明确哈希链本身只能检测**保留头尾的中间删除/任意修改**，不能单凭剩余自洽的链检测**尾部截断、整文件替换或全部清空**。若要求这些异常可检测，必须保存由独立位置/版本控制锚定的 `head_digest + entry_count + protocol/code/data/batch`，并在继续写入前比对。记录该锚的信任边界；不要虚称没有独立可信锚的 JSONL 具备不可抵赖性。
- 检查并发写入/重启：两个真实进程共用相同账本时，要么有唯一串行写入者，要么清晰拒绝第二写者；禁止都以同一 `prev` 成功写入却仅在事后 `verify_chain()` 报错。优先小型标准库机制（SQLite 已在仓库可用）或文件锁，**不要无理由引入新数据库/队列**。
- 预先写 RED：中间篡改、删最后一条、空文件替换、截断不完整 JSON 行、旧 hash、重复/并发写入、失败/重试重启后的预算保留；GREEN 后复测恢复读写、预算限额及破坏审计内容。
- 不得为了验证而删除或覆盖现有 M3/r1 `experiment-ledger.jsonl`；将攻击样本与测试工件放入临时目录。

## 5. R2-T4：架构、旧安全回归与证据卫生

- 回测、验证层仍不导入 `oms/risk/brokers`；保留 `scripts/check_architecture.py` 的 **5包扫描**及全部架构负例；不引入第二安全门、第二 OMS/风险权威。
- M2 A7 五轮真实崩溃恢复（逐 ID）与独立 Risk/OMS 拒绝、A6 50轮 spawn Barrier、A2 100轮线程竞争、1,080 故障矩阵等原验收意图完整保留；原 **522 pytest** 测试目标全部保留，新增测试只增不减，不能通过 `skip/xfail/except Exception: pass` 弱化。
- 本轮测试工件按新目录分批留证；**不可避免的历史测试自写日志**必须说明副作用、用 Git 保留历史并逐步重定向测试输出，禁止把新 PID 的重生成结果冒充原始首次 CI 证据。
- 完整执行：`python -m pytest -q`、故障矩阵专项、`python scripts/check_environment.py`、`check_architecture.py`、`scan_secrets.py`、`verify_live_blocked.py`、`smoke_mock.py`、`git diff --check`。每条命令保存真实退出码；保留失败→修复链条。
- 需要验证新的 CI 矩阵 Ubuntu/Windows，只有在**用户另外明确授权 push** 且该新 SHA 两平台真正 PASS 后才能写 `REMOTE_VERIFIED`；没有 push 则 `CI_REMOTE_PENDING`。

## 6. R2-T5：交付物、独立验收与阶段门

至少交付（按实际增量和仓库现有文件组织）：

```text
artifacts/evidence/M3/r2/baseline.md
artifacts/evidence/M3/r2/red-tests.log
artifacts/evidence/M3/r2/verification.log
artifacts/evidence/M3/r2/code-identity-manifest.md
artifacts/evidence/M3/r2/protocol-change-and-budget.md
artifacts/evidence/M3/r2/ledger-integrity-negative-tests.md
artifacts/evidence/M3/r2/architecture-health.md
docs/reviews/M3-r2-independent-closure.md
# 补充原三轨 M3-engineering / M3-strategy / M3-real-capital，不覆盖历史事实
```

每项分别声明 `FIXED / PASS / INCONCLUSIVE / BLOCKED_ENV`，给出实际 SHA、脚本、用例 ID、正反测试分母、日志路径和未达成项。**未完成任一 P0 / P1 必修证据，不得将 M3 关闭建议写成已通过。**

建议最终状态（取决于真实结果，不得预设 PASS）：

- 全部本地满足：`M3_R2_RESEARCH_INTEGRITY_LOCAL_PASS / CI_REMOTE_PENDING / M3_GATE=USER_PENDING`。
- 新 SHA GitHub 双矩阵满足：`M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY) / M3_GATE=USER_PENDING`。
- 不满足：`M3_R2_REMEDIATION_REQUIRED` 或 `M3_R2_INCONCLUSIVE`，列出具体门槛；不得自动更改 M3 门。

**强制 STOP**：完成获批的 R2 工程与验收准备后停止。无论 CI 多绿，都不得擅自置 `M3_GATE=CLOSED`，不得启动 M3.5（真实前向/Shadow/Paper）、M4（AI 研究）、任何真实供应商/Broker、资金操作；不得未经单独授权 push 或代签审批。

## 7. 交给 Codex 的短启动指令

> 阅读此文件、`AGENTS.md`、两份 v2.1 权威计划和 M3-R1 三轨报告。仅执行 M3-R2 T0–T5，先 RED 后 GREEN。最优先修复**真实研究代码未进入 code_hash**，然后补齐**100根门槛与20根官方样本的不一致**以及**账本恢复前未验链/尾截断缺可信锚**。保持 M2 A7 安全回归和 522 项基线、1,080 故障矩阵，严守纯合成离线工程边界。无需重写回测，禁止新 OMS/实盘/真实 Holdout/M3.5/M4，未经授权不 push；最后给出完整证据和阶段门建议后 STOP。
