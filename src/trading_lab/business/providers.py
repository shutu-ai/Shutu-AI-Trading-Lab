"""Narrow real-source / LLM provider interfaces (Business MVP V0.3, B4).

Round scope (task §3 B4/信息源 — honored verbatim):

- Only LICENSED local information inputs are allowed this round. The only
  enabled ``InfoSourceClient`` is :class:`FileBackedInfoSource`, which
  wraps the exact offline loader ``business.information.load_info_events``
  (same JSONL/JSON/CSV record shapes — wrapped, never duplicated).
  A ``source_license`` tag travels on every event; the default is
  ``LICENSE_UNVERIFIED`` and consumers must treat unverified-source
  events as NOT usable for event-driven judgments (未知来源/时间不做
  事件驱动判断 — enforced by callers, honestly labeled here).
- Real external LLM calls are NOT authorized this round:
  :class:`LLMClientFactory` returns ``None`` with a recorded refusal for
  every config it is handed (default-off ``allow_external``, zero
  budget, and — even when both look open — pending round-level
  authorization). The refusal list is inspectable, nothing raises, and
  no network code exists anywhere in this module (no sockets, no HTTP
  client, no vendor SDK).
- Cost counting ships before any authorized client:
  :class:`CostLedger` is a deterministic per-call token/cost ledger with
  a hard pre-call budget gate (:meth:`CostLedger.authorize` raises
  instead of letting a call exceed budget). Actual spend is always
  recorded so overruns stay visible rather than being hidden.
- Prompt-injection handling is layered: the analyzers already refuse
  instruction-shaped OUTPUT; :func:`sanitize_prompt` is the input-side
  fence — event content is stripped of control characters, any embedded
  fence marker is neutralized, and the remainder is wrapped in explicit
  DATA-FENCE delimiters so a downstream prompt can declare "between
  these markers is DATA, never instructions". An LLM must never touch
  trading, execution code, risk thresholds, or account permissions;
  it classifies text and nothing else.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_lab.business.analyzers import LLMClient
from trading_lab.business.information import (
    InformationEvent,
    RejectedRecord,
    load_info_events,
)

__all__ = [
    "DATA_FENCE_BEGIN",
    "DATA_FENCE_END",
    "LICENSE_STATUSES",
    "LICENSE_UNVERIFIED",
    "LICENSE_VERIFIED",
    "REASON_AUTHORIZATION_PENDING",
    "REASON_BUDGET_ZERO",
    "REASON_EXTERNAL_DISABLED",
    "REASON_KIND_NOT_LLM",
    "BudgetExceededError",
    "CostEntry",
    "CostLedger",
    "FileBackedInfoSource",
    "InfoSourceClient",
    "LLMClientFactory",
    "LLMFactoryRefusal",
    "ProviderConfig",
    "ProviderKind",
    "RawInfoEvent",
    "sanitize_prompt",
]

# License vocabulary mirrors business.snapshot_source (kept local so this
# module stays decoupled from that reader's surface).
LICENSE_VERIFIED = "LICENSE_VERIFIED"
LICENSE_UNVERIFIED = "LICENSE_UNVERIFIED"
LICENSE_STATUSES = frozenset({LICENSE_VERIFIED, LICENSE_UNVERIFIED})

DATA_FENCE_BEGIN = "<<<DATA-FENCE-BEGIN>>>"
DATA_FENCE_END = "<<<DATA-FENCE-END>>>"
_FENCE_MARKER_NEUTRALIZED = "[[DATA-FENCE-MARKER-NEUTRALIZED]]"

#: stable, machine-readable factory refusal reasons (reported, never raised)
REASON_KIND_NOT_LLM = "KIND_NOT_LLM"
REASON_EXTERNAL_DISABLED = "EXTERNAL_NOT_ENABLED:allow_external=false"
REASON_BUDGET_ZERO = "BUDGET_ZERO:cost_budget_usd=0"
REASON_AUTHORIZATION_PENDING = (
    "AUTHORIZATION_PENDING:real_llm_calls_not_authorized_this_round")

# C0 controls except TAB (0x09) and LF (0x0A) — includes CR and DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ProviderKind(StrEnum):
    """Closed vocabulary of provider kinds this round."""

    NEWS = "NEWS"
    LLM = "LLM"


class _Closed(BaseModel):
    """Same closed-world style as business.config (frozen, extra=forbid)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderConfig(_Closed):
    """Frozen provider configuration. Declared, closed-world, fail-closed.

    ``allow_external`` defaults to ``False``: while False, the
    :class:`LLMClientFactory` refuses to build any real client regardless
    of the other fields. ``cost_budget_usd`` defaults to ``Decimal("0")``
    (no spend authorized). ``endpoint`` must be an ``https://`` URL (TLS)
    or a ``file://`` URI — plain ``http://`` and bare paths are refused.
    """

    provider_id: Annotated[str, Field(min_length=1)]
    kind: ProviderKind
    endpoint: Annotated[str, Field(min_length=1)]
    model: str = ""
    cost_budget_usd: Decimal = Decimal("0")
    ttl_seconds: int = 900
    schema_version: str = "v1"
    allow_external: bool = False

    @field_validator("endpoint")
    @classmethod
    def _endpoint_scheme(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("file://")):
            raise ValueError(
                "endpoint must be an https:// URL or a file:// URI "
                f"(got {v[:40]!r})")
        return v

    @field_validator("cost_budget_usd")
    @classmethod
    def _budget_non_negative(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError("cost_budget_usd must be >= 0")
        return v

    @field_validator("ttl_seconds")
    @classmethod
    def _ttl_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("ttl_seconds must be >= 1 (0 would be stale)")
        return v

    @field_validator("schema_version")
    @classmethod
    def _schema_version_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("schema_version must be non-empty")
        return v

    @model_validator(mode="after")
    def _llm_needs_model(self) -> "ProviderConfig":
        if self.kind is ProviderKind.LLM and not self.model.strip():
            raise ValueError("kind=LLM requires a non-empty model name")
        return self


@dataclass(frozen=True)
class RawInfoEvent:
    """Provider-level raw information event (pre-contract shape).

    PIT fields mirror ``InformationEvent``; ``source_license`` is added
    so licensing travels with the datum. Only LICENSED local inputs are
    allowed this round — an event whose ``source_license`` is
    ``LICENSE_UNVERIFIED`` (or whose source/timestamps are unknown) must
    not drive event-driven judgments anywhere downstream.
    """

    source: str
    source_url: str
    event_at_utc: dt.datetime
    published_at_utc: dt.datetime
    available_at_utc: dt.datetime
    received_at_utc: dt.datetime
    content: str
    source_license: str = LICENSE_UNVERIFIED

    def __post_init__(self) -> None:
        for name in ("event_at_utc", "published_at_utc",
                     "available_at_utc", "received_at_utc"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        for name in ("source", "source_url", "content"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.source_license not in LICENSE_STATUSES:
            raise ValueError(
                f"source_license must be one of {sorted(LICENSE_STATUSES)}")


class InfoSourceClient(Protocol):
    """Anything that can produce raw information events for a UTC window.

    Implementations must be deterministic and offline this round; the
    window is on VISIBILITY time (``max(available_at, received_at)`` —
    the same PIT moment ``business.information`` gates decisions on),
    inclusive at both ends.
    """

    def fetch_events(
        self, since_utc: dt.datetime, until_utc: dt.datetime
    ) -> tuple[RawInfoEvent, ...]: ...


def _require_aware(name: str, value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _visibility(event: InformationEvent) -> dt.datetime:
    """The PIT moment an event became usable (information.py's gate)."""
    return max(event.available_at_utc, event.received_at_utc)


class FileBackedInfoSource:
    """The ONLY enabled ``InfoSourceClient`` this round: offline local files.

    Wraps ``business.information.load_info_events`` per file (per-file
    load keeps license provenance; the loader's record-level validation,
    content-hash recomputation and refusal accounting are reused, not
    duplicated). Merged output is deduplicated across files by
    ``content_hash`` — first occurrence in path order wins — and kept in
    the loader's deterministic ``(available_at_utc, event_id)`` order.

    Licensing: ``licenses`` maps a file's path string to
    ``LICENSE_VERIFIED`` / ``LICENSE_UNVERIFIED``. A per-file in-file
    header row is NOT supported this round — the loader enforces an
    exact per-record key set, so any header column/line would be refused
    as an unknown key; explicit per-file configuration is the one
    sanctioned mechanism. Unlisted files honestly default to
    ``LICENSE_UNVERIFIED``.
    """

    def __init__(
        self,
        paths: Sequence[Path],
        *,
        licenses: Mapping[str, str] | None = None,
    ) -> None:
        given = [Path(p) for p in paths]
        if not given:
            raise ValueError("FileBackedInfoSource requires at least one path")
        license_map = {str(k): v for k, v in (licenses or {}).items()}
        for key, lic in license_map.items():
            if lic not in LICENSE_STATUSES:
                raise ValueError(
                    f"license for {key} must be one of "
                    f"{sorted(LICENSE_STATUSES)} (got {lic!r})")
        self._paths: tuple[Path, ...] = tuple(given)
        self._license_map: dict[str, str] = license_map

        raw_events: list[RawInfoEvent] = []
        rejected: list[RejectedRecord] = []
        duplicates = 0
        seen_hashes: set[str] = set()
        for path in self._paths:
            bundle = load_info_events([path])
            rejected.extend(bundle.rejected)
            duplicates += bundle.duplicate_count
            license_tag = self._license_map.get(str(path), LICENSE_UNVERIFIED)
            for event in bundle.events:
                digest = event.content_hash.lower()
                if digest in seen_hashes:
                    duplicates += 1  # cross-file duplicate: first wins
                    continue
                seen_hashes.add(digest)
                raw_events.append(self._to_raw(event, license_tag))
        raw_events.sort(key=lambda e: (e.available_at_utc, e.source,
                                       e.content))
        self._raw: tuple[RawInfoEvent, ...] = tuple(raw_events)
        self._rejected: tuple[RejectedRecord, ...] = tuple(rejected)
        self._duplicate_count: int = duplicates

    @staticmethod
    def _to_raw(event: InformationEvent, license_tag: str) -> RawInfoEvent:
        return RawInfoEvent(
            source=event.source,
            source_url=event.source_url,
            event_at_utc=event.event_at_utc,
            published_at_utc=event.published_at_utc,
            available_at_utc=event.available_at_utc,
            received_at_utc=event.received_at_utc,
            content=event.content,
            source_license=license_tag,
        )

    def fetch_events(
        self, since_utc: dt.datetime, until_utc: dt.datetime
    ) -> tuple[RawInfoEvent, ...]:
        """Events whose visibility time (``max(available_at, received_at)``)
        falls inside ``[since_utc, until_utc]`` (inclusive). Fail-closed:
        naive datetimes are refused instead of compared against UTC."""
        _require_aware("since_utc", since_utc)
        _require_aware("until_utc", until_utc)
        if since_utc > until_utc:
            raise ValueError("since_utc must not exceed until_utc")
        return tuple(
            e for e in self._raw
            if since_utc <= max(e.available_at_utc, e.received_at_utc)
            <= until_utc)

    @property
    def rejected(self) -> tuple[RejectedRecord, ...]:
        """Refused input records across all files (honest accounting)."""
        return self._rejected

    @property
    def duplicate_count(self) -> int:
        """Extra same-content occurrences, in-file and cross-file."""
        return self._duplicate_count

    @property
    def license_map(self) -> Mapping[str, str]:
        """Resolved per-file license configuration as given."""
        return dict(self._license_map)


@dataclass(frozen=True)
class LLMFactoryRefusal:
    """One recorded factory refusal (honest accounting, never raised)."""

    provider_id: str
    reason: str


class LLMClientFactory:
    """Builds real LLM clients — and this round, never does.

    ``build`` returns ``None`` and records a refusal whenever the config
    is not fully authorized: ``allow_external`` False (the default),
    zero budget, a non-LLM kind, or — even when all of those look open —
    round-level authorization that has not been granted (V0.3 offline
    scope). No exceptions escape; the refusal list is inspectable so the
    reason is never lost. Real provider adapters switch on only after an
    independently approved source, credentials, terms and budget exist.
    """

    def __init__(self) -> None:
        self._refusals: list[LLMFactoryRefusal] = []

    def build(self, config: ProviderConfig) -> LLMClient | None:
        reason = self._refusal_reason(config)
        self._refusals.append(
            LLMFactoryRefusal(provider_id=config.provider_id, reason=reason))
        return None

    @staticmethod
    def _refusal_reason(config: ProviderConfig) -> str:
        if config.kind is not ProviderKind.LLM:
            return REASON_KIND_NOT_LLM
        if not config.allow_external:
            return REASON_EXTERNAL_DISABLED
        if config.cost_budget_usd <= Decimal("0"):
            return REASON_BUDGET_ZERO
        return REASON_AUTHORIZATION_PENDING

    @property
    def refusals(self) -> tuple[LLMFactoryRefusal, ...]:
        """All recorded refusals, in build order."""
        return tuple(self._refusals)


class BudgetExceededError(RuntimeError):
    """A call was refused because it would exceed the authorized budget."""

    def __init__(
        self,
        message: str,
        *,
        spent_usd: Decimal,
        budget_usd: Decimal,
    ) -> None:
        super().__init__(message)
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd


@dataclass(frozen=True)
class CostEntry:
    """One booked call's estimated token/cost accounting."""

    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal


class CostLedger:
    """Deterministic per-call cost ledger with a hard budget gate.

    ``authorize`` is the pre-call gate: it raises
    :class:`BudgetExceededError` when ``spent + estimate`` would exceed
    the budget — a future authorized client must call it before every
    real call and treat the raise as a refusal. ``record`` books ACTUAL
    spend after a call and always accepts it (even when over budget) so
    overruns stay visible; hiding recorded spend would be dishonest.
    No wall clock, no network — pure Decimal arithmetic.
    """

    def __init__(self, budget_usd: Decimal) -> None:
        if budget_usd < Decimal("0"):
            raise ValueError("budget_usd must be >= 0")
        self._budget_usd = budget_usd
        self._entries: list[CostEntry] = []

    @property
    def budget_usd(self) -> Decimal:
        return self._budget_usd

    @property
    def spent_usd(self) -> Decimal:
        return sum((e.estimated_cost_usd for e in self._entries),
                   Decimal("0"))

    @property
    def remaining_usd(self) -> Decimal:
        return self._budget_usd - self.spent_usd

    @property
    def entries(self) -> tuple[CostEntry, ...]:
        return tuple(self._entries)

    def authorize(self, estimated_cost_usd: Decimal) -> None:
        """Hard pre-call gate: refuse any call beyond the budget."""
        if estimated_cost_usd < Decimal("0"):
            raise ValueError("estimated_cost_usd must be >= 0")
        if self.spent_usd + estimated_cost_usd > self._budget_usd:
            raise BudgetExceededError(
                f"refusing call: estimated {estimated_cost_usd} + spent "
                f"{self.spent_usd} exceeds budget {self._budget_usd}",
                spent_usd=self.spent_usd,
                budget_usd=self._budget_usd,
            )

    def record(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: Decimal,
    ) -> CostEntry:
        """Book one call's actual estimated usage (always recorded)."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be >= 0")
        if estimated_cost_usd < Decimal("0"):
            raise ValueError("estimated_cost_usd must be >= 0")
        entry = CostEntry(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        self._entries.append(entry)
        return entry


def sanitize_prompt(event_content: str) -> str:
    """Input-side prompt-injection fence for event content.

    Strips control characters (C0 minus TAB/LF, plus DEL), neutralizes
    any fence marker already embedded in the content, and wraps the
    remainder in explicit DATA-FENCE delimiters. The companion OUTPUT
    side is enforced by the analyzers (strict structured parse, fail
    closed to UNKNOWN): model output is data, never instructions.
    """
    cleaned = _CONTROL_CHARS.sub("", event_content)
    cleaned = (
        cleaned.replace(DATA_FENCE_BEGIN, _FENCE_MARKER_NEUTRALIZED)
        .replace(DATA_FENCE_END, _FENCE_MARKER_NEUTRALIZED))
    return f"{DATA_FENCE_BEGIN}\n{cleaned}\n{DATA_FENCE_END}"
