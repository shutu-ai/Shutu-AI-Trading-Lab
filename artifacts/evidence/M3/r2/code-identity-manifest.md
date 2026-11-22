# M3-R2 T1 — 研究代码身份清单（R2-P0-1 修复）

- 权威实现: `src/trading_lab/validation/code_identity.py`（唯一计算点，无第二套）
- schema: `research-code-identity-v1`
- 测试: `tests/validation/test_code_identity.py`（19 项）

## 1. 修复的缺口（RED 实证）

`4ae119f` 上 `run_m3_baselines.py:71-72` 的 code_hash = **runner 单文件字节哈希**；
`engine.py`/`arms.py`/`validation/*`/contracts/security 及顶层 `__init__` 均不在
输入内。red-probe 实证：改 engine 源码字节 → legacy hash 不变；r1 账本 13 条
全部绑定该 legacy 值 `c0a9ede5bf4dea02e5a4141f3a494c29291039d678ed3aae2380619d510a8d0f`。

## 2. 固定契约

| 项 | 契约 |
|---|---|
| scope | ① 官方 runner（恰好一个，必须 `scripts/*.py` repo 相对路径）；② `src/trading_lab/backtest/**`、`validation/**`；③ import 期语义依赖：`contracts/**`、**整个 `security` 包**（其 `__init__` 在 import canonical 时执行全部安全子模块）、`src/trading_lab/__init__.py` |
| 排除 | `__pycache__`、非 `.py`、第三方依赖（属环境而非研究代码）、交易平面 `oms/risk/brokers/data`（架构规则禁止其被研究导入，永不入身份） |
| 归一化 | UTF-8 解码 → 去 BOM → CRLF/CR→LF → SHA-256。GitHub Windows(CRLF)/Linux(LF) 检出同一提交 → **同一 code_hash**（跨平台一致由 `test_windows_crlf_and_linux_lf_checkouts_hash_identically` 机械钉住） |
| 清单 | `files` = 按 POSIX 相对路径排序的 `(路径, 归一化内容 SHA-256)` 元组；`code_hash` = `sha256(canonical_json({schema, runner, files}))`（复用 security.canonical，无第二套 canonical） |
| git 记录 | `git_commit`/`git_tree` 仅记录用于独立复核，**不参与 hash**（身份是实际运行源码内容的函数，不是工作树状态函数） |
| fail-closed | 任何 scope 成员缺失（runner/包/顶层文件）→ `CodeIdentityError`；runner 不在 scripts/ → 拒绝 |
| 消费点 | runner→arms/engine（run_id、output_digest）→ ledger 每条 entry → experiment-summary → code-identity-manifest.json，**同一 code_hash** |

## 3. 官方运行身份（batch m3-r2-batch-1）

| 项 | 值 |
|---|---|
| code_hash | `af7ff10c425c0f153b2e7c1d1a86c6185267438610a81fa39a268a0f8d15f611` |
| 文件数 | 24 |
| runner | `scripts/run_m3_r2_baselines.py` |
| git_commit（记录值） | `4ae119fe17ab7118075adb2899def69eafe2cd78`（R2 变更所在工作树，提交前的 HEAD；代码身份以清单文件 digest 为准） |
| git_tree（记录值） | `8345984ad9cd7b9ed430d5f93f445892a3647551` |
| 完整清单 | `code-identity-manifest.json`（24 文件逐路径 digest） |

跨进程确定性：`test_same_hash_in_fresh_processes` 以 `python -I` 两进程 + 进程内
计算三方一致；`test_manifest_digest_is_canonical_json_of_sorted_file_list` 钉住
hash 构造纯度；git 字段变更不改变 code_hash（专测）。

## 4. 硬测试（隔离副本，全部 GREEN）

engine / arms / ledger / protocol / code_identity / contracts / security.canonical /
runner **逐文件字节变更 → code_hash 必变**（8 项参数化）；缓存与杂文件排除；
CRLF/BOM 等检出噪声不变；缺失 scope fail-closed；真实树 scope 成员完备且**零
交易平面泄漏**（逐路径白名单断言）。

## 5. legacy 边界（不改写历史）

- `LEGACY_R1_RUNNER_ONLY_HASH` 常量钉住 r1 值；专测断言其等于当前 r1 runner 源的
  归一化 digest——任何人改动 r1 runner 导致 r1 不可复现时会**响亮失败**。
- r2+ 实验一律使用全量清单身份；legacy 值在协议 v2 批次注册表中标记
  `code_hash_scope: RUNNER_ONLY_LEGACY`，不扩展、不重签、不重写。
- r1 账本加载路径现在也受身份绑定保护：用新协议/新 code_hash 打开它会
  fail-closed（identity mismatch）——旧 runner 在新协议下无法再向 legacy 账本追加。
