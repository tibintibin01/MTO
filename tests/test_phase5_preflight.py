import sys

from scripts import phase5_audit_observability_preflight as preflight


def _report(live_event_count):
    return {
        "audit": {
            "event_count": 10 + live_event_count,
            "legacy_event_count": 10,
            "live_event_count": live_event_count,
            "status": "verified",
        },
        "schema": {"active": True},
        "readiness_issues": [],
    }


def test_pilot_gate_rejects_a_verified_chain_without_a_live_event(
    monkeypatch,
):
    monkeypatch.setattr(preflight, "capture_preflight", lambda: _report(0))
    monkeypatch.setattr(
        sys,
        "argv",
        ["phase5-preflight", "--require-active", "--require-live-event"],
    )

    assert preflight.main() == 5


def test_pilot_gate_accepts_a_verified_chain_with_a_live_event(
    monkeypatch,
):
    monkeypatch.setattr(preflight, "capture_preflight", lambda: _report(1))
    monkeypatch.setattr(
        sys,
        "argv",
        ["phase5-preflight", "--require-active", "--require-live-event"],
    )

    assert preflight.main() == 0
