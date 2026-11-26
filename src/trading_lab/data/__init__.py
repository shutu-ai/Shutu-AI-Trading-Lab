"""M1 formal data layer: calendar, corporate-action recomputation, historical
membership/delisting, quality reports with explicit denominators,
deterministic snapshot manifests, and purpose-based acceptance.

Boundaries (enforced by scripts/check_architecture.py): this package must
not import trading_lab.oms/brokers/risk/strategies/research or anything
under artifacts/poc — the data plane never touches the trading plane.
"""

from .acceptance import (
    AcceptanceDecision,
    DataAcceptanceConfig,
    DataAcceptanceConfigError,
    PurposeRequirements,
    VendorFacts,
    VendorFactsError,
    evaluate_purpose,
    load_acceptance_config,
)
from .actions import (
    ADJUST_TRANSFORM_VERSION,
    ActionError,
    ActionRecord,
    AdjustmentResult,
    adjust_series,
)
from .calendar import (
    CalendarError,
    ET,
    MarketCalendar,
    SessionInfo,
    UTC,
)
from .historical import (
    HistoricalAcceptanceDecision,
    HistoricalBarRecord,
    HistoricalDataError,
    HistoricalSnapshotBuild,
    PIT_ASSUMED_NOT_VERIFIED,
    PURPOSE_ROW_PENDING_CALENDAR_FREEZE,
    build_historical_snapshot,
    calendar_deadline_violations,
    derive_max_latency_seconds,
    evaluate_historical_research,
    pit_level_of_manifest,
    write_historical_namespace,
)
from .historical_calendar import CalendarSupply, VersionedMarketCalendar
from .membership import (
    DelistingRecord,
    MembershipError,
    MembershipRecord,
    MembershipTable,
)
from .quality import (
    LatencyStats,
    MetricResult,
    QualityReport,
    bar_completeness,
    count_duplicate_or_out_of_order,
    field_coverage_metrics,
    latency_stats,
)
from .records import MARKER_UNKNOWN_AVAILABILITY, SourceRecord
from .snapshot import (
    DatasetEntry,
    SnapshotError,
    SnapshotManifest,
    build_snapshot,
    content_hash_of_rows,
)

__all__ = [
    "ADJUST_TRANSFORM_VERSION",
    "AcceptanceDecision",
    "ActionError",
    "ActionRecord",
    "AdjustmentResult",
    "CalendarError",
    "DataAcceptanceConfig",
    "DataAcceptanceConfigError",
    "DatasetEntry",
    "DelistingRecord",
    "ET",
    "LatencyStats",
    "MARKER_UNKNOWN_AVAILABILITY",
    "MarketCalendar",
    "HistoricalAcceptanceDecision",
    "HistoricalBarRecord",
    "HistoricalDataError",
    "HistoricalSnapshotBuild",
    "PIT_ASSUMED_NOT_VERIFIED",
    "PURPOSE_ROW_PENDING_CALENDAR_FREEZE",
    "CalendarSupply",
    "VersionedMarketCalendar",
    "build_historical_snapshot",
    "calendar_deadline_violations",
    "derive_max_latency_seconds",
    "evaluate_historical_research",
    "pit_level_of_manifest",
    "write_historical_namespace",
    "MembershipError",
    "MembershipRecord",
    "MembershipTable",
    "MetricResult",
    "PurposeRequirements",
    "QualityReport",
    "SessionInfo",
    "SnapshotError",
    "SnapshotManifest",
    "SourceRecord",
    "UTC",
    "VendorFacts",
    "VendorFactsError",
    "adjust_series",
    "bar_completeness",
    "build_snapshot",
    "content_hash_of_rows",
    "count_duplicate_or_out_of_order",
    "evaluate_purpose",
    "field_coverage_metrics",
    "latency_stats",
    "load_acceptance_config",
]
