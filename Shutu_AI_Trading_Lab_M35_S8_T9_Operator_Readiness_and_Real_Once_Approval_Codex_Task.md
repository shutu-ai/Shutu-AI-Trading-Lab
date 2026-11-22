# Shutu AI Trading Lab — M3.5 S8 T9
## Operator Readiness, Isolated Egress Proof Plan & First Real-Once Approval Packet

**Task ID**: `M35-S8-T9-OPERATOR-READINESS-AND-REAL-ONCE-APPROVAL-PACKET-R1-20261122`  
**基线 SHA（必须现场重新核对）**: `ca749890521ce0d16f31b0984a3f4f0518176369`  
**远端已核验**: GitHub Actions run [`45035699101`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45035699101), `head_sha=ca749890521ce0d16f31b0984a3f4f0518176369`; Ubuntu `960 passed in 75.73s`; Windows `960 passed in 331.30s`; 双平台架构检查 0 violation，secret scan 551 files / 0 finding，Paper/Live gate PASS。  
**上一阶段**: T8 `REMOTE_VERIFIED`; `TERMINAL_FENCE=PASS_WITH_SCOPE`, `OFFLINE_REPAIR=PASS_WITH_SCOPE`。  
**本轮授权范围**: 本地只读审查、离线环境检查、人工操作指引和证据模板、可选的 T8 CI 文档回填、本地文档提交。**不授权执行任何真实外连探针或采集。**

---

## 0. 不可逾越的边界

- `M3.5_GATE=USER_PENDING`; `API_VERIFIED=NONE`; `REAL_FORWARD_DAYS=0`; `FIRST_REAL_ONCE_READY=NO`。
- `OPERATOR_PREFLIGHT_A/B/C=PENDING_OPERATOR`; `HOST_EGRESS_ISOLATION_UNVERIFIED`。
- `PAPER_WRITE=NOT_AUTHORIZED`; `S=INCONCLUSIVE`; `R=NOT_STARTED`; `BROKER_BEHAVIOR_UNVERIFIED`; `BLOCKED_DATA=FULL_MARKET_HISTORY`; `M4=NOT_STARTED`。
- 本轮禁止：读取、索要、显示、复制、注入或校验任何真实密钥值；执行 `collect` 或 `collect --complete`（哪怕仅想测试退出码）；访问 Alpaca 真实 API；执行网络出口探针；下 Paper/Live 订单；购买/升级付费行情；向 GitHub 推送；启动 M4；将合成证据记为真实数据；替账户所有者签署 A/B/C。
- 不能为了让测试变绿而移除用例、降低门槛、调整冻结协议或修改过往历史证据。发现真实 P0 阻塞时停止并报告，未经新授权不展开无限的 T10/T11 代码整改。
- 本任务**不授权第一次真实 `collect --once`**。授权 Token 名称出现在文档中也不构成执行授权。

## T9.0 — 基线和工作树纪律（STOP/GO）

1. 读取 `AGENTS.md`、T8 任务书、`artifacts/evidence/M3.5/s8-contract-r3/review.md`、`docs/reviews/M3.5-s8-terminal-collection-fence-r3.md`、`artifacts/evidence/M3.5/s8-contract-r2/operator-readiness.md`、`artifacts/evidence/M3.5/s8-contract-r1/operator-preflight.md`、`configs/forward_observation_s8_real_v2.yaml`。
2. 核对 `git status --short`, `git rev-parse HEAD`, `git rev-parse origin/main`, `git log -3 --format='%h %s'`；只有已知的未跟踪 CI scratch 日志及本任务书可以例外，必须如实记录，**不得悄悄删除其他文件**。
3. 核对 T8 `ca74989` 的提交父链和 run `45035699101` 的 HEAD、两个 job ID、原始 pytest 计数及环境/架构/扫描/隔离步骤；若工具离线，使用已存在的真实 CI 记录并写 `NOT_RECHECKED`，不能冒充实时核验。
4. 冻结对账基线及目标输出位置；发现不明代码漂移或状态混入真实数据时 `HOLD`。

**交付**：`artifacts/evidence/M3.5/s8-operator-t9/baseline.md`。

## T9.1 — T8 远端 CI 证据回填（仅事实，不强制立即推送）

1. 只读引用 `ca74989` 和 CI `45035699101`；允许将官方原始日志的**必要摘要/核验哈希/网页链接**写入新增 `remote-ci-backfill.md`，但不得编造内容。
2. 若存在未跟踪 `r3/ci-run-45035699101.log`，只读检查其来源，核对敏感信息后决定是否仅摘录必要事实；**不默认将 scratch 全文入库，不覆盖旧证据**。
3. 更新当前状态索引时，使用追加式说明 `T8_CI=REMOTE_VERIFIED`；保留原 T8 评审历史中的 `LOCAL_ONLY / REMOTE_PENDING`，注明那是**提交当时**的真实状态。此文档回填不意味着 `API_VERIFIED`。
4. 没有需要修改的文件就不制造无意义提交；如有文档改动只在本地提交。

**交付**：`artifacts/evidence/M3.5/s8-operator-t9/remote-ci-backfill.md`（新增、可独立核查）。

## T9.2 — 独立运行环境方案评审（OFFLINE ONLY）

做出**最小可执行的操作者方案**，而不是继续扩充交易引擎代码。

- 目标：一个临时、独占、无 Broker 下单权限的采集环境；仅允许 `data.alpaca.markets:443` 的预注册 HTTPS GET；拒绝 `api.alpaca.markets`、`paper-api.alpaca.markets` 和任意其他互联网目的地。
- 说明：进程级 `GuardedGetClient` 的 GET/path/host 守卫不等于主机/容器出口隔离。一般 L3 IP 防火墙按动态域名字符串放行可能不稳健；必须解释 DNS A/AAAA、IPv4/IPv6、TLS/SNI、显式 HTTP(S)_PROXY、Windows 系统代理、HTTP CONNECT、代理服务器自身的外连 ACL、DNS 泄漏和重定向。**不可假设 Windows 上某项看似生效的规则自动覆盖代理隧道。**
- 优先建议专用 VM/容器或受控代理（default deny + 明确的主机/端口 ACL），而非让 Codex 在日常办公/家庭主机上临时放宽全机防火墙；给出具体实现方案的适用条件与未知项，**不得自动改变防火墙、代理、系统设置、DNS、路由或证书存储**。
- 说明如何证明采集器子进程获得同样的网络边界；说明如何在不同网络环境之间仅选择**一个经过验证的目标环境**，不要求办公/家庭两套都成功后才能开展单个环境的观察，但切换环境必须重验。
- 约束：单操作者 / 单实例 / 固定独立 state dir；T8 两次终态检查并非跨进程互斥。不能声称 TOCTOU 已消除；列出实际运行期间的防并发操作规程、异常停止规则，禁止在观察窗口中并发运行独立 CLI。

**交付**：`operator-environment-plan.md`，含边界图、风险项和可证伪的准入条件；全部为文档，不操作网络。

## T9.3 — A / B / C 操作者验证包（准备，不签署）

A. 账户/许可核对：本人确认 Paper-only、Basic/IEX 的**当前**条款、允许个人工程只读用途、无付费升级、未启用 Live；资料区分官方公开条款与用户特定账户实际状态。参考：
- <https://docs.alpaca.markets/us/docs/about-market-data-api>
- <https://docs.alpaca.markets/us/reference/stockbarsingle-1>
- <https://docs.alpaca.markets/us/docs/market-data-faq>

B. 凭证操作方案：仅操作者本人在**未来另一次明确授权之后**进行受控子进程注入；Codex 不读取、不显示、不迁移凭证，不把凭证放进仓库、日志、AI 聊天、截图或 CI。注意：`B=PREPARED` ≠ `B=VERIFIED_BY_OPERATOR`；没有操作事实不得虚构完成。不要把 `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` 非空当成市场数据 API 成功授权的证明。

C. 无凭证出口负例**仅提供日后本人操作的命令模板**，本轮严禁执行。设计测试矩阵：允许的数据域名 HTTPS TLS 应用层可收到响应（可能是 401/403，**不强求精确 401**）；两个交易域名与任意非白名单域名必须在网络层失败（不是 HTTP 401/403，也不是仅由应用层拒绝）；测试 v4/v6、直连与代理/CONNECT、子进程与操作者实际网络。若只能证明部分路径，记录 `BLOCKED` 或 `UNVERIFIED`，不得将未测路径推断成成功。不得为得到成功而修改 allowlist。

输出不含个人资料的空白 `operator-attestation-template.md`，签名与完整结果只能由操作者**本地保存、不进仓库**。Codex 生成的空白模板不是签署证据。定义 `PENDING_OPERATOR`、`VERIFIED_BY_OPERATOR`、`BLOCKED` 的客观转换条件。

**交付**：`operator-preflight-pack.md` + `operator-attestation-template.md`（空白）。

## T9.4 — 离线预演与退出码实测（不得访问真实 API）

- 新建专用**临时** state-dir；仅在无凭证、无授权 Token、无网络请求的进程环境运行 `check-config`、`selftest --no-evidence`、`status`；运行前确保是测试/临时目录，不要碰既有或未来真实 state dir。
- `check-config` 应显示 ranged 1Day、IEX、raw、当前协议 hash，`PAPER_WRITE=NOT_AUTHORIZED`；`selftest` 结果必须标 `SIMULATED_REAL_SHAPE_TEST_ONLY`，不能产生真实日数或 PASS；空状态 `status` 应为 `NOT_STARTED`, exit 0。
- 只用 unit/integration tests（mock/哨兵，不实际执行 collect）再次验证收据故障 6/7、终态 8、离线 `repair-completion`、凭证与网络隔离等契约；如有 960 测试基线要求，仍保留，不自动扩规模。
- 特别避免 T7/T8 RED 期间的污染路径：任何测试必须证明不会向 `s8-contract-r1/` 或其他历史证据目录写入未跟踪 simulated real-forward-window-status 文件；测试结束检查历史证据目录和 git status。

**交付**：`offline-rehearsal.md` 和实际退出码日志；不修改实盘链。

## T9.5 — 首次真实单周期的**未来授权申请包**（此任务不执行）

生成 `first-real-once-approval-request.md`，清楚列出：
1. 账户所有者本人对 A/B/C 的独立本地确认状态（尚未签署则全为 `PENDING_OPERATOR`）；
2. 唯一受控主机 / 唯一网络环境 / 独占进程 / 只读出口验证摘要 / 私有 state dir（只记环境标识及非敏感 hash，不记录账户密钥）；
3. 目标协议 `m35-s8-real-shadow-readonly-v2`、预注册 SPY/QQQ、IEX Basic、真实交易日及 ET 16:05–17:30 轮询窗口（**仅将其视为配置，不替操作者检查实际时钟**）；
4. 正确预期：`MARKET_CLOSED`、`OUTSIDE_POLL_WINDOW`、权限错误、空 bars、`NOT_A_DAILY_BAR`、429/5xx、CONFLICT 及退出码都可能出现；`exit 0` 不能自动赋予 `API_VERIFIED` 或真实交易日；未经实证不得放宽日线时间戳防御；
5. 明确提出未来**另一次、独立、范围限一次**的人类授权申请，不附带执行动作。完成至少五个**全覆盖真实交易日**及真实恢复证据之前，不可声称 E=PASS，也不得人工制造线上故障或注入模拟到真实链。

**交付**：预先填写可核对的事实、其余留空的授权请求草案；**本轮 `FIRST_REAL_ONCE_READY=NO`，不能把申请草案解释为许可**。

## T9.6 — 独立验收与停止

1. `git diff --check`, `python scripts/check_architecture.py`, `python scripts/scan_secrets.py`, `python scripts/verify_live_blocked.py`，按能力进行本地审阅和必要的离线测试，记录精确退出码；未实际运行的步骤标 NOT_RUN，不推断 PASS。
2. 审查全部新增文件是否只有文档和离线测试输出；如发现需要生产代码变更，停止并提交单独缺陷报告，**不得在本轮擅自修复**。
3. 保护此前所有已入库 M2、M3.5 证据字节；历史审计日志不得被回归测试自改写。若发生意外，保留证据后再处理，不可静默覆盖。
4. 本地提交（仅当有实际文档变更）；列出 commit SHA、父链、变更范围。**禁止 push**。
5. 输出两种独立判定：`T9_ENGINEERING_DOCUMENTS_READY_FOR_PUSH_APPROVAL`（仅回填/模板）或 `HOLD`；`OPERATOR_PREFLIGHT_A/B/C` 逐项保持实际状态；`FIRST_REAL_ONCE_READY=NO`，并说明只有在**账户所有者本人确认并独立授权**后才可能升级。
6. **在阶段门停止**，不要自行制造 T10、持续监控任务、自动排程、真实采集任务或 M4 工作。

## T9 完成的验收报告格式

```text
BASELINE_REMOTE_HEAD=ca749890521ce0d16f31b0984a3f4f0518176369
T8_CI=REMOTE_VERIFIED (run 45035699101; 960/960)
T9_DOCUMENT_VERDICT=READY_FOR_LOCAL_REVIEW | HOLD
T9_NEW_LOCAL_SHA=<sha or NONE>
T9_PUSH=NOT_AUTHORIZED
OPERATOR_PREFLIGHT_A=PENDING_OPERATOR
OPERATOR_PREFLIGHT_B=PENDING_OPERATOR
OPERATOR_PREFLIGHT_C=PENDING_OPERATOR
HOST_EGRESS_ISOLATION_UNVERIFIED
FIRST_REAL_ONCE_READY=NO
API_VERIFIED=NONE
REAL_FORWARD_DAYS=0
M3.5_GATE=USER_PENDING
PAPER_WRITE=NOT_AUTHORIZED
S=INCONCLUSIVE
R=NOT_STARTED
BROKER_BEHAVIOR_UNVERIFIED
BLOCKED_DATA=FULL_MARKET_HISTORY
REAL_API_CALLS=0
BROKER_ORDERS=0
M4=NOT_STARTED
NEXT_APPROVAL_REQUIRED=separate docs push approval (only if a commit exists); operator A/B/C attestations; separate first real read-only once authorization
```

**STOP**: T9 只建立“可供人判断的准入证据包”，绝不代替人的授权。所有操作者私有签署和真实凭证都应留在仓库、CI、AI 会话之外。
