"""Business MVP run report: summary.json, pipeline JSONL, report.html.

One replay run writes ONE self-contained output directory:

    summary.json          — run identity, labels, results, digest
    pipeline_sessions.jsonl — per-session features/regime/info/decision trace
    pipeline_executions.jsonl — mock execution intents/outcomes/fills
    report.html           — self-contained, opens directly in a browser

Determinism: the run digest is the canonical digest of summary.json's
payload (which itself embeds fixture/config/protocol/dataset hashes and
the per-session pipeline digest). Wall-clock time NEVER enters any file —
the only timestamps are fixture timestamps from the replay timeline.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from trading_lab.business.types import ExecutionOutcome, SessionRecord
from trading_lab.security.canonical import canonical_digest

__all__ = ["ReportBuilder", "json_safe"]

LABELS = {
    "data_mode": "SYNTHETIC_OFFLINE_ONLY",
    "ai_provider": "MOCK/RULE",
    "execution_backend": "FAKE_BROKER",
    "broker_behavior": "MOCK_ONLY",
    "evidence_class": "BUSINESS_DEMO_ONLY — not strategy effectiveness, "
                      "not formal stage acceptance",
}


def json_safe(obj: object) -> object:
    """Decimal/datetime/tuple-aware conversion for JSON serialization with
    stable formatting (determinism of the digest depends on this)."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def _dump_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> str:
    lines = [json.dumps(json_safe(r), sort_keys=True, ensure_ascii=False)
             for r in rows]
    text = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(text, encoding="utf-8")
    return canonical_digest(text)


def _esc(s: object) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class ReportBuilder:
    """Accumulates one run's artifacts and writes the output directory."""

    def __init__(self, *, output_dir: Path, run_id: str, command: str,
                 identity: Mapping[str, str]) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.command = command
        self.identity = dict(identity)  # fixture/config/protocol hashes etc.

    # -- artifact assembly -------------------------------------------------

    def finalize(
        self,
        *,
        session_records: Sequence[SessionRecord],
        executions: Sequence[ExecutionOutcome],
        backtest: Mapping[str, object],
        mock_execution: Mapping[str, object],
        fixture_summary: Mapping[str, object],
        rejections: Sequence[Mapping[str, object]],
        acceptance: Mapping[str, object],
    ) -> Path:
        sessions_rows = [self._session_row(r) for r in session_records]
        sessions_digest = _dump_jsonl(
            self.output_dir / "pipeline_sessions.jsonl", sessions_rows)
        exec_rows = [json_safe(dataclasses_asdict(e)) for e in executions]
        exec_digest = _dump_jsonl(
            self.output_dir / "pipeline_executions.jsonl", exec_rows)

        summary = {
            "run_id": self.run_id,
            "labels": dict(LABELS),
            "command": self.command,
            "identity": json_safe(dict(self.identity)),
            "fixture": json_safe(dict(fixture_summary)),
            "counts": {
                "sessions": len(session_records),
                "executions": len(executions),
                "rejections": len(rejections),
            },
            "backtest": json_safe(dict(backtest)),
            "mock_execution": json_safe(dict(mock_execution)),
            "rejections": json_safe(list(rejections)),
            "acceptance": json_safe(dict(acceptance)),
            "pipeline_digests": {
                "sessions": sessions_digest,
                "executions": exec_digest,
            },
        }
        summary["run_digest"] = canonical_digest(
            json_safe({k: v for k, v in summary.items() if k != "run_digest"}))
        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(
            json.dumps(json_safe(summary), indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n", encoding="utf-8")
        html_path = self.output_dir / "report.html"
        html_path.write_text(self._render_html(summary, session_records,
                                               executions), encoding="utf-8")
        return summary_path

    @staticmethod
    def _session_row(r: SessionRecord) -> dict[str, object]:
        return {
            "asof_utc": r.asof_utc,
            "session_date": r.session_date,
            "scenario_tag": r.scenario_tag,
            "regime_labels": list(r.regime_labels),
            "regime_confidence": r.regime_confidence,
            "regime_feature_hash": r.regime_feature_hash,
            "features": {
                sym: {
                    "status": fv.status,
                    "reasons": list(fv.reasons),
                    "feature_hash": fv.feature_hash,
                    "ma_short": fv.ma_short, "ma_long": fv.ma_long,
                    "rsi": fv.rsi, "atr": fv.atr,
                    "realized_vol": fv.realized_vol,
                    "returns_1d": fv.returns_1d,
                    "volume_ratio": fv.volume_ratio,
                }
                for sym, fv in r.features.items()
            },
            "info": list(r.info_assessments),
            "proposals": {
                sid: {
                    "exposure": dict(p.target_exposure),
                    "rationale": p.rationale,
                    "reject_reasons": list(p.reject_reasons),
                }
                for sid, p in r.proposals.items()
            },
            "decision": {
                "chosen": r.decision.chosen_strategy_id,
                "no_trade_reasons": list(r.decision.no_trade_reasons),
                "scores": dict(r.decision.candidate_scores),
                "rationale": r.decision.rationale,
                "decision_hash": r.decision.decision_hash,
            },
        }

    # -- html ----------------------------------------------------------------

    def _render_html(self, summary: Mapping[str, object],
                     records: Sequence[SessionRecord],
                     executions: Sequence[ExecutionOutcome]) -> str:
        labels = summary["labels"]
        identity = summary["identity"]
        backtest = summary["backtest"]
        mock = summary["mock_execution"]
        rows_html = self._sessions_table(records[:80], len(records))
        exec_html = self._exec_table(executions[:80], len(executions))
        bt_rows = "".join(
            f"<tr><td>{_esc(arm)}</td>"
            f"<td class='num'>{_esc(v.get('net_return_pct', '—'))}</td>"
            f"<td class='num'>{_esc(v.get('max_drawdown_pct', '—'))}</td>"
            f"<td class='num'>{_esc(v.get('turnover', '—'))}</td>"
            f"<td class='num'>{_esc(v.get('fees', '—'))}</td>"
            f"<td>{_esc(v.get('sample_gate', '—'))}</td>"
            f"<td>{_esc(v.get('note', ''))}</td></tr>"
            for arm, v in sorted(backtest.items()) if isinstance(v, dict))
        id_rows = "".join(
            f"<tr><th>{_esc(k)}</th><td><code>{_esc(v)}</code></td></tr>"
            for k, v in sorted(identity.items()))
        label_rows = "".join(
            f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>"
            for k, v in sorted(labels.items()))
        rej = summary.get("rejections") or []
        rej_rows = "".join(
            f"<tr><td>{_esc(r.get('scenario', ''))}</td>"
            f"<td>{_esc(r.get('outcome_state', ''))}</td>"
            f"<td>{_esc(r.get('risk_verdict', ''))}</td>"
            f"<td>{_esc(', '.join(r.get('risk_reasons', []) or []))}</td></tr>"
            for r in rej if isinstance(r, dict))
        acc = summary.get("acceptance") or {}
        acc_rows = "".join(
            f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
            for k, v in sorted(acc.items()) if not isinstance(v, dict))
        mock_block = "".join(
            f"<tr><th>{_esc(k)}</th><td><code>{_esc(v)}</code></td></tr>"
            for k, v in sorted(mock.items()) if not isinstance(v, (dict, list)))
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shutu 业务 MVP V0.1 回放报告</title>
<style>
:root {{ --ink:#1a1f2e; --muted:#5b6472; --line:#dfe3ea; --bg:#f7f8fa;
        --card:#ffffff; --accent:#0f5ea8; --warn:#a15c00; --ok:#0a7a4d; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
h2 {{ font-size:17px; margin:32px 0 8px; border-bottom:2px solid var(--line);
     padding-bottom:4px; }}
.sub {{ color:var(--muted); margin:0 0 16px; }}
.banner {{ background:#fff6e5; border:1px solid #ecd3a0; border-radius:8px;
          padding:10px 14px; margin:12px 0 20px; color:var(--warn);
          font-size:13.5px; }}
section {{ background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:14px 16px; margin:14px 0; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th,td {{ border:1px solid var(--line); padding:5px 8px; text-align:left; }}
th {{ background:#eef1f5; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
code {{ font-family:Consolas,Menlo,monospace; font-size:12.5px;
       background:#eef1f5; padding:1px 4px; border-radius:4px; }}
.scroll {{ max-height:420px; overflow:auto; }}
.ok {{ color:var(--ok); font-weight:600; }}
.tag {{ display:inline-block; background:#e8f0fa; color:var(--accent);
       border-radius:12px; padding:1px 10px; font-size:12.5px; margin:2px; }}
footer {{ color:var(--muted); font-size:12.5px; margin-top:28px; }}
</style>
</head>
<body>
<main>
<h1>Shutu AI Trading Lab — 业务 MVP V0.1 回放报告</h1>
<p class="sub">run {_esc(summary.get('run_id'))} · 一条命令的完整业务闭环演示</p>
<div class="banner">
  <strong>诚实性标注：</strong>{_esc(labels.get('data_mode'))} ·
  AI_PROVIDER={_esc(labels.get('ai_provider'))} ·
  EXECUTION_BACKEND={_esc(labels.get('execution_backend'))} /
  {_esc(labels.get('broker_behavior'))}。<br>
  {_esc(labels.get('evidence_class'))}。本报告不含真实市场收益，不得作为
  策略有效性、正式阶段验收或任何实盘依据。
</div>

<section><h2>运行身份与复现</h2>
<table>{id_rows}<tr><th>run_digest</th><td><code>{_esc(summary.get('run_digest'))}</code></td></tr>
<tr><th>命令</th><td><code>{_esc(self.command)}</code></td></tr></table>
<p>同 fixture/config/seed/protocol 重跑应得到相同 run_digest。</p>
</section>

<section><h2>回测与基准（正式 BacktestEngine · 演示批次）</h2>
<table><tr><th>组合</th><td class="num">净收益 %</td><td class="num">最大回撤 %</td>
<td class="num">换手</td><td class="num">费用</td><td>样本门</td><td>说明</td></tr>
{bt_rows}</table>
<p>样本不足或未验证处如实标注；统计性 Alpha 门为 INCONCLUSIVE（演示协议）。</p>
</section>

<section><h2>市场状态与决策流水（每 session）</h2>
<div class="scroll">{rows_html}</div>
<p>特征不足/过期 → UNKNOWN；全部候选不可用 → NO_TRADE 并给出理由。</p>
</section>

<section><h2>信息事件证据（RULE / MOCK LLM）</h2>
{_info_table(records)}
</section>

<section><h2>Mock 执行（FakeBroker · 虚构账户）</h2>
<table>{mock_block}</table>
{exec_html}
</section>

<section><h2>风险拒绝记录</h2>
<table><tr><th>场景</th><th>结果状态</th><th>风控判定</th><th>理由</th></tr>
{rej_rows or '<tr><td colspan=4>（无）</td></tr>'}</table>
</section>

<section><h2>验收观察点</h2>
<table>{acc_rows}</table>
</section>

<footer>自包含报告 · SYNTHETIC_OFFLINE_ONLY · 生成自
<code>{_esc(summary.get('run_id'))}</code> · 不读取 sealed Holdout</footer>
</main>
</body>
</html>"""

    def _sessions_table(self, records: Sequence[SessionRecord],
                        total: int) -> str:
        head = ("<table><tr><th>session</th><th>场景</th><th>状态标签</th>"
                "<th>置信</th><th>SPY 特征</th><th>QQQ 特征</th>"
                "<th>决策</th><th>理由</th></tr>")
        rows = []
        for r in records:
            spy = r.features.get("SPY")
            qqq = r.features.get("QQQ")
            fmt = (lambda fv: "UNKNOWN" if fv is None or fv.status != "OK"
                   else f"MA {fv.ma_short}/{fv.ma_long} RSI {fv.rsi}")
            dec = r.decision.chosen_strategy_id or "NO_TRADE"
            reason = ("; ".join(r.decision.no_trade_reasons)
                      if not r.decision.chosen_strategy_id
                      else r.decision.rationale[:60])
            rows.append(
                f"<tr><td>{_esc(r.session_date)}</td>"
                f"<td>{_esc(r.scenario_tag)}</td>"
                f"<td>{_esc(' '.join(r.regime_labels))}</td>"
                f"<td class='num'>{_esc(r.regime_confidence)}</td>"
                f"<td>{_esc(fmt(spy))}</td><td>{_esc(fmt(qqq))}</td>"
                f"<td><span class='tag'>{_esc(dec)}</span></td>"
                f"<td>{_esc(reason)}</td></tr>")
        note = (f"<p>共 {total} 个 session，显示前 {len(records)} 个；"
                "完整流水见 <code>pipeline_sessions.jsonl</code>。</p>"
                if total > len(records) else "")
        return head + "".join(rows) + "</table>" + note

    def _exec_table(self, executions: Sequence[ExecutionOutcome],
                    total: int) -> str:
        rows = "".join(
            f"<tr><td>{_esc(e.intent_id)}</td>"
            f"<td>{_esc(e.client_order_id)}</td>"
            f"<td>{_esc(e.risk_verdict)}</td><td>{_esc(e.outcome_state)}</td>"
            f"<td class='num'>{_esc(e.fill_qty)}</td>"
            f"<td class='num'>{_esc(e.fill_price)}</td></tr>"
            for e in executions)
        note = (f"<p>共 {total} 笔，显示前 {len(executions)} 笔；完整记录见 "
                "<code>pipeline_executions.jsonl</code>。</p>"
                if total > len(executions) else "")
        return (f"<div class='scroll'><table><tr><th>intent</th><th>coid</th>"
                f"<th>风控</th><th>状态</th><th>数量</th><th>价格</th></tr>"
                f"{rows}</table></div>{note}")


def _info_table(records: Sequence[SessionRecord]) -> str:
    seen: dict[str, str] = {}
    for r in records:
        for a in r.info_assessments:
            aid = str(a.get("assessment_id", ""))
            if aid and aid not in seen:
                seen[aid] = (
                    f"<tr><td>{_esc(aid)}</td>"
                    f"<td>{_esc(a.get('asset', ''))}</td>"
                    f"<td>{_esc(a.get('category', ''))}</td>"
                    f"<td>{_esc(a.get('direction', ''))}</td>"
                    f"<td class='num'>{_esc(a.get('confidence', ''))}</td>"
                    f"<td>{_esc(a.get('analyzer', ''))}</td>"
                    f"<td>{_esc(a.get('status', ''))}</td>"
                    f"<td>{_esc(a.get('evidence_ref', ''))}</td></tr>")
    body = "".join(seen[k] for k in sorted(seen)) or \
        "<tr><td colspan=8>（本回放无可评估信息事件）</td></tr>"
    return ("<div class='scroll'><table><tr><th>assessment</th><th>资产</th>"
            "<th>类别</th><th>方向</th><th>置信</th><th>分析器</th>"
            "<th>状态</th><th>证据指针</th></tr>"
            f"{body}</table></div>")


def dataclasses_asdict(obj: object) -> dict:
    import dataclasses

    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)  # type: ignore[arg-type]
    raise TypeError(f"not a dataclass: {type(obj)!r}")
