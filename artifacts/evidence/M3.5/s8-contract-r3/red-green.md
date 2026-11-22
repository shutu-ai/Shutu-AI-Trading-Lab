# T8 RED → GREEN 对照记录（red-green — LOCAL_ONLY，2026-11-22）

> 全部用例使用临时目录 + 合成 fixture 窗口（`SIMULATED_REAL_SHAPE_TEST_ONLY`），
> 哨兵化 feed/socket/preflight，不触碰真实采集状态与已提交证据集。
> 原始 RED 输出：`red-run-full.log`（14 failed, 2 passed）。

## P1-A：完成后仍可经采集入口修改窗口状态（终态写入隔离）

**旧路径（RED 实测）**：`cmd_collect` 的 `--once` 与 `--complete` 两路径都在
任何终态审查之前执行：凭证可见性审计（preflight）→ 网络客户端/`AlpacaIexDailyBarFeed`
构建 → `run_collection_cycle()`（先 `collect_once()` + 追加收据，再
`run_replay(complete=False)` 追加会话）。对已提交 `WINDOW_COMPLETED` 的窗口：

| RED 用例（未修复代码） | 旧行为实测 |
|---|---|
| `test_collect_once_after_completion_refuses_before_credentials_and_writes` | preflight 与哨兵 feed 均被调用、journal 追加会话、exit 0 |
| `test_collect_complete_after_completion_refuses_before_collecting` | 同上 + 事实漂移后走完成分支（零凭证环境下 exit 3 / 有门环境下可能"补采再修复"） |
| `test_collect_refused_on_corrupt_chain_before_any_access` | 链损坏时 cycle 照跑（先采集后拒绝） |
| `test_repeated_terminal_invocations_are_inert` | 重复调用持续变更 journal |

**修复（GREEN）**：`cmd_collect` 在 legacy 契约检查之后、**一切凭证读取/
网络客户端/feed 访问/链写入之前**执行只读终态审查 `_terminal_gate()`：
- 已提交 `WINDOW_COMPLETED` → `TERMINAL_WINDOW_REFUSED`，**exit 8**（新增、
  已文档化），零磁盘写入，附 `repair_hint` 指向 `repair-completion`；
- 收据链损坏 → `CHAIN_CORRUPT_REFUSED`，exit 6（既有完整性语义）；
- 合法未开始/进行中窗口原样通过（两个 guard 用例证明采集路径不变）；
- TOCTOU 缩小：cycle 执行前立即二次复核（残余风险如实记录于 `review.md`，
  不声称跨进程原子性）。
- 守卫复用评估：`run_collection_cycle` 不加硬围栏——它是内部/测试面
  （T7 漂移测试依赖其构造拒绝状态），唯一用户入口是 CLI，已围栏；
  该决策与精确边界记录于 `review.md`。

**GREEN 实测**：上述四用例全绿；哨兵 feed/preflight 零调用、socket 密封下
零网络、journal/收据/快照字节零变更、exit 8/6。

## P1-B：纯离线 `repair-completion`

**旧行为（RED）**：子命令不存在（argparse exit 2）；崩溃窗口唯一修复路径是
`collect --complete`——需 operator token + 凭证可见（否则 exit 3），且 T7 版
`operator-readiness.md` 恰把"重跑 collect --complete"写为崩溃窗口指引。

**修复（GREEN）**：新增 `repair-completion --state-dir <必填> [--config]`，
纯本地文件工作（哨兵证明：feed/preflight 零调用、socket 密封）：
- 资格门：恰一条链验证通过的 `WINDOW_COMPLETED` + 快照缺失 +
  `facts_digest`/`protocol_hash`/独立重算 eligibility 三重匹配；
- 成功 → 原子写快照（与完成路径同一 `_snapshot_text` 字节形状）→
  `REPAIRED_SNAPSHOT` exit 0（仅表示修复成功，非 E-Gate PASS）；
  收据/journal 字节零变更，不追加第二完成收据；
- 已验证快照存在 → `ALREADY_COMPLETE_NOOP` exit 0，零字节修改；
- 无已提交完成 → `NO_COMMITTED_COMPLETION` exit 1（绝不"帮忙完成"）；
- 链损坏 → `REFUSED_CHAIN_CORRUPT` exit 6；跨协议 → `REFUSED_PROTOCOL_MISMATCH`
  exit 6；摘要漂移 → `REFUSED_DIGEST_DRIFT` exit 6；重复完成 →
  `REFUSED_INTEGRITY` exit 6；已存在但篡改的快照 → `REFUSED_INTEGRITY`
  exit 6（验证不过的证据永不被覆盖）；
- 原子写失败（临时路径被目录占位，双平台一致）→ `REPAIR_WRITE_FAILED`
  exit 7，不制造假 COMPLETE（status 仍 exit 7），解除后重跑幂等修复。

**GREEN 实测**：9 个修复契约用例全绿（`fault-injection.log` §D 矩阵）。

## 附注（诚实披露）

1. **RED 期间的事故**：在未修复代码上运行 fence RED 用例时，旧
   `cmd_collect(complete=True)` 经 `evidence_dir=EVIDENCE_DIR` 向
   `r1/` 写入过一个未跟踪模拟 `real-forward-window-status.json`
   （`"completion": "COMPLETE_VERIFIED"` 修复型 payload，与 T7 轮同类）。
   该文件已删除；GREEN 围栏结构性阻止复发（已用三个套件轮次 + 二分定位
   验证零再污染）。两个既有测试（r2 persistence / r2 receipt-failure）
   当时因该污染文件断言失败，恢复干净后全绿——失败根因是外部污染状态，
   非本轮代码回归。
2. **test 编写期修正（非生产缺陷）**：`feed_sentinel` 首版为 pytest fixture，
   在窗口构建前生效导致 helper 自身被哨兵污染（`[1]*8`）——改为窗口构建后
   手动应用；repair 写失败注入首版阻塞快照目标路径（被 `exists()` 判为
   "已存在损坏"）——改为阻塞 `.tmp` 临时路径精确命中原子写失败分支。
   两处修正均只改测试文件，RED 失败记录基于修正后的最终 RED 运行。
