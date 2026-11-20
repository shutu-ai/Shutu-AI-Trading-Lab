# Shutu AI Trading Lab — Codex 分阶段执行任务书 v2.1（最终审查补充修订）

> 对应总体方案：`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`  
> **研发顺序：P0 基础可信 → P1 研究可信 → P2 多策略进化 → P3 受控实盘 → P4 长期财富管理**。  
> 强制三轨验收：**E 工程、S 策略证据、R 真实资金**；任意安全 FAIL 或未经人工 Live 审批时不得开展实盘。

本任务书为可单独放入仓库执行的里程碑和验收清单；具体数据契约、策略状态机、风控约束及财务定义见总体方案。

**正交状态定义**：`evidence_state`（NOT_EVALUATED / HIST_OOS_SUPPORTED / FORWARD_OBSERVING / FORWARD_SUPPORTED / INCONCLUSIVE / FAILED）描述证据；`deployment_state`（NOT_DEPLOYED / SHADOW_RUNNING / PAPER_RUNNING / LIVE_RUNNING / PAUSED / RETIRED）描述部署；`strategy_role`（CANDIDATE / CHALLENGER / CHAMPION_PAPER / CHAMPION_LIVE / NONE）描述角色；`final_holdout_status`（SEALED / PASS / FAILED / INCONCLUSIVE / INVALIDATED）描述最终检验。**M3.5/M8 可以先 PAPER_RUNNING/CHAMPION_PAPER 以获取前向证据，M9 终检不 PASS 时一律没有 Live 资格。**

---


## M-1～M11 任务与验收（含 M3.5）

> **统一任务协议**：每阶段必须交付代码或可复现设计工件、自动测试/故障注入、不可变证据、E/S/R 三轨报告及下一阶段依赖。实际执行需要用户后续明确下达阶段任务；**v2.1 设计冻结候选停在 ENGINEERING_START_APPROVAL_PENDING，不启动 M-1**。研究里程碑允许 `S=INCONCLUSIVE` 并继续工程研发，但不自动获得 Live 权限。

**统一报告**：`docs/reviews/{stage}-engineering.md`、`docs/reviews/{stage}-strategy.md`、`docs/reviews/{stage}-real-capital.md`，其中 `{stage}` 原样取 `M-1`, `M0`, `M1`, `M2`, `M3`, `M3.5`, `M4` … `M11`。证据统一为 `artifacts/evidence/{stage}/`；E 状态 `PASS/FAIL/BLOCKED_ENV/PENDING_FORWARD_WINDOW`（仅真实前向观察窗正常积累未满），S 状态 `SUPPORTED/INCONCLUSIVE/FAILED/N_A` 且必须另外写 `evidence_state`，R 状态 `NOT_STARTED/OBSERVING/SUFFICIENT_EVIDENCE/INCONCLUSIVE/FAILED`。

### M-1：开源底座真实 POC（P0，首个后续工程任务）

**任务**：锁定 RD-Agent、Qlib、FinRL-X、alpaca-py 版本与 LICENSE/NOTICE；评估研究、日线/5分钟、目标权重、最小 OMS/真实券商协议语义及候选数据供应商。**fake broker 必测**：完成下单/未知订单/崩溃/fencing 契约 POC；Alpaca Paper 是可选额外验证，不启动 Live；比较 `FinRL-X` 与 `alpaca-py + minimal OMS`，形成 ADR-001。

**E-Gate**：fake broker 正常、异常、未知订单、双执行者冲突测试有证据；mock/fake 成功只证明本地契约，**不能声称已验证真实 Alpaca Broker 行为**；未运行可选 Paper 则明确 `BROKER_BEHAVIOR_UNVERIFIED`，非必测而未做不等于 `BLOCKED_ENV`；每个候选有执行日志或确实环境阻塞；至少 1 个可复现日线与 5 分钟 POC；独立部署与不可共享账户写权限方案可画出/测试 mock；供应商矩阵具备历史成分、退市、企业行为、PIT、许可、成本、覆盖七项字段；上游 SHA 和许可可追踪。**S=N_A，evidence_state=NOT_EVALUATED，R=NOT_STARTED**。

**工件**：`docs/adr/ADR-001-core-selection.md`、`docs/licenses/third-party.md`、`artifacts/poc/M-1/`、三轨报告及 `artifacts/evidence/M-1/`。POC 结论放在 `docs/reviews/M-1-engineering.md`，不另立同名审查报告。

### M0：部署隔离、身份签批契约、工程事件与审计骨架（P0）

**任务**：搭建 Python 3.13 项目/CI（M0 候选运行基线 3.13；M-1 实际运行版本 3.13.15，从原 3.11 基线的偏差已经用户批准并记录于 `docs/reviews/M-1-independent-review.md` R5；研究侧隔离环境如 qlib/RD-Agent 的版本兼容性另行受控验证，不因本条视为已解决）；Pydantic 契约、两套独立 runtime 启动配置（Live 仅 mock 干运行）；测试签名器/验签器；可信公钥部署机制、审批 nonce、过期、撤销、额度/版本 hash 检查；研究 sandbox 与 Paper/Live 策略低权限子进程均无券商写权限；AI 代码不得在 OMS/风控进程动态执行，策略只输出经可信 Schema Gate 检查的信号/组合；手动 Kill Switch 与密钥泄漏扫描。

**未知订单与单写者出口设计契约（M-1 审查增补 R3/R4：M0 只冻结设计，M2 才实施代码与故障注入）**：(a) `SUBMITTING/UNKNOWN` 且请求**可能已到达**券商时，除存在可信未发送证据（如连接在请求构建前被拒）或经真实 Alpaca Paper 验证的明确幂等保证外，**不得补发**；`get_order(client_order_id)` 暂时查无、429、5xx、超时或对账通道不可用**均不得视作"未发送"证明**，一律进入 `HALT_NEW_RISK` 并保留完整日志，自动重试只允许针对只读查询；(b) 发送前崩溃与"发送后收到 ACK 前崩溃"必须区分**可证明事实**与**未知状态**分别记录，不得合并处理；(c) 对存在不确定结果的旧意图，不得生成任何"替代意图"绕过暂停；解除暂停须操作人显式授权并附已完成的券商订单/持仓/现金对账证据；(d) 每个 `(environment, account_id)` 只能有**一个**获得券商写权限的可信执行者；本地 fencing token/租约不是券商侧远端保证，旧 epoch 必须在**唯一订单出口**被拒；任何可能直接访问券商写 API 的进程、SDK、Agent/MCP 工具、异常恢复与运维脚本都不得绕过该出口；起步阶段以最小可信出口（单宿主、单进程持有写凭证）实现，不引入未经证明必要的中间件组件。

**E-Gate**：100% 已登记的跨域访问、AI 越权代码/非法 Schema 信号和假签批负例被拒；Paper 运行时不存在 Live 密钥/DB/OMS/endpoint；错账户、篡改 hash、超额度、过期、撤销/失联验签均 `FAIL_CLOSED`；无需或无法取得真实 Live 密钥。**S=N_A，evidence_state=NOT_EVALUATED，R=NOT_STARTED**。

**工件**：`src/trading_lab/contracts/`、`src/trading_lab/security/`、`configs/paper/`、`configs/live/`（仅模板）、`tests/security/`、`docs/adr/ADR-002-isolation.md`、三轨报告及阶段证据。

### M1：数据供应准入与点时刻可得性（P0）

**任务**：建立原始/复权/成分历史/退市/企业行为/公告时间模型和 UTC/ET 日历；编写供应商授权成本、覆盖/缺失/延迟矩阵；按 `configs/data_acceptance.yaml` 的非空阈值验收每种用途；限制不合格资产池。

**E-Gate**：全部注入的未来记录被阻断；质量测试报告每类字段的分母、缺失数、覆盖率、实际延迟和许可证状态；关键数据缺失产生 `BLOCKED_DATA/RESTRICT_SCOPE` 而非默默替代；snapshot hash 可重算。**S=N_A，evidence_state=NOT_EVALUATED，R=NOT_STARTED**。

**工件**：`src/trading_lab/data/`、`configs/data_acceptance.yaml`、`tests/no_lookahead/`、`docs/adr/ADR-003-data-contract.md`、`artifacts/evidence/M1/data-vendors.md`、三轨报告。

### M2：独立风控与 OMS 崩溃一致性（P0）

**任务**：实现持久化订单意图/outbox、风险快照、确定性订单 ID、模拟券商、部分成交和撤单；OMS/风控只接收通过可信 Schema Gate 的数据型信号，不能执行 AI 生成的代码；单账户写权限、单写者 Gateway 或单宿主不可并发验证、租约/fencing；失败后查单和真实账本对账；定义并严格校验全部 Live 风险强制字段（仅测试模板，不开 Live）。

**E-Gate**：≥1,000 次重复/故障组合中 0 重复 mock-broker 单、0 双主写、0 无意图直接发单、0 非法 Schema/未授权策略代码执行；在“发出后收到 ACK 前崩溃”等六类场景中 `UNKNOWN` 先对账、未解决时 0 新增风险；风险必填项缺失/过期数据/账户不一致 100% 拒绝；恢复需经对账 + 操作人解锁。**S=N_A，evidence_state=NOT_EVALUATED，R=NOT_STARTED**。

**UNKNOWN 盲重发与 fencing 出口负例（M-1 审查增补 R3/R4，可与上述验收合并断言）**：故障注入必须覆盖——请求已送达但响应丢失、响应延迟/乱序可见性、网络分区与进程重启、双实例争写、查单接口不可靠（429、5xx、超时、**暂时查无记录**）；全部未证实分支断言 **0 新增风险、0 盲重发、0 替代意图**；stale executor 休眠后恢复、租约过期、两实例同时启动、旧 token 写入、唯一订单出口不可用均必须 fail-closed；fake broker 的 `valid_fences` 网关行为属 **mock-only 证据**，真实 Alpaca 的幂等窗口/权限/网络行为仍为 `BROKER_BEHAVIOR_UNVERIFIED`，在 Alpaca Paper 实测通过前不得以本地 fencing 冒充券商侧保证（M0 任务中 "(a)–(d)" 契约在本阶段全部转化为自动测试断言）。

**工件**：`src/trading_lab/risk/`、`src/trading_lab/oms/`、`src/trading_lab/brokers/`、`configs/policies/risk_policy.paper.example.yaml`、`tests/fault_injection/`、`artifacts/evidence/M2/`、三轨报告。

### M3：透明规则基线、现实回测与冻结研究协议（P1）

**任务**：基线 B0–B8 的可执行实验夹具、现金/买入持有/单规则；延迟、价差、未成交、退市/复权与资金交收模型；明确历史滚动 OOS、独立最终 Holdout、未来前向 cohort 的日期/资产/事件独立边界及重叠披露、Walk-Forward、Purge/Embargo；M9 最终 Holdout 预注册**唯一候选选择规则**、PASS/FAILED/INCONCLUSIVE 判据、费用与样本门和唯一解封次数；**具体候选 `strategy_hash`/build hash 在 M8 结束且 M9 解封前按冻结规则不可逆锁定**；预注册 AI 与规则两套研究预算。

**E-Gate**：同一数据/seed/协议 hash 结果在预设容差内一致；封存数据未授权访问 100% 被阻断；假造未来价格/过多试验/不同搜索预算被检测；初始最终 Holdout 为 `SEALED`；合成 fixture 覆盖终检 `PASS/FAILED/INCONCLUSIVE/INVALIDATED`、未经披露的重叠和二次选择均被拒，真实最终 Holdout 不得在 M3 解封。**S=INCONCLUSIVE/N_A，evidence_state=NOT_EVALUATED（或仅 HIST_OOS_SUPPORTED，不具 Live 资格），R=NOT_STARTED**。

**工件**：`src/trading_lab/backtest/`、`src/trading_lab/validation/`、`configs/evaluation_protocol.yaml`、`docs/adr/ADR-004-evaluation.md`、`artifacts/evidence/M3/`、三轨报告。

### M3.5：最小 Shadow/Paper 前向工程验证（P1，新增）

**任务**：以一个冻结透明规则策略在真实到达的数据上先锁预测再观察；优先 Shadow，仅需时连接 Alpaca Paper，且不得取得 Live 密钥。验证事件时钟、重启、重复 event、订单幂等、持仓/现金对账、监控与日志；把前向 cohort 存入独立账本。

**E-Gate**：至少 5 个可观察美股交易日或等效预注册前向事件窗（不得人工合成冒充真实前向时长）、至少 1 次断网/重启和 1 次重复事件恢复，全部可重放；0 未经风险批准的真实券商模拟订单，0 重复 Paper 订单；采集系统正常、真实观察期仍不足时标 `E=PENDING_FORWARD_WINDOW`、`forward_window_status=ACCUMULATING`，不等于 PASS；实际行情/授权/时钟/运行环境阻碍采集才标 `E=BLOCKED_ENV`，不造假。完整窗口及故障测试通过才能 `E=PASS`。**S=INCONCLUSIVE，evidence_state=FORWARD_OBSERVING，deployment_state=SHADOW_RUNNING/PAPER_RUNNING；R=NOT_STARTED；不得以此申报 Alpha 或开放 Live**。

**工件**：`apps/trading_daemon/`（Shadow/Paper 最小模式）、`tests/forward_smoke/`、`artifacts/evidence/M3.5/`、三轨报告。

### M4：AI 策略研究工厂（P1）

**任务**：AI 提案、低权限无密钥/无券商出口沙箱执行、策略代码审查和不可变 build hash、Schema 信号验证、研究预算和不可删除全试验账本；对接 RD-Agent/Qlib 的研究接口；严格隔离 sealed/污染过的 Holdout、统计请求和券商写接口。

**E-Gate**：至少 3 个独立研究假设完整登记成功/失败/重试、计算/LLM 成本和数据时点；超过搜索预算、封存查询/权限跨界、恶意策略读取环境变量/发券商请求/在 OMS 中 `exec`/提交非法信号被 100% 拒绝；以合成 fixture 证明解封后污染且无法再作为独立证据；真实封存集仍保持密封至获授权最终检验。**S 按历史协议出具，若支持仅 `HIST_OOS_SUPPORTED`；R=NOT_STARTED**。

**工件**：`src/trading_lab/research/`、`src/trading_lab/strategies/registry/`、`artifacts/experiments/`、`artifacts/evidence/M4/`、三轨报告。

### M5：市场状态识别与误判价值（P2）

**任务**：趋势/震荡/高波动/事件多维标签、UNKNOWN、滞回和可得时间；比较 B2/B3/B4/B5 的净经济价值、错判损失和切换频率。

**E-Gate**：全部未来状态泄漏和过期快照被拒；缺失输出 UNKNOWN/NO_TRADE；滞回/回放一致。**S 按冻结协议报净增量或 INCONCLUSIVE，历史证据不能提升到 FORWARD_SUPPORTED；R=NOT_STARTED**。

**工件**：`src/trading_lab/regime/`、`tests/regime_misclassification/`、`artifacts/evidence/M5/`、三轨报告。

### M6：Champion–Challenger、证据晋级和淘汰（P2）

**任务**：研究版本不可变、`evidence_state / deployment_state / strategy_role / final_holdout_status` 正交状态机、策略退化/降级/现金、切换成本；支持 `FORWARD_OBSERVING + PAPER_RUNNING + CHAMPION_PAPER` 并获取前向证据，**不得要求 FORWARD_SUPPORTED 先于 Paper**；Live 要求 M9 Holdout=PASS、独立前向证据和独立签批；B5/B6/B7 消融。

**E-Gate**：伪造状态、旧 Holdout/最终 Holdout 失败或证据不足、未达前向样本、Paper/前向循环依赖、篡改版本/审批、退役策略自动复活全部被拒；NO_TRADE 合法；报告策略晋级/降级/冻结时的来源。**S 仅在独立新前向协议满足时可给 FORWARD_SUPPORTED，否则 INCONCLUSIVE；R=NOT_STARTED**。

**工件**：`src/trading_lab/evolution/`、`tests/strategy_lifecycle/`、`docs/adr/ADR-005-evolution-policy.md`、`artifacts/evidence/M6/`、三轨报告。

### M7：多策略组合、小资金与成本约束（P2）

**任务**：多策略在账户层净额化、0–100% 目标表达但受严格敞口上限；合规资金、现金、成本和碎股检查；B0–B8 同数据时点、等试验数与等经济预算两套比较。

**E-Gate**：冲突信号不产生对敲；交易与余额按最小精度对账；超阈值订单、异常风暴、过期行情拒绝；所有实验臂完整输出费用和失败次数。**S 按预注册经济净效应/统计阈值判定，报告市场状态及多策略是否确有增量，未证实可为 FAILED/INCONCLUSIVE；R=NOT_STARTED**。

**工件**：`src/trading_lab/portfolio/`、`src/trading_lab/costs/`、`tests/meta_portfolio/`、`artifacts/evidence/M7/`、三轨报告。

### M8：长周期 Alpaca Paper / Shadow 前向（P3）

**任务**：按锁定策略与统一快照持续运行与历史滚动 OOS、独立最终 Holdout 可区分且重叠披露的前向 cohort；**在 M8 结束、M9 解封前按 M3 选择规则封存唯一待测策略版本及 hash**；真实 Paper API 订单与回执/资金对账；调度、告警、恢复、数据质量/交易成本记录。60 个交易日可作为初步**工程稳定性**观察点，但不作为必然 Alpha 证明。

**E-Gate**：每一笔 Paper 单都有对应意图、风控、broker 回执/成交及对账；重复事件/断线恢复无未解决重复单；完整 Paper/Live 隔离；结果为连续真实前向时间序列（不可用回填代替）。**S=SUPPORTED 且 `evidence_state=FORWARD_SUPPORTED` 只有在预注册前向数量/经济效应/误报控制均通过时才成立，否则 INCONCLUSIVE/FORWARD_OBSERVING；R=NOT_STARTED**。

**工件**：`tests/paper_e2e/`、`docs/runbooks/`、`artifacts/evidence/M8/`、三轨报告。

### M9：策略增量确认及独立 Live Pilot 准入（P3）

**任务**：仅 M9 由独立验证进程核验 M3 已预注册规则及 M8 结束时冻结的唯一 `strategy_hash`，再单次解封最终 Holdout，运行冻结统计/净成本/风险及样本阈值，记录 `final_holdout_status=PASS/FAILED/INCONCLUSIVE/INVALIDATED` 与污染事件；检查历史滚动 OOS/最终 Holdout/前向 cohort 的日期、事件、资产重叠披露与去重，以及 B0–B8 等预算；只有 PASS 才允许生成待人工审批提案；签批、账户资格、撤销和回滚等安全负例只用 mock。**本 v2.1 交付不含 M9 实施，也不含 Live 真实交易授权**。

**E-Gate**：Live 验签器对签名篡改、旧 epoch、撤销、错账号、错风险 hash、超额、失效条件全拒绝；只有经明示本人批准的部署才可能开启真实交易；OMS 与风控故障测试已过。**M9 终检 PASS 是 Live 资格必要条件**：`final_holdout_status=FAILED/INCONCLUSIVE/INVALIDATED/SEALED` 一律禁止 Live 申请；并须 `S=SUPPORTED + evidence_state=FORWARD_SUPPORTED + E=PASS + cohort 独立性=PASS + 代码审查/信号 Schema/风控门=PASS + 独立人类签批`；R 在审批/实盘前为 NOT_STARTED，实际授权启动后为 OBSERVING。

**工件**：`docs/releases/live-pilot-approval.md`（模板，非有效签名）、`tests/live_safety_dry_run/`、`artifacts/evidence/M9/`、三轨报告。真实签批工件必须保存在与 Agent 隔离的批准存储，不放入 Git。

### M10：长期 Live 监测、退化治理与审慎扩容（P4）

**任务**：真实成交滑点、费用、净值、TWR/MWR、漂移与状态错判持续归因；已签批白名单内受控降权；人工重新批准任何增额或新策略版本；失效自动 NO_TRADE。

**E-Gate**：撤销/过期/证据退化后新增风险锁住且记录对账；任何资金上限变动未经新签批被拒绝。**S 可以退回 INCONCLUSIVE，证据状态按实际降级；R 仅在长期预注册实盘样本和费用/回撤/可负担门槛全部满足时可评估 SUFFICIENT_EVIDENCE，不能自动扩容**。

**工件**：`src/trading_lab/monitoring/`、`docs/reviews/M10-real-capital.md`、`artifacts/evidence/M10/`、三轨报告及审慎扩容审批/拒绝记录。

### M11：复利、资金积累与人工收益提取建议（P4）

**任务**：分别统计资金流、未实现盈亏、已实现损益、交收资金、研究/运营成本、税务准备金；计算提取建议（可为零），仅由本人在券商/银行端手工执行资金操作。

**E-Gate**：提现 API 或研究 Agent 直接转账权限不可达；账本收益与资金流清晰区分；可重放提取计算。**S 继续独立评估策略；R 不充分时必须输出 `$0 / INCONCLUSIVE`，不能凭某月盈利自动提取**。

**工件**：`src/trading_lab/capital/`、`src/trading_lab/wealth/`、`docs/adr/ADR-006-capital-policy.md`、`artifacts/evidence/M11/`、三轨报告。

## 跨阶段量化验收

### 10.1 工程（E）强制 100% 通过的安全断言

| 核心安全测试 | 硬性要求 |
|---|---|
| 研究进程访问 Paper/Live 写接口 | 全部拒绝，测试有日志 |
| 未审核 AI 生成代码在 OMS/风控进程执行或触及券商权限 | 低权限隔离、可信 Schema Gate；越权网络/文件/环境变量/动态执行负例全拒 |
| Paper 启动携带 Live key / URL | 全部拒绝，不能进行网络实盘写操作 |
| 无签批 Live、签批过期、超额度、不同策略 hash | 全部拒绝 |
| 强制违规交易（超额度、未交收资金、未知证券、异常价格） | 全部由独立风控拒绝 |
| 同一订单 ID 重放 / 失联恢复 | 在故障注入及≥1,000 次重复事件测试中**0 重复模拟 Broker 订单**；未知状态对账之前不重新发送 |
| 持久化意图与发单后崩溃 | 每单先持久化 Journal；提交后崩溃恢复必须查单，无法确认为 `HALT_NEW_RISK` |
| 双实例冲突与 fencing | 旧 epoch/过期租约写入全部拒绝；不能验证单写者就阻断 Live |
| 签批授权与撤销 | 身份、公钥、签名、工件 hash、额度、时间窗、nonce、撤销不符全部拒绝 |
| Live 风控字段缺失 | 必填风险上限缺项/null/过期统一 fail closed |
| 部分成交、撤单未知、持仓与 broker 不一致 | 冻结新增风险、查询状态、保留完整审计 |
| 数据异常、时区/美股 DST、复权和发布时间混淆 | 拦截全部预设的未来泄漏与数据损坏 fixtures |
| 数据供应商历史成分/退市/企业行为/许可不完整 | 供应商矩阵形成按用途 `REJECT/RESTRICT_SCOPE/BLOCKED_DATA`，不能误报可研究 |
| Holdout 二次解封/污染后再次当独立 OOS | 拒绝或降级为污染样本；事件与全部研究次数不可删除 |
| 最终 Holdout FAILED/INCONCLUSIVE/INVALIDATED/SEALED 申请 Live | 100% 拒绝；M9 必须预注册 PASS，三类证据不得偷换或未披露重叠 |
| M3.5 未积累满真实前向窗口但环境健康 | `E=PENDING_FORWARD_WINDOW`，不能算 PASS 或 BLOCKED_ENV；采集故障才 BLOCKED_ENV |
| 研究 Agent 修改协议或封存集 | 拒绝，记录审计 |
| 策略未批准自动上 Live | 拒绝；Paper 允许在规则内自动进化 |
| AI 提现/资金转出 | 完全禁止任何执行路径 |

这些是**测试覆盖范围内**的断言，生产中“零故障”仍要通过长期监控来判断；不能以测试通过保证永远不会发生事故。

### 10.2 策略（S）证据指标

每次策略审查至少包括：封存 OOS/滚动前向净收益、匹配风险的 B0–B8 增量、最大回撤、尾损、换手、成交率、不同状态下独立样本数、置信区间/多重比较修正、成本 ×1/×2/×3 压力、Regime 误判与策略切换成本、参数邻域敏感性、研究 Token/数据/计算费用。

**策略证据门槛不得事后更改**。M3 阶段内冻结协议后才可执行正式验证；M9 最终 Holdout 必须按冻结条件 PASS，FAILED/INCONCLUSIVE/INVALIDATED 不得 Live，滚动 OOS、最终 Holdout、前向 cohort 需独立与重叠披露；填写目标效应大小、主要检验、误报控制、最小独立机会数、折数或观察窗口与成本假设；若为 null，一律不能 S=SUPPORTED。另报 `evidence_state`：历史 OOS 只允许 `HIST_OOS_SUPPORTED`，实际新时段的事前锁定预测经过预注册前向检验才允许 `FORWARD_SUPPORTED`。M3.5 的短期 Shadow/Paper 一律只作工程证明。

### 10.3 真实资金（R）证据指标

记录 Live 每笔买卖的决策价、报价/可用时间、券商回执、实际成交及滑点、净现金流、真实佣金/税费、资金冻结与交收、现金分配、TWR/MWR、累计净回报、回撤、策略失效及中断原因、运行月成本与扩容后的增量可行性。**真实交易成本与实际收益验证无法在纯模拟盘中提前完成**。

Live Pilot 的必要条件包括：E=PASS、S=SUPPORTED、`evidence_state=FORWARD_SUPPORTED`、**M9 `final_holdout_status=PASS` 与 cohort 独立性验证通过**、已审核隔离策略代码和可信 Schema 信号、本人独立签名批准且 Live 验签器通过、账户/KYC/权限/费用核实、已生效且非空强制风控限制、撤销源可用和实时告警。进入后 R 初始仅为 OBSERVING；扩容和提现另需 R 证据，不得用一次获利推断长期能力。

### 10.4 事故和错误市场假设清单

- 数据：假期、提前收市、停牌、拆股、复权/退市、缺失 bar、乱序、旧新闻重放与错误时区；
- 研究：封存集泄漏、Holdout 解封污染后二次选择、过多候选或 Prompt 重试漏计、结果筛选、过拟合、低样本、不可复现、参数临时改变；
- 状态：状态误判、突发高波动、事件发布时延、标签抖动、市场状态未知；
- 交易：两策略冲突、双进程下单、失效 fencing 租约、发单前/后崩溃、重复 websocket、429/5xx/超时、未知撤单、部分成交、交收资金不足；
- 系统：机器重启、代理改变、网络抖动、主机时钟跳变、密钥错误、数据库中断、LLM 预算耗尽；
- 资金：入金/提现被误算成投资收益、未实现盈亏当作可提取资金、税费漏计、超风险预算扩容。

---

## 统一工件与权限规范（对应总体方案 §11.2–§11.3）

### 11.2 每阶段必须提交的机器可审计证据

```text
docs/reviews/{stage}-engineering.md     # commit / tested commands / environment / PASS|FAIL|BLOCKED_ENV|PENDING_FORWARD_WINDOW
docs/reviews/{stage}-strategy.md        # protocol hash / all_trials / evidence_state / S-Gate
docs/reviews/{stage}-real-capital.md    # live receipts / exposure / cost / TWR-MWR / R-Gate
docs/adr/ADR-*.md                  # decision, rejected alternatives, risks
artifacts/experiments/<id>/       # immutable data hash, code hash, model, seed, metrics, failures
artifacts/evidence/{stage}/       # logs, fault injection, 账户对账和签批负例证据
```

阶段不能因失败而自动降低验证阈值或删除失败实验。若执行环境阻塞，标注 `BLOCKED_ENV` 与复现步骤，不得生成虚假测试结果。研发代码可以在授权范围内提交推送；**实盘下单、策略实盘首次发布、增资或资金转移必须由真实账户所有者单独明确授权**。

---

### 11.3 唯一工件路径与权限边界（v2.1 规范）

- 规划文件：`docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`、`docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`；旧版不作为新任务执行入口。
- M-1 POC 分析包含在 `docs/reviews/M-1-engineering.md`；只有一个许可台账 `docs/licenses/third-party.md`；版本选择 `docs/adr/ADR-001-core-selection.md`；运行证据 `artifacts/poc/M-1/` 与 `artifacts/evidence/M-1/`。
- 任何阶段使用 `docs/reviews/{stage}-engineering.md`、`docs/reviews/{stage}-strategy.md`、`docs/reviews/{stage}-real-capital.md`；M3.5 文件名原样包含句点。禁止产生任何另一套并行命名的权威报告。
- `docs/releases/live-pilot-approval.md` **只是供将来人工签批的审查模板**，不能存放有效私人签名或私钥；真实批准工件在非 Agent 可写存储中保存，由 Live runtime 验证。文档生成不意味着授权。
- E/S/R 报告必须包含 `stage_id / commit / code_hash / protocol_hash / environment / test_commands / evidence_paths / findings / status / evidence_state / deployment_state / strategy_role / final_holdout_status / forward_window_status / next_gate / approver`；`NOT_APPLICABLE` 须解释，不能代写 `PASS`。



## 12. Codex 后续执行提示词（仅供审核通过后使用）

> **审查停止规则**：此处为未来 M-1 可复制任务文本，生成或打开文档不构成启动 M-1 的指令。v2.1 修订时状态为 `DESIGN_FREEZE_READY / ENGINEERING_START_APPROVAL_PENDING`；**当前状态：`M1_ENGINEERING_CLOSED_WITH_DATA_BLOCK / M2_IN_PROGRESS`**（用户 2026-11-20 批准关闭 M1 工程门并授权 M2，见 `docs/reviews/M1-independent-remediation.md` §7）。

```text
你是 Shutu AI Trading Lab 的平台工程与严格验收负责人。
先完整阅读：
docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md
docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md

仅在用户之后明确批准启动 M-1 时，才执行 M-1。禁止自动推进后续阶段。
目的：评审 RD-Agent/Qlib/FinRL-X/alpaca-py 等公开候选的真实代码、许可、依赖、PIT数据、历史成分与退市、交易适配。
必须完成 fake broker 契约测试；Alpaca Paper 为可选额外验证且未运行应标 BROKER_BEHAVIOR_UNVERIFIED。mock/fake 不等于真实券商 API 行为证明；不建立 Live Runtime，不获取/请求真实账户或密钥。
评审范围：事件/分钟能力、订单发出后崩溃、未知查单、双主 fencing、权限隔离、签批验签 mock、数据供应许可与成本。
记录采用或不采用的证据，不应凭 README 直接断言通过，不应完整 Fork 多个项目。
统一提交：
- docs/reviews/M-1-engineering.md
- docs/reviews/M-1-strategy.md (S=N_A; evidence_state=NOT_EVALUATED)
- docs/reviews/M-1-real-capital.md (R=NOT_STARTED)
- docs/adr/ADR-001-core-selection.md
- docs/licenses/third-party.md
- artifacts/poc/M-1/ 与 artifacts/evidence/M-1/
真实环境阻塞才标 BLOCKED_ENV；未来 M3.5 健康运行但真实样本不足用 PENDING_FORWARD_WINDOW，不伪造 E=PASS；阶段结束后暂停，等待人工评审。
严禁在任何阶段自行开启 Live、升级实盘策略/额度、提现或跳过审批。
```

### 12.1 Codex 单阶段统一提示词模板

```text
请先阅读两份 v2.1 docs/plans 文件，仅执行用户明确指定的 <stage_id>；当前阶段以阶段列表原样命名，如 M-1、M3.5。
核查上阶段三轨报告、数据/研究协议 hash、证据状态和签字门。
完成本阶段任务、自动化安全和负向测试、可重复证据；所有签批仅使用 mock 测试密钥。
交付 docs/reviews/{stage}-engineering.md、{stage}-strategy.md、{stage}-real-capital.md 及 artifacts/evidence/{stage}/；
报告 E、S、R 三门及正交的 evidence_state、deployment_state、strategy_role、final_holdout_status；真实前向窗口自然未满标 PENDING_FORWARD_WINDOW，不能冒充 BLOCKED_ENV。
未满足 E 安全门、FORWARD_SUPPORTED 或 M9 终检 PASS 时禁止申请 Live；不得自行解封 Holdout、修改阈值、批准/撤销实盘、发真实单或挪动资金。
真实环境无法采集/执行时如实 BLOCKED_ENV；真实前向窗口尚未积累完毕用 PENDING_FORWARD_WINDOW；阶段结束暂停，不自行进入下一阶段。
```


## v2.1 最终审查补充修订矩阵（与总体方案 §16 同步）

| 遗留项 | 对应执行阶段 | 验收判据 |
|---|---|---|
| M9 最终 Holdout 单次 PASS 准入、OOS/前向独立 | M3、M8、M9 | `FAILED/INCONCLUSIVE/INVALIDATED/SEALED` 禁止 Live；重叠审计必须可追溯 |
| 证据/部署/策略角色正交 | M3.5、M6、M8、M9 | `FORWARD_OBSERVING + CHAMPION_PAPER` 合法；无 Live 批准不得跳权限 |
| AI 策略代码低权限隔离与信号 Schema | M0、M2、M4、M9 | OMS/风控进程拒绝未审查 AI 代码和不合法信号 |
| fake broker 必测、Alpaca Paper 可选 | M-1；M8 真 Paper | fake broker 故障测试必过；mock 不等于真实券商行为证据 |
| M3.5 自然等待样本与环境故障区分 | M3.5 | `PENDING_FORWARD_WINDOW` 非 `BLOCKED_ENV`，阶段不伪造 PASS |

**统一停止门**：`DESIGN_FREEZE_READY / ENGINEERING_START_APPROVAL_PENDING`，本轮只修改文档，不启动 M-1、mock/Paper 或真实账户。

## 完成/暂停协议与文档审查门

1. 每一阶段必须交付 `docs/reviews/{stage}-engineering.md`、`{stage}-strategy.md`、`{stage}-real-capital.md`，以及 `artifacts/evidence/{stage}/`，报告 E/S/R 与独立 `evidence_state`；遇到环境阻塞标 `BLOCKED_ENV`，正常等待真实前向样本标 `PENDING_FORWARD_WINDOW`。
2. Live 的签批签名、真实账号、密钥不能进入 Codex 的运行目录和研究日志；策略/风控/发布 hash、额度、有效期、撤销状态任何一项不符，必须失败关闭。
3. 任何新实盘策略、额度变化或权益范围变化必须由账户所有者重新批准，AI 自身没有提升权限的通道。未达到独立 `FORWARD_SUPPORTED` 或 M9 `final_holdout_status=PASS`，不能申请 Live；Paper Champion 可以先运行以积累真实前向证据。
4. **本次 v2.1 只进行文档修订**。最终状态 `DESIGN_FREEZE_READY / ENGINEERING_START_APPROVAL_PENDING`：不运行 M-1、不运行任何 mock/Paper 实验、不接触 Live、不生成真实签批、不自动推进阶段。

**变更对照表**：完整 v2.0 → v2.1 十项矩阵见总体方案 §15，覆盖本任务书对应 M 阶段、工件路径、信任边界和验收负例。
