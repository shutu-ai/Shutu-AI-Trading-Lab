# M3-R2 T3 — 账本复核与不可抵赖边界（R2-P1-2 修复）

- 权威实现: `src/trading_lab/validation/ledger.py`（verify-before-replay /
  单写者锁 / 外部锚 / 批次绑定）
- 测试: `tests/validation/test_ledger_integrity_r2.py`（19 项）；既有 ledger
  测试保留，其中 2 项按**更强契约**更新（见 §4）

## 1. 修复的缺口（RED 实证，4ae119f）

1. `_load_existing()` 直接逐行重放：中间条目 retro-edit 的账本可重新打开并
   继续追加研究（red-probe 3a 实证）。
2. `verify_chain()` 只能验证保留头尾的链；尾部截断/整文件替换/清空不可检测
   （red-probe 3b 实证：删最后一条 → "2 entries verified" True）。
3. 无并发写保护：两个进程可各自以同一 `prev` 成功追加。

## 2. GREEN 机制

### 2.1 加载前先验证再重放（fail-closed 顺序）

构造器：取锁 → 解析（半行/坏 JSON → `LedgerIntegrityError`）→ 全链验 prev/digest
→ **身份绑定**（每条 entry 的 protocol/code/batch 与打开身份一致，否则拒绝；
旧 runner 无法再向 legacy 账本追加新协议数据）→ 重放计数并**逐条比对
`counters_after`**（链自洽但计数撒谎的重链攻击被捕获）→ 外部锚比对（若提供）
→ 才打开写句柄。任何一步失败：计数零消费、零追加、锁释放。

### 2.2 外部锚（诚实能力边界）

- `LedgerAnchor{entry_count, head_digest, tail_digest, protocol_hash,
  code_hash, batch_id, created_ts}`；`export_anchor()`（写者）/
  `read_ledger_anchor()`（只读，拒绝坏/空文件）产出；`anchor=` 打开时逐项比对，
  尾截断 / 整文件替换 / 清空全部 fail-closed。
- **信任边界（不虚称不可抵赖）**：哈希链单独只能检测保留头尾的中间删除/篡改；
  尾截断、整文件替换、清空的检测**完全依赖**独立存放的锚。锚的信任等于其存储
  位置：仓库内提交的 `ledger-anchor.json` 防静默本地篡改（跨文件改动会在 git
  历史留下交叉不一致），但能同时重写账本与锚存储的攻击者仍可伪造——
  **任何 JSONL 账本（带锚或不带锚）都不具备密码学签名意义上的不可抵赖性**，
  本模块不做此声称（模块 docstring、本文件、专用测试三处一致钉住）。
- 官方锚：`artifacts/evidence/M3/r2/ledger-anchor.json`（r2 批次 14 条，
  head `fa7fa0b0…` / tail `c0e6bf14…`）；r1 批次锚（13 条）已嵌入 r2 BATCH_INIT
  血缘记录。锚为**只增补**设施：未改写 r1 任何文件。

### 2.3 单写者锁

- `<ledger>.lock`（`O_CREAT|O_EXCL` 原子创建，含 pid+时间）：同进程/跨进程第二
  写者一律 `LedgerLockedError`——不存在"都以同一 prev 成功写入、事后 verify 才
  报错"的状态。子进程实测：持锁期间父进程被拒；子进程退出后打开成功且**预算
  完整保留**（trials=1）。
- 写者崩溃（A7 风格 `os._exit(37)`）**故意留下陈旧锁**：后续打开全部拒绝
  （fail-closed）；恢复是显式运维动作（取证后删锁 + 审计记录），恢复后历史与
  ALL_BILLED 预算（含 failure 计费）逐项保留（专测实证 returncode=37 全链）。
- 半行写入（崩溃残留）→ 加载拒绝（`malformed/incomplete JSON`），绝不静默丢弃。

### 2.4 批次绑定（合法版本迁移显式化）

`BATCH_INIT` 仅可作新文件首条；entry 顶层携带 `batch_id`；打开时 batch 不匹配
即拒绝——合法迁移 = 新文件 + 显式 BATCH_INIT 血缘引用，绝非文件内静默换身份。
无 batch_id 的 r1 格式文件仅能以 batch_id=None 打开（兼容不弱化）。

## 3. 负例矩阵（19 项测试 → 全部 GREEN）

| 类别 | 用例 |
|---|---|
| 加载前验链 | 中间 detail 篡改拒载；中间条目删除拒载；半行截断拒载；身份 mismatch（code/protocol）拒载 ×2 |
| 计数一致性 | 重链后 `counters_after` 撒谎 → 纯链验证盲、全量加载捕获（防线分层实证） |
| 重启预算 | failure+retry 后重启：计数/臂预算/ALL_BILLED 全保留，超额拒绝 |
| 外部锚 | 尾截断拒；整文件替换拒；清空拒；JSON 往返正控（完好文件+锚成功重开，计数保留）；**无锚验链对尾截断为 True（诚实边界永久钉住）**；坏文件拒绝出锚 |
| 单写者 | 同进程第二写者拒；跨进程第二写者拒（真实子进程）+ 退出后预算保留；崩溃陈旧锁拒 + 显式恢复 + 失败计费保留 |
| 批次 | BATCH_INIT 仅首条（二次拒）；batch mismatch 拒 ×2；r1 格式 batch_id=None 兼容；`verify_ledger_file` 报文契约与 legacy 一致（"3 entries verified"） |

## 4. 既有测试的更新声明（目的不变、契约加强）

`tests/validation/test_ledger.py::test_deletion_breaks_chain` 与
`test_history_edit_breaks_chain` 原假设"损坏文件可构造成功、事后 verify_chain
报错"。R2 后损坏文件在**构造时即被拒绝**（更强保证）。两测试改为断言
`LedgerIntegrityError`（构造期）**且** `verify_ledger_file` 独立报 chain break /
digest mismatch——检测目标（删除/篡改被检出）完全保留，验证时机前移。
无 skip/xfail/except 弱化；测试总数 522→572 只增不减。

## 5. 与 M2 安全回归的关系

本轮未触碰 `tests/fault_injection/`（A2/A5/A6/A7、1,080 故障矩阵专项目标）。
账本属于研究平面（validation 包），架构检查器继续强制其不导入 oms/risk/brokers/
data；运行后专项复跑 11 cases EXIT=0、`check_architecture` 5 包 27 文件 0 违规。
