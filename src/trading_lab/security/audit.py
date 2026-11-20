"""Append-only, hash-chained audit event log — the M0 audit skeleton.

Format: one JSON object per line (JSONL):

    {"seq": N, "prev_hash": "<hex>", "ts": "<iso8601>", "event_type": "...",
     "payload": {...}, "event_hash": "<hex>"}

- ``event_hash`` = SHA-256 over the canonical JSON of
  ``(seq, prev_hash, ts, event_type, payload)`` — any later mutation of a
  historical line breaks the chain and :meth:`AuditLog.verify` detects it.
- A companion **head record** (``<log>.head``) stores the expected last
  ``seq``/``event_hash`` after every append. Chain verification alone
  cannot detect tail truncation (a shorter chain is internally consistent);
  the head record closes that hole. The head file is runtime state co-located
  with the log.
- The log is opened append-only ('a'); the constructor never truncates.
- This is a *detection* control, not a prevention control: the M0 threat
  model (single host, platform-owned state files) treats write access as
  trusted and external tamper-proof storage as out of scope (ADR-002).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, sha256_hex

GENESIS_HASH = "0" * 64


class AuditLog:
    def __init__(self, path: str | os.PathLike[str], environment_tag: str) -> None:
        self._path = Path(path)
        self._head_path = Path(str(self._path) + ".head")
        self._environment_tag = environment_tag
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        self._load_existing()

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                seq = int(record["seq"])
                if seq != self._seq + 1:
                    raise ValueError(
                        f"audit log gap/corruption at line seq={seq} (expected {self._seq + 1})"
                    )
                self._seq = seq
                self._prev_hash = record["event_hash"]

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        seq = self._seq + 1
        digest_input = {
            "seq": seq,
            "prev_hash": self._prev_hash,
            "ts": ts,
            "event_type": event_type,
            "payload": payload,
        }
        event_hash = sha256_hex(canonical_json_bytes(digest_input))
        record = {**digest_input, "event_hash": event_hash}
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._seq = seq
        self._prev_hash = event_hash
        self._write_head(seq, event_hash)
        return record

    def _write_head(self, seq: int, last_hash: str) -> None:
        self._head_path.write_text(
            json.dumps({"seq": seq, "last_hash": last_hash}, sort_keys=True),
            encoding="utf-8",
        )

    def verify(self) -> tuple[bool, int]:
        """Recompute the whole chain and cross-check against the head record.

        Returns ``(ok, first_bad_seq)``; ``first_bad_seq`` is 0 when intact,
        otherwise the first inconsistent line, or ``head_seq`` on tail
        truncation (head claims more lines than the file holds).
        """
        expected_prev = GENESIS_HASH
        seen = 0
        if not self._path.exists():
            if self._head_path.exists():
                head = json.loads(self._head_path.read_text(encoding="utf-8"))
                if int(head.get("seq", 0)) > 0:
                    return False, int(head.get("seq", 0))
            return True, 0
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                seen += 1
                record = json.loads(line)
                if int(record["seq"]) != seen:
                    return False, seen
                digest_input = {
                    "seq": int(record["seq"]),
                    "prev_hash": record["prev_hash"],
                    "ts": record["ts"],
                    "event_type": record["event_type"],
                    "payload": record["payload"],
                }
                if record["prev_hash"] != expected_prev:
                    return False, seen
                expected = sha256_hex(canonical_json_bytes(digest_input))
                if record["event_hash"] != expected:
                    return False, seen
                expected_prev = record["event_hash"]
        if self._head_path.exists():
            head = json.loads(self._head_path.read_text(encoding="utf-8"))
            if int(head.get("seq", 0)) != seen or head.get("last_hash") != expected_prev:
                return False, int(head.get("seq", seen))
        return True, 0


__all__ = ["AuditLog", "GENESIS_HASH"]
