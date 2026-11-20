# M1 — 工程验收报告（engineering）

| 字段 | 值 |
|---|---|
| stage_id | M1（数据供应准入与点时刻可得性，P0） |
| commit | `c2505becb8beb0f722162059b25c5156f2ecf46f`（实现）；门记录 `463838f`；三轨报告提交见后续 SHA |
| code_hash | git tree at `c2505be` |
| protocol_hash | NOT_APPLICABLE（研究协议在 M3 冻结） |
| environment | Windows 11 Pro，Python 3.13.15（`.venv`），pydantic 2.14.3 / cryptography 50.0.2 / pytest 9.2.0；离线运行；供应商页面经代理只读抓取（无账户、无密钥、无注册） |
| test_commands | 见 §3（全部本地，EXIT=0）；远端 CI 状态 PENDING（未获推送授权） |
| evidence_paths | `artifacts/evidence/M1/checks.log`、`data-vendors.md`、`architecture-health.md` |
| findings | 见 §2 与 §4：工程子集全部达标；供应商覆盖证据为 DOCUMENTED 级，API 实测 BLOCKED_ACCESS；**本地工程缺陷为零，供应商证据不足为既定授权边界所致，二者不混淆** |
| status | **E = PASS_WITH_SCOPE（工程子集）；全市场研究用途数据准入 BLOCKED_DATA** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED (NOT_CREATED) |
| forward_window_status | NOT_APPLICABLE |
| next_gate | M1 阶段门人工复核；数据订阅/凭证授权（可选）以解锁 API_VERIFIED 实测；不自动进入 M2 |
| approver | USER_PENDING（Agent 不代签阶段门） |

## 1. 交付（对齐 M1 任务行）

| 任务行要求 | 交付 |
|---|---|
| 原始/复权/成分/退市/企业行为/公告时间模型 | `contracts` 复用 + `data/actions.py`（三时点独立、asof 知识约束、版本化重算）、`data/membership.py`（区间化成分/退市/映射/重用检测） |
| UTC/ET 日历 | `data/calendar.py`（zoneinfo DST 实测正确；假日/半日为运行时参数表） |
| 供应商授权成本/覆盖/缺失/延迟矩阵 | `artifacts/evidence/M1/data-vendors.md`（2026-11-20 官方页实抓，七字段×三供应商+按用途判定） |
| `configs/data_acceptance.yaml` 按用途非空阈值 | 4 用途全部必填字段齐备，缺失即配置错误（机器校验） |
| 限制不合格资产池 | `acceptance.evaluate_purpose` 判定矩阵 + `membership.universe_asof` PIT 查询 |

## 2. M1 E-Gate 对照表

| 判据 | 结果 | 证据 |
|---|---|---|
| PIT 可得性 | **PASS**：未来发布记录/公告晚于决策/迟到回填/事后复权全部被阻断或显式降级 | `tests/no_lookahead/`（`is_available` 门、`adjust_series` asof 约束、UNKNOWN_AVAILABILITY 显式化） |
| 历史证券池/退市 | **PASS（逻辑）/ BLOCKED_DATA（供应商数据）**：历史区间唯一来源、退市保留、重用检测；真实成分数据无授权来源 | `test_universe_uses_history_not_today` 等；data-vendors.md §4 |
| 复权 | **PASS（逻辑）**：原始+因子可重算、版本化、单因子变化可检测 | `test_split_recomputation_exact`、`test_deterministic_same_inputs_same_output` |
| 质量分母 | **PASS**：分母/缺失/覆盖率/延迟/样本量机查；零分母=INCONCLUSIVE | `test_zero_denominator_is_inconclusive_not_100` 等 |
| 许可/成本 | **BLOCKED_DATA（如实）**：三家均无凭证（任务禁止注册/购买）；个人研究许可条款 DOCUMENTED 级粗粒度（Massive individual terms） | data-vendors.md 各行层级标注 |
| snapshot | **PASS**：确定性 hash、单值改动必变、篡改可检测 | `test_deterministic_hash`、`test_single_value_change_changes_hash`、`test_tampered_manifest_detected` |
| 安全回归 | **PASS**：M0 140 用例原样全绿；`check_architecture` 0 违反；smoke/纯度门 PASS | `checks.log` |
| 架构健康 | **PASS**：§5 全表通过（见 architecture-health.md B 节七分类） | `architecture-health.md` + check_architecture EXIT=0 |

**准入判定（数据-vendors §4 摘要）**：全市场日线研究=BLOCKED_DATA；历史成分/退市研究=BLOCKED_DATA；企业行为可重算研究=BLOCKED_DATA；分钟线研究=RESTRICT_SCOPE；事件研究=RESTRICT_SCOPE；管道工程验证=ACCEPT（仅工程用途）；工程监控=ACCEPT（仅工程用途）。

**总 E-Gate 判定**：按冻结的 M1 必需用途（全市场日线研究），**数据准入 = BLOCKED_DATA**；工程实现子集 = PASS_WITH_SCOPE。两者不得合并为"完整数据供应准入 PASS"。

## 3. 实际运行命令与退出码（HEAD `c2505be`）

```text
scripts/check_environment.py   EXIT=0（3.13.15 基线）
python -m pytest -q            EXIT=0（187 passed = M0 140 + M1 47）
scripts/check_architecture.py  EXIT=0（data 包 0 违禁导入）
scripts/scan_secrets.py        EXIT=0（208 tracked files / 0 findings —— 本轮数）
scripts/verify_live_blocked.py EXIT=0
scripts/smoke_mock.py          EXIT=0（M0 安全回归）
git diff --check               干净
```

全文见 `artifacts/evidence/M1/checks.log`。**远端 CI = PENDING**（M1 提交未推送，未获授权；不得据本地宣称远端已过）。

## 4. 真实/合成证据界限（任务书 §4 明令区分）

- **合成 fixture 证明的**：PIT 门逻辑、复权重算正确性、分母统计、快照确定性、准入判定语义——全部为本地工程逻辑，与供应商无关。
- **DOCUMENTED 证明的**：供应商产品存在性、覆盖声明、价格档（$29/$199）、Alpaca Basic 2016+/15min/200rpm——来自官方页面（URL+检索日期在 data-vendors.md）。
- **不存在（未声称）**：任何 API_VERIFIED 实测行——三家均 BLOCKED_ACCESS；Sharadar 精确价格、Massive 退市深度、Alpaca 免费档 CA 包含性、各家个人研究许可全文 = UNVERIFIED。
- yfinance/qlib POC 数据维持 M-1 约束：不进 Alpha 证据链（ADR-003 D3）。

## 5. Findings（工程缺陷与边界）

1. **本地工程缺陷：0**（187 用例全绿；首轮 red 全部为 TDD 预期失败，已在实现中转绿）。
2. **供应商证据不足**：既定授权边界（禁止注册/购买）所致，非缺陷；解除条件与最小所需授权见 data-vendors.md §4 解除列（Sharadar 订阅 + Alpaca/Massive 凭证，均需用户批准）。
3. tzdata 依赖为 Windows zoneinfo 必需（干净环境实测），已记录于 architecture-health DEPENDENCIES。
4. 残余债务（architecture-health DEBT）：真实假日表接入（M3 前）、供应商适配层按真实 API 再建、coverage/missing 双阈值公式统一（M3 前）。
