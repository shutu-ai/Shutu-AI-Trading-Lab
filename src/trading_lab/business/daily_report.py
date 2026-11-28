"""Self-contained daily HTML report (Business MVP V0.3 §3 日报).

``render_daily_report`` turns one day's decision cycles into a SINGLE
self-contained HTML string: inline CSS, no JavaScript, no external
links, no web service — it opens directly in a browser and is the
operator-facing twin of the V0.2 ``report.html`` style.

Honesty requirements (task §3 日报 bullet, honored verbatim):

- The banner states DATA SOURCE (``REAL`` / ``DEMO`` / ``OFFLINE`` as
  passed in ``run_meta``), the admission/license level, and the
  information status — including ``NO_INFORMATION``, which is displayed
  as-is rather than papered over.
- Real data never present is labeled prominently: DEMO/OFFLINE reports
  carry an explicit not-for-live-use line.
- BACKTEST and MOCK books are rendered as two separately LABELED
  sections and never mixed: no combined curve, no combined equity
  number, no derived cross-book comparison.

Escaping: every interpolated value goes through the local ``_esc``
(copied from ``report.py`` — element-text escaping of ``&``, ``<``,
``>``); Decimal/datetime cells go through the local json_safe-style
``_scalar``/``_fmt_cell`` formatters. Deterministic: same inputs give
the same bytes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal

__all__ = [
    "ACTION_VALUES",
    "CYCLE_KEYS",
    "RUN_META_KEYS",
    "render_daily_report",
]

#: documented cycle-mapping contract (all keys optional; missing -> "—")
CYCLE_KEYS = (
    "asof_utc",     # decision clock (datetime or ISO string)
    "regime",       # market-state label(s)
    "chosen",       # chosen strategy id ("" / None -> NO_TRADE-like dash)
    "target",       # Mapping symbol -> target weight/exposure
    "action",       # PENDING | EXECUTED | NO_TRADE | REJECTED | CALENDAR_BLOCKED
    "risk_reasons", # sequence of risk refusal reasons
    "cash",         # Decimal cash after the cycle (MOCK book)
    "positions",    # Mapping symbol -> position (qty/notional)
    "equity",       # Decimal equity after the cycle (MOCK book)
    "rationale",    # decision rationale (escaped in HTML)
)

#: documented run_meta contract (all keys optional; missing -> "—")
RUN_META_KEYS = (
    "run_id",          # run identifier
    "data_source",     # REAL | DEMO | OFFLINE (banner label)
    "admission_level", # data admission level (e.g. NOT_RESEARCH_ADMITTED)
    "license_level",   # license level (e.g. LICENSE_UNVERIFIED)
    "info_status",     # information status incl. NO_INFORMATION
    "data_cutoff_utc", # data as-of / cutoff time
    "missing_data",    # honestly-stated missing data note
    "command",         # the one command that produced this report
    "backtest_book",   # Mapping of BACKTEST-book scalar metrics
    "mock_book",       # Mapping of MOCK-book scalar metrics
)

ACTION_VALUES = ("PENDING", "EXECUTED", "NO_TRADE", "REJECTED",
                 "CALENDAR_BLOCKED")

_DASH = "—"


def _esc(s: object) -> str:
    """Copied locally from report.py (never import a private symbol)."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _scalar(value: object) -> str:
    """json_safe-style display formatting for one value (never raises)."""
    if value is None:
        return _DASH
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def _fmt_cell(value: object) -> str:
    """Display formatting for a whole cell: mappings become ``k=v`` pairs,
    sequences become ``; ``-joined items, empties show an honest dash."""
    if value is None:
        return _DASH
    if isinstance(value, Mapping):
        pairs = [f"{_scalar(k)}={_scalar(v)}" for k, v in value.items()]
        return ", ".join(pairs) if pairs else _DASH
    if isinstance(value, (list, tuple)):
        items = [_scalar(v) for v in value]
        return "; ".join(items) if items else _DASH
    return _scalar(value)


def _meta(run_meta: Mapping[str, object], key: str) -> str:
    return _fmt_cell(run_meta.get(key))


def _honesty_banner(run_meta: Mapping[str, object]) -> str:
    data_source = _meta(run_meta, "data_source")
    extra = ""
    if data_source != "REAL":
        extra = (
            f"<br><strong>未取得真实数据 — 本报告整体为 "
            f"{_esc(data_source or 'OFFLINE')} 状态</strong>：不得作为策略"
            "有效性、正式阶段验收或任何实盘依据。")
    return f"""
<div class="banner">
  <strong>诚实性标注：</strong>DATA SOURCE={_esc(data_source)} ·
  ADMISSION={_esc(_meta(run_meta, "admission_level"))} ·
  LICENSE={_esc(_meta(run_meta, "license_level"))} ·
  INFO_STATUS={_esc(_meta(run_meta, "info_status"))} ·
  DATA CUTOFF={_esc(_meta(run_meta, "data_cutoff_utc"))}<br>
  缺失数据：{_esc(_meta(run_meta, "missing_data"))}。{extra}
</div>"""


def _cycle_row(cycle: Mapping[str, object]) -> str:
    action = _fmt_cell(cycle.get("action"))
    return (
        f"<tr>"
        f"<td>{_esc(_fmt_cell(cycle.get('asof_utc')))}</td>"
        f"<td>{_esc(_fmt_cell(cycle.get('regime')))}</td>"
        f"<td>{_esc(_fmt_cell(cycle.get('chosen')))}</td>"
        f"<td>{_esc(_fmt_cell(cycle.get('target')))}</td>"
        f"<td><span class='tag'>{_esc(action)}</span></td>"
        f"<td>{_esc(_fmt_cell(cycle.get('risk_reasons')))}</td>"
        f"<td class='num'>{_esc(_fmt_cell(cycle.get('cash')))}</td>"
        f"<td>{_esc(_fmt_cell(cycle.get('positions')))}</td>"
        f"<td class='num'>{_esc(_fmt_cell(cycle.get('equity')))}</td>"
        f"<td>{_esc(_fmt_cell(cycle.get('rationale')))}</td>"
        f"</tr>")


def _cycles_table(cycles: Sequence[Mapping[str, object]]) -> str:
    if not cycles:
        body = (f"<tr><td colspan='10'>本日无决策周期 "
                f"{_DASH} NO_INFORMATION / 覆盖不足时如实留空</td></tr>")
    else:
        body = "".join(_cycle_row(c) for c in cycles)
    return (f"<div class='scroll'><table>"
            f"<tr><th>asof</th><th>regime</th><th>chosen</th><th>target</th>"
            f"<th>action</th><th>风险理由</th><th>cash</th><th>positions</th>"
            f"<th>equity</th><th>rationale</th></tr>"
            f"{body}</table></div>")


def _book_table(book: object, *, label: str, empty_note: str) -> str:
    """One book's metrics as its own labeled table (books are NEVER mixed:
    this renders only the mapping handed in, with the book label baked
    into the heading)."""
    if isinstance(book, Mapping) and book:
        rows = "".join(
            f"<tr><th>{_esc(k)}</th><td><code>{_esc(_scalar(v))}</code>"
            f"</td></tr>"
            for k, v in sorted(book.items(), key=lambda kv: str(kv[0])))
        body = f"<table>{rows}</table>"
    else:
        body = f"<p class='muted'>{_esc(empty_note)}</p>"
    return f"<section><h2>{_esc(label)}</h2>{body}</section>"


def render_daily_report(
    cycles: Sequence[Mapping[str, object]],
    *,
    run_meta: Mapping[str, object],
) -> str:
    """Render one day's read-only analysis + virtual-account cycles as a
    single self-contained HTML string (inline CSS, no JS, no external
    links). See the module docstring for the honesty contract and
    ``CYCLE_KEYS`` / ``RUN_META_KEYS`` for the documented input shapes.
    """
    cycle_items: Sequence[Mapping[str, object]] = list(cycles)
    run_id = _meta(run_meta, "run_id")
    command = _meta(run_meta, "command")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shutu V0.3 每日只读分析日报</title>
<style>
:root {{ --ink:#1a1f2e; --muted:#5b6472; --line:#dfe3ea; --bg:#f7f8fa;
        --card:#ffffff; --accent:#0f5ea8; --warn:#a15c00; --ok:#0a7a4d; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1120px; margin:0 auto; padding:24px 16px 64px; }}
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
.scroll {{ max-height:480px; overflow:auto; }}
.tag {{ display:inline-block; background:#e8f0fa; color:var(--accent);
       border-radius:12px; padding:1px 10px; font-size:12.5px; }}
.muted {{ color:var(--muted); }}
footer {{ color:var(--muted); font-size:12.5px; margin-top:28px; }}
</style>
</head>
<body>
<main>
<h1>Shutu AI Trading Lab — V0.3 每日只读分析日报</h1>
<p class="sub">run {_esc(run_id)} · 只读分析与虚拟账户 · 不开后台服务、不连真实账户</p>
{_honesty_banner(run_meta)}

<section><h2>每日决策周期（PIT 视角）</h2>
{_cycles_table(cycle_items)}
<p>action 口径：PENDING=待下一事件确认后执行 · EXECUTED=已通过风险复核并由
FakeBroker 模拟成交 · NO_TRADE=无候选/无信息 · REJECTED=风险拒绝 ·
CALENDAR_BLOCKED=日历覆盖不足、诚实阻断。计划与成交分离：未到对应事件不得提前成交。</p>
</section>

{_book_table(run_meta.get("backtest_book"),
             label="BACKTEST 账簿（历史回测 · 独立核算）",
             empty_note="（本报告未包含 BACKTEST 账簿数据）")}
{_book_table(run_meta.get("mock_book"),
             label="MOCK 账簿（虚拟账户 FakeBroker · 独立核算）",
             empty_note="（本报告未包含 MOCK 账簿数据）")}
<p class="muted">两本账簿明确分开核算：BACKTEST 与 MOCK 的曲线与净值不得混合，
也不做跨账簿合并比较。</p>

<footer>自包含日报（无 JS / 无外链 / 无 Web 服务） · run
<code>{_esc(run_id)}</code>{f" · 命令 <code>{_esc(command)}</code>" if command != _DASH else ""}
 · 数据截止 {_esc(_meta(run_meta, "data_cutoff_utc"))}</footer>
</main>
</body>
</html>"""
