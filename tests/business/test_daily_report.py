"""V0.3 daily HTML report tests: zero-cycle rendering, the four (plus
NO_TRADE) action states, self-containment (no JS / no external links),
honesty banner labels, Decimal/datetime cell rendering, and HTML escaping
of hostile rationale text. Fully deterministic — render_daily_report is a
pure string function.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from trading_lab.business.daily_report import (
    ACTION_VALUES,
    render_daily_report,
)

UTC = dt.timezone.utc


def _run_meta(**over: object) -> dict[str, object]:
    meta: dict[str, object] = {
        "run_id": "RUN-DAILY-20261120",
        "data_source": "DEMO",
        "admission_level": "NOT_RESEARCH_ADMITTED",
        "license_level": "LICENSE_UNVERIFIED",
        "info_status": "NO_INFORMATION",
        "data_cutoff_utc": dt.datetime(2026, 11, 20, 21, 0, tzinfo=UTC),
        "missing_data": "incremental quotes missing after 20:00 UTC",
        "command": "python scripts/run_business_mvp.py --mode daily",
        "backtest_book": {
            "net_return_pct": "0.82", "max_drawdown_pct": "1.40",
            "note": "DEMO batch — INCONCLUSIVE alpha gate",
        },
        "mock_book": {
            "cash": Decimal("98765.43"),
            "equity": Decimal("101234.56"),
            "open_intents": 1,
        },
    }
    meta.update(over)
    return meta


def _cycle(action: str = "PENDING", **over: object) -> dict[str, object]:
    cycle: dict[str, object] = {
        "asof_utc": dt.datetime(2026, 11, 20, 14, 30, tzinfo=UTC),
        "regime": "UPTREND",
        "chosen": "ma-cross-spy",
        "target": {"SPY": Decimal("0.60")},
        "action": action,
        "risk_reasons": [],
        "cash": Decimal("98765.43"),
        "positions": {"SPY": Decimal("100")},
        "equity": Decimal("101234.56"),
        "rationale": "regime fits strategy; risk check pending",
    }
    cycle.update(over)
    return cycle


class TestZeroCycles:
    def test_renders_valid_html_with_empty_table(self) -> None:
        html = render_daily_report([], run_meta=_run_meta())
        assert html.startswith("<!doctype html>")
        assert "本日无决策周期" in html
        assert "每日决策周期" in html
        assert html.rstrip().endswith("</html>")

    def test_zero_cycles_keeps_books_separate(self) -> None:
        html = render_daily_report([], run_meta=_run_meta())
        assert "BACKTEST 账簿" in html
        assert "MOCK 账簿" in html
        assert "不得混合" in html


class TestCycleActions:
    def test_all_documented_actions_render(self) -> None:
        cycles = [_cycle(action=a) for a in ACTION_VALUES]
        assert set(ACTION_VALUES) == {
            "PENDING", "EXECUTED", "NO_TRADE", "REJECTED",
            "CALENDAR_BLOCKED"}
        html = render_daily_report(cycles, run_meta=_run_meta())
        for action in ACTION_VALUES:
            assert action in html

    def test_cycle_cells_render(self) -> None:
        html = render_daily_report(
            [_cycle(action="REJECTED",
                    risk_reasons=["MAX_NOTIONAL_EXCEEDED"],
                    rationale="risk veto: notional cap")],
            run_meta=_run_meta())
        assert "ma-cross-spy" in html
        assert "SPY=0.60" in html
        assert "MAX_NOTIONAL_EXCEEDED" in html
        assert "risk veto: notional cap" in html


class TestSelfContained:
    def test_no_scripts_no_external_links(self) -> None:
        html = render_daily_report([_cycle()], run_meta=_run_meta())
        lowered = html.lower()
        assert "<script" not in lowered
        assert "http://" not in html
        assert "https://" not in html
        assert "<link" not in lowered
        assert "onclick" not in lowered
        assert "<style>" in lowered  # inline CSS, single file

    def test_doctype_and_charset_present(self) -> None:
        html = render_daily_report([], run_meta=_run_meta())
        assert 'charset="utf-8"' in html
        assert html.startswith("<!doctype html>")


class TestHonestyLabels:
    def test_demo_labels_prominent(self) -> None:
        html = render_daily_report([], run_meta=_run_meta())
        assert "DATA SOURCE=DEMO" in html
        assert "ADMISSION=NOT_RESEARCH_ADMITTED" in html
        assert "LICENSE=LICENSE_UNVERIFIED" in html
        assert "INFO_STATUS=NO_INFORMATION" in html
        assert "未取得真实数据" in html

    def test_offline_labels_prominent(self) -> None:
        html = render_daily_report([], run_meta=_run_meta(
            data_source="OFFLINE"))
        assert "DATA SOURCE=OFFLINE" in html
        assert "OFFLINE 状态" in html

    def test_real_source_states_the_label(self) -> None:
        html = render_daily_report([], run_meta=_run_meta(
            data_source="REAL"))
        assert "DATA SOURCE=REAL" in html


class TestCells:
    def test_decimal_and_datetime_cells_render(self) -> None:
        html = render_daily_report([_cycle()], run_meta=_run_meta())
        assert "98765.43" in html       # Decimal cash (cycle + mock book)
        assert "101234.56" in html      # Decimal equity
        assert "2026-11-20T14:30:00+00:00" in html  # datetime asof
        assert "SPY=100" in html

    def test_missing_cells_show_dash(self) -> None:
        html = render_daily_report(
            [{"action": "CALENDAR_BLOCKED"}], run_meta=_run_meta())
        assert "CALENDAR_BLOCKED" in html
        assert "—</td>" in html


class TestEscaping:
    def test_hostile_rationale_is_escaped(self) -> None:
        html = render_daily_report(
            [_cycle(rationale="<script>alert('x')</script>")],
            run_meta=_run_meta())
        assert "<script" not in html.lower()
        assert "&lt;script&gt;" in html

    def test_hostile_run_meta_is_escaped(self) -> None:
        html = render_daily_report([], run_meta=_run_meta(
            missing_data="<img src=x onerror=alert(1)>"))
        assert "<img" not in html.lower()
        assert "&lt;img src=x onerror=alert(1)&gt;" in html

    def test_ampersand_escaped(self) -> None:
        html = render_daily_report(
            [_cycle(rationale="A&B<C")], run_meta=_run_meta())
        assert "A&amp;B&lt;C" in html


class TestDeterminism:
    def test_same_inputs_same_bytes(self) -> None:
        cycles = [_cycle(action="EXECUTED"), _cycle(action="PENDING")]
        meta = _run_meta()
        assert (render_daily_report(cycles, run_meta=meta)
                == render_daily_report(cycles, run_meta=_run_meta()))
