# 操作者预检清单（operator-preflight，T3.3/T3.4 — 由账户所有者本人完成）

> 本清单由**用户（账户所有者）**逐项本地确认；Codex 不得代签、不得读取/记录任何凭证值。未确认前采集器保持 `BLOCKED_ENV`。

## A. 账户与许可（签批条款 3）

- [ ] Alpaca 账户已由本人注册/登录（Paper Only，未开通 Live、未入金）
- [ ] 本人已核对当期市场数据条款，确认免费 Basic 计划 + IEX feed 可用于个人工程观察用途
- [ ] 确认不订阅任何付费计划（SIP/Algo Trader Plus 永不授权）
- [ ] `license_attestation.operator_confirmed` 的声明与上述事实一致（该声明是配置陈述，**不是**已验证事实——本清单签署后才转为本地确认记录）

## B. 凭证安全（不写入仓库/日志/回执/CI/会话）

- [ ] `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` 仅注入采集子进程环境（secret mount / 进程级注入）
- [ ] 凭证未发送到任何 AI 会话/剪贴板工具/截图；未写入 `.env`/git/CI
- [ ] 注入后以 `scripts/run_m35_s8_shadow_real.py status` 验证（状态命令不读凭证值，仅审计可见性名单）

## C. 主机/网络出口隔离（T3.4 — 应用层守卫不能替代）

- [ ] 出站白名单：仅 `data.alpaca.markets:443` 可达
- [ ] `api.alpaca.markets`、`paper-api.alpaca.markets` 及泛互联网出站被防火墙/容器策略阻断
- [ ] 已用无凭证负例验证隔离（如 `GET https://api.alpaca.markets/…` 在网络层失败）
- [ ] 若本机无法证明上述策略：如实标记 `HOST_EGRESS_ISOLATION_UNVERIFIED`——禁止在报告中声称"网络层完全只读"
- [ ] 代理差异（办公网 192.168.1.2:8080 vs 家庭直连）已确认不影响白名单语义；不为通网放宽白名单

## D. 首次真实采集序列（未来单独授权后，禁止本轮执行）

1. `check-config`（默认 = ranged v2 协议）→ `selftest`（离线，不得计入真实窗口）→ `status`（`NOT_STARTED`）
2. 完成 A–C 后注入凭证 → **首轮仅采集一个真实周期**（`collect --once`）→ 状态只能升为实测取证后的 `API_VERIFIED` 或维持 BLOCKED（不得猜测）
3. 每个合法真实交易日只读采集一个会话（不回填冒充前向）；完成 ≥5 全覆盖真实日 + 断线/重复恢复证据后，独立复核再申请 `M3.5_GATE=CLOSED_WITH_REAL_FORWARD_SCOPE`
4. Alpaca Paper 下单是**完全独立的未来签批**（`PAPER_WRITE=NOT_AUTHORIZED` 保持）；M4 不自动启动

## 签署（账户所有者本人，本地保存，不入仓库）

> 签署行仅保存于操作者本地（本文件提交时不包含任何签名/凭证/账户信息）。

- [ ] A 全部 / [ ] B 全部 / [ ] C 全部 — 签署人：＿＿＿ 日期：＿＿＿
