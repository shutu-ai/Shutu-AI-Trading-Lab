# M0 — 工程验收报告（engineering）

| 字段 | 值 |
|---|---|
| stage_id | M0（部署隔离、身份签批契约、工程事件与审计骨架，P0） |
| commit | `59ef4698a6f6fe8ee4c4c1e4d96fd92c1230e1e8`（实现）；`0ee76f4`（构建产物清理）；阶段门复核于工作树 clean 状态 |
| code_hash | git tree `c2152d7f472ee6c8fff185111f71077c0554079c`（commit 59ef4698 全部跟踪文件） |
| protocol_hash | NOT_APPLICABLE —— 研究评估协议在 M3 冻结，M0 不产生协议工件 |
| environment | Windows 11 Pro，Python 3.13.15（`.venv`，用户批准的 3.13 基线，见 `M-1-independent-review.md` R5）；pydantic 2.14.3 / cryptography 50.0.2 / pytest 9.2.0；离线运行，无任何网络/券商连接 |
| test_commands | 见 §3（全部本地离线执行，退出码 0） |
| evidence_paths | `artifacts/evidence/M0/checks.log`、`artifacts/evidence/M0/smoke_mock.log` |
| findings | 见 §4（含两条已知限制，未降低任何验收阈值） |
| status | **E = PASS（限定范围：测试覆盖范围内）** |
| evidence_state | NOT_EVALUATED |
| deployment_state | NOT_DEPLOYED |
| strategy_role | NONE |
| final_holdout_status | SEALED（未创建任何 Holdout，占位语义） |
| forward_window_status | NOT_APPLICABLE（M0 无前向窗口） |
| next_gate | M0 阶段门人工复核（本报告不自我批准）；通过后由用户决定是否启动 M1 |
| approver | USER_PENDING（Agent 不代签阶段门） |

## 1. 交付范围（严格对齐两份 v2.1 计划 M0 任务行）

| 计划任务 | 交付 |
|---|---|
| Python 3.13 项目/CI | `pyproject.toml`（src 布局，editable 安装验证通过）；`.github/workflows/ci.yml`（py3.13 × ubuntu/windows 矩阵：pytest + 密钥扫描 + Paper 纯度门） |
| Pydantic 契约 | `src/trading_lab/contracts/`：§2.2 全部 20 个事件契约 + 运行时配置契约；strict 模式、Decimal 资金字段（float 显式拒绝）、UTC 时区强制、`extra="forbid"`、frozen |
| 两套独立 runtime 启动配置（Live 仅 mock 干运行） | `configs/paper/runtime.example.yaml`（可加载，验证过）；`configs/live/runtime.template.yaml`（模板，占位符未解析前加载即拒；LIVE 强制 `dry_run: true`；凭据仅 `secret_store:` 引用）。`RuntimeContext` 冻结绑定，进程内不可切换环境（§6.3） |
| 测试签名器/验签器 | `security/signing.py`（Ed25519，TEST-ONLY 密钥）+ `security/verifier.py`（§6.4 验证链） |
| 可信公钥部署、nonce、过期、撤销、额度/版本 hash | 钉扎信任根（out-of-band 部署，自建公钥不可替换）；nonce 防重放账本；valid_from/expires_at + 时钟偏移负例；revocation epoch/denylist/新鲜度（不可用即 FAIL_CLOSED）；capital/order cap 与 strategy/build/protocol/policy hash 逐项绑定 |
| 研究 sandbox 与策略子进程无券商写权限 | `ResearchSandboxPolicy`（结构上 `broker_write=False`，越权即拒 + 审计）；M0 平台**不存在** `trading_lab.brokers` 模块——无任何可发单代码路径（fail-closed by absence），单写者出口接缝留待 M2（设计契约 (d)，只冻结不实现） |
| AI 代码不得动态执行、只过 Schema Gate | `security/schema_gate.py`：唯一通道是原始 JSON 字节；pickle/对象/命令串结构上不可通过；非法信号一律 `NO_TRADE` + 审计事件，不抛异常 |
| 手动 Kill Switch | `security/kill_switch.py`：持久化 halt（重启不清除）、`require_tradable()` 接缝、解除必须显式授权引用、全程审计 |
| 密钥泄漏扫描 | `scripts/scan_secrets.py`（PEM/Alpaca/AWS/字面量赋值模式 + 占位值识别）；全树扫描 0 命中 |
| 工程事件与审计骨架 | `security/audit.py`：追加写 JSONL + 哈希链 + head 记录（尾截断可检测）；`verify()` 重算全链 |
| M0 工件 | `docs/adr/ADR-002-isolation.md`、三轨报告、`artifacts/evidence/M0/`（本报告即为 `M0-engineering.md`） |

**未实现（按计划本就不属于 M0）**：OMS/风控引擎、broker 适配、数据接入、研究协议、真实签批终端（M9）。R3/R4 的 UNKNOWN/fencing 契约在 M0 仅冻结设计（两份计划 M0 契约段 + `RuntimeContext.broker_write_path_exists()` 接缝），M2 才实施代码与故障注入。

## 2. E-Gate 逐项映射（全部由自动测试断言覆盖）

| E-Gate 要求 | 证据（测试/脚本） |
|---|---|
| 跨域访问 100% 被拒 | `test_isolation.py::TestResearchSandbox`（越权 → `IsolationViolation` + `CROSS_DOMAIN_ACCESS_REFUSED` 审计） |
| AI 越权代码 / 非法 Schema 信号被拒 | `test_schema_gate.py`：pickle、非 JSON、命令串注入、未知字段、未审查 build hash、过期 TTL、NaN/超界/负权重、池外标的 → 全部 `NO_TRADE` |
| 假签批负例被拒 | `test_verifier.py::TestIdentityAndForgery`：自建公钥替换信任根、载荷篡改、垃圾签名、错误算法、身份不符 |
| Paper 运行时无 Live 密钥/DB/OMS/endpoint | `scripts/verify_live_blocked.py` PASS；`RuntimeConfig._environment_purity`（Paper 指向 live host 即拒加载）；`TestPaperPurity`（植入 Live key/endpoint 即检出） |
| 错账户 | `test_verifier.py::TestScope::test_wrong_account_rejected` |
| 篡改 hash | `test_strategy/build/policy_hash_mismatch_rejected` |
| 超额度 | `test_over_capital/order_cap_rejected` + smoke 负例 2 |
| 过期 | `test_expired_rejected`（时钟偏移法，契约层窗口校验另测于 `TestLiveRelease`） |
| 撤销 | denylist 命中 / epoch 被超越 / 源不可达 / 状态陈旧（含时钟回拨负例）→ 全 FAIL_CLOSED |
| 失联验签 | 信任根缺失/为空 → 构造即失败；nonce 账本损坏 → 拒绝或 fail-closed；`test_unreachable_revocation_source_fails_closed` |
| 无需真实 Live 密钥 | 全部签批为 mock 测试密钥 + 虚构账户（§6.5）；`check_environment.py` 确认本机无 APCA 凭证且 M0 不需要 |

## 3. 实际运行的命令与退出码（全部离线）

```text
.venv/Scripts/python.exe scripts/check_environment.py     # EXIT=0（3.13.15 基线 OK）
.venv/Scripts/python.exe -m pytest                        # EXIT=0，123 passed
.venv/Scripts/python.exe scripts/scan_secrets.py          # EXIT=0，0 命中
# （计数勘误，M0-REVIEW-REMEDIATION-001 R5：本节初稿写 164 文件为中期快照；
#   该次最终日志 artifacts/evidence/M0/checks.log 记录 197 tracked files / 0 findings，
#   以 197 为该次日志事实。整改轮新扫描为 200 tracked files / 0 findings，
#   见 artifacts/evidence/M0/remediation/，不得与上数混用。）
.venv/Scripts/python.exe scripts/verify_live_blocked.py   # EXIT=0，Paper 纯度 PASS
.venv/Scripts/python.exe scripts/smoke_mock.py            # EXIT=0，SMOKE PASS
.venv/Scripts/python.exe -m pip install -e . --no-deps    # 成功（导入验证通过）
```

输出全文见 `artifacts/evidence/M0/checks.log`、`smoke_mock.log`。CI 工作流已交付但未在 GitHub Actions 上执行过（本地以同命令集运行作为证据；推送后的 Actions 运行结果在后续阶段报告引用）。

## 4. Findings 与已知限制（不降低验收阈值）

1. **OS 级权限攻击测试未做**（ADR-002 已记录）：研究沙箱隔离目前是结构/策略/审计层面；§6.5 "签批隔离要通过实际权限攻击测试证明" 的 OS 层部分归 M4（AI 研究工厂实现时以真实低权限进程验证）。M0 覆盖的是 mock 层负例矩阵。
2. **GitHub Actions 首次执行暴露并修复一个问题**：初版 `pyproject.toml` 的 `license = "Proprietary"` 非合法 SPDX 表达式，两矩阵 Install 步骤失败（run `44755037633` ✗）；改为 `LicenseRef-Proprietary` 后推送（`5656dc5`），**run `44755451594` 双矩阵（ubuntu/windows）全绿**——pytest + 密钥扫描 + Paper 纯度门在 CI 实际通过。剩余注解仅 GitHub 平台自身的 actions Node 20 弃用提醒，非本仓库问题。
3. **审计日志为单机文件**（含 head 记录防尾截断）：M0 威胁模型内足够；外部化防篡改存储留待后续阶段按需评估。
4. **smoke 的 LIVE 干运行**：使用临时目录物化的 mock 配置（虚构账户 `MOCK_LIVE_DRYRUN_ACCOUNT`、mock 测试密钥）；`configs/live/runtime.template.yaml` 因占位符存在无法直接加载（fail-closed by design）。

**E=PASS 限定语义**：与 M-1 相同——"PASS" 只指上述测试覆盖范围内 100% 负例被拒且全部可复现；不声明生产环境零故障，不构成任何真实交易能力证明。
