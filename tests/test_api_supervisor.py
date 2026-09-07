import os
from pathlib import Path
import subprocess
import sys
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


def test_direct_script_bootstraps_project_root_before_package_import(tmp_path):
    project_root = Path(__file__).resolve().parent.parent
    script = project_root / "scripts" / "run_api_supervisor.py"
    scripts_directory = script.parent
    code = (
        "import runpy,sys; "
        f"sys.path=[r'{scripts_directory}']+[p for p in sys.path "
        f"if p not in ('',r'{project_root}')]; "
        f"runpy.run_path(r'{script}',run_name='phase2_import_check'); "
        "print('SUPERVISOR_IMPORT_OK')"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "MTO_ENVIRONMENT": "test",
            "ENVIRONMENT": "test",
            "MTO_REQUIRE_TLS": "0",
            "MTO_SUPERVISOR_HEALTH_URL": "http://127.0.0.1:8001/readyz",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SUPERVISOR_IMPORT_OK" in result.stdout


def test_startup_task_uses_package_module_entrypoint():
    project_root = Path(__file__).resolve().parent.parent
    content = (project_root / "scripts" / "install_api_startup_task.ps1").read_text(
        encoding="utf-8"
    )

    assert '-Argument "-m scripts.run_api_supervisor"' in content
