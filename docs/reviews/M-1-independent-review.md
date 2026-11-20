# M-1 独立审查与整改记录

| 字段 | 值 |
|---|---|
| Task ID | M-1-REVIEW-REMEDIATION-001（任务书：仓库根 `Shutu_AI_Trading_Lab_M-1_Review_Remediation_Codex_Task.md` v1.0） |
| 审查基线 | 仓库 `https://github.com/shutu-ai/Shutu-AI-Trading-Lab`，审查时 HEAD `582d9e063ab7b321a960caa813ae5a17a7453844`（= M-1 三轨报告推送头，执行前已重新核对一致） |
| 审查/整改日期 | 2026-11-19 |
| 审查性质 | 对已完成 M-1 的定向审查整改；**不是**重做 M-1，不改变 P0–P4 / M-1～M11（含 M3.5）路线 |
| 三轨报告地位 | `docs/reviews/M-1-{engineering,strategy,real-capital}.md` 仍是三轨验收唯一规范报告；本文件是补充审查记录，不取代也不改写三轨结论 |
| approver | **USER_APPROVED**（原 USER_PENDING；用户于 2026-11-20 明确指示："批准关闭 M-1，并授权启动 M0，仅执行 M0 范围，完成后停在 M0 阶段门"。关闭由用户签批，非 Agent 代签） |

## 1. 审查材料与证据链接

- 两份冻结基线：`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`
- 决策与三轨：`docs/adr/ADR-001-core-selection.md`、`docs/reviews/M-1-engineering.md`、`docs/reviews/M-1-strategy.md`、`docs/reviews/M-1-real-capital.md`
- 许可台账：`docs/licenses/third-party.md`
- POC：`artifacts/poc/M-1/fake_broker_poc/`（README、`fake_broker/{oms,journal,fencing}.py`、tests）
- 原始 M-1 证据：`artifacts/evidence/M-1/`（含 `fake_broker/pytest_run_1.log`、`candidates/qlib/SHASUMS256.txt`）
- 本次整改新增证据：`artifacts/evidence/M-1/remediation/`

## 2. 三轨状态保持（整改不改变）

| 门 | 状态 | 说明 |
|---|---|---|
| E | **PASS（限定范围：测试覆盖范围内）** | 维持 M-1 原结论；限定条件见 engineering 报告 §5.3 |
| S | **N_A**，`evidence_state=NOT_EVALUATED` | 不变 |
| R | **NOT_STARTED** | 不变 |

`ADR-001` 状态：**ACCEPTED_WITH_SCOPE** —— 方案 B（alpaca-py + 自有最小 OMS）维持不变；使用范围与剩余风险：真实 Alpaca 订单/权限/网络行为 `BROKER_BEHAVIOR_UNVERIFIED`，OMS 生产级实现与 ≥1,000 次故障注入属 M2；研究侧 qlib/RD-Agent 为候选/暂缓，不构成本 ADR 交易底座的一部分。

已知事实（不再重复验证）：M-1 fake broker 契约日志 `20 passed`（原始日志 `artifacts/evidence/M-1/fake_broker/pytest_run_1.log`）仅代表**本地契约**验证；`BROKER_BEHAVIOR_UNVERIFIED` 未解除；现有数据供应商结论仅为 M1 输入，不是数据准入。

## 3. R1–R5 发现与整改记录

### R1 — fake broker 证据日志路径（P1）→ **PASS（已整改）**

- **发现**：工程报告引用规范路径 `artifacts/evidence/M-1/fake_broker/pytest_run_1.log`，但文件实际被跟踪在 `artifacts/poc/evidence/M-1/fake_broker/pytest_run_1.log`（生成日志时的相对路径少一级所致）。
- **证据（整改前）**：`git ls-files` 仅命中错误路径；规范路径无跟踪文件。
- **整改**：`git mv` 归位至规范路径；空目录清理；全仓库搜索旧路径引用——仅任务书自身引用问题的文字命中，报告/清单/脚本零残留。
- **完整性核验**：迁移前后 SHA256 均为 `effe6e455178122717898915d7936d0726177a1110c8d56baa733c3b4c09c2e9`（仅迁移，内容未变）；日志含 `collected 20 items` 与 `20 passed`。
- **验证方法**：`git ls-files artifacts/evidence/M-1/fake_broker/pytest_run_1.log`；`sha256sum`；全仓库引用搜索（见 §5 检查命令）。
- **状态**：已完成。

### R2 — qlib 数据 SHA256 清单引用（P1）→ **PASS（已整改）**

- **发现**：`docs/licenses/third-party.md` 引用被 Git 忽略的 `candidates/qlib/data/SHASUMS256.txt`（死链）；实际跟踪路径为 `artifacts/evidence/M-1/candidates/qlib/SHASUMS256.txt`。
- **整改**：台账更新为可跟踪路径，保留两个 zip 的原始文件名、完整 SHA256 与来源 URL（CN v3 release / PIT v2 release）；注明 zip 与解压目录仍保留在本机且被 Git 忽略；补充最小复现说明——对**原始 zip 字节**计算 SHA-256 对照清单（不得对解压目录计算）；明确该清单是 M-1 下载时刻记录，**未声称已重新验证远端文件**。
- **边界**：未把任何大型数据加入 Git；未变更既有历史改写映射（`M-1-engineering.md` §0 记录保持原样）。
- **状态**：已完成。

### R3 — UNKNOWN 订单恢复风险（P0 安全契约）→ **PASS（已记录 + 契约增补；代码修复归 M2）**

**源码证据**（POC 现状，整改未改动其交易逻辑）：

- `artifacts/poc/M-1/fake_broker_poc/fake_broker/oms.py:91` `recover()`；`:99` `snap = broker.get_order(coid)`；`:100` `if snap is not None:` 采纳分支；**`:99–126` 的反分支**：查无订单且本地存在未决 attempt 时，`:117` 直接 `_send_once(...)` 补发一次并记 `COMPLETED_SEND_ONCE`（`:126`）。

**反例（真实券商网络下不成立的前提）**：该分支把 `get_order` 返回 None 等价于"已证明订单不在券商"。POC 的 `get_order` 是本地内存查询，不可能瞬态失败；真实网络下"暂时查无"可能来自：最终一致性/请求仍在券商处理队列、查单超时或 429/5xx 被适配层吞成 None、网络分区。此时补发 = **重复订单风险**。POC 以"broker 侧 client_order_id 幂等"为第二道防线，但 Alpaca 真实幂等窗口与重单行为属 `BROKER_BEHAVIOR_UNVERIFIED`——**20/20 本地契约测试不能证明生产 exactly-once**。

**契约增补**（两份 v2.1 计划 M0/M2 同步，阶段次序未变）：
- 架构 §9 M0 与执行计划 M0 新增「未知订单与单写者出口设计契约 (a)–(d)」：可能已到达的 `SUBMITTING/UNKNOWN` 不得补发（除非可信未发送证据或经真实 Paper 验证的幂等保证）；查无/429/5xx/超时/对账不可用一律 `HALT_NEW_RISK`，自动重试仅限只读查询；发送前崩溃与发送后 ACK 前崩溃按可证明事实/未知状态区分；不确定旧意图不得以替代意图绕过暂停，解除须操作人显式授权 + 完成对账。
- 架构 §9 M2 与执行计划 M2 新增「UNKNOWN 盲重发与 fencing 出口负例」验收：注入送达-响应丢失、延迟/乱序、分区/重启、双实例争写、查单不可靠；未证实分支 0 新增风险 / 0 盲重发 / 0 替代意图。
- **边界重申**：M0 只冻结设计契约，M2 才实施 OMS 代码修复与故障注入；本整改未对 POC 代码做任何"顺便修复"。

**可测试性**：上述规则均可转化为自动断言（状态断言 + 券商提交计数断言 + 意图计数断言），M2 落地。

### R4 — fencing 可信执行边界（P0 安全契约）→ **PASS（已记录 + 契约增补）**

- **发现**：POC 的 `valid_fences` 网关是 mock 构造（`fake_broker.py`，本机内存集合）；Alpaca API 不天然识别自定义 fencing epoch。本地 token 通过 ≠ 券商侧拒绝旧执行者。
- **契约增补**（与 R3 同一批编辑，见上文 (d) 条与 M2 负例段）：单账户唯一可信执行者；旧 epoch 在**唯一订单出口**被拒；本地 token/租约不构成券商侧保证；所有可能直连券商写 API 的进程/SDK/Agent/MCP 工具/恢复与运维脚本不得绕过出口；起步用最小可信出口（单宿主单进程持写凭证），不引入未经证明必要的 Redis/Kafka/微服务；`valid_fences` 行为列为 **mock-only 证据**，真实行为 `BROKER_BEHAVIOR_UNVERIFIED`；M2 负例清单：stale executor 休眠恢复、租约过期、双实例同启、旧 token 写入、出口不可用 fail-closed。
- **一致性**：两份计划对"谁有券商写权限"的定义完全一致（同一 (d) 条文本）；mock/真实边界在本文件与两份计划三处一致。
- **状态**：已完成。

### R5 — Python 3.13 环境偏差与配置一致性（P1）→ **PASS（已同步）**

- **发现**：M-1 按用户批准的 Python 3.13.15 实施，而两份 v2.1 的 M0 任务与架构 §11.1 共 3 处仍写 3.11。
- **整改**：3 处最小同步为「M0 候选运行基线 Python 3.13」，保留 M-1 实际 3.13.15 证据与批准记录引用；研究侧隔离环境（qlib 需 `mlflow<3`、RD-Agent 需 WSL2/POSIX 等）标注为**独立受控验证待办**，不视为已解决。本轮未创建 venv、未安装/升级任何依赖。
- **验证**：`rg 'Python 3\.11'` 于 docs/ 零命中（§5 检查记录）。
- **状态**：已完成。

## 4. 仍未解除（下一阶段阻断条件，不因本次整改视为解决）

| 项 | 阻断的阶段 | 解除条件 |
|---|---|---|
| `BROKER_BEHAVIOR_UNVERIFIED` | M2 OMS 实装前 | 真实 Alpaca **Paper** 实测（订单幂等窗口、超时后查单语义、回报格式、权限边界），需用户开通 paper key 并明确授权；期间一切 broker 行为按最保守 UNKNOWN 处理 |
| UNKNOWN 补发语义的生产实现 | M2 | 按 M0 契约 (a)–(c) 实施代码并全部转为自动断言 |
| 故障注入规模 | M2 | ≥1,000 次重复/故障组合、子进程级 kill（M-1 POC 仅 20 个确定性契约用例 + 注入异常模型） |
| M1 数据许可/质量 | M1 | 按供应商矩阵实测 Sharadar / Polygon(Massive) / Alpaca Basic；Yahoo 不可进入研究证据链 |
| 研究侧环境兼容 | M4 前 | qlib `mlflow<3` 钉扎与 US 数据接入实测；RD-Agent 需 WSL2、LLM 凭证与预算门（当前 `BLOCKED_ENV`） |

## 5. 自检命令与结果（2026-11-19 实际运行，另存 `artifacts/evidence/M-1/remediation/`）

逐项输出与退出码见 `artifacts/evidence/M-1/remediation/checks.log`（要点）：

```text
git status --porcelain              # 整改前仅任务书自身未跟踪
git rev-parse HEAD                  # 582d9e063...（与审查基线一致）
git ls-files artifacts/evidence/M-1/fake_broker/pytest_run_1.log          # 命中（R1 后）
git ls-files artifacts/evidence/M-1/candidates/qlib/SHASUMS256.txt        # 命中
rg 'artifacts/poc/evidence|M-1/candidates/qlib/data/SHASUMS256' docs/ …   # 旧引用 0 命中
rg 'Python 3\.11' docs/plans/ docs/                                       # 0 命中（R5 后）
python -m pytest artifacts/poc/M-1/fake_broker_poc/tests -q               # 20 passed（离线重跑，回归）
```

- fake broker 回归为**纯离线**运行（无网络、无券商连接），日志存于整改证据目录 `artifacts/evidence/M-1/remediation/pytest_run_remediation.log`，**未覆盖**原始 M-1 日志（回归结果 20 passed，与原始记录一致）。
- Markdown 内部路径检查：脚本扫描 docs/ 内反引号路径引用并核对 Git 跟踪/磁盘存在性，结果见 `checks.log`。检查发现一处**真实死链**——工程报告 §1 的候选评估花括号引用覆盖 `alpaca-py/eval.md`，但该文件此前缺失（alpaca-py 评估仅留了 `logs/offline_contract.txt`）→ 整改中补齐 `artifacts/evidence/M-1/candidates/alpaca-py/eval.md`（仅汇总既有已验证事实，未新增测试主张）。其余未命中引用均为**计划模板中的未来阶段工件**（如 `docs/adr/ADR-006-capital-policy.md`、`configs/data_acceptance.yaml`）或本文件对 R1 旧路径的**发现引文**，非活性死链。

## 6. 正式状态

- ~~本文件整改全部验证通过后的状态：**`M-1_REVIEW_REMEDIATION_COMPLETE / M0_START_APPROVAL_PENDING`**~~
- **现行状态（2026-11-20 更新）：`M-1_REVIEW_CLOSED`** —— 用户于 2026-11-20 批准关闭本审查并授权启动 M0（范围仅 M0，完成即停在 M0 阶段门等待人工复核）。M-1 三轨报告与本审查记录就此封存，不再修改（本节状态行除外）。
- 该关闭**只授权 M0 范围内的工程启动**，不产生任何真实交易许可；Alpaca Paper/Live、真实密钥、资金操作仍全部禁止，Live 相关签批仅可使用 mock 测试密钥。
- approver = **USER_APPROVED**（2026-11-20，用户直接指示；Agent 不代签）。
