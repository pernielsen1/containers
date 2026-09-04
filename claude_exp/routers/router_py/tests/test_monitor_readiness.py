"""wait_for_ready()'s upstream branch must not trust connections.router alone - that flag only
flips to False once something notices the link is dead, and can report True long after a
connection has actually gone stale (see upstream_host/main.py's _write_frame/disc_evt and
monitor/main.py's _upstream_connection_live). This is the exact gap that let a soak's first
/start land on a dead connection and send an entire before_kill stage into the void after a real
WSL restart (soak_resilience_hard.py's real-crypto findings, 2026-08-30/2026-09-04 - see
[[project_resilience_hard_soak]]) - only ever verified end to end via full-stack soak runs before
this test existed. These tests pin the decision logic directly and fast, with requests.get mocked
so no real actor process is needed.
"""
import time

from monitor import main as monitor_main

_ACTOR = {"command_port": 9999, "type": "upstream", "name": "upstream_1"}


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_wait_for_ready_upstream_returns_quickly_when_flag_and_probe_agree(monkeypatch):
    probe_calls = []

    def fake_get(url, timeout=1):
        if url.endswith("/stats"):
            return _FakeResponse(200, {"connections": {"router": True}})
        if url.endswith("/probe_connection"):
            probe_calls.append(1)
            return _FakeResponse(200, {"connected": True})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(monitor_main.requests, "get", fake_get)

    start = time.monotonic()
    monitor_main.wait_for_ready(_ACTOR, timeout=5)
    elapsed = time.monotonic() - start

    assert probe_calls, "the flag alone must not be enough - a live probe must actually happen"
    assert elapsed < 2, "must return as soon as the probe confirms live, not wait out the timeout"


def test_wait_for_ready_upstream_keeps_waiting_when_flag_true_but_probe_false(monkeypatch):
    """The exact scenario the fix targets: /stats' connections.router still says True (nothing
    has tried to write on the stale connection yet), but an active probe reveals it's actually
    dead. wait_for_ready must not declare ready off the flag alone."""
    probe_calls = []

    def fake_get(url, timeout=1):
        if url.endswith("/stats"):
            return _FakeResponse(200, {"connections": {"router": True}})
        if url.endswith("/probe_connection"):
            probe_calls.append(1)
            return _FakeResponse(200, {"connected": False})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(monitor_main.requests, "get", fake_get)

    start = time.monotonic()
    monitor_main.wait_for_ready(_ACTOR, timeout=0.5)
    elapsed = time.monotonic() - start

    assert len(probe_calls) > 1, "must keep actively probing, not accept the flag once and stop"
    assert elapsed >= 0.5, "must not return early on a stale-but-flagged connection"


def test_upstream_connection_live_false_on_probe_failure(monkeypatch):
    """A probe that can't even be reached (actor down, network error) must count as not-live,
    not raise - wait_for_ready's callers treat this the same as an explicit connected:false."""

    def fake_get(url, timeout=1):
        raise ConnectionError("boom")

    monkeypatch.setattr(monitor_main.requests, "get", fake_get)
    assert monitor_main._upstream_connection_live(_ACTOR) is False
