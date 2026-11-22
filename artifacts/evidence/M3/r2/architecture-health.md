# M3-R2 T4 — 架构、旧安全回归与证据卫生

- 日期: 2026-11-21；基线 HEAD `4ae119fe17ab7118075adb2899def69eafe2cd78`

## 1. 架构完整性

| 检查 | 结果 |
|---|---|
| `scripts/check_architecture.py` | **5 包 27 文件（+1：validation/code_identity.py），0 violations，EXIT=0** |
| 研究平面方向规则 | backtest/validation 仍仅允许 contracts + security；本轮新代码（code_identity、ledger、protocol、r2 runner）零新跨包依赖（ledger/protocol 沿用 security.canonical；code_identity 仅 stdlib + security.canonical） |
| 38 项架构负例 + 5 包扫描 | 全部保留（`tests/architecture/` 全绿） |
| 第二安全门/第二 OMS/风险权威 | 未引入（账本与身份清单是研究证据工具，不进入交易平面） |

## 2. M2 安全回归与既有目标（只增不减）

| 目标 | 本轮状态 |
|---|---|
| M2 A7 五轮真实 `os._exit(37)` claim-holder crash + HALT 负例 | 未触碰，`tests/fault_injection/` 全绿（本套件 572 内） |
| 1,080 故障矩阵（9 类） | 专项重跑 `tests/fault_injection/test_fault_matrix.py`：11 cases passed，EXIT=0（verification.log） |
| A2 100 轮线程竞争 / A5 spawn barrier / A6 50 轮严格证明 | 未触碰；随全套件执行 |
| 522 项既有 pytest 目标 | 全部保留：**522 → 572（+50 新增，0 删除/跳过/xfail）** |
| 既有测试更新（共 3 处，非弱化） | ① `test_protocol.py:35` protocol_id 断言 v1→v2（随受控协议变更，目的不变）；②③ `test_ledger.py` 两项损坏账本测试改为**构造期拒绝 + 独立验链双断言**（契约加强，详见 ledger-integrity-negative-tests.md §4） |

## 3. 证据卫生

- `artifacts/evidence/M3/r2/` 全部新建；`git status` 证实 `M3/r1/` 与
  `M2/**` 零改动（r1 账本 13 条 re-verify True）。
- A2/A5/A6 证据日志副作用（M2 起每次运行重写自身日志，r1 已披露）：本轮
  全套件运行再次触发同设计重生成（行数一致、全通过）；原始版本在 git 历史
  可追溯。1,080 矩阵聚合报告按既有测试设计再写
  `artifacts/evidence/M2/fault_matrix_report.txt`（同一路径、同一格式，r1 已披露
  的"unchanged path per M2 lineage"行为延续）。
- RED 全部在临时目录/隔离副本执行：未篡改任何正式历史工件；官方 r2 账本对
  已存在文件拒绝重跑。

## 4. 验证电池（全部真实退出码，见 verification.log）

| 命令 | 结果 |
|---|---|
| `python -m pytest`（全套件） | **572 passed in 165.05s，EXIT=0** |
| `pytest tests/backtest tests/validation` | 186 passed，EXIT=0 |
| `pytest tests/fault_injection/test_fault_matrix.py` | 11 passed，EXIT=0（1,080 实例） |
| `check_environment.py` | EXIT=0（Python 3.13.15，alpaca env absent） |
| `check_architecture.py` | EXIT=0（5 包 27 文件 0 违规） |
| `scan_secrets.py` | EXIT=0（370 tracked files，0 findings） |
| `verify_live_blocked.py` | EXIT=0（paper 运行时无 live 工件） |
| `smoke_mock.py` | EXIT=0（paper gate + kill switch + mock live 验证 fail-closed） |
| `git diff --check` | EXIT=0（仅 LF/CRLF 提示类 warning，与 r1 同类） |
| 官方 r2 运行 | EXIT=0（样本门 SATISFIED，14 条链验证，锚点落盘） |

## 5. CI 状态

本轮新 SHA **未推送**（无授权）：CI_REMOTE_PENDING。既有 REMOTE_VERIFIED
事实不变：run `44938095081`（SHA `dde7a8b`，非本轮受测代码）Ubuntu job
`136949069626` / Windows job `136949069758` 均 `522 passed`（一手日志，
2026-11-21 本轮 gh 复核）。新 SHA 双矩阵需用户单独授权 push 后方可写
`REMOTE_VERIFIED`。
