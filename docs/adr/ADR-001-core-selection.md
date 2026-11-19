# ADR-001：核心开源底座选型

| 字段 | 值 |
|---|---|
| 状态 | ACCEPTED（M-1 阶段门产出，待用户审查） |
| 日期 | 2026-11-19 |
| 决策范围 | 交易执行底座（ADR-001 三选一）+ 研究侧组件采用方式 |
| 证据 | `artifacts/evidence/M-1/`（各候选 eval.md + 原始日志）、`artifacts/poc/M-1/` |
| 冻结基线 | `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md` §3 |

## 1. 决策

**采用方案 B：`alpaca-py + 自有最小 OMS/风险边界` 作为交易执行底座。**

- **方案 A（FinRL-X 作为受控交易模块）：拒绝**——真实代码证据表明其不具备通过 OMS/事件验收的任何基础能力（见 §3.1）。
- **方案 C（NautilusTrader）：拒绝**——当前全部可安装工件中不存在 Alpaca 适配器，且复杂度/运维成本远超单券商小资金系统的需要（见 §3.2）。
- 研究侧：qlib 作为**研究数据/回测候选组件**在 M1/M3 再做深入实测（采用方式=受控复用，不整仓拼装）；RD-Agent 评估受限（LLM 凭证缺失），M4 前不承诺采用。均不属于本 ADR 的交易底座决策。

## 2. 决策依据（全部来自真实运行/代码阅读，非 README）

### 2.1 alpaca-py（采用：BrokerAdapter 基座）

| 事实 | 证据 |
|---|---|
| 0.45.0 在 Windows + Python 3.13 安装并可用 | `candidates/alpaca-py/logs/offline_contract.txt` |
| 官方维护（2026-11-16 仍有提交）、Apache-2.0 | clone SHA `f8fd955` |
| Paper/Live 端点常量分离（`paper-api.alpaca.markets` vs `api.alpaca.markets`） | `alpaca/common/enums.py:23-24` |
| 数量/名义金额下单、碎股、OCO/bracket、盘后、client_order_id 全部支持 | 同上离线契约日志 |
| **负面发现**：SDK pydantic 模型接受负数量 `-1`（qty/notional 互斥校验存在，但符号校验缺失） | 同上，"negative qty: ACCEPTED" |
| **边界**：本阶段未连接 Alpaca（无密钥）→ 真实订单语义 `BROKER_BEHAVIOR_UNVERIFIED` | `env/environment_and_decisions.md` |

结论：SDK 职责正确（协议语义），但校验不足 → 我方 OMS 必须在 intent 层做完整参数/风控校验（已在本 POC 的 `OrderIntent.validate()` 演示）。

### 2.2 自有最小 OMS（采用：M-1 POC 已验证可行性）

fake broker 契约 POC（`artifacts/poc/M-1/fake_broker_poc/`，20/20 用例通过）证明基线 §6.1 的核心协议在 Python 3.13 + SQLite(WAL, synchronous=FULL) 上可用最小实现约 **500 行核心代码 + 20 个契约用例**：

- 先持久化后外发（`CrashBeforeSend` 后 journal 已有 intent，broker 0 次）
- UNKNOWN 先对账：按 `client_order_id` 查单采纳，**0 重发**；不可解 → `HALT_NEW_RISK` + 操作者显式解锁
- 崩溃恢复：新实例 + 新 fencing epoch；"发送前崩溃"由恢复补发**恰好一次**
- fencing：epoch 单调、租约过期失效、旧 epoch 写入被网关拒绝、冻结执行者唤醒后 0 双写
- 环境隔离：Paper 执行者无法写 Live 命名空间；配置扫描拒绝 live 工件；adapter 无布尔升级路径

### 2.3 成本与风险对比（三方案）

| 维度 | A: FinRL-X | B: alpaca-py + 最小 OMS（选中） | C: NautilusTrader |
|---|---|---|---|
| 技术复杂度 | 低（但它只做了一层薄 REST 包装，还引入缺陷） | 中：OMS 核心协议 ~500 行已验证可行，M2 扩展到 ≥1000 故障组合 | **极高**：~49 万行（Rust 为主），学习面 15–20 核心概念 |
| 订单安全语义 | **全缺**：client_order_id=0 处、无对账、无恢复、无部分成交处理 | 我方按 §6.1 契约实现（POC 已证） | 内在优秀（对账默认开启、状态机严格），但 crash-safe journal 需 Redis/Postgres，**非默认** |
| Alpaca 集成 | 手写 requests 调 REST（声明 alpaca-py 却 0 引用） | 官方 SDK，事件/流式接口原生 | **无适配器**（clone/PyPI 稳定版/2.0rc9 均无） |
| 可维护性 | 差：0 测试 0 CI、缺陷密集（见 §3.1） | 好：自研代码 + 契约测试全覆盖 | 差（对小团队）：live 问题可能要读 Rust；2.0 rc 期 breaking changes 频繁 |
| 许可 | Apache-2.0 | n/a（自研）+ Apache-2.0 SDK | LGPL-3.0（未修改使用无义务；修改源码需开源该部分） |
| 运维成本 | 低但不可信 | 低：SQLite 单文件起步（§11.1 技术栈一致） | 需 Redis/Postgres 才有持久 journal；32 crates 运行面 |

## 3. 被拒方案的关键证据

### 3.1 FinRL-X（FinRL-Trading @ `4409abe`，Apache-2.0）→ 方案 A 拒绝

真实代码审查（`candidates/finrl-x/eval.md`，全部带 file:line）：

- **安装即失败（Python 3.13）**：`finnhub>=2.4.19` 无任何可解析发行版（且该依赖在 src/ 中 0 处导入，属死依赖）；剔除该行后其余依赖可装（记录为偏差）。
- **OMS 能力 10 项核查全不达标**：无 client_order_id（全仓库 0 命中）、无对账/恢复/重试/部分成交处理、无事件循环（仅一次性脚本）；执行路径 fire-and-forget，旗舰 paper 路径**绕过**仅有的风控检查。
- **真实缺陷 6 处**（含卖出腿 `NameError`、静默 `$100` 价格兜底、行情请求打到交易主机等）。
- README 宣称（"Alpaca multi-account integration with pre-trade risk checks"）与代码现实不符。
- 维护状态：2026 年仍活跃但突发式、多为直传提交；**0 测试、0 CI**。

结论：作为交易模块无法通过基线 §10.1 的任何一条订单安全断言；其可取部分（权重→订单的再平衡思路）在自研最小 OMS 中按需重写即可。

### 3.2 NautilusTrader（@ `8a4ac22`，LGPL-3.0）→ 方案 C 拒绝

（`candidates/nautilus/eval.md`，代码级引用）

- **Alpaca 适配器不存在**：整个 clone、PyPI 稳定版 1.231.0、2.0.0rc9 中 "alpaca" 0 命中；21 个适配器无 Alpaca。基线 §3 引用的适配能力与当前现实不符。
- 采用它仍需自写 Alpaca LiveExecClient + 部署 Redis/Postgres 持久化，且正处 2.0 rc 迁移期。
- 优点属实（对账默认开启、严格状态机、Windows+Py3.13 可跑离线回测），但"单券商、小资金、Python 团队"场景下引入 49 万行 Rust 引擎不满足 §0.2/§11.1 的最小复杂度原则。
- 保留意见：若未来需要多场所/高频事件或 Alpaca 适配器回归，可重新评估（不构成自动升级路径）。

## 4. 研究侧组件（非交易底座，M1/M3/M4 深化）

| 组件 | M-1 结论 | 采用方式 |
|---|---|---|
| qlib 0.9.8 | Py3.13 安装+LightGBM Alpha158 工作流端到端跑通（Windows，10m27s；需钉扎 `mlflow<3`，mlflow 3.x 破坏 recorder）；CN 样本数据 PIT 成分真实存在但价格面板有快照伪影（88 个早停标的中 87 个同日截止）、公开数据止于 2022-12、无 US 样本 | **候选封装**：仅复用其 bin 格式数据管道与回测引擎思路；数据供应按 §4.1 供应商矩阵另建（qlib 公开数据不进入研究证据链）。M1 实测 US 数据接入成本后再定最终角色 |
| RD-Agent 1.0.0 | 安装成功（=锁定 v1.0.0 tag）；**原生 Windows 不可用**（POSIX 硬编码：`/bin/sh`、`select.poll()`、unix socket）→ 需 Linux/WSL2；Docker 可选（qlib 场景默认 conda）；LLM 循环无凭证 `BLOCKED_ENV`，默认 gpt-4-turbo + evolving_n=10 成本需预算门；依赖足迹大（286 包）；LiteLLM 后端存在内部 AttributeError 缺陷 | **暂缓**：M4 前不承诺。若采用：Linux/WSL2 隔离沙箱内运行（其 README:436 自述要求隔离 worker），试验账本必须写回我方不可删除账本（对接点=注入我方 runner 类，非拼接），先建 LLM 预算硬门 |
| FinRL-X | 见 §3.1 | **拒绝**（仅作设计参考：权重→订单再平衡语义的反面教材与部分思路） |
| alpaca-py | 见 §2.1 | **采用**（BrokerAdapter 唯一基座） |
| NautilusTrader | 见 §3.2 | **拒绝**（保留重评条件，无自动路径） |

## 5. 风险与缓解（选中方案 B 的已知风险）

| 风险 | 缓解 |
|---|---|
| Alpaca 真实订单语义未验证（超时后查单行为、幂等窗口、回报格式） | M2 前必须完成 Alpaca Paper 实测（需用户开通 paper key）；在此之前所有 broker 行为按 UNKNOWN 最保守处理（本 POC 语义已按此设计） |
| alpaca-py 校验不足（负数量通过） | 我方 intent 层完整校验（POC 已演示）；M2 风控层再做独立校验 |
| SQLite WAL 在断电/并发下的恢复边界 | M2 用子进程级 kill + ≥1000 故障组合实测（§6.1 要求）；必要时评审 PostgreSQL |
| 最小 OMS 自研的维护责任 | 契约测试随代码走（20 用例→M2 扩展）；规模可控（~500 行核心） |
| qlib mlflow 耦合、数据快照伪影 | 若采用：钉扎 `mlflow<3`；数据另建（供应商矩阵），qlib 仅作引擎 |

## 6. 后续动作（属于 M0/M1/M2，不在本 ADR 授权内执行）

1. M0：按本 ADR 搭建 `src/trading_lab/brokers/alpaca_adapter.py` 接口壳（不连网）。
2. M1：按供应商矩阵实测 Sharadar / Polygon(Massive) / Alpaca Basic。
3. M2：扩展 fake broker 契约到 ≥1000 故障组合 + 子进程级 kill；接入真实 Alpaca Paper 做协议语义对照（需用户另行授权与提供 paper key）。
