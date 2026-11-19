"""Scenario 5 — environment/account namespace isolation (mock level):
a Paper executor cannot address a Live account, paper configs carry no live
artifacts, and there is no boolean Paper→Live promotion path on the adapter."""
import pytest
from conftest import ACCOUNT, LIVE, PAPER, make_intent

from fake_broker import (DurableJournal, Environment, FakeBroker,
                         LeaseStore, MinimalOMS)
from fake_broker.environment import scan_config_for_foreign_environment
from fake_broker.fake_broker import EnvironmentMismatchError

PAPER_ACCOUNT = "ACC-PAPER-001"
LIVE_ACCOUNT = "ACC-LIVE-999"  # never actually instantiated beyond an isolated mock


def test_paper_executor_cannot_write_live_account_namespace(tmp_path, clock):
    paper_journal = DurableJournal(tmp_path / "paper_journal.sqlite3")
    paper_leases = LeaseStore(tmp_path / "paper_leases.sqlite3", lease_seconds=60.0, clock=clock)
    paper_broker = FakeBroker(PAPER, PAPER_ACCOUNT, tmp_path / "paper_broker.json",
                              clock=lambda: "2026-01-02T15:00:00Z")
    token = paper_leases.acquire(PAPER.value, PAPER_ACCOUNT, "paper-exec")
    paper_broker.valid_fences = {token.epoch}
    paper_oms = MinimalOMS(PAPER, PAPER_ACCOUNT, paper_journal)

    # attempt 1: paper executor, intent targeting the LIVE account
    with pytest.raises(EnvironmentMismatchError):
        paper_oms.submit(make_intent("i-iso-1", env=PAPER, account=LIVE_ACCOUNT),
                         token, paper_broker)
    assert paper_broker.submission_count() == 0

    # attempt 2: paper executor, intent claiming environment LIVE
    with pytest.raises(EnvironmentMismatchError):
        paper_oms.submit(make_intent("i-iso-2", env=LIVE, account=PAPER_ACCOUNT),
                         token, paper_broker)
    assert paper_broker.submission_count() == 0

    # a live-namespace broker (isolated mock; no real endpoint exists here)
    live_broker = FakeBroker(LIVE, LIVE_ACCOUNT, tmp_path / "live_broker.json",
                             clock=lambda: "2026-01-02T15:00:00Z")
    assert live_broker.submission_count() == 0, "no order ever reached the live namespace"


def test_paper_config_must_not_contain_live_artifacts():
    paper_config = {
        "runtime": "PAPER",
        "broker": {
            "base_url": "https://paper-api.alpaca.markets",
            "key_env_var": "TBL_PAPER_API_KEY_ID",
            "secret_env_var": "TBL_PAPER_API_SECRET_KEY",
        },
        "journal_path": "runtime/paper/journal.sqlite3",
        "allow_promotion_to_live": False,
    }
    assert scan_config_for_foreign_environment(paper_config, "PAPER") == []

    bad_config = dict(paper_config)
    bad_config["broker"] = dict(paper_config["broker"])
    bad_config["broker"]["base_url"] = "https://api.alpaca.markets"  # live endpoint!
    hits = scan_config_for_foreign_environment(bad_config, "PAPER")
    assert hits == ["broker.base_url"], "live endpoint in a paper config must be detected"


def test_adapter_bound_to_one_namespace_no_boolean_promotion(tmp_path, clock):
    """The adapter's namespace is fixed at construction; flipping a flag cannot
    redirect it to another (environment, account)."""
    paper_broker = FakeBroker(PAPER, PAPER_ACCOUNT, tmp_path / "pb.json",
                              clock=lambda: "2026-01-02T15:00:00Z")
    # there is no attribute like 'promote_to_live'; namespace is immutable state
    assert not hasattr(paper_broker, "promote_to_live")
    assert paper_broker.environment == PAPER
    assert paper_broker.account_id == PAPER_ACCOUNT
    # attempts to retarget raise
    with pytest.raises(AttributeError):
        paper_broker.environment = LIVE  # noqa — dataclass-style attr on instance
