# Shutu AI Trading Lab — M0 独立验收整改 Codex 任务书

> **任务 ID**：`M0-REVIEW-REMEDIATION-001`  
> **基线仓库**：`https://github.com/shutu-ai/Shutu-AI-Trading-Lab`  
> **复审基线**：`cd194cae7f2b9c7e7546a915ffcc2af12e970b4c`（执行前先核对本地及远端 HEAD；如果已变化，先审阅差异，不能覆盖后续修改）  
> **目标状态**：`M0_REMEDIATION_READY_FOR_REVIEW / M1_START_APPROVAL_PENDING`  
> **授权范围**：仅本任务所列 M0 定向整改与测试；不构成 M0 阶段门签批、不授权 M1、不授权 Paper/Live 下单或真实账户操作。

## 0. Codex 可直接执行的总指令

你是 **Shutu AI Trading Lab 的安全工程、Python 打包与 CI 验收负责人**。阅读两份冻结计划：

- `docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md`
- `docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md`

同时阅读：

- `docs/reviews/M0-engineering.md`、`M0-strategy.md`、`M0-real-capital.md`
- `docs/adr/ADR-002-isolation.md`
- 当前 `src/trading_lab/contracts/runtime.py`、`contracts/events.py`、`security/schema_gate.py` 和关联 tests
- `.github/workflows/ci.yml`、`pyproject.toml`

**只实施下文 R1–R5，先复现缺陷并增补失败测试，再做最小修复，最后执行全量回归。** 不重新设计架构；P0–P4、M-1～M11（含 M3.5）、三轨 E/S/R 状态、不经授权不得启动后续阶段的原则均保持不变。

本任务只允许操作本地代码、虚构账户、mock 测试密钥与离线测试。**禁止连接 Alpaca、申请或使用券商密钥、生成有效 Live 签批、实际发单、进入 M1 或改动市场/策略研究模块。**

## 1. 审查已知事实与整改边界

- 远端 `cd194ca` 的 M0 本地证据：`artifacts/evidence/M0/checks.log` 显示 `123 passed`，Paper 纯度门与离线 smoke 通过。**这些是已有日志，不要冒充本任务新测试。**
- 远端 GitHub Actions run `44755037633`：Ubuntu `Install` 失败，Windows 因同次运行被取消；因此 CI 并未通过。
- 根因：`pyproject.toml` 中 `[project] license = "Proprietary"` 不是当前构建后端接受的有效 SPDX 字符串；构建隔离环境中的 setuptools 校验失败。无需重做 M0 或修改项目许可立场。
- 代码审查发现 Paper endpoint 判断包含字符串 `"paper"`，可能允许 Live 主机的附加路径/查询值伪装；`evaluate_portfolio()` 缺少独立可信来源/运行账户上下文；`SchemaGate._parse()` 对意外输入类型可能抛出 `TypeError`。
- `docs/reviews/M0-engineering.md` 密钥扫描统计（`164`）与最终 `artifacts/evidence/M0/checks.log`（`197 tracked files`）不一致，应按证据统一。
- M0 的 OS 级安全隔离仍为已记录限制（归既定 M4 验证）；签批/nonce/撤销持久性在真实多进程与故障情形下的生产验证仍属后续阶段；不要把上述事项扩大为本轮开发。

## 2. R1 — 构建元数据和跨平台 CI（P0）

**文件**：`pyproject.toml`、必要时 `.github/workflows/ci.yml`、对应测试/说明。

### 工作内容

1. 在干净的隔离构建环境中复现当前 `pip install -e ".[dev]"` 失败，并保存错误摘要。
2. 移除或以构建规范支持的正确方式修正 `license = "Proprietary"` 元数据。**首选最小处理：删除此无效字段，保持仓库原有私有版权定位；不要改写为 MIT、Apache-2.0 或其他并未获得授权的开源许可。** 如需要，在项目文档中说明“未授予开源许可”，但不必引入新许可证文件或发布机制。
3. 分别验证 `pip install -e ".[dev]"`（启用 build isolation）及 `python -m pytest`、密钥扫描、Paper 纯度门。不可仅以 `--no-build-isolation` 或本地现有依赖绕过真正的 CI 问题。
4. 核对 GitHub Actions 工作流是否确实执行 `ubuntu-latest` 和 `windows-latest` 两个环境；不要通过删除/跳过作业、降低 Python 版本、禁用安全门来制造绿灯。
5. 如远端 CI 无法在未获批准推送的情况下验证：将本地修复提交为待推送状态，标记 `CI_REMOTE_PENDING`，并等待人工授权推送后再核验。**未完成两平台运行时不得宣称远端 CI PASS。**

### 验收

- 干净构建隔离安装 `EXIT=0`。
- 两个平台的 GitHub Actions 全部作业实际完成，Install/环境检查/pytest/密钥扫描/Paper 纯度门均为 PASS；如未获本轮推送授权，明确记录 `CI_REMOTE_PENDING` 而非编造结果。
- 现有私有许可立场不变。

## 3. R2 — Paper/Live endpoint 解析与白名单（P0）

**文件**：`src/trading_lab/contracts/runtime.py`、`tests/security/test_isolation.py`（或等价现有测试），必要时 `security/isolation.py`。

### 工作内容

1. 先新增负例：`https://api.alpaca.markets/v2?paper=test`、`https://api.alpaca.markets/paper`、携带 `paper` 字符的路径或 fragment、错误 scheme、用户名/密码伪装 host、host 后缀混淆、大小写、端口及非法/空 URL。注意使用实际解析的 hostname，而非输入字符串是否包含关键字。
2. 对 Alpaca Paper endpoint 使用严格 URL 解析与 **精确 scheme + hostname 白名单**，例如 HTTPS 且 hostname 精确为 `paper-api.alpaca.markets`。Live 模板仅接受其预期主机；M0 保持 `LIVE dry_run=true`、无可发单 BrokerAdapter 的原有限制。
3. 允许的 URL path/query/port 范围必须有明确策略并被测试，禁止用宽松 `endswith`、`"paper" in URL` 等逻辑放行。若业务上不需要 path/query/userinfo/fragment，最简单是全部拒绝；如存在既有合法路径，列出明确白名单并说明理由。
4. 确保 `verify_live_blocked.py` 的静态扫描不会掩盖配置校验失败；无论静态扫描结果如何，运行态配置都必须 fail-closed。

### 验收

- 所有构造的伪装 Live URL 在 Paper 配置验证阶段被拒绝；正常 Paper 配置仍可加载。
- Live 模板依旧无法未经签批启动真实执行；不新增环境切换快捷方式。

## 4. R3 — Portfolio Gate 可信来源与账户绑定（P0）

**文件**：`src/trading_lab/security/schema_gate.py`，必要时 `src/trading_lab/contracts/events.py` 和 `tests/security/test_schema_gate.py`。

### 工作内容

1. 建立与 `evaluate_signal()` 同等严格的 **可信生产者** 校验：组合只能来自已审核的策略/可信聚合器，且其 build hash 必须在独立配置的允许集合中。未经审核的 JSON 不能仅凭结构正确就获得 `ALLOW_PORTFOLIO`。
2. `TargetPortfolio.account_id` 必须与 **独立于 JSON 的运行时可信账户** 比较。不得使用 JSON 内自报的 account_id、producer 身份、risk_budget_id 来作为它们自己的验证依据。
3. 组合的 snapshot/时间有效性、risk_budget 与生产者来源应由**可信上下文**核对。选择最小改动方式：可扩展当前 Schema 字段或给 Gate 注入不可由外部数据控制的 `TrustedProducerContext`/`ExpectedBinding`，但不得新增服务或中间件。若新增字段需维持 Pydantic strict、`extra=forbid`、Decimal 与 UTC 契约，并更新正反测试。
4. 重点防止：任意程序直接投递一个资金权重合法的 `TargetPortfolio` 而绕过 `reviewed_build_hash` 检查；以及某账户的组合被发送到另一账户。
5. 明确 `ALLOW_PORTFOLIO` 仍只代表数据准入，不是交易执行授权；独立风控与 OMS 的最终决定保持在 M2，不能在 M0 添加券商下单路径。

### 必测负例

- 未审核生产者、伪造/不匹配 build hash、可信上下文缺失 → `NO_TRADE`。
- JSON 自报账户与运行时绑定账户不符 → `NO_TRADE`。
- 过期/不匹配 snapshot、无效 risk budget、池外 symbol、非法权重/现金和未知字段 → `NO_TRADE`。
- 已审核生产者 + 正确账户/快照/预算 + 合法权重 → `ALLOW_PORTFOLIO`（仅数据准入）。

## 5. R4 — 任意非法输入不得使 Schema Gate 抛出解析异常（P1）

**文件**：`src/trading_lab/security/schema_gate.py`、`tests/security/test_schema_gate.py`。

1. 对 `raw` 做显式 `bytes|str` 类型边界检查；`dict`、`list`、`None`、`int`、带有异常 `decode()` 的不可信对象等均返回 `GateDecision(action="NO_TRADE", allow=False)`。
2. 非法 UTF-8、非 JSON、JSON 标量/数组、额外字段、错误字段类型均返回 `NO_TRADE`；拒绝事件仍写审计，且 reason code 稳定可分类。
3. 不得通过宽泛吞错将**审计存储故障或信任边界不可用**伪装成可继续交易的 `ALLOW_*`。审计不可用时同样必须 fail-closed（可以有明确拒绝/停止错误，但不允许继续执行）。
4. 复核 `evaluate_signal()` 与 `evaluate_portfolio()` 都调用一致的安全解析路径。

## 6. R5 — M0 验收报告与证据一致性（P1）

**文件**：`docs/reviews/M0-engineering.md`、`artifacts/evidence/M0/` 中的新整改证据，以及独立整改报告。

1. 修正原 M0 工程报告中的密钥扫描数量冲突。历史事实应注明：原始摘要一处写 164，最终日志写 197；采用 `197 tracked files / 0 findings` 为该次日志事实。**新一轮扫描文件数应另外报告，不能拿旧数冒充当前数。**
2. 保留原始 M0 三轨报告的真实状态：`E=PASS（原本地验证范围内）`、`S=N_A/NOT_EVALUATED`、`R=NOT_STARTED`；同时在独立整改报告中指出**当前阶段门因远端 CI 失败尚未关闭**，不能仅凭本地测试放行 M1。
3. 建立 `docs/reviews/M0-independent-remediation.md`（补充审查记录；**不能替代** `M0-engineering.md`、`M0-strategy.md`、`M0-real-capital.md`），列出 R1–R5、缺陷复现、修复 diff、真实测试命令与退出码、残余风险、是否实际完成远端 CI、下一门状态。
4. 原日志不可覆盖，新增工件存入 `artifacts/evidence/M0/remediation/`。没有 GitHub Actions 运行证据时记录为 `UNVERIFIED`/`CI_REMOTE_PENDING`，不得伪造成功记录。

## 7. 统一验证命令（Windows PowerShell / CI）

在当前项目根目录、使用已批准的 Python 3.13：

```powershell
py -3.13 -m venv .venv-m0-review
.\.venv-m0-review\Scripts\python.exe -m pip install -U pip
.\.venv-m0-review\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-m0-review\Scripts\python.exe scripts/check_environment.py
.\.venv-m0-review\Scripts\python.exe -m pytest -q
.\.venv-m0-review\Scripts\python.exe scripts/scan_secrets.py
.\.venv-m0-review\Scripts\python.exe scripts/verify_live_blocked.py
.\.venv-m0-review\Scripts\python.exe scripts/smoke_mock.py
git diff --check
git status --short
```

- 如依赖拉取受代理限制，记录真实网络/证书错误为 `BLOCKED_ENV`，不能算 PASS；不要随意禁用 TLS 校验。
- 所有命令将实际 `EXIT`、Python 版本、依赖版本、测试用例数与失败摘要写入 `artifacts/evidence/M0/remediation/`。
- GitHub Actions 远端验证必须使用实际运行的 URL、提交 SHA、两个 job 的状态及必要日志摘录；推送前先按本次授权状态执行，**没有明确推送授权则停在本地，不自行 push 或 force-push**。

## 8. 阶段门与停止规则

**全项验收**：

| 维度 | 硬性条件 |
|---|---|
| 构建 | 干净 build isolation 下安装通过，未改变许可立场 |
| CI | Ubuntu + Windows 两个 GitHub Actions job **实际 PASS**（未获授权推送则 `CI_REMOTE_PENDING`，不能称整体验收通过） |
| URL 隔离 | 精确主机校验、全部绕过负例拒绝，Paper 正例保留 |
| Portfolio Gate | 可信来源 + 绑定账户 + 快照/有效性/预算负例拒绝，正例通过 |
| Schema Gate | 非字符串、非法 JSON、非法 Schema 都 `NO_TRADE`；不产生未审计放行 |
| 回归 | 原 M0 用例 + 新增测试全过，安全扫描 0 真密钥，mock/纯度门通过 |
| 三轨 | S、R 不提升，保留原始证据，新增独立整改记录 |
| 业务边界 | 无 BrokerAdapter/真实订单；无 M1 数据源或策略研发；无 Live 凭证或真实签名 |

**交付形式**：本地变更/提交（按照现有仓库工作流），`docs/reviews/M0-independent-remediation.md`，`artifacts/evidence/M0/remediation/`，R1–R5 矩阵与命令日志。任何规范变更须先报告冲突，不得擅自降低安全门槛。

**完成后状态**：

- 若本地测试全过、尚无用户授权推送：`M0_REMEDIATION_LOCAL_PASS / CI_REMOTE_PENDING / M1_START_APPROVAL_PENDING`。
- 若推送经明确授权且两个远端作业均真实通过：`M0_REMEDIATION_VERIFIED / M0_GATE=USER_PENDING / M1_START_APPROVAL_PENDING`。
- 任意核心安全负例失败或 CI 持续失败：`M0_REMEDIATION_BLOCKED`，附复现证据，**绝不能自动宣告 M0 PASS**。

**不要替用户签署 M0 阶段门，不自动启动 M1，不启动 Paper/Live 下单。**
