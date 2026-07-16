from urllib.error import URLError

from scripts import run_api_supervisor as supervisor


class _FakeChild:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_unhealthy_child_is_replaced_after_failure_threshold(monkeypatch):
    child = _FakeChild()
    monkeypatch.setattr(supervisor, "STARTUP_GRACE_SECONDS", 0)
    monkeypatch.setattr(supervisor, "HEALTH_CHECK_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(supervisor, "MAX_CONSECUTIVE_HEALTH_FAILURES", 2)
    monkeypatch.setattr(supervisor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        supervisor,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    monkeypatch.setattr(supervisor, "_log", lambda _message: None)

    exit_code, replaced = supervisor._wait_for_child(child)

    assert replaced is True
    assert exit_code == -15
    assert child.terminated is True
