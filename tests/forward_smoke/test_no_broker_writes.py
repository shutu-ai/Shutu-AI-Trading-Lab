"""No-broker-writes proof (task S1/S3): the SHADOW/REPLAY path has zero
broker egress, even with broker credentials visible in the environment,
and a wired FakeBroker is never called — its ACKs can never become
shadow execution "evidence" because no call ever happens."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from apps.trading_daemon import driver
from apps.trading_daemon.fixture import build_fixture_events

REPO_ROOT = Path(__file__).resolve().parents[2]

DAEMON_PACKAGE = REPO_ROOT / "apps" / "trading_daemon"

FORBIDDEN_IMPORT_FRAGMENTS = (
    "trading_lab.brokers",
    "trading_lab.oms",
    "trading_lab.risk",
    "socket",
    "ssl",
    "urllib",
    "http.client",
    "requests",
    "websockets",
    "alpaca",
)

CREDENTIAL_ENV_NAMES = (
    "APCA_API_KEY_ID", "APCA_API_SECRET_KEY",
    "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY",
)


def _daemon_sources():
    return sorted(DAEMON_PACKAGE.rglob("*.py"))


def test_daemon_sources_have_no_broker_or_network_imports():
    """Static: no daemon module may even name a broker/network import."""
    import ast
    assert _daemon_sources(), "daemon package missing"
    for path in _daemon_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(
                        f in alias.name for f in FORBIDDEN_IMPORT_FRAGMENTS), \
                        f"{path.name}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(
                    f in mod for f in FORBIDDEN_IMPORT_FRAGMENTS), \
                    f"{path.name}: from {mod} import ..."


def test_daemon_sources_never_read_environment_values():
    """Static (AST): no daemon module reads ANY environment VALUE
    (os.environ[...] / os.environ.get(...)). Membership checks
    (``name in os.environ``) are allowed — they leak no secret."""
    import ast

    def _is_environ(node) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "environ"

    assert _daemon_sources(), "daemon package missing"
    for path in _daemon_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                raise AssertionError(
                    f"{path.name}:{node.lineno} reads an environment "
                    "value via os.environ[...]")
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    node.func.attr == "get" and _is_environ(node.func.value):
                raise AssertionError(
                    f"{path.name}:{node.lineno} reads an environment "
                    "value via os.environ.get(...)")


def test_replay_makes_zero_broker_calls_with_monitor_wired(
        tmp_path, prereg, fixture_events, monkeypatch):
    """Runtime: instrument the real BrokerPort implementation surface and
    prove zero calls during a full replay."""
    calls = {"submit_order": 0, "cancel_order": 0}
    from trading_lab.brokers import fake as fake_brokers

    original_submit = fake_brokers.FakeBroker.submit_order
    original_cancel = fake_brokers.FakeBroker.cancel_order

    def counting_submit(self, *a, **k):
        calls["submit_order"] += 1
        return original_submit(self, *a, **k)

    def counting_cancel(self, *a, **k):
        calls["cancel_order"] += 1
        return original_cancel(self, *a, **k)

    monkeypatch.setattr(fake_brokers.FakeBroker, "submit_order",
                        counting_submit)
    monkeypatch.setattr(fake_brokers.FakeBroker, "cancel_order",
                        counting_cancel)

    summary = driver.run_replay(state_dir=tmp_path / "state", prereg=prereg,
                                events=fixture_events, session_index=1)
    assert calls == {"submit_order": 0, "cancel_order": 0}
    assert summary.counters["scored"]["total"] == 25


def test_replay_refuses_network_even_if_attempted(
        tmp_path, prereg, fixture_events, monkeypatch):
    """Runtime: any socket usage during replay fails the test outright."""
    import socket

    def no_network(*a, **k):  # pragma: no cover - tripwire
        raise AssertionError("network attempted during offline replay")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    summary = driver.run_replay(state_dir=tmp_path / "state", prereg=prereg,
                                events=fixture_events, session_index=1)
    assert summary.counters["consumed"] == len(fixture_events)


def test_broker_credentials_visible_but_never_used(
        tmp_path, prereg, fixture_events, monkeypatch):
    """Even with Alpaca LIVE/PAPER-style credentials present, the replay
    must not read them, connect, or change behavior (task S3)."""
    for name in CREDENTIAL_ENV_NAMES:
        monkeypatch.setenv(name, "FAKE-CREDENTIAL-VALUE")
    seen = {"socket": 0}
    import socket

    def no_socket(*a, **k):  # pragma: no cover - tripwire
        seen["socket"] += 1
        raise AssertionError("socket used while credentials present")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)

    summary = driver.run_replay(state_dir=tmp_path / "state", prereg=prereg,
                                events=fixture_events, session_index=1)
    assert seen["socket"] == 0
    assert summary.credential_env_visible == sorted(CREDENTIAL_ENV_NAMES)
    assert summary.counters["scored"]["total"] == 25
    assert summary.no_broker_writes is True


def test_wired_fakebroker_is_never_called_and_never_is_execution_evidence(
        tmp_path, prereg, fixture_events, monkeypatch):
    """A FakeBroker instance is instrumented in the test process (the
    only broker machinery allowed offline); the daemon never touches it,
    and the replay summary contains no execution/ACK claims at all."""
    from trading_lab.brokers.fake import FakeBroker

    calls = {"submit_order": 0, "cancel_order": 0}
    original_submit = FakeBroker.submit_order
    original_cancel = FakeBroker.cancel_order

    def counting_submit(self, *a, **k):
        calls["submit_order"] += 1
        return original_submit(self, *a, **k)

    def counting_cancel(self, *a, **k):
        calls["cancel_order"] += 1
        return original_cancel(self, *a, **k)

    monkeypatch.setattr(FakeBroker, "submit_order", counting_submit)
    monkeypatch.setattr(FakeBroker, "cancel_order", counting_cancel)

    summary = driver.run_replay(state_dir=tmp_path / "state", prereg=prereg,
                                events=fixture_events, session_index=1)
    assert calls == {"submit_order": 0, "cancel_order": 0}

    def _keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield str(k)
                yield from _keys(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                yield from _keys(item)

    banned = ("ack", "fill", "execution", "broker_order", "order_id")
    keys = [k.lower() for k in _keys(summary.as_dict())]
    assert not any(b in k for k in keys for b in banned), keys
    assert summary.no_broker_writes is True
