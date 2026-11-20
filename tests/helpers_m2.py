"""Shared M2 suite helpers (unique module name)."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_lab.brokers import FakeBroker  # noqa: E402
from trading_lab.contracts import Environment, MarketSnapshot, TradeIntent  # noqa: E402
from trading_lab.oms import BrokerEgress, FenceCoordinator, OmsEngine, OrderJournal  # noqa: E402
from trading_lab.risk import ExposureState, RiskEngine, RiskPolicy, TrustedProducer  # noqa: E402
from trading_lab.security import ApprovalSecrets, AuditLog, KillSwitch  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 21, 0, 0, tzinfo=dt.timezone.utc)
ACCOUNT = "PAPER_TEST_ACCOUNT"
SYMBOL = "SPY"
BUILD = "a" * 32

POLICY_DICT = {
    "version": 1,
    "environment": Environment.PAPER,
    "account_id": ACCOUNT,
    "policy_hash": "b" * 32,
    "max_gross_exposure_pct": Decimal("60"),
    "max_net_exposure_pct": Decimal("60"),
    "max_single_symbol_pct": Decimal("30"),
    "max_single_order_notional_usd": Decimal("100"),
    "max_daily_loss_pct": Decimal("2"),
    "max_peak_to_trough_drawdown_pct": Decimal("6"),
    "max_abnormal_orders_per_minute": 8,
    "max_market_bar_age_seconds": 120,
    "max_account_snapshot_age_seconds": 30,
    "max_broker_order_ack_wait_seconds": 10,
    "require_settled_funds": True,
    "allow_margin": False,
    "allow_short": False,
    "allowed_symbols": ("SPY", "QQQ", "IWM"),
    "recovery_requires": (
        "broker_orders_positions_cash_reconciled",
        "operator_release_after_incident",
    ),
}


def make_intent(
    seq: int,
    account: str = ACCOUNT,
    env: Environment = Environment.PAPER,
    desired: str = "50",
    expired: bool = False,
) -> TradeIntent:
    return TradeIntent(
        intent_id=f"int-{seq:06d}",
        release_id="rel-mock-0001",
        account_id=account,
        environment=env,
        desired_change=Decimal(desired),
        source_hash=BUILD,
        expires_at_utc=NOW - dt.timedelta(minutes=1) if expired else NOW + dt.timedelta(minutes=5),
        deterministic_client_order_id=f"{env.value}:{account}:{seq:08d}",
    )


def fresh_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id="snap-fix-1",
        asof_utc=NOW - dt.timedelta(seconds=10),
        knowledge_cutoff_utc=NOW - dt.timedelta(seconds=10),
        dataset_hash="c" * 32,
        data_quality="synthetic-engineering-fixture",
    )


@pytest.fixture()
def stack(tmp_path):
    """A fresh, fully-wired fake trading stack per test."""
    broker = FakeBroker()
    audit = AuditLog(tmp_path / "audit.jsonl", "PAPER")
    journal = OrderJournal(tmp_path / "journal.sqlite3")
    fence = FenceCoordinator(tmp_path / "fence.sqlite3", Environment.PAPER, ACCOUNT)
    approval_secrets = ApprovalSecrets.mint()
    egress = BrokerEgress(broker, fence, audit, now_fn=lambda: NOW,
                      journal=journal, approval_secrets=approval_secrets)
    ks = KillSwitch(Environment.PAPER, ACCOUNT, tmp_path / "ks", audit)
    policy = RiskPolicy.model_validate(dict(POLICY_DICT))
    producer = TrustedProducer.mint("portfolio_agg_v1", BUILD)
    engine = RiskEngine(
        policy=policy,
        kill_switch=ks,
        audit=audit,
        trusted_producer=producer,
        now_fn=lambda: NOW,
        snapshot_provider=fresh_snapshot,
        exposure_provider=lambda: ExposureState(
            gross_exposure_usd=Decimal("0"),
            net_exposure_usd=Decimal("0"),
            equity_usd=Decimal("1000"),
            settled_cash_usd=Decimal("1000"),
        ),
        approval_secrets=approval_secrets,
    )
    oms = OmsEngine(
        environment=Environment.PAPER,
        account_id=ACCOUNT,
        journal=journal,
        egress=egress,
        fence=fence,
        audit=audit,
        kill_switch=ks,
        now_fn=lambda: NOW,
        expected_policy_hash=policy.policy_hash,
        approval_secrets=approval_secrets,
    )
    token = fence.acquire(NOW)
    return {
        "broker": broker, "audit": audit, "journal": journal, "fence": fence,
        "egress": egress, "ks": ks, "policy": policy, "producer": producer,
        "engine": engine, "oms": oms, "token": token, "tmp": tmp_path,
    }
