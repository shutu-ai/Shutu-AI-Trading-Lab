# M0 独立验收整改记录（M0-REVIEW-REMEDIATION-001）

| 字段 | 值 |
|---|---|
| 任务 ID | M0-REVIEW-REMEDIATION-001（任务书：仓库根 `Shutu_AI_Trading_Lab_M0_Remediation_Codex_Task.md`） |
| 复审基线 | `cd194cae7f2b9c7e7546a915ffcc2af12e970b4c`（任务书指定）；实际执行基线 **`b9d08a1`（最新 HEAD）**——经核对，`cd194ca..b9d08a1` 差异仅为 5656dc5（license 修复）与 b9d08a1（CI 结果补记），与本任务 R1 内容一致且为已获用户授权的推送，无冲突后按用户指示在最新版本上执行 |
| 执行日期 | 2026-11-20 |
| 性质 | 对 M0 的定向验收整改；不重做 M0、不改架构、不动 P0–P4/M-1～M11 路线与三轨结论 |
| 三轨报告地位 | `M0-engineering/strategy/real-capital.md` 仍是 M0 验收唯一规范报告；本文件是补充整改记录，不取代任何一轨 |
| approver | **USER_PENDING**（M0 阶段门与 M1 启动均待用户签批；Agent 不代签） |

## 0. 审查已知事实核对（任务书 §1 与实际情况的差异说明）

| 任务书已知事实 | 核对结果 |
|---|---|
| CI run `44755037633` Ubuntu Install 失败、Windows 被取消，CI 未通过 | **属实**（针对基线 cd194ca）。根因 `license="Proprietary"` 非 SPDX——已复现并留存证据（§R1） |
| `pyproject.toml` license 元数据待修 | 已在 `5656dc5` 修复为 `LicenseRef-Proprietary`（SPDX 自定义标识语法，保持**原有私有许可立场不变**，未引入任何开源许可）；修复经用户授权推送后 **run `44755451594` 双矩阵（ubuntu/windows）实际 PASS** |
| Paper endpoint 判断含 `"paper"` 子串、可能被路径/查询伪装绕过 | **属实**，R2 整改前已直接复现：`https://api.alpaca.markets/paper`（Live 主机）被当作 Paper endpoint 接受 |
| `evaluate_portfolio()` 缺可信来源/账户上下文 | **属实**，结构合法即可 `ALLOW_PORTFOLIO`（R3 前缺陷） |
| `SchemaGate._parse()` 对意外输入类型可能抛异常 | **属实**：非 bytes/str 输入会传播 TypeError（R4 前缺陷） |
| 工程报告扫描计数 164 与最终日志 197 不一致 | **属实**，R5 已勘误 |
| OS 级隔离/签批持久性属后续阶段 | 维持原判，不在本轮扩大范围 |

## 1. R1 — 构建元数据与跨平台 CI（P0）→ **PASS（远端已验证）**

- **缺陷复现**：`git worktree` 检出 `cd194ca` + 全新 venv + build isolation 安装 → `INSTALL_EXIT=1`，setuptools 报 `project.license` 非法（证据：`artifacts/evidence/M0/remediation/R1_baseline_cd194ca_install_fail.log`、`R1_reproduction_note.md`）。
- **修复**：`5656dc5`，`license = "LicenseRef-Proprietary"`。任务书允许"移除或以构建规范支持的正确方式修正"；选择 SPDX 自定义标识而非删除字段，理由：保留显式的"未授予开源许可"标记，私有版权立场不变，且为 PEP 621/SPDX 规范合法形式。**未改为 MIT/Apache 等任何开源许可。**
- **远端验证**：push `cd194ca..5656dc5`（用户于本会话明确授权"推送"）→ **run `44755451594`：ubuntu-latest ✓（12s）+ windows-latest ✓（31s），Install/环境检查/pytest/密钥扫描/Paper 纯度门全部实际执行**。URL：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44755451594`。
- **本地验证**：见 §5 统一验证（干净 `.venv-m0-review`，build isolation 开启，EXIT=0）。

## 2. R2 — Paper/Live endpoint 解析与白名单（P0）→ **PASS**

- **缺陷复现（整改前）**：`RuntimeConfig._environment_purity` 用 `"api.alpaca.markets" in url and "paper" not in url` 判断，`https://api.alpaca.markets/paper` 直接绕过（测试级红证：`test_disguised_or_invalid_paper_endpoints_rejected` 整改前 FAILED；直证脚本输出 `BYPASS CONFIRMED`）。
- **修复**：`src/trading_lab/contracts/runtime.py` 新增 `_validate_broker_origin()`：`urlsplit` 严格解析——scheme 必须 `https`；hostname **精确等于**白名单（PAPER={`paper-api.alpaca.markets`}，LIVE={`api.alpaca.markets`}，小写比较）；username/password、显式端口、非空 path/query/fragment **一律拒绝**（业务上 M0 只需要 bare origin，故全部禁用，无宽松 endswith/包含判断）。LIVE 模板接受且仅接受其预期主机；`dry_run=true` 与"无 BrokerAdapter"限制原样保留，未新增任何环境切换途径。
- **负例（14 个伪装/非法 URL 全拒）**：live host + `/paper` 路径、`?paper=` 查询、后缀混淆（`.evil.com`）、路径混淆（`evil.com/paper-api...`）、http/ftp scheme、userinfo、端口 8443、`/v2` 路径、尾部斜杠、query、不可解析串、空串、无 host。正例：大小写变体 hostname 精确匹配放行、正常 Paper 配置可加载、LIVE 模板解析后可加载且 paper host 进 LIVE 配置被拒。
- **fail-closed 优先级**：运行态配置校验（本修复）为权威门；`verify_live_blocked.py` 静态扫描保持为第二条防线，其结果不影响配置校验必然执行（脚本在配置无效时独立返回 EXIT=2）。

## 3. R3 — Portfolio Gate 可信来源与账户绑定（P0）→ **PASS**

- **缺陷复现（整改前）**：`evaluate_portfolio` 仅做结构与池内校验，任意程序投递结构合法的组合即得 `ALLOW_PORTFOLIO`；无账户绑定；测试级红证为整改前 `ImportError`（新契约不存在）。
- **修复（最小改动，无新增服务/中间件）**：`src/trading_lab/security/schema_gate.py` 新增 `TrustedProducerContext`（运行时侧信任事实，全部来自独立配置，JSON 不可影响自身生产者的可信性）：
  - `reviewed_portfolio_producers: dict[producer_id -> reviewed_build_hash]`——生产者白名单与其 build hash 在**配置侧绑定**；`evaluate_portfolio(raw, producer_id)` 的 producer 标识来自调用通道（M2 起即进程边界），不由 JSON 自报；
  - `runtime_account_id`——JSON 自报 `account_id` 必须与该运行时绑定比较（不得自证）；
  - `allowed_risk_budget_ids`、`max_portfolio_age_seconds`——预算与时间有效性由可信上下文核对（陈旧/未来时间戳拒绝，含 60s 时钟偏移容差）。
  - Gate 未配置上下文时所有组合一律 `PORTFOLIO_NO_TRUSTED_CONTEXT` 拒绝。
- **边界重申**：`ALLOW_PORTFOLIO` 文档化定义为**数据准入**而非交易授权；独立风控与 OMS 最终决定保持在 M2，M0 未添加任何券商下单路径。
- **契约保持**：未改动 `TargetPortfolio` Schema 字段（Pydantic strict/extra=forbid/Decimal/UTC 全部原样）。

## 4. R4 — 非法输入不抛异常 + 审计 fail-closed（P1）→ **PASS**

- **输入边界**：`_parse()` 显式 `isinstance(raw, (bytes, str))`；`None/int/float/bool/dict/list/tuple/任意对象`（含 `decode()` 抛异常的对象）→ `NO_TRADE(INPUT_TYPE_INVALID)`；非法 UTF-8 → `NOT_VALID_JSON`；JSON 标量/数组/坏 Schema → `SCHEMA_VALIDATION_FAILED:*`。reason code 全部稳定可分类；两个 evaluate 方法走同一 `_parse` 路径。
- **审计 fail-closed**：决策**先写审计再返回**——审计写失败抛 `SchemaGateAuditUnavailable`（明确停止错误），任何情况下不会在审计不可用时返回 `ALLOW_*`；这不是宽泛吞错，而是有类型的停止信号。负例：磁盘满模拟（monkeypatch append 抛 OSError）对"本应放行的合法信号"与"垃圾输入"均验证为停止错误。

## 5. 统一验证（§7 命令，实际运行）

干净隔离环境 `.venv-m0-review`（新 venv、pip 升级、build isolation 开启、代理按环境策略）：

```text
pip install -e ".[dev]"        EXIT=0（build isolation，非 --no-build-isolation 绕过）
scripts/check_environment.py   EXIT=0（Python 3.13.15 基线）
python -m pytest -q            EXIT=0（140 passed = 原 123 + 新增 17）
scripts/scan_secrets.py        EXIT=0（200 tracked files / 0 findings —— 本轮新数）
scripts/verify_live_blocked.py EXIT=0（Paper 纯度 PASS）
scripts/smoke_mock.py          EXIT=0（SMOKE PASS）
git diff --check               干净
```

逐项输出与退出码：`artifacts/evidence/M0/remediation/remediation_checks.log`、`R1_baseline_cd194ca_install_fail.log`、`R1_reproduction_note.md`。原 `artifacts/evidence/M0/checks.log`（123 passed 时代）**未覆盖**，作为历史证据保留。

## 6. R5 — 报告与证据一致性（P1）→ **PASS**

- `M0-engineering.md` §3 扫描计数已勘误：原始摘要 164 为中期快照，该次最终日志以 **197 tracked files / 0 findings** 为准；本轮整改扫描为 **200 tracked files / 0 findings**，另行报告，不与旧数混用。
- 原三轨报告真实状态保留：**E=PASS（原本地验证范围内）、S=N_A（NOT_EVALUATED）、R=NOT_STARTED**，未提升。
- 本文件即独立整改记录（R1–R5、复现、修复、验证、残余风险、门状态），不替代三轨报告。
- 原日志不可覆盖原则遵守：整改证据全部在 `artifacts/evidence/M0/remediation/`。

## 7. 残余风险与边界（不因整改视为解决）

| 项 | 归属 |
|---|---|
| OS 级权限攻击测试（§6.5 的 OS 层） | M4（原 ADR-002 已记录） |
| 签批/nonce/撤销持久性的多进程与故障生产验证 | M2+ |
| R2 白名单当前仅含 Alpaca 官方两主机；接入其他券商/网关须先扩白名单并评审 | M2（BrokerAdapter 实装时） |
| `producer_id` 的进程级来源鉴别（当前为调用方声明，配置侧绑定 build hash） | M2 进程边界实现时收口 |
| GitHub Actions 平台注解（actions checkout/setup-python 的 Node 20 弃用提醒） | 非本仓库问题，随上游 action 版本升级消除 |

## 8. 门状态

- 本轮整改提交（`b9c5f7a` R2–R4 + `36c6ffc` 报告）经用户明确授权推送（`b9d08a1..36c6ffc`）后，远端 CI **双矩阵实际 PASS**：
  - **run `44762931848`：ubuntu-latest ✓（20s）+ windows-latest ✓（27s）**，URL `https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/44762931848`；
  - R1 修复提交的远端验证为 run `44755451594`（见 §R1）。两条 run 均为真实执行（Install/环境检查/pytest/密钥扫描/Paper 纯度门），无跳过或降级。
- **现行状态（2026-11-20 更新）：`M0_REMEDIATION_VERIFIED / M0_GATE=USER_PENDING / M1_START_APPROVAL_PENDING`**
- M0 阶段门复核与 M1 启动均由用户决定；本文件与三轨报告不自我签批。
- approver = **USER_PENDING**。
