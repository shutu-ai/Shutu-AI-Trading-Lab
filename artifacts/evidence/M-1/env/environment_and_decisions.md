# M-1 执行环境与冲突处置记录

## 执行环境（2026-11-19 实测）

| 项 | 值 | 证据 |
|---|---|---|
| 主机 | Windows 11 Pro 10.0.26200 | 系统信息 |
| Python | 3.13.15（`.venv`） | `env/python_version.txt` |
| Git | 2.55.0.windows.3 | 同上 |
| 网络 | 强制代理 `http://192.168.1.2:8080`（用户指令） | 本文件 |
| Alpaca 密钥 | 环境中不存在（`APCA_API_KEY_ID/SECRET` 未设置） | 本文件；因此 Alpaca Paper 实测未运行 |
| LLM API 密钥 | 不存在 | RD-Agent LLM 循环 BLOCKED_ENV 的原因 |

Python 可用版本：3.13.15 / 3.14.6 / 3.15.2（无 3.11；`py -3.11` 失败）。

## 冲突与处置（授权要求：记录并解决后才实施）

| # | 发现 | 处置 | 依据 |
|---|---|---|---|
| 1 | 授权书与基线引用 `docs/plans/*.md`，实际文件位于 `docs/` 根目录 | 移动到 `docs/plans/`，与基线 §11.3 唯一工件路径一致；baseline commit `0c31e65` | §11.3 |
| 2 | 基线指定 Python 3.11，本机无 3.11 | **用户中途指令改用 Python 3.13**；全部候选在 3.13 上实测，兼容性结果进入各候选 eval | 用户指令（本记录留痕） |
| 3 | 项目非 Git 仓库，而 E/S/R 报告要求 commit 字段 | `git init`；placeholder 身份 `Shutu Lab Engineering <engineering@shutu.local>`（用户可后续修改/重写历史） | §11.2 报告字段要求 |
| 4 | 下载需走代理 | 所有 pip/git 网络操作显式走 `http://192.168.1.2:8080` | 用户指令 |
| 5 | 基线 §0.4/§12 称"当前停于 ENGINEERING_START_APPROVAL_PENDING，不启动 M-1" | 用户已在本会话明确下达 M-1 启动授权（授权书原文），状态视为已放行 M-1；其余阶段门不变 | 用户授权 |

## 审计事实

- 上游克隆均为 `--depth 1`，锁定 SHA 记录于 `docs/licenses/third-party.md`；完整历史未取（shallow clone 限制已在候选评估中披露）。
- 所有 PASS 结论均有对应原始命令输出日志；所有 FAIL 均含原始错误文本。
- 本阶段未连接任何真实券商；未创建任何账户/密钥；未发起任何真实下单。
