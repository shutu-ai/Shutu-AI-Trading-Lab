# 授权申请草案：B-only 无网络凭证注入核验（b-only-authorization-request — T9.7.3，本轮不执行，签批栏空白）

> 本文件是**草案**：它不是授权，不构成执行许可。只有用户在批复栏明确批准后，
> 账户所有者本人才可在指定环境执行**一次**下述核验；执行与签署永远由本人
> 完成，Codex/Agent 零接触。本申请**不涉及任何网络访问、API 调用、行情采集
> 或下单**；其批准**绝不**延伸授权首次真实采集（那是另一份独立申请）。

## 1. 申请人前提（申请时如实填写；未满足则本申请不得提交）

- [ ] A = VERIFIED_BY_OPERATOR（本人签署副本在操作者本地；仓库内只有空白模板）
- [ ] C = VERIFIED_BY_OPERATOR（F-1～F-8 全矩阵通过；`HOST_EGRESS_ISOLATION`
      已去掉 UNVERIFIED 标注）
- [ ] 目标环境身份已固定（`operator-gate-reconciliation.md` §5 登记表填写完成；
      含 §6 持久状态卷方案）
- [ ] `B_PLAN_READY=TRUE`（本人已签署 `operator-attestation-template.md` §B
      的方案理解栏——该准备事实不等于本申请的执行授权）

环境标识（非敏感）：＿＿＿＿＿＿＿＿＿＿　state dir 标识/hash：＿＿＿＿＿＿＿＿

> **2026-11-23 T9.8 修订（直连受限试点例外——上述 §1 前置不删除，新增可
> 验证替代分支）**：经用户批示（`Shutu_M35_S8_T9_8_Windows_Direct_Limited_
> Pilot_Approval.md`；审批记录见 `../s8-operator-t9-8/windows-direct-pilot-
> approval-record.md`），C 前置出现**政策例外分支**。现行门语义：
>
> `A_verified AND ((C_verified AND environment_frozen) OR
>  (direct_pilot_exception_approved AND local_risk_acceptance_signed AND
>   environment_frozen))`
>
> - 替代分支下 C 保持**实测原值** `OPERATOR_PREFLIGHT_C=BLOCKED`
>   （2026-11-23 直连主机 F-2 失败）、`HOST_EGRESS_ISOLATION_UNVERIFIED`
>   保持——例外**不写成** `C=VERIFIED_BY_OPERATOR`、`F-2=PASS`；
> - 走替代分支的申请须随附：T9.8 批示 + 例外审批记录引用 +
>   **本人已签署的本地直连残余风险接受记录**（approval-record §8.2，
>   签署副本仅存本地，仓库内只填非敏感索引）；
> - 原 §1 全矩阵路径（C=VERIFIED）**保持可用、未被废除**；本修订不改变
>   §2 范围、§3 诚实边界与两授权独立性，本身不构成任何执行授权。

## 2. 申请范围（严格有限，逐条）

1. 在指定环境的**一个受控子进程**中，由本人注入
   `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`（进程级环境变量或 secret mount）；
2. 执行**名称级可见性检查**：确认两个变量名存在于该子进程环境
   （仅存在性，永不输出值/长度/前后缀/散列/任何可回推标识）；
3. 立即终止该子进程并**清除**注入（确认进程树终止、环境内无残留副本）；
4. 记录无敏感事实：检查结果（存在/不存在）、时间、环境标识、清除确认。

**明确不授权**（超出以下任一条即违规）：
- 任何网络请求（包括对 `data.alpaca.markets` 的"测试一下"）；
- 任何 API 调用、行情采集（`collect`）、Paper/Live 下单、付费订阅；
- 把凭证值/派生信息交给任何第二人、工具、会话、日志、仓库；
- 用"变量存在"推断 Alpaca 授权有效、升级 `API_VERIFIED` 或宣称 API 成功
  （凭证可用性只能由未来的真实采集回执链证明）。

## 3. 核验后的诚实边界（执行者必须先读）

- 本核验通过 → B 可由本人签署为 `VERIFIED_BY_OPERATOR`——它只证明
  "注入/清除操作已由本人完成"，**不证明**凭证有效、市场数据权限正确、
  账户条款合规（那些属 A 与未来真实采集的回执）；
- 本核验**不改变**：`API_VERIFIED=NONE`、`REAL_FORWARD_DAYS=0`、
  `FIRST_REAL_ONCE_READY=NO`、`M3.5_GATE=USER_PENDING`。

## 4. 执行记录栏（本人填写，本地保存；仓库内本草案保持空白）

- 批准人：＿＿＿＿　批准日期：＿＿＿＿
- 执行日期/时间：＿＿＿＿
- 注入方式：＿＿＿＿（进程级；无敏感细节）
- 可见性检查结果：＿＿＿＿（存在/不存在）
- 清除确认：＿＿＿＿（进程树终止 + 无残留）
- 异常/偏离（如有）：＿＿＿＿＿＿＿＿＿＿＿＿

## 5. 批复栏（授权人填写）

- [ ] 批准：范围限本文件 §2 全部四条，环境限 §1 登记标识，一次性
- [ ] 拒绝 / 补充条件：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿
- [ ] 提示（签批即确认知悉）：本批准与"首次真实 collect --once"授权
      **完全独立**，本批准不构成后者的任何预授权。

签署（授权人）：＿＿＿＿＿＿＿＿　日期：＿＿＿＿-＿＿＿-＿＿＿＿
