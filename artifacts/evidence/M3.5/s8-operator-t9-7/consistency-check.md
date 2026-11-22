# 离线静态一致性检查（consistency-check — T9.7.4，LOCAL_ONLY，2026-11-22）

> 全部为只读 grep/文件存在性检查 + 工具链；未执行网络、未重跑全量测试
> （纯文档轮，按 T9.7.4.2 避免触发 M2 自重写）、未触碰历史证据。

## 1. 冻结事实静态核对（文档 ↔ 冻结配置）

| 检查项 | 结果 |
|---|---|
| 协议 ID `m35-s8-real-shadow-readonly-v2` 在文档与 `forward_observation_s8_real_v2.yaml` 一致 | PASS（config 1 处；first-real-once-request 引用） |
| 轮询窗口 `16:05`–`17:30` ET（config `poll_window_et`） | PASS（config 2 处；request 引用） |
| 预注册符号 SPY/QQQ | PASS |
| `feed=iex` / `timeframe=1Day` | PASS |
| 退出码契约 0/1/3/4/5/6/7/8（T7/T8 冻结） | PASS（request §4"退出码契约（T7/T8 冻结）：0 / 1 / 3 / 4 / 5 / 6 / 7 / 8"+ status 语义行；reconciliation §6/§8 引用 status exit 6/7） |
| 状态枚举（PENDING_OPERATOR / VERIFIED_BY_OPERATOR / BLOCKED / PREPARED / B_PLAN_READY 不冒充签署） | PASS（action-card 5 处、reconciliation 4 处、b-only-request 一致使用三态+准备事实） |
| 交叉引用文件存在性（operator-gate-reconciliation / operator-action-card / b-only-authorization-request / operator-attestation-template） | PASS（全部存在） |
| 旧表述"只有未来单独授权真实采集时才需要执行注入"已无未修订残留 | PASS（0 处未标注残留；r2 文件原文以删除线+修订标注处置） |

## 2. 本轮修订后的文档依赖一致性（死锁消解核对）

- `operator-preflight-pack.md` §B（注入时点 → 授权 1）↔
  `b-only-authorization-request.md`（授权 1 载体）↔
  `first-real-once-approval-request.md` §1/§6（授权 2 前置引用授权 1）↔
  `operator-action-card.md` 步骤 4/5/7 —— 四者对依赖顺序的描述一致，
  无互相矛盾（决策图见 reconciliation §3）。
- `operator-environment-plan.md` §5 方案 A 补充"销毁仅指计算资源；状态卷
  跨日持久" ↔ reconciliation §6 持久状态卷要求 —— 一致。

## 3. 工具链退出码（本轮实跑）

| 命令 | 退出码 |
|---|---|
| `python scripts/check_architecture.py` | 0（`architecture-check.log`） |
| `python scripts/scan_secrets.py` | 0（`secret-scan.log`） |
| `python scripts/verify_live_blocked.py` | 0（`verify-live-blocked.log`） |
| `git diff --check` | 干净 |

## 4. 明确未执行（NOT_RUN，如实标注）

- 全量 pytest / M2 故障矩阵：**NOT_RUN**——纯文档轮，按任务书 T9.7.4.2
  不强制重跑，避免自改写 M2 历史证据；无代码变更故无重跑必要性；
- 任何网络探针 / collect / 凭证操作：**未执行**（最高优先级禁令）；
- `r1/r2/r3` 旧验收日志：**零触碰**（本轮新资料只存
  `artifacts/evidence/M3.5/s8-operator-t9-7/` + 4 个带日期标注的最小修订）；
- T9 未跟踪 `s8-operator-t9/ci-run-45038488439.log`：只读核验来源（gh watch
  原始输出，无敏感信息）后**保持原位**——不删除、不移动、不入库（遵
  T9.7.4.3，待处置授权）。
