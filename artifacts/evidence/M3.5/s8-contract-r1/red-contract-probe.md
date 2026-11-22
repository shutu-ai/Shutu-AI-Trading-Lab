# RED 契约探针（T0.2，2026-11-22，对整改前代码实跑）

> `red-tests.log`：`tests/s8_gateway/test_red_contract_probe.py` 对**整改前**代码 4/4 PASSED（EXIT=0），钉死两项 P0 缺陷的现行为。全部载荷为人工构造的官方文档形状离线夹具；**没有任何真实 API 返回或网络调用**。

## RED-1：官方 `bars/latest` 形状被旧质量门拒收（无法解析真实响应）

- 依据：官方文档（`official-api-contract.md` §1，检索 2026-11-22）——单标的 `/v2/stocks/{symbol}/bars/latest` 返回**分钟线**，响应必填键为 `bar`（单对象）+ `symbol`（schema `stock_latest_bars_resp_single`）。
- 现行为（测试 `test_red_official_latest_shape_is_rejected_by_legacy_gate`）：把文档精确形状 `{"symbol":"SPY","bar":{...分钟 bar...}}` 喂给旧 `validate_raw_bar` → `SCHEMA` 拒绝（detail 含 `bars`）。即：**旧契约无法解析任何真实响应**（fail-closed 但合同错误——采集器对真实世界零可用性）。
- 请求侧旁证（`test_red_legacy_request_contract_asks_for_minute_bars`）：旧 feed 请求 `/bars/latest` **无 timeframe 参数**（该端点本就是分钟线语义），且回执硬编码 `"request_query": "feed=iex"` 掩盖了真实请求。

## RED-2：分钟戳 bar 在旧契约下被当作日线事件（无日线/分钟判别）

- 现行为（`test_red_minute_stamped_bar_becomes_daily_event_under_legacy`）：盘中分钟戳（16:05 ET，`2026-11-23T21:05:00Z`）的 bar 走完旧管线 → 被当作 `interval=1d` 事件、贴上会话收盘 `ts_event`、带分钟收盘价进入前向管线。**分钟 close ≠ 日线 close，改 interval 标签不能修复**（任务书 P0-1 原话）。

## RED-3：五日 PASS 判据缺少持久事实来源（P0-2）

- 现行为（`test_red_window_facts_lack_pass_criterion_fields`）：构造含**喂错误 episode + 后续恢复回执 + 幂等重复投递**的完整模拟窗口（journal 含 `DUPLICATE` 审计拒绝），`window_facts_from_journal()` 输出中 **`disconnect_recoveries` / `duplicate_recoveries` / `audits_passed` 三个字段全部缺失**——即：即便真实窗口完美，`evaluate_eligibility(claim='PASS')` 也永远无法从事实源取到所需判据，只能拒绝；且窗口资格没有任何持久化、链绑定的评估记录。

## 整改后

- RED-1/1b/2 三个探针**原样保留**为钉死的 legacy 模式回归（legacy 分支冻结，仅证据复现可用；生产 ranged 契约走新路径）。
- RED-3 探针翻转为 GREEN（`test_green_window_facts_now_provide_pass_criterion_fields`）：同窗口现暴露三个链计算字段；合成旗标下 PASS 仍拒绝（字段是必要条件，真实到达才是充分条件）。
