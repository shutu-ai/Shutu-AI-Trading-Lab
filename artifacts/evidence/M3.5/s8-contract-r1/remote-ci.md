# s8-contract-r1 远端 CI 记录（remote-ci.md）

| 字段 | 值 |
|---|---|
| 状态 | **`CI_REMOTE_PENDING`**（首次新代码 run 失败 → 缺陷定位修复并本地提交 → 待再次授权推送） |
| run 1（新代码） | [`45018794107`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45018794107)（head `fc5c0c5`，用户 2026-11-22 授权推送）：**ubuntu ✓（926 passed）/ windows ✗（2 failed, 924 passed）** |
| 失败项 | 仅 `tests/s8_gateway/test_protocol_migration.py` 两个字节冻结 pin（synthetic + legacy 预注册） |
| 根因（如实） | **pin 测试设计缺陷，非冻结文件漂移**：pin 用工作副本**原始字节**哈希；Windows CI 检出时 git 做 LF→CRLF 翻译 → 字节哈希随检出平台漂移（ubuntu/LF 检出与本地一致故绿）。两个配置文件内容零漂移 |
| 修复 | pin 改为 **LF 规范化内容哈希**（BOM 剥离 + CRLF→LF；与仓库 code-identity 同一平台无关纪律）；pin 值不变（本地 LF 副本规范化前后一致，已自检复核）；本地 12/12 绿 |
| 历史事实 | run `45013402697`（双矩阵 887+887）只证明旧 S8 工程（head `2e189eb`），不覆盖本轮 |
| 本轮 | `S8_CONTRACT_REMEDIATION_LOCAL_PASS / CI_REMOTE_PENDING`——修复后本地全量回归重跑（计数见 `verification.log`），零删减/零 skip/零 xfail/零阈值变化 |
| 升级路径 | 用户单独批准推送修复提交 → 新 SHA 双平台 CI 绿 → 方可写 `REMOTE_VERIFIED`（不得复用旧 SHA 冒充） |
| push 纪律 | 每次推送单独授权（AGENTS.md / S8 授权 / 任务书 T0.2） |
