# M3-R1 — 真实资金验收报告（real-capital）

| 字段 | 值 |
|---|---|
| stage_id | M3-R1（SYNTHETIC_ENGINEERING_ONLY） |
| status | **R = NOT_STARTED** |
| deployment_state | NOT_DEPLOYED |
| broker_access | 无（Alpaca Paper/Live 密钥不存在于本机；`check_environment.py` 确认 alpaca env vars absent） |
| real_money_movements | 0（零真实订单、零资金操作、零券商 API 调用） |

## 1. 本轮与真实资金的关系：无接触

- 全部工作为合成数据 + 纯离线工程（FakeBroker/合成价格路径）。
- `verify_live_blocked.py` EXIT=0：paper 运行时无 live 工件；live 配置不可达。
- `scan_secrets.py` EXIT=0：356 个受控文件零密钥发现。
- 回测内核与验证层被架构检查器（5 包规则）强制禁止导入 oms/brokers/risk/data——
  研究代码不存在触达真实订单路径的静态可能；运行时无网络探针佐证。

## 2. 不变量保持

| M2 安全不变量 | 本轮状态 |
|---|---|
| 1,080 故障矩阵（9 类） | 未改动；专项重跑 11 cases EXIT=0，0 违例 |
| A7 五轮 claim-holder crash + 自动 HALT | 因 3505799 退化而被删除 → 本轮恢复并强化（P0，GO 门） |
| Paper/Live 完全隔离（configs/live、runtime 检查） | 未触碰；verify_live_blocked 继续通过 |
| 唯一 OMS/Risk/Broker 权威 | 未引入第二执行器；研究包禁止导入交易平面（架构检查器强制） |
| BLOCKED_DATA / U-1 UNRESOLVED / BROKER_BEHAVIOR_UNVERIFIED | 不变 |

## 3. 资金门（恒定，直至用户另行签批）

- 真实券商/资金操作在所有阶段被禁止，直到 M9 之后由账户所有者另行签批（AGENTS.md 规则 3）。
- M3-R1 不申请、不预批、不预连接任何 Paper/Live 环境。
- Live 准入硬守卫链（E∧S∧evidence_state∧final_holdout_status∧forward∧签批）本轮
  无任何一项被推进；final_holdout_status 仍为 SEALED_NOT_MATERIALIZED。
