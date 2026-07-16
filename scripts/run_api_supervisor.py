# -*- coding: utf-8 -*-
"""Keep the MTO API process alive and record unexpected exits."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "logs" / "api_supervisor.log"
LOCK_PATH = PROJECT_ROOT / "logs" / "api_supervisor.lock"
MIN_STABLE_RUNTIME_SECONDS = 30
INITIAL_RESTART_DELAY_SECONDS = 2
MAX_RESTART_DELAY_SECONDS = 30
HEALTH_URL = os.getenv("MTO_SUPERVISOR_HEALTH_URL", "http://127.0.0.1:8001/readyz")
HEALTH_CHECK_INTERVAL_SECONDS = 5
HEALTH_CHECK_TIMEOUT_SECONDS = 2
STARTUP_GRACE_SECONDS = 30
MAX_CONSECUTIVE_HEALTH_FAILURES = 6


def _log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _acquire_single_instance_lock():
    """Keep manual launchers and the Windows startup task from duplicating."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    if LOCK_PATH.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _child_environment() -> dict[str, str]:
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_path
        else str(PROJECT_ROOT) + os.pathsep + existing_path
    )
    env["MTO_API_SUPERVISED"] = "1"
    return env


def _attach_child_lifetime(child: subprocess.Popen):
    """On Windows, terminate the API child if the supervisor is terminated."""
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            raise ctypes.WinError(ctypes.get_last_error())

        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            job_handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            job_handle,
            wintypes.HANDLE(child._handle),
        )
        if not assigned:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job_handle)
            raise ctypes.WinError(error)
        return job_handle
    except Exception as exc:
        _log(f"Could not attach API child lifetime protection: {exc!r}")
        return None


def _close_child_lifetime(handle) -> None:
    if handle is None or os.name != "nt":
        return
    import ctypes

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


def _stop_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def _wait_for_child(child: subprocess.Popen) -> tuple[int, bool]:
    """Wait for the child while replacing it if its health endpoint stalls."""
    started_at = time.monotonic()
    health_failures = 0

    while child.poll() is None:
        time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
        if time.monotonic() - started_at < STARTUP_GRACE_SECONDS:
            continue

        try:
            request = Request(HEALTH_URL, method="GET")
            with urlopen(request, timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as response:
                if response.status >= 500:
                    raise HTTPError(
                        HEALTH_URL,
                        response.status,
                        "Health endpoint returned a server error",
                        response.headers,
                        None,
                    )
            if health_failures:
                _log("API health recovered")
            health_failures = 0
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            health_failures += 1
            if health_failures == 1:
                _log(f"API health check failed: {exc!r}")
            if health_failures >= MAX_CONSECUTIVE_HEALTH_FAILURES:
                _log(
                    "API remained unhealthy for "
                    f"{health_failures * HEALTH_CHECK_INTERVAL_SECONDS}s; "
                    "replacing the child process"
                )
                _stop_child(child)
                return child.returncode if child.returncode is not None else -2, True

    return child.returncode if child.returncode is not None else -1, False


def run() -> int:
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        _log("Another API supervisor is already running; duplicate launch ignored")
        return 0

    restart_delay = INITIAL_RESTART_DELAY_SECONDS
    child: subprocess.Popen | None = None

    _log(f"API supervisor started with Python {sys.executable}")
    while True:
        started_at = time.monotonic()
        child_job_handle = None
        try:
            _log("Starting API child process")
            child = subprocess.Popen(
                [sys.executable, "-m", "backend.main"],
                cwd=PROJECT_ROOT,
                env=_child_environment(),
            )
            child_job_handle = _attach_child_lifetime(child)
            exit_code, replaced_unhealthy = _wait_for_child(child)
        except KeyboardInterrupt:
            _log("Supervisor stop requested")
            if child is not None:
                _stop_child(child)
            return 0
        except Exception as exc:
            exit_code = -1
            replaced_unhealthy = False
            _log(f"Could not launch API child: {exc!r}")
        finally:
            if child_job_handle is not None:
                _close_child_lifetime(child_job_handle)
            elif child is not None and child.poll() is None:
                _stop_child(child)
            child = None

        runtime = time.monotonic() - started_at
        exit_reason = "was replaced after a health-check failure" if replaced_unhealthy else "exited"
        _log(
            f"API child {exit_reason} with code {exit_code} after {runtime:.1f}s; "
            f"restarting in {restart_delay}s"
        )
        time.sleep(restart_delay)

        if runtime >= MIN_STABLE_RUNTIME_SECONDS:
            restart_delay = INITIAL_RESTART_DELAY_SECONDS
        else:
            restart_delay = min(restart_delay * 2, MAX_RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    raise SystemExit(run())
