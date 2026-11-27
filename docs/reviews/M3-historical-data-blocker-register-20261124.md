# M3-H — BLOCKED_DATA 专项开放问题登记表（2026-11-24 首版）

> 治理规则：
> 1. **记录阻塞 ≠ 解决阻塞**。本表是持续跟踪工具：每个阻塞项必须登记到"客观解除条件可被独立验证"或显式 CLOSED 为止，禁止停留在"等数据"式描述。
> 2. 每行固定列：`scope/use_case, evidence, owner_role, blocker, impact, permitted_next_action, authorization_needed, objective_unblock_condition, review_trigger, status`。
> 3. 更新为**追加式**：状态变更以新行（日期戳）记录，不删除旧行；status 词表 `OPEN / IN_PROGRESS / UNBLOCKED_PENDING_VERIFICATION / CLOSED_UNBLOCKED / CLOSED_REJECTED`。
> 4. `objective_unblock_condition` 必须是可机器或可人工核验的**客观**条件；"供应商文档声明"不是解除证据（AGENTS.md 规则 9）。
> 5. 本表不改变任何门语义，不是第四种准入状态；判定权威仍是 `configs/data_acceptance.yaml` + `acceptance.evaluate_purpose`（ADR-003 D5 冻结顺序）。

---

## R1 全市场日线策略研究（H2-external）

| 列 | 值 |
|---|---|
| scope/use_case | 全市场日线策略研究（需历史成分+退市+企业行为+PIT+许可齐备） |
| evidence | `artifacts/evidence/M1/data-vendors.md:50`（BLOCKED_DATA 判定）；`docs/reviews/M1-engineering.md:47`；Sharadar 为唯一可行源（`docs/adr/ADR-003-data-contract.md:82-83`） |
| owner_role | 账户所有者（订阅成本/许可决策唯此人可做）；Agent 无行动权 |
| blocker | Sharadar（经 Nasdaq Data Link）无订阅（`BLOCKED_ACCESS`，无凭证且历轮任务禁止注册/购买）；个人研究许可条款文本 UNVERIFIED；订阅价格 UNVERIFIED |
| impact | 横截面/全市场选股研究、指数成分研究完全不可开展；H1 成功不改变本项（任务书 §3 Scope H2 明文） |
| permitted_next_action | 用户自行评估订阅成本与条款；如决定购买，先获取条款全文再书面授权实测 |
| authorization_needed | 用户购买决定 + 书面授权（订阅并允许凭证实测） |
| objective_unblock_condition | 已订阅账户 + 七字段供应商矩阵对 Sharadar 完成 API_VERIFIED 实测（成分/退市/CA/PIT/许可/成本/覆盖）+ `evaluate_purpose(historical_research_daily)` 出具有据 ACCEPT |
| review_trigger | 供应商矩阵更新、用户主动发起、或每季度例行复查（下一触发：2027-02-24） |
| status | OPEN（2026-11-24 首版登记） |

## R2 受限 ETF 历史研究试点（H1，本工作流主线）

| 列 | 值 |
|---|---|
| scope/use_case | 受限 ETF 日线历史研究试点：SPY/QQQ、日线、IEX、候选 2017–2025（工作流 B §2） |
| evidence | 用途行缺失：`configs/data_acceptance.yaml:11-70` 仅 4 purpose 无中间档（审计 E5）；历史接口使用从未获批：全部历史任务书均禁 `collect`；Alpaca Basic 历史 2016+=DOCUMENTED（`data-vendors.md:40`）；IEX 历史深度/CA 包含/许可=UNVERIFIED（`data-vendors.md:38-41`） |
| owner_role | 账户所有者（签批+许可核对+凭证注入）；工程执行=Agent（获批后） |
| blocker | (a) 历史区间 API 使用无授权；(b) IEX feed 历史深度 UNVERIFIED；(c) Basic 档企业行为可用性 UNVERIFIED；(d) 个人研究许可条款 UNVERIFIED；(e) `data_acceptance.yaml` 无对应用途行 |
| impact | **一切真实历史数据研究为空**——这是"历史研究长期停留在 BLOCKED_DATA"的直接载体（审计 Q1/Q3） |
| permitted_next_action | 用户审阅并签署 H1 授权草案（`docs/reviews/M3-historical-readonly-data-authorization-draft-20261124.md`）；获批后 Agent 执行 H1（用途行新增→最小只读采集→事实登记） |
| authorization_needed | 用户签署 H1 草案 §7 文本（或逐字等价）；另加：push 如需远端 CI 另行授权 |
| objective_unblock_condition | 用途行机器校验通过 + SPY/QQQ 全冻结区间 ranged bars 真实回执链 + 许可书面确认 + 快照 `research_admissible` + `evaluate_purpose(historical_research_limited_etf)` 给出 ACCEPT/RESTRICT_SCOPE 有据判定 → 状态转 UNBLOCKED_PENDING_VERIFICATION（H1 门人工复核后 CLOSED） |
| review_trigger | H1 执行完成时；供应商文档变更时；请求预算耗尽或质量门失败时 |
| status | OPEN（H1 授权草案 `AUTHORIZATION_PENDING`，2026-11-24） |

## R3 分钟线研究

| 列 | 值 |
|---|---|
| scope/use_case | 分钟级 bar 策略研究 |
| evidence | `data-vendors.md:55`（RESTRICT_SCOPE：Basic 仅 IEX 实时 + 15 分钟 SIP 延迟；深度历史需付费档） |
| owner_role | 账户所有者（付费决策） |
| blocker | 免费档分钟深度历史不可用；付费档未订阅 |
| impact | M5+ 若需分钟级 Regime/执行研究的可行性未证 |
| permitted_next_action | 无（低优先级；H1/H2 结论前不动） |
| authorization_needed | 用户付费订阅决定 + 实测授权 |
| objective_unblock_condition | 付费档凭证实测分钟历史覆盖+许可确认 + 用途判定 ACCEPT |
| review_trigger | H2 完成后若研究路线需要分钟数据 |
| status | OPEN |

## R4 事件/公告时点研究

| 列 | 值 |
|---|---|
| scope/use_case | 事件驱动/公告时点研究（`event_research` 用途） |
| evidence | `data-vendors.md:56`（RESTRICT_SCOPE：Sharadar EOD 无盘中事件时点；Massive 公告时点 UNVERIFIED）；M-1 已列 Databento 等候选（`docs/reviews/M-1-engineering.md` 供应商矩阵） |
| owner_role | 账户所有者（数据源选型与付费决策） |
| blocker | 无已准入的事件级时点数据源；候选源成本/覆盖未实测 |
| impact | 事件类因子/策略永远无法通过 PIT 门（ADR-003 D1），只能拒绝或降级 |
| permitted_next_action | 无（H2 之前不动）；H2 后可申请候选源离线评估授权 |
| authorization_needed | 候选源订阅/试用授权 + 实测授权 |
| objective_unblock_condition | 至少一个源 API_VERIFIED 级证明 event_at/published_at/available_at 三时点可分离 + `event_research` 用途判定 ACCEPT |
| review_trigger | H2 完成后 |
| status | OPEN |

## R5 Alpaca Basic 企业行为/复权数据可用性

| 列 | 值 |
|---|---|
| scope/use_case | H1/H2 数据的复权与企业行为处理（原始价研究的补集） |
| evidence | CA API 存在但 Basic 档包含性 UNVERIFIED（`data-vendors.md:39`）；本试点 raw-only（H1 草案 §2 adjustment=raw） |
| owner_role | 账户所有者（未来单独 CA 授权申请时决策）；【2026-11-26 勘误 P0-2：原"Agent（H1 内单次只读探测）"废止——H1 严格 bars-only】 |
| blocker | 免费档 CA 端点包含性未实测 |
| impact | raw-only 研究必须披露拆股/分红偏差；跨 2017–2025 区间 SPY/QQQ 的拆股事件会使 raw 序列出现阶跃，H2 必须显式处理（披露或 RESTRICT_SCOPE） |
| permitted_next_action | 【2026-11-26 勘误 P0-2，取代原"并入 H1 执行（授权范围内的只读 CA 端点探测）"】CA 端点探测**延期至另行单独申请**：新授权必须写明准确端点路径、请求上限、权限/许可与 GET 守卫负例测试；H1 期间本项保持 UNVERIFIED，raw-only 拆股/分红偏差在 H2 强制披露 |
| authorization_needed | 未来的独立 CA 探测授权（**不在 H1 签批范围内**——原"H1 签批已含（≤30 请求预算内的探测）"作废，2026-11-26 勘误 P0-2） |
| objective_unblock_condition | 【2026-11-26 勘误 P0-2 后】未来单独授权下的 CA 端点免费档实测回执 → UNVERIFIED 转 API_VERIFIED(限定范围)；不可用则维持 UNVERIFIED 并在 H2 强制披露（不可凭 raw-only 材料承诺完整复权净收益） |
| review_trigger | 未来单独 CA 授权申请提交时；或 H1 完成复核时（原"H1 完成时"随之扩展，2026-11-26 勘误 P0-2） |
| status | OPEN（依赖 R2） |

## R6 IEX 单所数据 vs 全市场 SIP 的可比性

| 列 | 值 |
|---|---|
| scope/use_case | 历史研究的成交假设、买入持有基准比较、成本模型现实性 |
| evidence | IEX=单一交易所聚合、样本偏 IEX 成交（`artifacts/evidence/M3.5/s8/source-license-and-feed.md:11`）；SIP 未授权（`configs/forward_observation_s8_real_v2.yaml:46`：`SIP is NOT authorized`） |
| owner_role | Agent（研究内披露与敏感性设计）；账户所有者（如决定 SIP 付费） |
| blocker | 无 SIP 数据；IEX 代表性偏差的量化未做 |
| impact | H2 结论的成交量上限/价差假设可能失真；与 B1 基准（全市场价格口径惯例）的可比性受限 |
| permitted_next_action | H2 协议中强制 IEX 偏差披露节 + 成本敏感性（×1/×2/×3 已有）+ 不做超过数据支持的执行现实性声称 |
| authorization_needed | 披露义务无需授权；SIP 数据需付费授权 |
| objective_unblock_condition | （披露路径）H2 重叠/偏差报告落盘即视为已治理；（完全解除）SIP 授权+实测——与 R3 同类付费决策 |
| review_trigger | H2 协议冻结时；SIP 决策时 |
| status | OPEN（披露路径可治理，完全解除依赖付费） |

---

## 维护记录（追加式）

| 日期 | 动作 | 依据 |
|---|---|---|
| 2026-11-24 | 首版建立 R1–R6（自既有仓库证据登记，零新增外部事实） | 任务书 `M3-HISTORICAL-RESEARCH-ROADMAP-CORRECTION-20261124-R1` §6；审计 §2 证据表 |
| 2026-11-26 | R5 依 P0-2 勘误：CA 端点探测移出 H1、延至另行单独申请（H1 bars-only）；R5 status 维持 OPEN（依赖 R2 + 未来 CA 授权）。R1–R4、R6 本轮无状态变化 | 任务书 `M3-H1-CONTRACT-PREFLIGHT-RESUME-20261125-001` T1 P0-2；原任务书 `M3-H1-CONTRACT-PREFLIGHT-REMEDIATION-20261124-R1` §2 P0-2 |
| 2026-11-27 | **R2 进展登记（H1A/H1B 工程侧，status 维持 OPEN）**：R2(d) 用途行缺失已解除——`historical_research_limited_etf` 经 2017–2025 冻结日历（nyse-2017-2026-01-frozen-v1，hash 826bd96a…，9 年 VERIFIED_FULL 零冲突）后追加进 configs（历史阻塞项(e)）；R2(b) IEX 历史深度、(c) CA、(d→新) 个人研究许可仍 UNVERIFIED/OPEN——UNVERIFIED 不因配置/工程就绪改变；新增日历来源条款 `LICENSE_UNVERIFIED`（ICE 网站条款对系统化采集/缓存模糊偏限制，见 h1b 报告 §日历）。R2 的 objective_unblock_condition 不变；R1/R3/R4/R6 无状态变化。P0-Q1/Q2 质量缺口（H1B 任务书发现的跨标的覆盖虚高、OHLC 交叉未拦）已 RED→GREEN 修复 | 任务书 `M3-H1B-HISTORICAL-QUALITY-AND-CALENDAR-FREEZE-20261127-R1`；`docs/reviews/M3-H1B-historical-quality-calendar-freeze-20261127.md`；`artifacts/evidence/M3-H/h1b/` |
