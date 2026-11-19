# Shutu AI Trading Lab — M-1 独立审查整改任务书

> **Task ID:** M-1-REVIEW-REMEDIATION-001  
> **版本:** v1.0 · 2026-11-19  
> **执行者:** Codex CLI  
> **目标仓库:** `https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> **基线:** `main`，审查时 HEAD `582d9e063ab7b321a960caa813ae5a17a7453844`（执行前务必重新核对）  
> **执行边界:** 仅 M-1 阶段后审查整改；**不启动 M0、M1、M2，不连接 Alpaca Paper/Live，不处理任何资金**  
> **阶段出口:** `M-1 REVIEW_ACCEPTED_WITH_ACTIONS` → 修订证据完整后 `M-1_REVIEW_CLOSED / M0_START_APPROVAL_PENDING`（是否关闭由人工复核批准）

## 0. 任务性质与不可突破的约束

本任务是对已完成 M-1 的**定向审查整改**，不是重做 M-1，也不允许修改项目 v2.1 的 P0–P4、M-1～M11（含 M3.5）研发路线。

1. 保留 **ADR-001** 已作出的方案 B 选择：`alpaca-py + 自有最小 OMS`，不重新选型、不引入新交易框架。
2. 保留 M-1 三轨结论：`E=PASS（测试覆盖范围内）`、`S=N_A / evidence_state=NOT_EVALUATED`、`R=NOT_STARTED`；整改不应伪装成新的 POC 或策略证据。
3. **不能操作或索取任何券商 API Key**；不发起 Alpaca 网络连接、不发单、不创建 Live 实例、不批准实盘。
4. 本次只修文档、工件路径和未来阶段安全契约。**不更改 fake broker / OMS 的交易逻辑以“顺便修复”**；如发现当前 POC 潜在不安全路径，应记录为待实现的 M2 阻断条件。
5. 不回写或重写 Git 历史，不执行 `filter-branch`/`filter-repo`/强制推送，不追踪 qlib 大型数据集、虚拟环境、凭证和运行时密钥。
6. 执行前检查 `git status --porcelain`、`git rev-parse HEAD` 和 `git remote -v`。若工作区存在与本任务不相关的变更，停止并报告，不覆盖他人工作。
7. **只完成本任务就停止**；不得自动启动 M0，所有下一阶段必须由用户明确授权。

## 1. 先读取的权威文件

按顺序核对以下仓库文件及其引用链（不要只依赖本任务书中的快照）：

- `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`
- `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`
- `docs/adr/ADR-001-core-selection.md`
- `docs/reviews/M-1-engineering.md`
- `docs/reviews/M-1-strategy.md`
- `docs/reviews/M-1-real-capital.md`
- `docs/licenses/third-party.md`
- `artifacts/poc/M-1/fake_broker_poc/README.md`
- `artifacts/poc/M-1/fake_broker_poc/fake_broker/{oms,journal,fencing}.py`
- `artifacts/poc/M-1/fake_broker_poc/tests/test_03_crash_recovery.py`
- `artifacts/poc/M-1/fake_broker_poc/tests/test_04_dual_executor_fencing.py`
- `artifacts/evidence/M-1/candidates/qlib/SHASUMS256.txt`

**已知事实：** M-1 fake broker 契约日志为 `20 passed in 18.34s`，仅代表本地契约验证；`BROKER_BEHAVIOR_UNVERIFIED` 未解除。现有数据供应商结论只是 M1 的输入，不是最终数据准入。

## 2. 整改任务与验收条件

### R1 — 统一 fake broker 证据日志路径（必做，P1）

**问题：** M-1 工程报告引用：

```text
artifacts/evidence/M-1/fake_broker/pytest_run_1.log
```

但审查时实际跟踪的是：

```text
artifacts/poc/evidence/M-1/fake_broker/pytest_run_1.log
```

**操作：**

- 核实当前真实文件位置和 Git 跟踪状态。如果仍如上，优先用 `git mv` 将日志归位至规范路径 `artifacts/evidence/M-1/fake_broker/pytest_run_1.log`。
- 仓库内搜索所有引用（Markdown、manifest、脚本注释），只修正受影响路径，不能替换/重造日志内容。
- 若另有相同文件，先对比 SHA-256、长度和内容，不得静默覆盖；记录去重动作。
- 确认最终**只有一个规范证据路径**且所有引用可解析。

**验收：** `git ls-files` 中存在规范日志；日志仍含 `collected 20 items` 与 `20 passed`；旧错误引用为零；提交前后日志 SHA-256 未变化（仅迁移）。

### R2 — 修正 qlib 数据 SHA256 清单引用（必做，P1）

**问题：** 许可证台账引用了被忽略的 `.../qlib/data/SHASUMS256.txt`；实际追踪的是：

```text
artifacts/evidence/M-1/candidates/qlib/SHASUMS256.txt
```

**操作：**

- 更新 `docs/licenses/third-party.md` 及其他报告的清单引用，统一到上方可跟踪路径。
- 保留两个 zip 数据包原始文件名、完整 SHA256 和来源 URL；说明 zip/解压大文件仍保留在本机且被 Git 忽略。
- 必要时添加最小复现说明：下载原始文件后对其**原始 zip 字节**计算 SHA-256，对照追踪清单，而不是对解压目录计算；不可声称本次重新验证了远端文件，除非实际重新下载/校验并留证。
- 不把大型数据添加到 Git，也不变更现有已审计的历史重写映射。

**验收：** `git ls-files` 能定位清单；许可证文件中的路径存在；全部 qlib 数据清单相关内部链接无死链；Git 无新增大型数据文件。

### R3 — 将 UNKNOWN 订单恢复风险写为 M2 硬阻断项（必做，P0 安全契约）

**问题：** 当前 POC 的 `recover()` 在 `SUBMITTING` 且查询未找到订单时可能触发 `_send_once()`。在真实券商网络下，**“暂时查无订单”不是“已证明请求从未发送”**。当前 20/20 测试不能证明生产 `exactly-once`。

**操作：**

- 在 `docs/reviews/M-1-independent-review.md` 记录源码证据及反例，并指明 `artifacts/poc/M-1/fake_broker_poc/fake_broker/oms.py` 中 `recover()` 的相关路径。
- 在两份 v2.1 计划的 **M0 安全契约**与 **M2 OMS 任务/验收**同步增补，不改变阶段次序：
  - 发送前崩溃与发送后 ACK 前崩溃须区分可证明事实与未知状态。
  - `SUBMITTING/UNKNOWN` 且可能已发出的请求，除非有**可信未发送证据**或经过真实 Alpaca Paper 验证的**明确幂等保证**，否则不得补发。
  - `get_order(client_order_id)` 返回暂时未找到、429、5xx、超时或对账不可用，不得直接视作“未发送”；进入 `HALT_NEW_RISK` 并保留日志，重试只针对只读查询。
  - 对存在不确定结果的旧意图，系统不得生成“替代意图”绕过暂停；解除须有操作人显式授权和已完成的持仓/订单对账证据。
  - M2 必须用 fake broker 注入延迟可见性、请求送达但响应丢失、网络分区/重启、重复执行者和查询不可靠场景。所有未证实时分支应 0 新增风险、0 盲重发。
- 明确 **M0 只冻结设计契约，M2 才实施 OMS 代码修复与故障注入**；本任务不得对现有 POC 直接做未授权代码替换。

**验收：** 两份计划 M0/M2 章节规则无矛盾；审查报告有对应代码证据与反例；新增 M2 验收可以转化为自动测试断言。

### R4 — 明确 fencing 的可信执行边界（必做，P0 安全契约）

**问题：** fake broker 通过 `valid_fences` 拒绝旧 epoch，但 Alpaca API 并不天然识别自定义 fencing epoch。

**操作：**

- 在 M0 设计契约、M2 OMS 验收及独立审查报告中说明：**单账户只能有一个获得券商写权限的可信执行者**；旧 epoch 须在**唯一订单出口**被拒，不能把本地 token 交给券商当作远端保证。
- 对本地单机起步，优先最小化可信出口；不要直接添加 Redis、Kafka、微服务等未经证明必要的组件。
- 明确所有可能直接访问 Alpaca 写 API 的进程、SDK/MCP/Agent 工具都不能绕过这个出口；包括异常恢复和操作维护脚本。
- 将模拟网关 `valid_fences` 的行为列为 mock-only 证据，真实 broker 的权限/网络行为仍 `BROKER_BEHAVIOR_UNVERIFIED`。
- M2 验收应包含 stale executor 休眠后恢复、租约过期、两个实例同时启动、旧 token 写入、网关不可用时 fail-closed 等负例。

**验收：** 两份文档对“谁有券商写权限”具有唯一一致定义；Mock fencing ≠ 实券商 fencing 的限制在审查报告明确记载。

### R5 — Python 3.13 环境偏差与配置一致性（必做，P1）

**问题：** M-1 按已获用户批准的 Python 3.13.15 实施，而 v2.1 执行计划的 M0 仍存在 Python 3.11 字样。

**操作：**

- 审阅实际 v2.1 中所有 Python 版本声明，最小范围同步为**本项目 M0 候选运行基线 Python 3.13**，并保留 M-1 的实际 `3.13.15` 证据。
- 如存在不适配依赖，标注为独立受控 venv/WSL2 兼容性待验，不假装 qlib/RD-Agent 问题已经解决。
- 将版本偏差写入独立审查报告；不在本轮创建 venv 或安装、升级依赖。

**验收：** M0 任务中不存在相互冲突的 Python 版本要求；本项目运行基线与研究侧隔离环境可区分；无新依赖安装。

### R6 — 独立审查记录与阶段门（必做，P1）

新增唯一文件：

```text
docs/reviews/M-1-independent-review.md
```

内容至少包括：

1. 审查基线（仓库、实际 HEAD、审查日期）、材料与证据链接；
2. 三轨状态保持：`E=PASS（限定范围）`、`S=N_A / NOT_EVALUATED`、`R=NOT_STARTED`；
3. `ADR-001=ACCEPTED_WITH_SCOPE`（选择 B，使用范围与剩余风险）；
4. R1–R5 问题列表：严重度、证据、整改动作、责任阶段、验证方法、状态；
5. 已完成的路径整改证据（原路径/新路径、实际 SHA256、引用搜索结果）；
6. 仍未解除：`BROKER_BEHAVIOR_UNVERIFIED`、M2 故障注入规模、M1 数据许可/质量等；
7. **正式状态：`M-1_REVIEW_REMEDIATION_COMPLETE / M0_START_APPROVAL_PENDING`（仅在整改验证全部通过时）**；此状态不是 M0 授权，不能产生真实交易许可；
8. 记录 `approver=USER_PENDING`，不得由 Agent 代签审查或阶段放行。

**注意：** 只在报告和计划中添加最小必要修订，不重写 ADR-001 的选型事实、不重新生成此前测试结果。根据既有规范，原有 `docs/reviews/M-1-{engineering,strategy,real-capital}.md` 仍为三轨验收的唯一规范报告；独立审查是补充，不取代三轨报告。

## 3. 自检流程与质量门

完成编辑后，Codex 至少执行以下**离线、只读或文档检查**（若环境缺少命令，使用等价工具并记录输出）：

```powershell
# 在仓库根目录

git status --short
git rev-parse HEAD
git ls-files artifacts/evidence/M-1/fake_broker/pytest_run_1.log
git ls-files artifacts/evidence/M-1/candidates/qlib/SHASUMS256.txt

# 搜索可能残留的错误路径 / 旧版本要求
rg -n 'artifacts/poc/evidence/M-1/fake_broker|candidates/qlib/data/SHASUMS256|Python 3\.11|BROKER_BEHAVIOR_UNVERIFIED' docs artifacts/poc/M-1/fake_broker_poc/README.md

# 文档审查：检查 M0/M2 的 UNKNOWN/fencing 条款与验收对齐
rg -n 'UNKNOWN|HALT_NEW_RISK|fencing|single.writer|单账户|幂等|M0|M2' docs/plans
```

建议重跑本地 fake broker 回归测试（**只在完全离线且不触发任何券商连接时**），并将本次日志放在独立的审查整改证据目录，不覆盖原始 M-1 日志：

```powershell
python -m pytest artifacts/poc/M-1/fake_broker_poc/tests -q
```

如该测试需要安装依赖、修改环境或联网，则不强制重跑：标记 `NOT_RERUN` 与原因，不得宣称新测试 PASS。对于 MD 变更，建议生成 markdown lint 或内部链接检查结果（可用简易脚本，勿新增重量级组件）。

**审查验收门（全部满足才可标记 `REMEDIATION_COMPLETE`）：**

| 检查项 | 通过标准 |
|---|---|
| R1 日志路径 | 规范位置存在，旧引用 0；内容 SHA-256 未变化 |
| R2 qlib SHA | 单一可跟踪路径；引用全可解析；无大数据入库 |
| R3 UNKNOWN 契约 | M0/M2/审查报告三处一致，不将查无记录视为未发送证明 |
| R4 fencing 契约 | 券商写权限单出口、陈旧执行者 fail-closed，mock/真实边界明确 |
| R5 Python 版本 | M0 基线与 M-1 已批准的 Python 3.13 一致，例外有记录 |
| R6 审查报告 | 三轨结论不被篡改，未决项、责任阶段、用户审批状态齐全 |
| 结构 | P0–P4、M-1～M11（含 M3.5）完整、原计划不推翻 |
| 安全 | 无真实券商调用/密钥/资金操作，无 M0 自动实施 |
| 仓库 | 无不相关文件变更、无历史重写、无大型数据文件 |

## 4. 提交、停止和最终汇报规范

1. 输出 `git diff --stat` 和关键文档差异摘要；保存 `git diff --check` 结果。
2. 如已获该仓库正常提交权限，可**仅提交本任务整改**，建议提交信息：`docs(M-1): close independent review findings and align stage contracts`；**不要自动 push，除非用户已单独授权本次推送**。
3. 最终报告应按以下结构：
   - R1–R6 各项 `PASS / OPEN / BLOCKED`，附具体文件路径；
   - M-1 三轨状态与 ADR-001 状态；
   - `BROKER_BEHAVIOR_UNVERIFIED` 等下一阶段阻断条件；
   - 实际运行的检查命令、退出码与结果；
   - 变更文件清单、commit SHA（如已提交）、工作树状态；
   - **明确宣告停止在 `M0_START_APPROVAL_PENDING`**。
4. 不应将“证据补档完成”写成“OMS 实盘安全已验证”，也不得直接推进 M0/M2。

## 5. 可直接粘贴给 Codex 的启动指令

```text
请在当前 Shutu-AI-Trading-Lab 仓库，仅执行文档
Shutu_AI_Trading_Lab_M-1_Review_Remediation_Codex_Task.md 所定义的
M-1 独立审查整改（R1～R6）。

开始前读取两份 docs/plans v2.1、ADR-001、M-1 三轨报告和相关 POC 代码；
核对实际 HEAD、工作树和证据位置。

严格只做定向修订：修复 fake broker 日志及 qlib SHA 清单的路径引用；
补充 UNKNOWN 不得盲重发、真实券商 fencing 不由 mock 自动保证的安全契约；
同步 Python 3.13 环境基线；新增 M-1-independent-review.md。
不得重写选型，不修改 OMS 交易逻辑，不连接券商、不索取密钥、
不运行 Paper/Live，不启动 M0/M1/M2，不允许 Agent 自批阶段门。

完成后执行文档/路径静态检查，必要时离线重跑当前 POC 的单元测试，
逐项报告 R1～R6 结果、证据、剩余风险和 git diff。
只有全部整改项满足才标记 REMEDIATION_COMPLETE；
最后停在 M0_START_APPROVAL_PENDING，等待我审查。
```

---

**本文件只授权 Codex 执行 M-1 审查整改范围内的工作，不构成券商连接、策略部署、实盘启用或下阶段工程启动授权。**
