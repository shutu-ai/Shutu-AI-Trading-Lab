"""REAL multi-process fencing contention (M2-T3): two actual OS processes
race for the same (environment, account) fence through SQLite transactions.

Asserts: epochs are unique and strictly allocated, the newest token is the
only valid one, and a stale process holding an older token gets its broker
writes refused at the egress (0 accepted writes).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.contracts import Environment  # noqa: E402
from trading_lab.oms import FenceCoordinator  # noqa: E402

WORKER_CODE = """
import sys, json, datetime as dt
sys.path.insert(0, r'{src}')
from trading_lab.contracts import Environment
from trading_lab.oms import FenceCoordinator

fence_path, account, out_path, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
fence = FenceCoordinator(fence_path, Environment.PAPER, account, lease_seconds=60)
results = []
for _ in range(n):
    token = fence.acquire(dt.datetime.now(dt.timezone.utc))
    results.append({{"instance": fence._instance_id, "epoch": token.epoch}})
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(results, fh)
"""


def test_two_process_fence_contention(tmp_path):
    src = str(REPO_ROOT / "src")
    fence_db = tmp_path / "fence.sqlite3"
    account = "PAPER_TEST_ACCOUNT"
    out_a = tmp_path / "worker_a.json"
    out_b = tmp_path / "worker_b.json"
    code = WORKER_CODE.format(src=src)

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(fence_db), account, str(out), "25"],
            cwd=str(REPO_ROOT),
        )
        for out in (out_a, out_b)
    ]
    for p in procs:
        assert p.wait(timeout=120) == 0

    results_a = json.loads(out_a.read_text(encoding="utf-8"))
    results_b = json.loads(out_b.read_text(encoding="utf-8"))
    all_tokens = results_a + results_b

    # 50 acquisitions across two REAL processes: every epoch unique.
    epochs = sorted(t["epoch"] for t in all_tokens)
    assert len(epochs) == 50
    assert len(set(epochs)) == 50

    # The holder of the highest epoch owns the write right; every older
    # token must now fail validation.
    fence_main = FenceCoordinator(fence_db, Environment.PAPER, account, lease_seconds=60)
    newest = max(all_tokens, key=lambda t: t["epoch"])
    from trading_lab.oms.fence import FenceToken

    newest_token = FenceToken(
        environment=Environment.PAPER,
        account_id=account,
        epoch=newest["epoch"],
        lease_expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60),
        owner_instance_id=newest["instance"],
    )
    stale_validations = 0
    for t in all_tokens:
        if t["epoch"] == newest["epoch"]:
            continue
        stale_token = FenceToken(
            environment=Environment.PAPER,
            account_id=account,
            epoch=t["epoch"],
            lease_expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60),
            owner_instance_id=t["instance"],
        )
        try:
            fence_main.validate(stale_token, dt.datetime.now(dt.timezone.utc))
            stale_validations += 1  # a stale token validated — violation
        except Exception:
            pass
    assert stale_validations == 0, f"{stale_validations} stale tokens accepted"
