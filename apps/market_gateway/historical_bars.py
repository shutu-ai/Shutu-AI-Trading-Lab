"""Historical daily-bars client (H1A, M3-H workstream) — thin, read-only,
reuse-only.

NO new network code path: every byte flows through the existing
:class:`GuardedGetClient` (GET-only, https, host allowlist, path regex,
no redirects, no body, Decimal JSON). This module adds only the H1
business entry gate and the offline pagination loop:

- symbols ``SPY``/``QQQ`` only; ``feed=iex``; ``timeframe=1Day``;
  ``adjustment=raw`` — fixed constants, not parameters;
- request dates must sit inside the FROZEN license window (checked
  BEFORE any request — business rule, not a transport rule);
- request budget per execution window, hard-capped at the authorized
  30; the budget-exceeding request is never sent;
- ``next_page_token`` chaining with loop detection, symbol-echo
  contract, empty-page refusal, per-bar schema/price/ordering checks;
- an honest request audit (URLs + counts, never credential values).

Offline by construction: all of this runs against an injected fake
``opener`` with NO API keys present (tests pin it). When a real pilot
is separately authorized, the ONLY change is operator-injected
``APCA-*`` headers through the same guard — no new endpoints, no new
verbs, no trading hosts.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from trading_lab.data.calendar import ET

from .http_client import GuardedGetClient

__all__ = [
    "ADJUSTMENT",
    "AUTHORIZED_SYMBOLS",
    "DEFAULT_MAX_REQUESTS",
    "DEFAULT_PAGE_LIMIT",
    "FEED",
    "HISTORY_HOST",
    "HISTORY_PATH_PATTERN",
    "HistoricalBarsClient",
    "HistoricalFetchResult",
    "HistoricalRequestRefused",
    "HistoricalWindow",
    "TIMEFRAME",
]

HISTORY_HOST = "data.alpaca.markets"
AUTHORIZED_SYMBOLS = frozenset({"SPY", "QQQ"})
HISTORY_PATH_PATTERN = r"^/v2/stocks/(SPY|QQQ)/bars$"
FEED = "iex"
TIMEFRAME = "1Day"
ADJUSTMENT = "raw"
DEFAULT_MAX_REQUESTS = 30  # authorized budget (incl. probing + pagination)
DEFAULT_PAGE_LIMIT = 10000


class HistoricalRequestRefused(ValueError):
    """The H1 business entry gate refused the request before any byte
    was sent (or the vendor response violated the pinned contract)."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class HistoricalWindow:
    """The frozen license window: request dates outside it are refused
    at the business entry, before any request."""

    start: dt.date
    end: dt.date
    label: str = "unlabeled-window"

    def __post_init__(self) -> None:
        if not isinstance(self.start, dt.date) or not isinstance(self.end, dt.date):
            raise HistoricalRequestRefused("BAD_WINDOW", "start/end must be dates")
        if self.start > self.end:
            raise HistoricalRequestRefused("BAD_WINDOW", "inverted window")

    def contains(self, start: dt.date, end: dt.date) -> bool:
        return self.start <= start <= end and self.start <= end <= self.end


@dataclass(frozen=True)
class HistoricalFetchResult:
    """One symbol's validated historical daily bars plus the request
    audit (URLs + counts; credential values can never appear here)."""

    symbol: str
    start: dt.date
    end: dt.date
    rows: tuple[dict[str, Any], ...]
    pages: int
    request_count: int
    request_urls: tuple[str, ...]
    page_tokens_seen: tuple[str, ...]
    complete: bool


class HistoricalBarsClient:
    """Read-only historical daily bars over the guarded client."""

    def __init__(
        self,
        *,
        client: GuardedGetClient,
        window: HistoricalWindow,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        page_limit: int = DEFAULT_PAGE_LIMIT,
    ) -> None:
        if not isinstance(client, GuardedGetClient):
            raise HistoricalRequestRefused(
                "CONFIG", "historical client requires the guarded GET client"
            )
        if max_requests < 1 or max_requests > DEFAULT_MAX_REQUESTS:
            raise HistoricalRequestRefused(
                "CONFIG",
                f"request budget must be within the authorized cap "
                f"(1..{DEFAULT_MAX_REQUESTS}), got {max_requests}",
            )
        if page_limit < 1 or page_limit > DEFAULT_PAGE_LIMIT:
            raise HistoricalRequestRefused(
                "CONFIG", f"page limit must be 1..{DEFAULT_PAGE_LIMIT}, got {page_limit}"
            )
        if not isinstance(window, HistoricalWindow):
            raise HistoricalRequestRefused("CONFIG", "window must be a HistoricalWindow")
        self._client = client
        self._window = window
        self._max_requests = max_requests
        self._page_limit = page_limit
        self.request_count = 0  # shared across fetches: one execution window

    # -- business entry -------------------------------------------------------

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        start: dt.date,
        end: dt.date,
        received_at_utc: dt.datetime,
        headers: Mapping[str, str] | None = None,
    ) -> HistoricalFetchResult:
        """Fetch and validate one symbol's daily bars for ``[start, end]``.

        ``received_at_utc`` is recorded on the caller's side for
        provenance; the client itself needs no keys (offline runs pass
        ``headers=None``) and no credentials are ever logged."""
        del received_at_utc  # provenance belongs to the data-layer adapter
        if symbol not in AUTHORIZED_SYMBOLS:
            raise HistoricalRequestRefused(
                "SYMBOL_NOT_AUTHORIZED",
                f"{symbol!r} outside the authorized symbol set "
                f"{sorted(AUTHORIZED_SYMBOLS)}",
            )
        if not isinstance(start, dt.date) or not isinstance(end, dt.date):
            raise HistoricalRequestRefused("BAD_DATE_RANGE", "start/end must be dates")
        if start > end:
            raise HistoricalRequestRefused("BAD_DATE_RANGE", f"{start} > {end}")
        if not self._window.contains(start, end):
            raise HistoricalRequestRefused(
                "OUTSIDE_LICENSE_WINDOW",
                f"[{start.isoformat()}, {end.isoformat()}] outside the frozen "
                f"license window [{self._window.start.isoformat()}, "
                f"{self._window.end.isoformat()}] ({self._window.label})",
            )

        rows: list[dict[str, Any]] = []
        urls: list[str] = []
        tokens_seen: list[str] = []
        seen_tokens: set[str] = set()
        pages = 0
        token: str | None = None
        complete = False

        while not complete:
            if self.request_count >= self._max_requests:
                raise HistoricalRequestRefused(
                    "REQUEST_BUDGET_EXCEEDED",
                    f"{self.request_count} requests spent, authorized budget "
                    f"is {self._max_requests} — the next request was NOT sent",
                )
            params = {
                "adjustment": ADJUSTMENT,
                "end": end.isoformat(),
                "feed": FEED,
                "limit": str(self._page_limit),
                "start": start.isoformat(),
                "timeframe": TIMEFRAME,
            }
            if token is not None:
                params["page_token"] = token
            path = f"/v2/stocks/{symbol}/bars"
            query = urllib.parse.urlencode(sorted(params.items()), doseq=True)
            urls.append(f"https://{HISTORY_HOST}{path}?{query}")
            # budget accounting counts wire INTENT before the send (review
            # fix 2026-11-26): a failed transport attempt consumes the
            # authorized budget exactly like a success, so operator retry
            # loops cannot push unlimited failed wire requests past the
            # cap. Guard-refused requests never reach the wire and are
            # not counted.
            self._client.validate_request(HISTORY_HOST, path, headers)
            self.request_count += 1
            payload = self._client.get_json(
                host=HISTORY_HOST, path=path, params=params, headers=headers
            )
            pages += 1

            echo = payload.get("symbol")
            if echo is None:
                raise HistoricalRequestRefused(
                    "SCHEMA", "response.symbol (documented required echo) missing"
                )
            if echo != symbol:
                raise HistoricalRequestRefused(
                    "SYMBOL_MISMATCH", f"response echo {echo!r} != requested {symbol!r}"
                )
            bars = payload.get("bars")
            if not isinstance(bars, list):
                raise HistoricalRequestRefused("SCHEMA", "response.bars must be a list")
            if not bars:
                raise HistoricalRequestRefused(
                    "EMPTY_PAGE", f"page {pages} carried no bars — refusing, not padding"
                )
            last_ts: dt.datetime | None = None
            if rows:
                last_ts = dt.datetime.fromisoformat(rows[-1]["t"].replace("Z", "+00:00"))
            for bar in bars:
                validated = self._validate_bar(
                    bar, symbol=symbol, start=start, end=end, last_ts=last_ts
                )
                last_ts = dt.datetime.fromisoformat(validated["t"].replace("Z", "+00:00"))
                rows.append(validated)

            token = payload.get("next_page_token")
            if token is None:
                complete = True
                break
            if not isinstance(token, str) or not token:
                raise HistoricalRequestRefused(
                    "MALFORMED_PAGE_TOKEN", f"next_page_token must be a non-empty string, got {token!r}"
                )
            if token in seen_tokens:
                raise HistoricalRequestRefused(
                    "PAGE_TOKEN_LOOP",
                    f"token {token!r} already followed — vendor is looping",
                )
            seen_tokens.add(token)
            tokens_seen.append(token)

        return HistoricalFetchResult(
            symbol=symbol,
            start=start,
            end=end,
            rows=tuple(rows),
            pages=pages,
            request_count=self.request_count,
            request_urls=tuple(urls),
            page_tokens_seen=tuple(tokens_seen),
            complete=complete,
        )

    # -- per-bar validation -----------------------------------------------------

    @staticmethod
    def _validate_bar(
        bar: Any,
        *,
        symbol: str,
        start: dt.date,
        end: dt.date,
        last_ts: dt.datetime | None,
    ) -> dict[str, Any]:
        if not isinstance(bar, dict):
            raise HistoricalRequestRefused("SCHEMA", "bar must be an object")
        for key in ("t", "o", "h", "l", "c", "v"):
            if key not in bar:
                raise HistoricalRequestRefused("SCHEMA", f"bar missing field {key!r}")
        t_text = str(bar["t"])
        try:
            ts = dt.datetime.fromisoformat(t_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HistoricalRequestRefused(
                "SCHEMA", f"bar t is not an ISO timestamp: {t_text!r}"
            ) from exc
        if ts.tzinfo is None:
            raise HistoricalRequestRefused("SCHEMA", "bar t must carry a timezone")
        session_date = ts.astimezone(ET).date()
        if session_date < start or session_date > end:
            raise HistoricalRequestRefused(
                "OUT_OF_RANGE_BAR",
                f"session {session_date.isoformat()} outside requested "
                f"[{start.isoformat()}, {end.isoformat()}]",
            )
        prices: dict[str, Decimal] = {}
        for key in ("o", "h", "l", "c"):
            value = bar[key]
            if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
                raise HistoricalRequestRefused(
                    "SCHEMA",
                    f"{key} must be an exact number (Decimal/int), got {type(value).__name__}",
                )
            d = Decimal(value) if isinstance(value, int) else value
            if not d.is_finite():
                raise HistoricalRequestRefused("NON_FINITE_PRICE", f"{key} is not finite: {d}")
            if d <= 0:
                raise HistoricalRequestRefused("PRICE", f"{key} must be positive: {d}")
            prices[key] = d
        if prices["l"] > prices["h"]:
            raise HistoricalRequestRefused("PRICE", "low exceeds high")
        volume = bar["v"]
        if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
            raise HistoricalRequestRefused(
                "SCHEMA", f"volume must be a non-negative int, got {volume!r}"
            )
        if last_ts is not None and ts <= last_ts:
            raise HistoricalRequestRefused(
                "DUPLICATE_OR_OUT_OF_ORDER",
                f"bar {t_text} is not strictly after the previous bar",
            )
        return {
            "t": t_text,
            "o": prices["o"],
            "h": prices["h"],
            "l": prices["l"],
            "c": prices["c"],
            "v": volume,
            "symbol": symbol,
            "session_date": session_date.isoformat(),
        }
