# 操作者阶段门消歧与准入交接（operator-gate-reconciliation — T9.7.1/T9.7.2，LOCAL_ONLY，2026-11-22）

> 本文件消解 T9 文档中的 **B 项审批死锁**（P1），并给出环境/出口/状态持久性
> 检查表。全部为文档；本轮零网络、零凭证接触、零生产代码变更。
> 状态冻结不变：`OPERATOR_PREFLIGHT_A/B/C=PENDING_OPERATOR`；
> `B_PLAN_READY=UNVERIFIED_OR_PENDING_OPERATOR`；
> `B_ONLY_INJECTION_AUTHORIZATION=NOT_AUTHORIZED`；
> `FIRST_REAL_ONCE_AUTHORIZATION=NOT_AUTHORIZED`；`FIRST_REAL_ONCE_READY=NO`。

## 1. 死锁的精确陈述（T9.7.1）

T9 成文文档中存在两条互相锁死的规则：

- 规则 R1（`operator-preflight-pack.md` §B / `r2/operator-readiness.md` §B）：
  凭证进程级注入"仅在未来的**独立真实采集授权**之后执行"；
- 规则 R2（`first-real-once-approval-request.md` §1 / §6）：首次真实采集
  授权的前置条件是 **A/B/C 全部 VERIFIED_BY_OPERATOR**；
- 而按 `operator-preflight-pack.md` §状态定义，B 无实际注入事实就不得标
  VERIFIED。

→ B 需要"采集授权后才能注入"，采集授权需要"B 已 VERIFIED"：**依赖环**。

## 2. 消歧原则（不降低任何门槛）

把"注入"从"采集授权"中拆出来，成为**两个互相独立的授权**；每个授权仍然
独立审批、独立签批、范围严格有限：

- **`B_PLAN_READY`**：操作者已理解、核对并**签署凭证注入与清理方案**
  （`operator-attestation-template.md` §B）。这是**准备事实**，永远不是
  `B=VERIFIED_BY_OPERATOR`；三态枚举下 B 仍记录 `PENDING_OPERATOR`，
  `B_PLAN_READY` 作为独立布尔事实另记。
- **授权 1 —— B-only 无网络凭证注入核验**（新增的独立授权点）：
  在 **A 本人签署通过 + C 全矩阵验证通过 + 目标环境身份固定** 之后，
  由操作者向用户**单独申请**："仅在受控子进程执行一次凭证注入/可见性检查/
  立即清除，**不访问任何网络/API/下单路径**"。未获批准前禁止执行。
  执行与签署只由账户所有者本人完成；输出只能包含无敏感信息的事实
  （检查结果、时间、环境标识、清除结果），**绝不含凭证值/长度/前后缀/
  散列/任何可回推标识**。
  - B-only 本人核验通过并本地签署后，B 才可标 `VERIFIED_BY_OPERATOR`；
  - 即使确认环境变量存在，也**不得**认定 Alpaca 授权有效、不得升级
    `API_VERIFIED`、不得宣称任何 API 成功——凭证可用性只能由**授权 2**
    的真实采集回执链证明。
- **授权 2 —— 首次真实行情单周期**：仅当 **A/B/C 的人工签署记录实际成立、
  安全环境未变化、CI 基线一致**时，另行发出明确申请；范围仅
  `collect --once` 一次、指定环境、指定日期、指定只读数据端点。
  **B-only 批准绝不自动授权此步骤。**

## 3. 决策图（顺序表）

```text
步骤 0（已完成，工程侧）    T7/T8/T9 文档与围栏就绪，CI 960/960 远端验证
   │
步骤 1  A 本人核对并签署     （人工，本地；operator-attestation §A）
   │                          产出：A=VERIFIED_BY_OPERATOR 或 BLOCKED
   ▼
步骤 2  C 无凭证负例全矩阵    （人工，目标环境；F-1～F-8，attestation §C）
   │                          产出：C=VERIFIED_BY_OPERATOR 或 BLOCKED/
   │                           部分 UNVERIFIED（→ 停，不得推进）
   ▼
步骤 3  固定目标环境身份      （人工；target_environment_id 等 blanks 见 §5）
   │
   ▼
步骤 4  申请【授权 1：B-only】 （操作者 → 用户，单独、范围限注入核验）
   │        未批准 = 禁止注入。批准后：
   │     本人执行：子进程注入 → 可见性检查（名称级） → 立即清除 → 记录
   │        （无敏感信息；不触网、不调 API、不下单）
   │                          产出：B=VERIFIED_BY_OPERATOR（本人签署）
   ▼
步骤 5  申请【授权 2：首次 collect --once】
   │        前置：A/B/C 签署实际成立 + 环境身份未变 + CI 基线一致 +
   │        跨日状态卷就绪（§6）
   │        未批准 = 不执行。批准后：一次、指定环境、指定日期
   ▼
步骤 6  真实回执链证明        API_VERIFIED 只能由可审计回执升级；
   │                          ≥5 全覆盖真实日 + 真实恢复证据才可能谈 E=PASS
   ▼
（更远）M3.5 关门属用户明示批准，永不自动。
```

**顺序硬约束**：1→2→3→4→5→6 不得跳跃、不得并行；任何一步 BLOCKED/异常
即停（§8）。本图取代此前文档中"完成 A–C 后注入凭证 → 首轮仅采集一个真实
周期"的连读（该读法即死锁来源）。

## 4. 各文档一致性修订记录（最小改动 + 日期标注，本轮执行）

| 文件 | 修订 |
|---|---|
| `s8-operator-t9/operator-preflight-pack.md` §B | 注入时点从"真实采集授权之后"改为"授权 1（B-only）批准之后"；补 B_PLAN_READY 定义 |
| `s8-operator-t9/first-real-once-approval-request.md` | §1 前置表补 B-only 签批列；§2 补环境身份与跨日状态连续性检查；§6 补前置清单 |
| `s8-contract-r2/operator-readiness.md` §D | 补日期标注：注入与首次采集是两个独立授权 |
| `s8-operator-t9/operator-environment-plan.md` §5 方案 A | 补日期标注："一次性销毁"仅指计算资源；状态卷必须跨日持久（见 §6） |

## 5. 候选采集环境登记表（T9.7.2.1 —— 全部空白，由操作者固定后填写，仅方案不自动选定）

```text
target_environment_id      : ＿＿＿＿＿＿（操作者起的非敏感标识）
方案                        : ＿＿＿（A VM / A 容器 / B 受控代理 / C 降级-不推荐）
network_mode               : ＿＿＿（default-deny 出站 + 白名单；v4/v6 处理方式）
proxy_mode                 : ＿＿＿（直连 / 显式代理+CONNECT ACL；代理 ACL 摘要）
DNS                        : ＿＿＿（固定解析器地址；白名单外域名处理）
IPv4/IPv6                  : ＿＿＿（各自放行/拒绝面）
default-deny 策略证据位置    : ＿＿＿（操作者本地留档索引）
单实例承诺                  : 单操作者 / 单实例 / 唯一 state dir（签署）
环境重建程序                : ＿＿＿（含 §6 状态卷重挂与链验证步骤）
```

## 6. 状态持久性冲突与持久状态卷要求（T9.7.2.2 —— 关键修正）

**冲突陈述**：`operator-environment-plan.md` §5 方案 A 推荐"一次性 VM，
采集完即弃"；但真实窗口需要 **≥5 个全覆盖交易日** 的 receipt/journal 链
**跨日持续存在**且原始字节不被覆盖。销毁计算资源 ≠ 销毁状态；若状态随
VM 销毁，证据链断裂，窗口作废重来（且不得用任何复制摘要冒充延续）。

**持久状态卷要求**（操作者在步骤 3 固定环境时必须落实）：

1. **独占**：状态卷只服务真实采集链（`receipts.jsonl`、`forward/journal.jsonl`
   及 head/anchor、`forward-window-evaluation.json`）；与任何模拟/自测状态
   目录物理隔离，永不混用；
2. **权限最小化**：仅采集账户可读写；不建议网络共享路径；
3. **加密/受保护**：卷级加密（BitLocker/LUKS 等由操作者选择），密钥管理在
   操作者本地，不入仓库/CI/会话；
4. **跨日原始字节不覆盖**：链是 append-only（机制保证 + 操作纪律）；
   禁止任何"整理/压缩/重写"工具触碰状态目录；
5. **备份与校验摘要**：每个观察日结束后，操作者本地另存当日副本并记录
   SHA-256 摘要（摘要本身不含敏感数据，可入本地签署记录）；
   **摘要只能用于事后对账，复制了摘要 ≠ 验证通过**——验证必须对实际文件
   重算并跑 `status`（预期 COMPLETE 路径 exit 0 / 进行中 exit 0）；
6. **环境重建绑定**：VM/容器重建后必须重挂同一状态卷并**先验证再采集**：
   `status` 退出码语义（0/6/7）+ 两条链的 verify 结果 + 快照摘要比对
   全部通过后才允许后续采集；状态目录**路径保持不变**（或如实记录新路径并
   同步更新所有命令与 attestation 记录）；
7. **协议身份连续**：重建环境不得改变预注册、代码身份与 protocol hash 的
   验证方式；跨协议的旧链对新预注册本来就是毒化状态（现有机制会拒绝）。

## 7. C 项判据精化（T9.7.2.3 —— 对 F-1～F-8 的补充判读规则）

1. **允许域成功必须是"真到达"**：`data.alpaca.markets` 的 HTTPS 响应须核实
   证书链与目标主机名（curl `-v` 的 TLS 握手信息或等效证据）。以下情况
   **一律不算 F-1 通过**：代理认证 407、 captive/劫持页、DNS 错配解析到
   非预期地址、被重定向到别处（3xx）、或自签/无关证书；
2. **禁行域 401/403 = 失败**（请求到达了对端应用层 = 网络层没拦住）；
   只有连接超时/拒绝/DNS 解析失败才算通过；
3. 适用路径必须**逐条有真实证据**：代理/CONNECT、WinINET/WinHTTP 系统代理、
   DNS、IPv4/IPv6、采集器同型子进程——"应该会拦"不写判定栏；
4. **只验收实际用于采集的网络环境**；切换环境 = 全矩阵重验（F-1～F-8 重跑）；
5. 任一必需项无法证明 → 维持 `HOST_EGRESS_ISOLATION_UNVERIFIED`。

## 8. 运行期纪律重申（T9.7.2.4/T9.7.2.5）

- 应用层 `GuardedGetClient`（GET-only + 禁交易 host）**不等于**凭证原生
  只读，也**不等于**主机级安全隔离；Alpaca 账户/市场数据权限以操作者核验的
  实际条款与控制台状态为准（`BROKER_BEHAVIOR_UNVERIFIED` 保持）；
- T8 残余 TOCTOU 是**运行规程缓解**（单操作者/单实例/唯一状态目录 + 入口与
  cycle 前双重复核），**不是跨进程原子互斥**——任何疑似并发执行、状态链
  漂移（digest 不匹配、链 verify 失败、status exit 6/7）或采集进程异常，
  **立即停止后续采集**，人工复核后再决定是否继续；
- 每次异常都如实记录时间/退出码/状态输出摘要到操作者本地记录。

## 9. T9.8 附录：Windows 直连受限试点例外（2026-11-23，增量修订——§1–§8 原文保持不变）

> 依据：用户批示（根目录 `Shutu_M35_S8_T9_8_Windows_Direct_Limited_Pilot_
> Approval.md`）；审批记录
> `../s8-operator-t9-8/windows-direct-pilot-approval-record.md`。
> 批准：`S8_WINDOWS_DIRECT_PILOT_POLICY=APPROVED_WITH_SCOPE`、
> `HOST_EGRESS_ISOLATION_EXCEPTION=APPROVED_WITH_SCOPE(WINDOWS_DIRECT_READ_ONLY_PILOT)`。

1. **实测事实（2026-11-23，操作者直连主机）**：ActiveStore 三档
   `DefaultOutboundAction=Allow`；`data/api/paper-api.alpaca.markets:443`
   实测可达；网络层 **F-2 不成立**。现势状态：
   `OPERATOR_PREFLIGHT_C=BLOCKED`（§2/§3 成文时的 `PENDING_OPERATOR` 为
   T9.7 时点记录，保留不改）；`HOST_EGRESS_ISOLATION_UNVERIFIED` 保持。
2. **例外分支（仅限批示定义的直连受限只读试点范围）**：单用户、非资金、
   只读 IEX 日线、冻结标的（SPY/QQQ，最多原批准 3 个）、前台人工操作；
   程序级守卫（GuardedGetClient 等）仍是必要纵深防御，**不等于**宿主
   网络拦截或凭证只读。
3. **准入门语义替代（不删除原门槛，改为可验证析取）**：
   `A_verified AND ((C_verified AND environment_frozen) OR
   (direct_pilot_exception_approved AND local_risk_acceptance_signed AND
   environment_frozen))`。例外分支下，§3 决策图的步骤 2 以
   "本人签署本地直连残余风险接受记录（approval-record §8.2）"替代
   "C 全矩阵 VERIFIED"；步骤顺序 1→(2 或 2′)→3→4→5→6 与两授权独立性
   不变。`environment_frozen` = §5 登记表完成 + §6 持久状态卷落实。
4. **不变的禁令**：不改 C 原值（例外 ≠ `C=VERIFIED`/F-2=PASS）；不跳过
   B-only 独立授权；不跳过首次 once 独立授权；不改写已冻结历史记录；
   F-1～F-8 原始 FAIL/UNVERIFIED 证据不得虚构。
5. **停止/撤销**：触发条件与动作见 approval-record §6——泄露迹象、交易域
   访问、意外订单、环境改变、版本漂移等任一即停；Key 撤销/轮换由账户
   所有者执行；证据不自动清除、不自动续采；用户可随时明示撤销例外，
   撤销后回落到 §3 原全矩阵路径。
