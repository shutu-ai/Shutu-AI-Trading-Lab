"""Unified market-data views for the replay pipeline (V0.2 B1).

Both the synthetic demo fixture and a collected historical snapshot are
presented to the replay loop through the SAME ``MarketDataView``: the
downstream feature/regime/strategy/decision/execution pipeline is
source-agnostic and is never duplicated. A snapshot bundle carries its
admission truth (license / PIT / release status) with it; an
exploratory-only snapshot is usable for OFFLINE INTEGRATION runs but is
never silently treated as research-admitted, and the label travels into
every report and snapshot provider.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping, Sequence

from trading_lab.business.fixtures import build_demo_dataset
from trading_lab.business.fixtures import DemoDataset
from trading_lab.business.snapshot_source import load_historical_snapshot
from trading_lab.business.snapshot_source import SnapshotBundle
from trading_lab.business.series import SeriesStore
from trading_lab.security.canonical import canonical_digest

__all__ = ["MarketDataView", "build_demo_view", "build_snapshot_view"]

NextOpenFn = Callable[[str, dt.date], Decimal | None]


@dataclass(frozen=True)
class MarketDataView:
    """One replay's market data, whatever its origin."""

    stores: Mapping[str, SeriesStore]
    bars: Mapping[str, Sequence[object]]   # per-symbol MarketBar sequences
    session_dates: tuple[dt.date, ...]
    dataset_hash: str
    next_open_price: NextOpenFn
    scenario_tags: Mapping[str, str]
    data_quality: str                      # snapshot-provider label
    source_mode: str                       # "demo" | "historical"
    admission: Mapping[str, object] = field(default_factory=dict)
    # demo-only extras (absent on historical views)
    demo: DemoDataset | None = None

    @property
    def research_admitted(self) -> bool:
        return bool(self.admission.get("research_admitted", False))

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(self.admission.get("blockers", ()))


def build_demo_view(config) -> MarketDataView:
    """The V0.1 synthetic demo fixture as a view."""
    demo = build_demo_dataset(config)
    store = SeriesStore.from_dataset(demo.dataset)
    return MarketDataView(
        stores={"SPY": store, "QQQ": store},
        bars=dict(demo.dataset.bars),
        session_dates=demo.session_dates,
        dataset_hash=demo.dataset.dataset_hash,
        next_open_price=demo.next_open_price,
        scenario_tags=dict(demo.scenario_tags),
        data_quality="SYNTHETIC_OFFLINE_DEMO",
        source_mode="demo",
        admission={"research_admitted": False,
                   "blockers": ("SYNTHETIC_FIXTURE",)},
        demo=demo,
    )


def build_snapshot_view(snapshot_dir: Path) -> MarketDataView:
    """A collected historical snapshot as a view (V0.2 B1)."""
    bundle: SnapshotBundle = load_historical_snapshot(snapshot_dir)
    admission = {
        "research_admitted": bundle.research_admitted,
        "blockers": bundle.blockers,
        "manifest": dict(bundle.manifest_summary),
    }
    return MarketDataView(
        stores=dict(bundle.stores),
        bars=dict(bundle.bars),
        session_dates=bundle.session_dates,
        dataset_hash=bundle.dataset_hash,
        next_open_price=bundle.next_open_price,
        scenario_tags=dict(bundle.scenario_tags),
        data_quality="HISTORICAL_RESEARCH_ADMITTED"
        if bundle.research_admitted else "HISTORICAL_EXPLORATORY",
        source_mode="historical",
        admission=admission,
        demo=None,
    )


def view_code_digest(view: MarketDataView) -> str:
    """Deterministic identity fragment for reports (not a research
    dataset hash — the view's dataset_hash is the authoritative one)."""
    return canonical_digest({
        "mode": view.source_mode,
        "dataset_hash": view.dataset_hash,
        "sessions": len(view.session_dates),
        "symbols": sorted(view.stores.keys()),
    })
