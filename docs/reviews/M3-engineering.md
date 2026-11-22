# M3-R1 — 工程验收报告（engineering）

| 字段 | 值 |
|---|---|
| stage_id | M3-R1（独立验收整改 + 合成离线研究闭环，SYNTHETIC_ENGINEERING_ONLY） |
| commits | T1 `8f03b06`（P0 A7 恢复）；T2 `4ca84a0`（协议冻结）；T3/T4/T5 `464896a`（回测/臂/验证）；T6/T7 见后续 SHA |
| 基线审计 | `artifacts/evidence/M3/r1/baseline.md`：远端 CI run `44929797426` 双平台**实际 343 passed**（一手 job 日志取证），提交信息"347"不实；退化源头 = `TestA7T1ClaimHolderCrash` 5 项参数化删除（净 -4 精确吻合） |
| protocol_hash | `48dee8613dd727b3fce04230851c75062c9a6e85e634709d8bab09df1cf6ed83`（v1.1，修订留痕见 protocol-freeze.md；v1.0 `9158028...` 未被任何官方实验消耗） |
| dataset_hash（官方合成集） | `441980e3a64a5494fa90376dd23edf10ca79a777984f9bc1469225491d0eb435` |
| environment | Windows 11 Pro，Python 3.13.15（`.venv`，pytest 9.2.0），离线；零新第三方依赖 |
| test_commands | 全套件 522 passed EXIT=0（含 RUN1 失败→修复→绿链条，见 verification.log）；backtest+validation 136 passed；1,080 故障矩阵专项 11 cases EXIT=0；check_environment/architecture/scan_secrets/verify_live_blocked/smoke_mock 全 EXIT=0；git diff --check 干净 |
| evidence_paths | `artifacts/evidence/M3/r1/{baseline.md, security-regression.md, protocol-freeze.md, verification.log, negative-tests.log, experiment-ledger.jsonl, experiment-summary.json, cohort-overlap-report.md, architecture-health.md, fault-matrix-r1.txt, t1-*, t2-*, t3-red.txt}` |
| findings | P0（A7 回归）已修复并强化；测试模块名冲突（conftest sys.modules 污染）已修复；协议预算修订（v1.0→v1.1）发生在任何官方实验消耗前并双版本留痕 |
| status | **E = PASS_WITH_SCOPE (SYNTHETIC_ENGINEERING_ONLY) — REMOTE_VERIFIED**：用户授权推送 `dde7a8b` 后 CI run `44938095081` 双矩阵 success（Ubuntu `522 passed` / Windows `522 passed`，一手 job 日志取证见 `remote-ci.md`），与本机 522 完全一致 |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED_NOT_MATERIALIZED |
| forward_window_status | NOT_APPLICABLE |
| next_gate | **M3_GATE=USER_PENDING**；推送、M3 关闭、M3.5/M4 启动均需用户另行签批 |
| approver | USER_PENDING |

## 1. P0 恢复（第一 STOP/GO 门：GO）

- RED：3505799 上 A7 文件仅 3 项收集，五轮 crash proof 不存在（t1-red-collection.txt）。
- GREEN：逐字恢复 f27892d 的 `TestA7T1ClaimHolderCrash[1..5]` 并强化为无条件双层阻断
  （恢复后 RiskEngine 必拒 + HALT 前合法密封决策提交必 HALT_NEW_RISK + 零 broker 副作用）；
  8/8 passed（t1-green-ids.txt 逐 ID）；fault_injection 全目录 30 passed。
- 测试总数 348 ≥ 旧 347；1,080 故障矩阵与 Paper/Live 隔离测试零改动。

## 2. T2–T7 交付对照

| 任务 | 交付 |
|---|---|
| T2 协议 | 唯一加载器 fail-closed；hash=canonical_digest（复用 security.canonical）；9 节受控变更→新 hash 探针；运行时不可变；SET/NOT_SETTABLE 门（statistical_alpha 恒 INCONCLUSIVE）；删除 `max_drawdown_pct: 100` 假门；结构化等试验预算（ALL_BILLED）+ 诚实 NOT_APPLICABLE_YET 经济预算；M9 选择规则预注册 + SEALED_NOT_MATERIALIZED 无伪造 ID |
| T3 回测内核 | 消费 contracts.MarketBar（桩 Bar 删除）；Decimal 全链拒绝 float/int/str；负/零价、资金不足、超卖、缺价 fail-closed；乱序/重复 bar 拒绝（按原始输入序）；T+2 交收账本与精确守恒恒等式；次开成交 + spread/slippage/commission + 量上限 + 部分/未成交/取消事件；SPLIT/DIVIDEND/DELISTING 复用 contracts.CorporateAction；退市后代码复用拒绝；输出 digest 绑定 seed+protocol/dataset/code hash；PIT 访问器 |
| T4 B0–B2 | B0 现金（诚实 0 收益）；B1 买入持有（分红/拆股/跳空）；B2 预声明 MA 交叉，参数仅 Train/Validation 选择并冻结（网格按预算计费）；盈利/亏损/零交易/跳空/全额不成交/费用超收益/拆股分红/交收夹具逐类断言；成本 ×1/×2/×3 敏感性；全部结果打 SYNTHETIC_ENGINEERING_ONLY 标，绝无 HIST_OOS_SUPPORTED/alpha 声称 |
| T5 验证 | cohort 五维重叠检测（sealed 样本定义维度重叠=非法，域重叠=披露）；purge/embargo fail-closed；滚动 walk-forward 不重叠 OOS；前向 cohort 先锁预测后观察、一次性评分污染；封存 Holdout 状态机（研究角色读/聚合/差分/探测全拒+审计；治理角色唯一解封→污染标记；二次解封与冠军重选无条件拒绝；四态 verdict 齐备）；append-only 哈希链账本（预算 fail-closed、失败即 HALT、重启恢复、删除/篡改检测） |
| T6 架构 | check_architecture.py 3→5 包；研究包仅允许 contracts+security；data/risk/oms 禁导入研究包（既有方向规则扩展）；38 项新负例（含前缀相似不误报、常量动态导入、相对导入、运行时无网络探针、诚实静态限制钉子）；零新依赖 |
| T7 实测 | 全套件 522 passed；官方实验 9 trials+4 queries 全入账（链验证 13 entries）；cohort 独立性报告 independent=True；三轨报告与全工件落盘 |

## 3. 已知风险与边界（如实）

1. ~~REMOTE 未验证~~ → **已消除**：用户授权推送后 CI run `44938095081`（SHA `dde7a8b`）双矩阵 522 passed，REMOTE_VERIFIED 记录见 `artifacts/evidence/M3/r1/remote-ci.md`。
2. 静态检查不能覆盖计算性动态导入/exec（钉子测试如实披露；OS 级隔离归 M4）。
3. Holdout 封存为应用层权限模拟，非 OS 沙箱（模块 docstring 明示）。
4. 官方账本的经济预算行为 NOT_APPLICABLE_YET（M3 各臂零 LLM/人工预算，美元对等留 M4）。
5. 交收/日历为协议假设（T+N 日历日），不冒充真实券商行为；BROKER_BEHAVIOR_UNVERIFIED 不变。
6. **A2/A5/A6 证据日志副作用披露**：这三个测试自 M2 起就在每次运行时重写自身
   日志（新 PID 替换旧 PID；行数一致，且都是通过运行）。本轮 fault_injection 全目录
   回归与全套件运行按测试设计再次重写了这三个文件（commit c0c49ae 含此变更）。
   原始版本在 Git 历史（3505799 及更早）中可追溯；M2 gate record 的审计披露已记录
   该重生成行为。未对断言或测试逻辑做任何改动。

---

# M3-R2 补充（研究证据完整性定向补强，2026-11-21）

> 本节为 R2 追加，不改动上文任何历史事实。完整独立验收见
> `docs/reviews/M3-r2-independent-closure.md`；证据在 `artifacts/evidence/M3/r2/`。

| 字段 | R2 值 |
|---|---|
| status | **M3_R2_RESEARCH_INTEGRITY_REMOTE_VERIFIED / E=PASS_WITH_SCOPE(SYNTHETIC_ENGINEERING_ONLY)**（2026-11-22 用户授权推送；受测代码 SHA `906bf6f`，run `44998829308` 双矩阵 `572 passed`，一手 job 日志见 `artifacts/evidence/M3/r2/remote-ci.md`；上文 REMOTE_VERIFIED 属 dde7a8b 的既有测试范围，本轮为 R2 变更的独立验证）。远端过程含如实披露：SHA 9e640bd attempt1 ubuntu 失败于既有 M2 A6 进程竞争 flake（571/572），attempt2 windows 失败于 R2 自身 CRLF 前置断言测试缺陷（已修复），修复 SHA 双矩阵全绿。M3_GATE=USER_PENDING 不变 |
| R2-P0-1 code 身份 | FIXED：24 文件全量清单 `af7ff10c…`（RED：engine 字节变更 legacy hash 不动）；legacy `c0a9ede5…` 钉为 RUNNER_ONLY_LEGACY，r1 证据零改写 |
| R2-P1-1 样本门 | FIXED：`sample_gate` API + 官方运行前强制拒绝 + 结果层强制印章；20-bar r1 注册为 SYNTHETIC_SMOKE_ONLY_LEGACY；120-bar 官方批次 `m3-r2-batch-1`（v2 协议 `8afb5207…`，9 trials + 4 queries，0 失败，成本 ×1→×3 单调退化） |
| R2-P1-2 账本 | FIXED：加载前验链 + 身份/计数一致性 fail-closed + 单写者锁 + 外部锚；尾截断/替换/清空经锚可检测；**诚实边界钉住**：无独立锚的 JSONL 不具备不可抵赖性 |
| 测试分母 | 522 → **572**（+50，0 删/跳/xfail；3 处既有测试更新均非弱化，逐处声明见 r2 evidence）；1,080 矩阵专项重跑 11 cases EXIT=0；architecture 5 包 27 文件 0 违规 |
| next_gate | 不变：M3_GATE=USER_PENDING；push/M3 关闭/M3.5/M4 需用户分别签批 |
