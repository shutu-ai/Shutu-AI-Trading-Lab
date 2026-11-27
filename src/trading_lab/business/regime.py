"""Rule-based market regime classifier (Business MVP V0.1, MOCK_ONLY).

Transparent fixed rules only: no HMM/RL, no fitting, no AI-generated
labels. Every threshold comes from ``RegimeConfig`` — a FIXED prior
declared before execution (AGENTS.md #8) — never fitted on replay
outcomes, never claiming anything about real markets.

Label vocabulary (multi-label tuple; dimensions coexist):

- ``TREND_UP`` / ``TREND_DOWN`` / ``RANGE`` — from the primary symbol's
  ``ma_short`` vs ``ma_long`` vs ``regime.trend_band_pct``. Exactly one
  of the three is always present when the primary features are usable.
- ``HIGH_VOL`` — primary ``realized_vol`` strictly above the fixed
  nearest-rank percentile (``high_vol_percentile``) of the trailing
  ``vol_history`` (last ``high_vol_lookback`` values), only when
  ``len(vol_history) >= min_history_for_vol_percentile``; otherwise the
  label is silently absent (no error — honest insufficiency).
- ``EVENT_ACTIVE`` — any usable information assessment with status
  ``ASSESSED``, direction != ``UNKNOWN``, horizon ``SHORT`` and
  confidence >= ``regime.confidence_floor``.
- ``UNKNOWN`` — the primary feature vector is missing or unusable:
  labels become ``("UNKNOWN",)`` with confidence 0.0 (fail-safe).

The primary symbol is the documented constant ``PRIMARY_SYMBOL = "SPY"``:
the V0.1 demo universe is SPY/QQQ/CASH and SPY is the routing primary.

Two entry points, both deterministic:

- :class:`RuleRegimeClassifier` — pure, stateless ``classify``. The
  ``previous`` argument is accepted for call-site symmetry with the
  replay loop signature and is intentionally NOT used by the pure
  function (hysteresis lives in the session wrapper below).
- :class:`RegimeClassifierSession` — stateful wrapper called once per
  session by the replay loop. It applies ``hysteresis_sessions``: a
  label change versus the committed regime must persist that many
  consecutive classifications before taking effect. Data loss (a raw
  ``UNKNOWN`` result) bypasses hysteresis and commits immediately.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_CEILING, Decimal
from typing import Mapping, Protocol, Sequence

from trading_lab.business.config import RegimeConfig
from trading_lab.business.types import STATUS_OK, FeatureVector
from trading_lab.contracts.events import RegimeAssessment
from trading_lab.security.canonical import canonical_digest

__all__ = [
    "PRIMARY_SYMBOL",
    "MODEL_VERSION",
    "CONFIDENCE_CAP",
    "LABEL_TREND_UP",
    "LABEL_TREND_DOWN",
    "LABEL_RANGE",
    "LABEL_HIGH_VOL",
    "LABEL_EVENT_ACTIVE",
    "LABEL_UNKNOWN",
    "InformationAssessmentView",
    "RuleRegimeClassifier",
    "RegimeClassifierSession",
]

PRIMARY_SYMBOL = "SPY"
MODEL_VERSION = "RULE-REGIME-V1"

# Fixed cap on the confidence formula output (declared prior, not fitted).
CONFIDENCE_CAP = Decimal("0.90")

LABEL_TREND_UP = "TREND_UP"
LABEL_TREND_DOWN = "TREND_DOWN"
LABEL_RANGE = "RANGE"
LABEL_HIGH_VOL = "HIGH_VOL"
LABEL_EVENT_ACTIVE = "EVENT_ACTIVE"
LABEL_UNKNOWN = "UNKNOWN"

# Information-plane status / direction / horizon string values consumed
# by the EVENT_ACTIVE rule (structural view; the authoritative enums
# live in the information plane, another workstream).
INFO_STATUS_ASSESSED = "ASSESSED"
INFO_DIRECTION_UNKNOWN = "UNKNOWN"
INFO_HORIZON_SHORT = "SHORT"

_REASON_UNUSABLE = "PRIMARY_FEATURES_UNUSABLE"


class InformationAssessmentView(Protocol):
    """Structural view of the information plane's assessment objects.

    The information plane (another workstream) owns the authoritative
    frozen dataclass; regime/strategies/router consume only this shape
    and never import that module.
    """

    @property
    def status(self) -> str: ...

    @property
    def direction(self) -> str: ...

    @property
    def confidence(self) -> float: ...

    @property
    def horizon(self) -> str: ...

    @property
    def assessment_id(self) -> str: ...

    @property
    def valid_until(self) -> dt.datetime: ...


class RuleRegimeClassifier:
    """Pure, stateless fixed-rule classifier producing ``RegimeAssessment``."""

    def __init__(self, config: RegimeConfig) -> None:
        self._config = config

    @property
    def config(self) -> RegimeConfig:
        return self._config

    def classify(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        info_assessments: Sequence[InformationAssessmentView],
        previous: RegimeAssessment | None,
        vol_history: Sequence[Decimal],
        valid_until: dt.datetime,
    ) -> RegimeAssessment:
        """Classify one session. ``previous`` is accepted for signature
        symmetry with the replay loop and intentionally unused (the pure
        classification is previous-independent; hysteresis belongs to
        :class:`RegimeClassifierSession`). Deterministic in all inputs."""
        fv = features.get(PRIMARY_SYMBOL)
        if not self._primary_usable(fv):
            reasons = (_REASON_UNUSABLE,) + (fv.reasons if fv is not None else ())
            return RegimeAssessment(
                labels=(LABEL_UNKNOWN,),
                confidence=0.0,
                asof_utc=asof_utc,
                model_version=MODEL_VERSION,
                feature_hash=canonical_digest({"reasons": list(reasons)}),
                valid_until=valid_until,
            )
        assert fv is not None  # narrowed by _primary_usable
        trend = self._trend_label(fv)
        labels: list[str] = [trend]
        if self._high_vol_active(fv, vol_history):
            labels.append(LABEL_HIGH_VOL)
        if self._event_active(info_assessments):
            labels.append(LABEL_EVENT_ACTIVE)
        return RegimeAssessment(
            labels=tuple(labels),
            confidence=float(self._confidence(fv, trend)),
            asof_utc=asof_utc,
            model_version=MODEL_VERSION,
            feature_hash=self._feature_hash(fv),
            valid_until=valid_until,
        )

    # -- rule components ---------------------------------------------------

    @staticmethod
    def _primary_usable(fv: FeatureVector | None) -> bool:
        if fv is None or fv.status != STATUS_OK:
            return False
        return fv.ma_short is not None and fv.ma_long is not None and fv.ma_long != 0

    def _trend_label(self, fv: FeatureVector) -> str:
        assert fv.ma_short is not None and fv.ma_long is not None
        spread = (fv.ma_short - fv.ma_long) / fv.ma_long
        band = self._config.trend_band_pct
        if abs(spread) <= band:
            return LABEL_RANGE
        return LABEL_TREND_UP if spread > 0 else LABEL_TREND_DOWN

    def _trend_spread(self, fv: FeatureVector) -> Decimal:
        assert fv.ma_short is not None and fv.ma_long is not None
        return (fv.ma_short - fv.ma_long) / fv.ma_long

    def _high_vol_active(self, fv: FeatureVector, vol_history: Sequence[Decimal]) -> bool:
        if fv.realized_vol is None:
            return False
        usable = [v for v in vol_history if v is not None]
        if len(usable) < self._config.min_history_for_vol_percentile:
            return False  # honest insufficiency: no label, no error
        lookback = self._config.high_vol_lookback
        if lookback <= 0:
            return False
        window = usable[-lookback:]
        threshold = self._percentile(window, self._config.high_vol_percentile)
        return fv.realized_vol > threshold

    @staticmethod
    def _percentile(values: Sequence[Decimal], pct: Decimal) -> Decimal:
        """Nearest-rank percentile (fixed, deterministic): sorted ascending,
        rank = ceil(pct * n), threshold = sorted[rank - 1]. Strictly above
        the threshold activates the label; equality does not."""
        ordered = sorted(values)
        n = len(ordered)
        rank = int((pct * Decimal(n)).to_integral_value(rounding=ROUND_CEILING))
        rank = max(1, min(n, rank))
        return ordered[rank - 1]

    def _event_active(self, info_assessments: Sequence[InformationAssessmentView]) -> bool:
        floor = self._config.confidence_floor
        for a in info_assessments:
            if a.status != INFO_STATUS_ASSESSED:
                continue
            if a.direction == INFO_DIRECTION_UNKNOWN:
                continue
            if a.horizon != INFO_HORIZON_SHORT:
                continue
            if Decimal(str(a.confidence)) >= floor:
                return True
        return False

    def _confidence(self, fv: FeatureVector, trend_label: str) -> Decimal:
        """confidence_base + strength_gain * min(1, |ma_spread|/band),
        capped at CONFIDENCE_CAP; 0.0 for the UNKNOWN fail-safe branch
        (handled by the caller). Deterministic Decimal math throughout."""
        if trend_label == LABEL_UNKNOWN:
            return Decimal(0)
        spread = self._trend_spread(fv)
        band = self._config.trend_band_pct
        if band <= 0:
            strength = Decimal(0) if spread == 0 else Decimal(1)
        else:
            strength = min(Decimal(1), abs(spread) / band)
        conf = self._config.confidence_base + self._config.confidence_strength_gain * strength
        return min(CONFIDENCE_CAP, conf)

    @staticmethod
    def _feature_hash(fv: FeatureVector) -> str:
        if len(fv.feature_hash) >= 16:
            return fv.feature_hash
        # Declared fallback so the contract is always constructible from
        # an honest fixture that carries no feature plane hash.
        return canonical_digest(
            {
                "symbol": fv.symbol,
                "ma_short": str(fv.ma_short),
                "ma_long": str(fv.ma_long),
                "rsi": str(fv.rsi),
                "realized_vol": str(fv.realized_vol),
                "asof_bar_ts": None if fv.asof_bar_ts is None else fv.asof_bar_ts.isoformat(),
            }
        )


class RegimeClassifierSession:
    """Stateful per-session wrapper applying label hysteresis.

    The replay loop calls :meth:`step` exactly once per session. The full
    sorted label tuple is the unit of change: a candidate regime that
    differs from the committed one must be observed on
    ``hysteresis_sessions`` consecutive classifications before it
    commits. A raw ``UNKNOWN`` (data loss) commits immediately, bypassing
    hysteresis, and resets any pending counter. Leaving ``UNKNOWN``
    again requires a sustained (non-fluttering) change, like any other
    transition. Both this wrapper and the underlying pure classifier are
    deterministic.
    """

    def __init__(self, classifier: RuleRegimeClassifier) -> None:
        self._classifier = classifier
        self._committed: RegimeAssessment | None = None
        self._pending_labels: tuple[str, ...] | None = None
        self._pending_count = 0

    @property
    def committed_labels(self) -> tuple[str, ...] | None:
        return None if self._committed is None else self._committed.labels

    @property
    def pending_count(self) -> int:
        return self._pending_count

    def step(
        self,
        asof_utc: dt.datetime,
        features: Mapping[str, FeatureVector],
        info_assessments: Sequence[InformationAssessmentView],
        vol_history: Sequence[Decimal],
        valid_until: dt.datetime,
    ) -> RegimeAssessment:
        raw = self._classifier.classify(
            asof_utc, features, info_assessments, self._committed, vol_history, valid_until
        )
        if raw.labels == (LABEL_UNKNOWN,):
            # Data loss: fail-safe applies immediately, no hysteresis.
            self._commit(raw)
            return raw
        if self._committed is None:
            # First observation: there is no prior regime to protect.
            self._commit(raw)
            return raw
        if raw.labels == self._committed.labels:
            self._pending_labels, self._pending_count = None, 0
            self._committed = raw
            return raw
        if raw.labels == self._pending_labels:
            self._pending_count += 1
        else:
            self._pending_labels, self._pending_count = raw.labels, 1
        if self._pending_count >= self._hysteresis_sessions():
            self._commit(raw)
            return raw
        return self._hold(raw)

    # -- internals ---------------------------------------------------------

    def _hysteresis_sessions(self) -> int:
        return max(1, self._classifier.config.hysteresis_sessions)

    def _commit(self, raw: RegimeAssessment) -> None:
        self._committed = raw
        self._pending_labels, self._pending_count = None, 0

    def _hold(self, raw: RegimeAssessment) -> RegimeAssessment:
        """Keep the committed labels + confidence, refresh the session
        timestamps and the current input hash so the audit trail reflects
        this session's data. Deterministic."""
        assert self._committed is not None
        held = RegimeAssessment(
            labels=self._committed.labels,
            confidence=self._committed.confidence,
            asof_utc=raw.asof_utc,
            model_version=MODEL_VERSION,
            feature_hash=raw.feature_hash,
            valid_until=raw.valid_until,
        )
        self._committed = held
        return held
