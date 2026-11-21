"""M3-R1-T5 — cohort hygiene: overlap detection, Purge/Embargo,
Walk-Forward, forward-cohort locking, overlap report.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from trading_lab.validation import CohortError  # noqa: E402
from trading_lab.validation.cohorts import (  # noqa: E402
    CohortRole,
    CohortSpec,
    ForwardCohort,
    apply_purge_embargo,
    check_overlaps,
    walk_forward_splits,
)

U = dt.timezone.utc
T0 = dt.datetime(2025, 1, 1, tzinfo=U)


def d(n: int) -> dt.datetime:
    return T0 + dt.timedelta(days=n)


def cohort(role, a, b, symbols=("SPY",), events=(), labels=(),
           available=()):
    return CohortSpec(role=role, start=d(a), end=d(b),
                      symbols=frozenset(symbols),
                      event_ids=frozenset(events),
                      label_intervals=tuple(
                          (d(x), d(y)) for (x, y) in labels),
                      available_ats=tuple(d(x) for x in available))


class TestOverlapDetection:
    def test_sealed_final_vs_anything_is_illegal(self):
        train = cohort(CohortRole.TRAIN, 0, 400, symbols=("SPY",),
                       events=("e1",))
        sealed = cohort(CohortRole.SEALED_FINAL, 400, 500, symbols=("SPY",),
                        events=("e1",))
        rep = check_overlaps([train, sealed])
        assert not rep.independent
        assert any(not p["legal"] for p in rep.pairwise)

    def test_sealed_final_disjoint_is_legal(self):
        train = cohort(CohortRole.TRAIN, 0, 400, symbols=("SPY",),
                       events=("e1",))
        sealed = cohort(CohortRole.SEALED_FINAL, 400, 500, symbols=("QQQ",),
                        events=("e9",))
        rep = check_overlaps([train, sealed])
        assert rep.independent

    def test_symbol_overlap_disclosed(self):
        a = cohort(CohortRole.HIST_OOS, 400, 450, symbols=("SPY", "QQQ"))
        b = cohort(CohortRole.FORWARD, 500, 550, symbols=("QQQ", "TSLA"))
        rep = check_overlaps([a, b])
        entry = rep.pairwise[0]
        assert entry["time"] is False
        assert entry["symbols"] is True
        # forward vs hist-oos symbol overlap is a disclosure, not illegality
        assert entry["legal"] is True

    def test_event_id_and_label_intersection_detected(self):
        a = cohort(CohortRole.HIST_OOS, 400, 420,
                   events=("e1", "e2"),
                   labels=[(410, 415)])
        b = cohort(CohortRole.HIST_OOS, 430, 440,
                   events=("e2", "e3"),
                   labels=[(405, 412)])
        entry = check_overlaps([a, b]).pairwise[0]
        assert entry["event_ids"] is True
        assert entry["labels"] is True
        assert entry["time"] is False

    def test_available_at_proximity_flagged(self):
        a = cohort(CohortRole.HIST_OOS, 400, 410, available=[409, 500])
        b = cohort(CohortRole.FORWARD, 500, 510, available=[500, 600])
        entry = check_overlaps([a, b]).pairwise[0]
        assert entry["available_ats"] is True

    def test_reverse_time_cohort_rejected(self):
        with pytest.raises(CohortError, match="reverse"):
            cohort(CohortRole.TRAIN, 100, 0)

    def test_report_markdown_roundtrip(self):
        rep = check_overlaps([
            cohort(CohortRole.TRAIN, 0, 400),
            cohort(CohortRole.SEALED_FINAL, 400, 500),
        ])
        md = rep.to_markdown()
        assert "| pair |" in md
        assert "independent" in md


class TestPurgeEmbargo:
    def test_labels_crossing_boundary_purged(self):
        train = cohort(CohortRole.TRAIN, 0, 400,
                       labels=[(390, 398), (300, 305)])
        val = cohort(CohortRole.VALIDATION, 400, 500)
        adj_train, _ = apply_purge_embargo(
            train, val, label_horizon=dt.timedelta(days=2),
            embargo=dt.timedelta(days=5))
        assert (d(300), d(305)) in adj_train.label_intervals
        assert (d(390), d(398)) not in adj_train.label_intervals
        assert adj_train.end == d(395)  # 400 − 5 embargo

    def test_embargo_gap_enforced(self):
        train = cohort(CohortRole.TRAIN, 0, 400)
        val = cohort(CohortRole.VALIDATION, 400, 500)
        adj, _ = apply_purge_embargo(
            train, val, label_horizon=dt.timedelta(days=1),
            embargo=dt.timedelta(days=10))
        assert adj.end == d(390)
        assert val.start == d(400)  # 10-day embargo gap

    def test_label_still_crossing_after_embargo_fails_closed(self):
        # a kept label whose start + horizon crosses the embargoed boundary
        # is a leak the purge cannot fix — fail closed, never silent
        train = cohort(CohortRole.TRAIN, 0, 400, labels=[(397, 398)])
        val = cohort(CohortRole.VALIDATION, 400, 500)
        with pytest.raises(CohortError, match="fail closed"):
            apply_purge_embargo(train, val,
                                label_horizon=dt.timedelta(days=10),
                                embargo=dt.timedelta(days=2))

    def test_purge_drops_labels_ending_in_embargo_gap(self):
        train = cohort(CohortRole.TRAIN, 0, 400, labels=[(396, 399)])
        val = cohort(CohortRole.VALIDATION, 400, 500)
        adj, _ = apply_purge_embargo(train, val,
                                     label_horizon=dt.timedelta(days=1),
                                     embargo=dt.timedelta(days=2))
        assert adj.label_intervals == ()  # (396,399) ended at 399 > 398

    def test_embargo_consumes_window_fails_closed(self):
        train = cohort(CohortRole.TRAIN, 398, 400)
        val = cohort(CohortRole.VALIDATION, 400, 500)
        with pytest.raises(CohortError, match="embargo"):
            apply_purge_embargo(train, val,
                                label_horizon=dt.timedelta(days=1),
                                embargo=dt.timedelta(days=30))

    def test_overlapping_input_rejected(self):
        train = cohort(CohortRole.TRAIN, 0, 450)
        val = cohort(CohortRole.VALIDATION, 400, 500)
        with pytest.raises(CohortError, match="must not overlap"):
            apply_purge_embargo(train, val,
                                label_horizon=dt.timedelta(days=1),
                                embargo=dt.timedelta(days=1))


class TestWalkForward:
    def test_folds_deterministic_and_disjoint(self):
        folds1 = walk_forward_splits(
            d(0), d(300), n_folds=4,
            train_fraction=Decimal("0.5"),
            embargo=dt.timedelta(days=3))
        folds2 = walk_forward_splits(
            d(0), d(300), n_folds=4,
            train_fraction=Decimal("0.5"),
            embargo=dt.timedelta(days=3))
        assert folds1 == folds2
        oos_windows = [(o.start, o.end) for _, o in folds1]
        for (s1, e1), (s2, e2) in zip(oos_windows, oos_windows[1:]):
            assert e1 <= s2  # strictly non-overlapping, chronological
        for train, oos in folds1:
            assert train.end <= oos.start  # embargo gap respected
            assert train.role == CohortRole.TRAIN
            assert oos.role == CohortRole.HIST_OOS

    def test_embargo_leaves_gap_between_train_and_oos(self):
        folds = walk_forward_splits(
            d(0), d(300), n_folds=3, train_fraction=Decimal("0.6"),
            embargo=dt.timedelta(days=7))
        for train, oos in folds:
            assert (oos.start - train.end).days >= 7

    def test_two_folds_minimum(self):
        with pytest.raises(CohortError, match=">= 2"):
            walk_forward_splits(d(0), d(100), n_folds=1,
                                train_fraction=Decimal("0.5"),
                                embargo=dt.timedelta(days=1))

    def test_bad_fraction_rejected(self):
        for bad in (Decimal("0"), Decimal("1"), Decimal("1.5")):
            with pytest.raises(CohortError, match="train_fraction"):
                walk_forward_splits(d(0), d(100), n_folds=2,
                                    train_fraction=bad,
                                    embargo=dt.timedelta(days=1))

    def test_no_future_leakage_fold_wise(self):
        """Every fold's train window ends before its OOS begins; labels are
        purged so no training label reaches into the OOS window."""
        folds = walk_forward_splits(
            d(0), d(200), n_folds=3, train_fraction=Decimal("0.5"),
            embargo=dt.timedelta(days=2))
        for train, oos in folds:
            for (a, _b) in train.label_intervals:
                assert a + dt.timedelta(days=1) <= train.end


class TestForwardCohorts:
    def test_prediction_must_precede_observation(self):
        with pytest.raises(CohortError, match="BEFORE"):
            ForwardCohort("fc1", prediction_locked_at=d(10),
                          observation_available_at=d(5))

    def test_score_before_observation_forbidden(self):
        fc = ForwardCohort("fc1", prediction_locked_at=d(5),
                           observation_available_at=d(10))
        with pytest.raises(CohortError, match="not available"):
            fc.score(now=d(9))
        assert fc.polluted_for_future_selection is False

    def test_score_after_observation_pollutes_once(self):
        fc = ForwardCohort("fc1", prediction_locked_at=d(5),
                           observation_available_at=d(10))
        assert fc.score(now=d(11)) == "SCORED"
        assert fc.polluted_for_future_selection is True
        with pytest.raises(CohortError, match="re-used"):
            fc.score(now=d(12))

    def test_naive_timestamp_rejected(self):
        with pytest.raises(CohortError):
            ForwardCohort("fc", dt.datetime(2026, 1, 1), d(10))
