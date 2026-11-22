# s8-contract-r1 远端 CI 记录（remote-ci.md）

| 字段 | 值 |
|---|---|
| 状态 | **`CI_REMOTE_PENDING`**（未获 push 授权，未推送，远端未运行） |
| 历史事实 | run `45013402697`（双矩阵 887+887）**只证明旧 S8 工程**（head `2e189eb`），不覆盖本轮新代码 |
| 本轮 | `S8_CONTRACT_REMEDIATION_LOCAL_PASS`——本地 926 passed（887 基线 + 39 新增，零删减/零 skip/零 xfail/零阈值变化）+ 全 gates EXIT=0（`verification.log`） |
| 升级路径 | 用户单独批准 push → 新 SHA 双平台 CI 绿 → 方可写 `REMOTE_VERIFIED`（不得复用旧 SHA 冒充） |
| push 纪律 | 每次推送单独授权（AGENTS.md / S8 授权 / 任务书 T0.2）；本轮**未推送**（用户指令：只提交本地） |
