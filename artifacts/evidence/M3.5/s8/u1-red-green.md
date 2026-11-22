# S8-T1 — M1 U-1 修复 RED→GREEN 记录

> 签批依据：`artifacts/evidence/M3.5/s8/authorization-check.md` 条款 2
> 范围声明：**本修复不解除全市场历史研究 `BLOCKED_DATA`**（签批原文明确）。

## 缺陷定义（M3-R1 审查登记项 U-1）

`VendorFacts` 的四个能力字段（`history_membership_coverage`、`delisting_coverage`、`corporate_actions_coverage`、`pit_availability`）为开放 `str`，仅靠 `evaluate_purpose` 内的 `==` 比较。任何词表外的值——供应商营销串（`"PIT-ready (vendor marketing claim)"`）、`"partially"`、大小写错误（`"YES"`）、空白变体、`None`、非字符串——**既不命中 unknown→BLOCKED，也不命中 no→on_fail**，静默落穿全部检查进入 `ACCEPT`。

## RED（修复前，2026-11-22，本地实跑）

`u1-red-reproduction.txt`（本目录，对修复前代码实跑，EXIT=0）：

```
DEFECT-1 CONSTRUCTION: illegal values accepted -> 'partially' / 'event-level capable per vendor page'
DEFECT-2 EVALUATION verdict = ACCEPT reasons = []
RED CONFIRMED: illegal enum values flowed through to ACCEPT.
```

即：构造放行 + 全满足覆盖 + 营销串 PIT ⇒ **ACCEPT（零理由）**——正是"误放行"。

## GREEN（修复后）

最小修复（`src/trading_lab/data/acceptance.py`）：

- 新增封闭词表常量：`COVERAGE_FACT_VALUES = {yes,no,unknown}`、`PIT_AVAILABILITY_VALUES = {event_level,eod_only,none,unknown}`；
- `VendorFacts.__post_init__` 构造校验：词表外值抛 `VendorFactsError`（`DataAcceptanceConfigError` 子类，既有 except 链兼容）；**无任何向"具备能力"的回退**；
- `evaluate_purpose` 判定矩阵与冻结顺序**零改动**。

测试（`tests/no_lookahead/test_vendor_facts_u1.py`，26 项，全绿）：

- 正例：全部合法组合可构造；`event_level+全 yes → ACCEPT`、`unknown → BLOCKED_DATA` 语义逐字不变；
- 反例（参数化 ×4 字段）：营销串 / `partially` / `YES` / `"yes "` / `""` / `None` / `123` / 尾换行 / 近似拼写（`eod-level`、`event-level`）→ 一律构造期拒绝；缺字段 → TypeError；
- 端到端：RED 场景（营销串 PIT + 全 yes）修复后**对象无法构造**，准入面无法被冒充；
- 范围守护：`unknown` 事实仍 BLOCKED_DATA —— 修复不收紧合法准入、不解除历史研究封锁。

既有 M1 准入回归（`test_remediation_m1rr001.py` + `test_quality_snapshot_acceptance.py`）**零改动全绿**；`VendorFacts(` 全仓构造点仅两个测试 helper，均为合法值。

## 状态

`M1 U-1 = FIXED（工程与测试范围）`；全市场历史研究 `BLOCKED_DATA` **保持**；Sharadar/PIT/退市缺口**仍在**（签批文本明示不解除）。
