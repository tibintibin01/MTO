from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import phase5_signing_readiness as gate

NOW = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
THUMBPRINT = "A1" * 20


def _python_ready() -> dict:
    return {
        "version": "3.11.9",
        "major": 3,
        "minor": 11,
        "bits": 64,
        "executable_name": "python.exe",
    }


def _certificate_ready(**overrides) -> list[dict]:
    certificate = {
        "store": "LocalMachine/My",
        "has_private_key": True,
        "code_signing_eku": True,
        "trusted_chain": True,
        "not_before_utc": (NOW - timedelta(days=30)).isoformat(),
        "not_after_utc": (NOW + timedelta(days=365)).isoformat(),
    }
    certificate.update(overrides)
    return [certificate]


def _tool_paths(tmp_path: Path) -> tuple[Path, Path]:
    sign_tool = tmp_path / "signtool.exe"
    inno = tmp_path / "ISCC.exe"
    sign_tool.write_bytes(b"test tool")
    inno.write_bytes(b"test tool")
    return sign_tool, inno


def _capture_ready(
    tmp_path: Path,
    *,
    managed_key_attested: bool = True,
    certificate_probe=None,
    timestamp_url: str = gate.DEFAULT_TIMESTAMP_URL,
) -> dict:
    sign_tool, inno = _tool_paths(tmp_path)
    return gate.capture_signing_readiness(
        thumbprint=THUMBPRINT,
        timestamp_url=timestamp_url,
        managed_key_attested=managed_key_attested,
        python_probe=_python_ready,
        sign_tool_resolver=lambda: sign_tool,
        inno_resolver=lambda: inno,
        certificate_probe=certificate_probe or (lambda _value: _certificate_ready()),
        now=NOW,
    )


def test_ready_gate_passes_without_disclosing_full_thumbprint(tmp_path: Path):
    report = _capture_ready(tmp_path)

    assert report["status"] == "PASS"
    assert report["finding_count"] == 0
    assert report["components"]["certificate"]["thumbprint_short"] == (
        f"{THUMBPRINT[:8]}...{THUMBPRINT[-8:]}"
    )
    assert THUMBPRINT not in json.dumps(report)


def test_missing_build_tools_and_certificate_fail_closed():
    report = gate.capture_signing_readiness(
        thumbprint="",
        python_probe=lambda: None,
        sign_tool_resolver=lambda: None,
        inno_resolver=lambda: None,
        certificate_probe=lambda _value: pytest.fail("probe must not run"),
        now=NOW,
    )

    assert report["status"] == "FAIL"
    assert {
        "PYTHON_311_NOT_FOUND",
        "WINDOWS_SIGN_TOOL_NOT_FOUND",
        "INNO_SETUP_COMPILER_NOT_FOUND",
        "SIGNING_CERTIFICATE_NOT_SELECTED",
    }.issubset({item["code"] for item in report["findings"]})


def test_python_runtime_requires_version_and_architecture():
    result = gate.capture_python_runtime(
        probe=lambda: {
            "version": "3.12.10",
            "major": 3,
            "minor": 12,
            "bits": 32,
            "executable_name": r"C:\unsafe\path\python.exe",
        }
    )

    assert result["status"] == "FAIL"
    assert result["executable_name"] == "python.exe"
    assert {item["code"] for item in result["findings"]} == {
        "PYTHON_BUILD_VERSION_UNAPPROVED",
        "PYTHON_BUILD_ARCHITECTURE_UNAPPROVED",
    }


def test_invalid_thumbprint_is_rejected_before_store_probe():
    result = gate.capture_certificate(
        thumbprint="not-a-thumbprint",
        probe=lambda _value: pytest.fail("invalid thumbprint reached store probe"),
        now=NOW,
    )

    assert result["status"] == "FAIL"
    assert result["thumbprint_short"] is None
    assert result["findings"][0]["code"] == ("SIGNING_CERTIFICATE_THUMBPRINT_INVALID")


def test_certificate_fails_closed_on_key_eku_trust_and_validity():
    result = gate.capture_certificate(
        thumbprint=THUMBPRINT,
        minimum_valid_days=90,
        managed_key_attested=True,
        probe=lambda _value: _certificate_ready(
            has_private_key=False,
            code_signing_eku=False,
            trusted_chain=False,
            not_after_utc=(NOW + timedelta(days=30)).isoformat(),
        ),
        now=NOW,
    )

    assert result["status"] == "FAIL"
    assert {item["code"] for item in result["findings"]} == {
        "SIGNING_PRIVATE_KEY_UNAVAILABLE",
        "CODE_SIGNING_EKU_MISSING",
        "SIGNING_CERTIFICATE_CHAIN_UNTRUSTED",
        "SIGNING_CERTIFICATE_VALIDITY_WINDOW_INSUFFICIENT",
    }


def test_managed_key_custody_requires_explicit_attestation(tmp_path: Path):
    report = _capture_ready(tmp_path, managed_key_attested=False)

    assert report["status"] == "REVIEW"
    assert report["components"]["certificate"]["status"] == "REVIEW"
    assert [item["code"] for item in report["findings"]] == [
        "MANAGED_KEY_CUSTODY_NOT_ATTESTED"
    ]


@pytest.mark.parametrize(
    "timestamp_url",
    [
        "http://timestamp.example.test",
        "https://user:password@timestamp.example.test",
        "https://timestamp.example.test/#fragment",
        "not-a-url",
    ],
)
def test_timestamp_configuration_rejects_unsafe_urls(timestamp_url: str):
    result = gate.capture_timestamp_configuration(timestamp_url)

    assert result["status"] == "FAIL"
    assert result["configured"] is False
    assert result["findings"][0]["code"] == "TIMESTAMP_URL_INVALID"


def test_component_exception_is_redacted(tmp_path: Path):
    sign_tool, inno = _tool_paths(tmp_path)

    def broken_probe():
        raise RuntimeError("sensitive-local-detail")

    report = gate.capture_signing_readiness(
        thumbprint=THUMBPRINT,
        managed_key_attested=True,
        python_probe=broken_probe,
        sign_tool_resolver=lambda: sign_tool,
        inno_resolver=lambda: inno,
        certificate_probe=lambda _value: _certificate_ready(),
        now=NOW,
    )

    assert report["status"] == "FAIL"
    serialized = json.dumps(report)
    assert "sensitive-local-detail" not in serialized
    assert "RuntimeError" in serialized


def test_report_is_written_as_valid_json(tmp_path: Path):
    report = _capture_ready(tmp_path)
    destination = tmp_path / "reports" / "signing-readiness.json"

    written = gate.write_report(report, destination)

    assert written == destination.resolve()
    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert list(destination.parent.glob("*.tmp")) == []


@pytest.mark.parametrize(
    ("status", "require_ready", "expected"),
    [("PASS", False, 0), ("REVIEW", False, 4), ("REVIEW", True, 2), ("FAIL", False, 2)],
)
def test_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    require_ready: bool,
    expected: int,
):
    report = {
        "status": status,
        "components": {
            "python_runtime": {"status": status},
            "certificate": {
                "status": status,
                "thumbprint_short": None,
                "managed_key_custody_attested": False,
            },
        },
        "finding_count": 0,
        "findings": [],
    }
    monkeypatch.setattr(gate, "capture_signing_readiness", lambda **_kwargs: report)
    destination = tmp_path / f"{status.lower()}.json"
    arguments = ["--output", str(destination)]
    if require_ready:
        arguments.append("--require-ready")

    assert gate.main(arguments) == expected
    assert destination.is_file()
