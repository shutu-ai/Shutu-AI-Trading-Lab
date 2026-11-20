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
