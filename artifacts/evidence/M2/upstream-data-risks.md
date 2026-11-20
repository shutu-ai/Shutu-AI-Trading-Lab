# M2 上游（M1）数据风险登记 — T6

> 任务书 §M2-T6：只读复核/隔离合成测试确认或驳回，**不借 M2 范围重写 M1 数据模块**。
> 复核日期：2026-11-20。复核人：M2 执行会话。状态：**确认存在，未修复（待单独授权）**。

## U-1 — VendorFacts 枚举字段无词值校验，非法字面量静默按"满足"处理（已确认）

- **路径**：`src/trading_lab/data/acceptance.py` — `VendorFacts`（plain dataclass，str 字段）+ `evaluate_purpose`（R1 整改后的 PIT 矩阵与覆盖分支只匹配**已知字面值**）。
- **隔离合成复现**（未触碰任何生产/测试代码，直接构造 VendorFacts）：
  1. `pit_availability='PIT-ready (marketing claim)'`（非法词值）+ 其余全部满足 → `historical_research_daily` 判定 **ACCEPT**，reasons 为空——非法值不匹配 `none/eod_only/unknown` 任一分支，静默按"具备 PIT"处理。
  2. `history_membership_coverage='partially'` 等三个覆盖字段全部填非法值 → 同样 **ACCEPT**——既非 `unknown`（BLOCKED）也非 `no`（ABSENT），覆盖按满足处理。
- **对照正确行为**：已知值 `unknown` → BLOCKED_DATA、`no` → on_fail（M1 R1/R2 整改已覆盖）；缺口仅在**词表外字面量**。
- **影响**：真实研究数据解封时，手工整理供应商事实的脚本/人工输入若拼写偏差或混入营销用语，会静默获得研究准入。当前 BLOCKED_DATA 状态下无实际暴露（license_confirmed=False 先行硬阻断），但**解封前必须修复**。
- **修复方向（待授权后实施，约 10 行）**：`VendorFacts` 改为带词表校验的 frozen 模型（`pit_availability ∈ {event_level, eod_only, none, unknown}`、coverage 三字段 ∈ `{yes, no, unknown}`，非法值加载即拒），与 R2 的 `available_at_rule` 词表化同构；并补非法词值 → BLOCKED_DATA 的负例测试。
- **责任阶段**：真实研究数据解封（API_VERIFIED 引入）之前，作为该解锁的**前置阻断项**；修复本身很小，但属 M1 范围变更，需用户单独授权。
- **判定动词**：`BLOCKED_DATA`（维持）；本项不改变 M2 的 MOCK_ONLY 结论。

## U-2 — API_VERIFIED = NONE（既定事实，非新发现）

无 Sharadar 订阅、无 Alpaca/Massive 凭证、无许可全文：三家供应商均 BLOCKED_ACCESS。
M2 全程使用 `synthetic-engineering-fixture` 标注数据与本地 FakeBroker；M3 真实数据
研究能力不因 M2 工程通过而解锁。
