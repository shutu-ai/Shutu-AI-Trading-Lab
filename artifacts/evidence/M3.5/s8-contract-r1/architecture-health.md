# s8-contract-r1 架构健康（T4）

## 检查器

`scripts/check_architecture.py`：6 平面扫描（src 五包 + daemon + gateway），**0 违规**（`verification.log` EXIT=0）。gateway 规则不变：唯一网络平面、仅 urllib、禁 brokers/oms/risk/第三方 SDK/stdlib 网络原语；daemon 禁网规则原样保留（测试锁定）。

## 分类（相对 S8 R0 基线 `2e189eb` + 本地 `1b3460e`）

| 类别 | 内容 |
|---|---|
| REUSE | 引擎/journal/session/envelope/rule/identity/AuditLog/Calendar/Canonical/Cohorts/eligibility 机器全部复用（eligibility 零改动——新事实字段由 gateway 侧 facts 源提供） |
| MODIFY | `alpaca_feed.py`（contract switch：legacy 分支**字节冻结** + ranged 生产分支：有界窗/分页/真实 query 序列化/disconnect 分类）；`quality.py`（新增 `validate_raw_daily_bars`；legacy `_validate` 冻结为 `validate_raw_bar` 钉证据）；`prereg_real.py`（schema v2=legacy 钉定 / v3=ranged 硬约束 + `data_contract`）；`offline_fixtures.py`（双形状 dispatch + page_token 链）；runner（`--config` 显式选择、legacy 拒绝 exit 5、`WINDOW_COMPLETED` 持久化 + 快照校验）；identity（范围含新配置 + 双夹具） |
| ADD | `configs/forward_observation_s8_real_v2.yaml`（schema v3，`m35-s8-real-shadow-readonly-v2`）；`fixtures/selftest_daily_bars_v2.json`（官方 ranged 形状夹具）；`tests/s8_gateway/{test_daily_bar_contract,test_forward_gate_persistence,test_protocol_migration}.py` + RED 探针文件；证据目录 `s8-contract-r1/` |
| REPLACE | 无（legacy 分支保留为钉定证据，非替换） |
| REMOVE | 无 |
| POC-ISOLATE | 无 POC 依赖 |
| DEPENDENCIES | **零新增**（stdlib urllib/json/decimal/hashlib；pyproject 未动） |
| DEBT | legacy contract 分支（`PreregistrationReal.contract_legacy=True` 路径 + 旧夹具 + 旧质量门）：仅证据复现消费者（pinned 测试 + RED 探针）；真实采集结构性拒绝。待 legacy 证据冻结需求消失后可在未来版本移除（独立审批） |

## 唯一职责（防第二实现）

无第二 Shadow 引擎/第二 PIT 规则/第二 eligibility 机器/第二 journal。facts 字段由唯一 `window_facts_from_journal` 计算；`evaluate_eligibility` 未改语义。receipt 链 v2（`disconnect_eligible` 分类）是既有 AuditLog 机制的记录 schema 演进，非新机制。

## 可复现命令

```
.venv\Scripts\python.exe -I scripts\check_architecture.py     # 0 violations
.venv\Scripts\python.exe -m pytest -q                          # 926 passed
.venv\Scripts\python.exe -I scripts\run_m35_s8_shadow_real.py check-config
.venv\Scripts\python.exe -I scripts\run_m35_s8_shadow_real.py collect  # exit 3/4/5 拒绝路径
```
