import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fake_broker import Environment, OrderIntent  # noqa: E402

PAPER = Environment.PAPER
LIVE = Environment.LIVE
ACCOUNT = "ACC-PAPER-001"


@pytest.fixture
def clock():
    class Clock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, s):
            self.t += s
    return Clock()


def make_intent(intent_id="intent-0001", symbol="SPY", qty="1", env=PAPER,
                account=ACCOUNT) -> OrderIntent:
    return OrderIntent(intent_id=intent_id, environment=env, account_id=account,
                       symbol=symbol, side="BUY", qty=Decimal(qty),
                       created_at_utc="2026-01-02T15:00:00Z")
