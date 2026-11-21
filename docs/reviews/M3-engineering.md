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
| status | **E = PASS_WITH_SCOPE (SYNTHETIC_ENGINEERING_ONLY)**（本地；REMOTE_VERIFIED 需用户授权 push 后按实际 CI 双矩阵另评） |
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

1. REMOTE 未验证：全部证据为本地；push 须用户授权，之后按实际 CI 双矩阵评 REMOTE_VERIFIED。
2. 静态检查不能覆盖计算性动态导入/exec（钉子测试如实披露；OS 级隔离归 M4）。
3. Holdout 封存为应用层权限模拟，非 OS 沙箱（模块 docstring 明示）。
4. 官方账本的经济预算行为 NOT_APPLICABLE_YET（M3 各臂零 LLM/人工预算，美元对等留 M4）。
5. 交收/日历为协议假设（T+N 日历日），不冒充真实券商行为；BROKER_BEHAVIOR_UNVERIFIED 不变。
