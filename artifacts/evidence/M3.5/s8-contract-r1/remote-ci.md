# s8-contract-r1 远端 CI 记录（remote-ci.md）

| 字段 | 值 |
|---|---|
| 状态 | **`REMOTE_VERIFIED`**（2026-11-22 用户授权推送修复后，双矩阵一次通过） |
| run 2（受测代码） | [`45023566557`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45023566557)（head `2a60864fd072f1dd3dde0ef62b303224da6f9781`，push 自用户授权）：**ubuntu ✓ / windows ✓** |
| ubuntu-latest | **926 passed** in 46.92s（job 137211543143） |
| windows-latest | **926 passed** in 384.09s ≈ 6m24s 测试（job 137211542872） |
| 基线对照 | 887 基线 + 39 新增 = 926；零删减 / 零 skip / 零 xfail / 零阈值变化 |
| run 1（失败历史，如实保留） | [`45018794107`](https://github.com/shutu-ai/Shutu-AI-Trading-Lab/actions/runs/45018794107)（head `fc5c0c5`）：ubuntu ✓ / windows ✗（2 failed, 924 passed）——根因 = 字节冻结 pin 用原始工作副本字节哈希，随 Windows 检出 LF→CRLF 翻译漂移；**冻结文件零漂移**。修复 = pin 改 LF 规范化内容哈希（值不变，自检复核），提交 `a3bf463`；run 2 的 windows 绿在同一平台矩阵上证实了该根因分析与修复 |
| 历史事实 | run `45013402697`（双矩阵 887+887）证明旧 S8 工程（head `2e189eb`）；run 45023566557 证明 R1 整改代码 |
| 注解 | 仅既有 Node.js 20→24 deprecation 警告（历史 run 同有，非本轮引入）；A6 flake 未重现 |
| 边界（不变） | `REMOTE_VERIFIED` 只证明工程与测试双平台绿：真实行情 `API_VERIFIED=NONE`、`REAL_FORWARD_DAYS=0`、`S8_REAL_DATA_READY=OPERATOR_PENDING`、`S=INCONCLUSIVE`、`PAPER_WRITE=NOT_AUTHORIZED`、全市场历史 `BLOCKED_DATA` 全部保持 |
| push 纪律 | 本记录的 docs 回填提交按每推送单独授权纪律，提交在本地、待用户下一次推送授权 |
