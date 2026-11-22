"""Guarded read-only HTTP client — the ONLY network-capable module in the
S8 collector plane.

Every request is validated BEFORE any byte is sent; a guard violation
raises :class:`TransportError` without touching the network (negative
tests prove the transport is never invoked for rejected requests):

- **GET only** — there is no API surface for another verb, and the guard
  re-asserts the frozen verb constant;
- **https only**, host must be in the preregistered allowlist, and the
  trading-API hosts (``api.alpaca.markets``, ``paper-api.alpaca.markets``)
  are rejected EVEN IF a broken configuration ever allowed them;
- **path whitelist** — every path must match a preregistered market-data
  pattern (the v2 loader already refuses any pattern outside
  ``/v2/stocks/``);
- **no request body**; **no redirects** (a 3xx is an error, never a
  silent hop to another host);
- header names are whitelisted (``APCA-*`` credentials plus ``accept``);
  credential VALUES are passed through to the transport but never appear
  in receipts, errors or logs;
- JSON bodies are parsed with ``parse_float=Decimal`` — platform-wide
  rule: floats never carry market data.

Honest boundary (recorded, not hidden): the guard is an application-level
control in the collector process. Host/network-level isolation (egress
firewall rules, separate credentials) belongs to the operator setup the
signed approval assigns to the account owner, not to this module.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Callable, Mapping

import urllib.error
import urllib.parse
import urllib.request

__all__ = ["GuardedGetClient", "TransportError", "market_data_headers"]

#: trading hosts can NEVER be contacted from the read-only plane — this
#: constant is checked on every request, independently of configuration.
TRADING_API_HOSTS = frozenset(
    {"api.alpaca.markets", "paper-api.alpaca.markets"})

_HEADER_RE = re.compile(r"^[A-Za-z0-9-]+$")
_ALLOWED_HEADER_NAMES = frozenset({"accept"})


class TransportError(RuntimeError):
    """The request was refused by the guard, or the transport failed.

    ``reason`` is a stable machine token; ``detail`` never carries
    credential material (only header NAMES may appear)."""

    def __init__(self, reason: str, detail: str,
                 status: int | None = None) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.status = status


class _RedirectForbidden(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Surface as HTTPError so the caller sees "redirect refused" with
        # the status; the target URL is never followed.
        return None  # returning None makes urllib raise HTTPError(code)


def market_data_headers(key_id: str, secret_key: str) -> dict[str, str]:
    """Alpaca market-data credential headers. Values come from the
    operator-injected environment at call time; they are never logged or
    receipted."""
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
    }


class GuardedGetClient:
    """GET-only JSON client over a preregistered host/path allowlist."""

    METHOD = "GET"

    def __init__(
        self,
        *,
        allowed_hosts: list[str] | tuple[str, ...],
        allowed_paths: list[str] | tuple[str, ...],
        timeout_seconds: float = 20.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._hosts = frozenset(h.lower() for h in allowed_hosts)
        if not self._hosts:
            raise TransportError(
                "CONFIG", "allowed_hosts must be non-empty")
        if set(self._hosts) & TRADING_API_HOSTS:
            raise TransportError(
                "TRADING_HOST_FORBIDDEN",
                "the trading-API hosts can never be allowlisted here")
        if not allowed_paths:
            raise TransportError(
                "CONFIG", "allowed_paths must be non-empty")
        self._path_patterns = tuple(
            re.compile(p) for p in allowed_paths)
        self._timeout = float(timeout_seconds)
        if opener is not None:
            self._open = opener
        else:
            self._opener = urllib.request.build_opener(_RedirectForbidden())
            self._open = self._opener.open

    # -- guard ----------------------------------------------------------------

    def validate_request(self, host: str, path: str,
                         headers: Mapping[str, str] | None = None) -> None:
        """Fail closed BEFORE any network I/O. Negative-tested so the rule
        cannot silently rot."""
        if self.METHOD != "GET":
            raise TransportError(
                "METHOD_GUARD",
                f"the read-only client is GET-only (found {self.METHOD!r})")
        host_l = host.lower()
        if host_l in TRADING_API_HOSTS:
            raise TransportError(
                "TRADING_HOST_FORBIDDEN",
                f"host {host_l} is a trading-API host — the read-only "
                "collector never contacts it")
        if host_l not in self._hosts:
            raise TransportError(
                "HOST_NOT_ALLOWED",
                f"host {host_l} is not in the preregistered allowlist "
                f"{sorted(self._hosts)}")
        if not path.startswith("/"):
            raise TransportError(
                "PATH_NOT_ALLOWED", f"path must start with '/', got {path!r}")
        if not any(p.match(path) for p in self._path_patterns):
            raise TransportError(
                "PATH_NOT_ALLOWED",
                f"path {path!r} matches no preregistered market-data "
                "pattern")
        for name in (headers or {}):
            if not isinstance(name, str) or not _HEADER_RE.match(name):
                raise TransportError(
                    "HEADER_NOT_ALLOWED", f"malformed header name {name!r}")
            if name.lower() not in _ALLOWED_HEADER_NAMES and \
                    not name.lower().startswith("apca-"):
                raise TransportError(
                    "HEADER_NOT_ALLOWED",
                    f"header {name!r} is outside the read-only whitelist "
                    "(credential APCA-* and accept only)")

    # -- request ----------------------------------------------------------------

    def get_json(
        self,
        *,
        host: str,
        path: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """One guarded GET returning the parsed JSON body.

        ``params`` values must be simple strings (the feed selector etc.);
        they are URL-encoded in sorted order for reproducibility."""
        self.validate_request(host, path, headers)
        for key, value in (params or {}).items():
            if not isinstance(value, str):
                raise TransportError(
                    "MALFORMED_PARAM",
                    f"query param {key!r} must be a string, got "
                    f"{type(value).__name__}")
        query = urllib.parse.urlencode(
            sorted((params or {}).items()), doseq=True)
        url = f"https://{host}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, method=self.METHOD)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        if request.data is not None:
            raise TransportError(
                "BODY_FORBIDDEN",
                "the read-only client never sends a request body")
        try:
            response = self._open(request, timeout=self._timeout)
            with response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Redirects land here too (no redirect handler installed):
            # a 3xx is refused, never followed.
            raise TransportError(
                "HTTP_STATUS",
                f"{exc.code} for {host}{path}"
                + (" (redirect refused — never followed)"
                   if 300 <= exc.code < 400 else ""),
                status=exc.code) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if "APCA-API-SECRET-KEY" in detail:
                detail = "TRANSPORT_FAILURE (detail withheld)"
            raise TransportError("TRANSPORT", detail) from exc
        try:
            text = raw.decode("utf-8")

            def _refuse_non_finite(_literal: str) -> Decimal:
                raise ValueError(
                    f"non-finite JSON literal {_literal!r} is refused — "
                    "market data never rides on NaN/Infinity")

            parsed = json.loads(
                text, parse_float=Decimal,
                parse_constant=_refuse_non_finite)
        except (ValueError, UnicodeDecodeError) as exc:
            raise TransportError(
                "UNPARSEABLE",
                f"{host}{path}: body is not UTF-8 JSON "
                f"({type(exc).__name__})") from exc
        if not isinstance(parsed, dict):
            raise TransportError(
                "UNPARSEABLE",
                f"{host}{path}: expected a JSON object, got "
                f"{type(parsed).__name__}")
        return parsed
