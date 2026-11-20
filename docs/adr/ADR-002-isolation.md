# ADR-002: M0 部署隔离与签批验证实现决策

| 字段 | 值 |
|---|---|
| 状态 | ACCEPTED（M0 范围内） |
| 日期 | 2026-11-20 |
| 阶段 | M0（部署隔离、身份签批契约、工程事件与审计骨架） |
| 依据 | 两份 v2.1 计划 §2.1/§2.5/§2.6/§6.3–§6.5；M-1 审查整改 R3/R4 契约 |

## 决策

M0 以**最小可信边界 + 失败关闭**实现部署隔离骨架，不引入任何中间件组件
（沿用 R4 结论：起步阶段单宿主、单进程持有写凭证；Redis/Kafka/微服务均无
必要证据）。

### D1 — 结构隔离：配置即身份，进程绑定不可切换

运行时身份只来自 `RuntimeConfig`（YAML）→ `RuntimeContext`（frozen
dataclass）。环境（PAPER/LIVE）是配置校验的一部分：Paper 配置引用 Live
host、LIVE 配置非 dry_run、凭据内联字面量、模板占位符未解析——任一命中
即拒绝加载。`RuntimeContext` 冻结后无任何切换接口，满足 §6.3
"不得在一个进程里通过 paper=false 切换环境"。

- 备选：环境变量开关 / 单进程双环境。拒绝原因：正是 §6.3 禁止的形态，
  且无法通过 §2.5 的隔离测试。

### D2 — 签批验证：Ed25519 + 规范化 JSON + 离线钉扎信任根

- 签名覆盖 LiveRelease 除 `signature` 外全部字段的规范化 JSON
  （sort_keys、无空白、Decimal 渲染为字符串，`canonical.py`）。
- 信任根 = 部署外带（out-of-band）投递的公钥集合（key_id = 公钥原始字节
  SHA-256 前 16 hex）。验签时对钉扎集合逐键尝试验证；自建公钥不可能通过。
  备选（release 内嵌 key_id 字段）需修改 §2.2 契约字段，M0 不改契约。
- 全部负例（§6.5 表：身份、伪造、范围、时效、撤销、故障）由
  `tests/security/test_verifier.py` 覆盖，全部使用**mock 测试密钥与虚构
  账户**；真实签批终端、真实账户准备属 M9，需用户另行授权。
- nonce = 批准操作防重放（JSONL 账本），非逐单令牌（§6.4 明确）。
- 撤销源 = denylist JSONL + freshness 记录 + 最大陈旧度；缺失、不可读、
  过期一律 FAIL_CLOSED——不存在"大概没撤销"的放行路径。

### D3 — Schema Gate：数据是唯一跨界物

策略子进程 → 交易面唯一通道是原始 JSON 字节，严格校验
`StrategySignal`/`TargetPortfolio`（extra=forbid、Decimal 资金字段、
有限性、[0,1] 权重、禁止负权重、池内标的、TTL、已审查 build hash 白名单）。
拒绝产生 `NO_TRADE` + 审计事件，**永不抛异常**（非法信号不得把交易面带入
未定义状态）。Pickle/对象/命令字符串在结构上不可通过（非 JSON 即拒）。

### D4 — 审计骨架：追加写 JSONL + 哈希链

每行含 `seq/prev_hash/event_hash`，`event_hash` 为正文规范化 JSON 的
SHA-256。`verify()` 重算全链，历史行任何改动可检测。M0 威胁模型（单宿主、
平台自身可信写文件）下这是检测控制而非防篡改控制；链的防篡改存储升级
记录为后续阶段待办，不在 M0 夸大。

### D5 — Kill Switch：持久化、显式授权解除

按 (environment, account) 写持久 halt 文件，重启不清除；所有加风险路径
必须先过 `require_tradable()`（M0 为骨架接缝，M2 风控引擎接线）；解除
要求非空 `authorization_ref`（操作人 + 对账证据指针）并审计。无定时、
无隐式解除路径。

### D6 — M0 无券商执行路径

M0 平台内不存在任何 broker 执行模块（`trading_lab.brokers` 不存在），
`RuntimeContext.broker_write_path_exists()` 恒 False。"Live 仅 mock 干
运行"由**代码缺失**保证，而非由配置约束保证：没有可发单的代码路径。
单写者出口（设计契约 (d)）在 M2 于该接缝实现。

## 已知限制与风险（诚实记录）

1. **权限隔离靠结构不靠 OS ACL**：研究沙箱的低权限隔离目前是策略对象 +
   拒绝 + 审计（`ResearchSandboxPolicy`），M0 未做 OS 级用户分离/ACL
   攻击测试。§6.5 "签批隔离要通过实际权限攻击测试证明"在 M0 仅 mock
   层面覆盖，OS 层隔离测试归入 M4（AI 研究工厂）实现时。
2. **nonce/撤销账本为单机 JSONL**：M0 规模下足够；并发与崩溃恢复语义
   与 OMS Journal 一并在 M2 处理（同一持久化标准）。
3. **CI 工作流交付但本地不可执行 GitHub Actions**：以本地同命令运行
   （pytest + scan_secrets + verify_live_blocked）作为 M0 证据；推送后
   Actions 运行结果在后续阶段报告中引用。
4. **canonical JSON 对 Decimal 以字符串表示**：跨语言验签方必须按同一
   规则序列化；该约定写入 `canonical.py` 文档字符串与签批模板（M9）。

## 影响

- 满足 M0 E-Gate 全部负例要求（见 M0-engineering 报告映射表）。
- 未实现（按计划本就不属于 M0）：OMS/风控引擎、broker 适配、真实签批、
  数据接入。M0 结束停在阶段门。
