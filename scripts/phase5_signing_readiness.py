"""Read-only code-signing readiness gate for original remediation Phase 5.

The gate inspects the dedicated desktop build runtime, Windows signing tools,
Inno Setup compiler, selected Authenticode certificate, and timestamp URL. It
does not install software, import or export certificates, sign files, contact a
timestamp service, create a release tag, or change production state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-original-phase-5-signing-readiness.json"
)
DEFAULT_TIMESTAMP_URL = "https://timestamp.digicert.com"
DEFAULT_MINIMUM_VALID_DAYS = 90
FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_5_CODE_SIGNING_READINESS"
CODE_SIGNING_EKU = "1.3.6.1.5.5.7.3.3"
THUMBPRINT_PATTERN = re.compile(r"^[0-9A-F]{40,64}$")
SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _finding(component: str, code: str, detail: str, severity: str) -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _status_for_findings(findings: list[dict]) -> str:
    highest = max(
        (
            SEVERITY_ORDER.get(str(item.get("severity") or "").upper(), 3)
            for item in findings
        ),
        default=0,
    )
    if highest >= SEVERITY_ORDER["HIGH"]:
        return "FAIL"
    if highest >= SEVERITY_ORDER["MEDIUM"]:
        return "REVIEW"
    return "PASS"


def _capture_component(name: str, operation: Callable[[], dict]) -> dict:
    try:
        result = operation()
    except Exception as exc:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "SIGNING_READINESS_CHECK_FAILED",
                    f"{name} check failed with {type(exc).__name__}.",
                    "HIGH",
                )
            ],
        }
    status = str(result.get("status") or "").upper()
    if status not in {"PASS", "REVIEW", "FAIL"}:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "SIGNING_READINESS_STATUS_INVALID",
                    f"{name} returned an invalid readiness status.",
                    "HIGH",
                )
            ],
        }
    return result


def _run_json_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    runner: Callable = subprocess.run,
) -> object:
    completed = runner(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError("READ_ONLY_PROBE_FAILED")
    try:
        return json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("READ_ONLY_PROBE_INVALID") from exc


def _probe_python_runtime(
    python_path: Path | None = None,
    *,
    runner: Callable = subprocess.run,
) -> dict | None:
    commands: list[list[str]] = []
    if python_path is not None:
        commands.append([str(python_path)])
    else:
        launcher = shutil.which("py")
        if os.name == "nt" and launcher:
            commands.append([launcher, "-3.11"])
        python311 = shutil.which("python3.11")
        if python311:
            commands.append([python311])

    probe = (
        "import json,os,struct,sys;"
        "print(json.dumps({"
        "'version':'.'.join(map(str,sys.version_info[:3])),"
        "'major':sys.version_info[0],"
        "'minor':sys.version_info[1],"
        "'bits':struct.calcsize('P')*8,"
        "'executable_name':os.path.basename(sys.executable)"
        "}))"
    )
    for prefix in commands:
        try:
            payload = _run_json_command(
                [*prefix, "-c", probe],
                runner=runner,
            )
        except (OSError, RuntimeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def capture_python_runtime(
    *,
    python_path: Path | None = None,
    probe: Callable[[], dict | None] | None = None,
) -> dict:
    findings: list[dict] = []
    payload = probe() if probe is not None else _probe_python_runtime(python_path)
    if not payload:
        findings.append(
            _finding(
                "python_runtime",
                "PYTHON_311_NOT_FOUND",
                "An approved Python 3.11 build runtime was not found.",
                "HIGH",
            )
        )
        return {
            "status": "FAIL",
            "present": False,
            "version": None,
            "architecture_bits": None,
            "findings": findings,
        }

    version = str(payload.get("version") or "")
    major = int(payload.get("major") or 0)
    minor = int(payload.get("minor") or 0)
    bits = int(payload.get("bits") or 0)
    if (major, minor) != (3, 11):
        findings.append(
            _finding(
                "python_runtime",
                "PYTHON_BUILD_VERSION_UNAPPROVED",
                "The desktop release build runtime must be Python 3.11.",
                "HIGH",
            )
        )
    if bits != 64:
        findings.append(
            _finding(
                "python_runtime",
                "PYTHON_BUILD_ARCHITECTURE_UNAPPROVED",
                "The desktop release build runtime must be 64-bit.",
                "HIGH",
            )
        )
    return {
        "status": _status_for_findings(findings),
        "present": True,
        "version": version,
        "architecture_bits": bits,
        "executable_name": Path(
            str(payload.get("executable_name") or "python.exe")
        ).name,
        "findings": findings,
    }


def _resolve_sign_tool() -> Path | None:
    command = shutil.which("signtool.exe")
    if command:
        return Path(command)
    kits_root = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if not kits_root.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in kits_root.rglob("signtool.exe")
            if path.parent.name.lower() == "x64"
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _resolve_inno_setup() -> Path | None:
    candidates = (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _capture_tool(
    *,
    component: str,
    missing_code: str,
    missing_detail: str,
    resolver: Callable[[], Path | None],
) -> dict:
    path = resolver()
    findings: list[dict] = []
    if path is None or not path.is_file():
        findings.append(_finding(component, missing_code, missing_detail, "HIGH"))
        return {
            "status": "FAIL",
            "present": False,
            "executable_name": None,
            "findings": findings,
        }
    return {
        "status": "PASS",
        "present": True,
        "executable_name": path.name,
        "findings": findings,
    }


def capture_sign_tool(
    *, resolver: Callable[[], Path | None] = _resolve_sign_tool
) -> dict:
    return _capture_tool(
        component="sign_tool",
        missing_code="WINDOWS_SIGN_TOOL_NOT_FOUND",
        missing_detail="Windows SDK signtool.exe was not found.",
        resolver=resolver,
    )


def capture_inno_setup(
    *, resolver: Callable[[], Path | None] = _resolve_inno_setup
) -> dict:
    return _capture_tool(
        component="installer_compiler",
        missing_code="INNO_SETUP_COMPILER_NOT_FOUND",
        missing_detail="Inno Setup 6 ISCC.exe was not found.",
        resolver=resolver,
    )


def _normalize_thumbprint(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _short_thumbprint(value: str) -> str:
    return f"{value[:8]}...{value[-8:]}"


def _probe_windows_certificate(
    thumbprint: str,
    *,
    runner: Callable = subprocess.run,
) -> list[dict]:
    if os.name != "nt":
        return []
    environment = os.environ.copy()
    environment["MTO_SIGNING_THUMBPRINT_PROBE"] = thumbprint
    powershell = (
        "$ErrorActionPreference='Stop';"
        "$target=($env:MTO_SIGNING_THUMBPRINT_PROBE -replace ' ','').ToUpperInvariant();"
        "$result=@();"
        "foreach($scope in @('CurrentUser','LocalMachine')){"
        "$path=('Cert:\\'+$scope+'\\My');"
        "if(Test-Path $path){"
        "Get-ChildItem -LiteralPath $path | Where-Object {"
        "(($_.Thumbprint -replace ' ','').ToUpperInvariant()) -eq $target"
        "} | ForEach-Object {"
        "$cert=$_;"
        "$chain=New-Object System.Security.Cryptography.X509Certificates.X509Chain;"
        "$chain.ChainPolicy.RevocationMode=[System.Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck;"
        "$trusted=$false;"
        "try{$trusted=$chain.Build($cert)}finally{$chain.Dispose()};"
        "$ekus=@($cert.EnhancedKeyUsageList | ForEach-Object {$_.ObjectId.Value});"
        "$result += [pscustomobject]@{"
        "store=($scope+'/My');"
        "has_private_key=[bool]$cert.HasPrivateKey;"
        "code_signing_eku=[bool]($ekus -contains '1.3.6.1.5.5.7.3.3');"
        "not_before_utc=$cert.NotBefore.ToUniversalTime().ToString('o');"
        "not_after_utc=$cert.NotAfter.ToUniversalTime().ToString('o');"
        "trusted_chain=[bool]$trusted"
        "}"
        "}"
        "}"
        "};"
        "ConvertTo-Json -InputObject @($result) -Compress"
    )
    payload = _run_json_command(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            powershell,
        ],
        environment=environment,
        runner=runner,
    )
    if not isinstance(payload, list):
        raise RuntimeError("CERTIFICATE_PROBE_INVALID")
    return [item for item in payload if isinstance(item, dict)]


def _parse_utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def capture_certificate(
    *,
    thumbprint: str | None,
    minimum_valid_days: int = DEFAULT_MINIMUM_VALID_DAYS,
    managed_key_attested: bool = False,
    now: datetime | None = None,
    probe: Callable[[str], list[dict]] = _probe_windows_certificate,
) -> dict:
    findings: list[dict] = []
    normalized = _normalize_thumbprint(thumbprint)
    base = {
        "selected": bool(normalized),
        "thumbprint_short": (
            _short_thumbprint(normalized)
            if THUMBPRINT_PATTERN.fullmatch(normalized)
            else None
        ),
        "minimum_valid_days": minimum_valid_days,
        "managed_key_custody_attested": bool(managed_key_attested),
    }
    if not normalized:
        findings.append(
            _finding(
                "certificate",
                "SIGNING_CERTIFICATE_NOT_SELECTED",
                "No managed code-signing certificate thumbprint was selected.",
                "HIGH",
            )
        )
        return {
            **base,
            "status": "FAIL",
            "matches": 0,
            "certificate": None,
            "findings": findings,
        }
    if not THUMBPRINT_PATTERN.fullmatch(normalized):
        findings.append(
            _finding(
                "certificate",
                "SIGNING_CERTIFICATE_THUMBPRINT_INVALID",
                "The selected certificate thumbprint format is invalid.",
                "HIGH",
            )
        )
        return {
            **base,
            "status": "FAIL",
            "matches": 0,
            "certificate": None,
            "findings": findings,
        }

    matches = probe(normalized)
    if len(matches) != 1:
        code = (
            "SIGNING_CERTIFICATE_NOT_FOUND"
            if not matches
            else "SIGNING_CERTIFICATE_AMBIGUOUS"
        )
        detail = (
            "The selected certificate was not found in an approved Windows store."
            if not matches
            else "The selected certificate matched more than one Windows store entry."
        )
        findings.append(_finding("certificate", code, detail, "HIGH"))
        return {
            **base,
            "status": "FAIL",
            "matches": len(matches),
            "certificate": None,
            "findings": findings,
        }

    item = matches[0]
    has_private_key = bool(item.get("has_private_key"))
    code_signing_eku = bool(item.get("code_signing_eku"))
    trusted_chain = bool(item.get("trusted_chain"))
    if not has_private_key:
        findings.append(
            _finding(
                "certificate",
                "SIGNING_PRIVATE_KEY_UNAVAILABLE",
                "The selected certificate does not expose an accessible private key.",
                "HIGH",
            )
        )
    if not code_signing_eku:
        findings.append(
            _finding(
                "certificate",
                "CODE_SIGNING_EKU_MISSING",
                "The selected certificate does not permit code signing.",
                "HIGH",
            )
        )
    if not trusted_chain:
        findings.append(
            _finding(
                "certificate",
                "SIGNING_CERTIFICATE_CHAIN_UNTRUSTED",
                "The selected certificate chain is not trusted on the build host.",
                "HIGH",
            )
        )

    captured_at = now or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    else:
        captured_at = captured_at.astimezone(timezone.utc)
    remaining_days: int | None = None
    not_before_text = str(item.get("not_before_utc") or "")
    not_after_text = str(item.get("not_after_utc") or "")
    try:
        not_before = _parse_utc(not_before_text)
        not_after = _parse_utc(not_after_text)
        remaining_days = int((not_after - captured_at).total_seconds() // 86400)
        if captured_at < not_before:
            findings.append(
                _finding(
                    "certificate",
                    "SIGNING_CERTIFICATE_NOT_YET_VALID",
                    "The selected certificate is not yet valid.",
                    "HIGH",
                )
            )
        elif captured_at >= not_after:
            findings.append(
                _finding(
                    "certificate",
                    "SIGNING_CERTIFICATE_EXPIRED",
                    "The selected certificate has expired.",
                    "HIGH",
                )
            )
        elif remaining_days < minimum_valid_days:
            findings.append(
                _finding(
                    "certificate",
                    "SIGNING_CERTIFICATE_VALIDITY_WINDOW_INSUFFICIENT",
                    "The selected certificate expires before the approved readiness window.",
                    "HIGH",
                )
            )
    except (TypeError, ValueError):
        findings.append(
            _finding(
                "certificate",
                "SIGNING_CERTIFICATE_VALIDITY_INVALID",
                "The selected certificate validity period could not be verified.",
                "HIGH",
            )
        )

    if not managed_key_attested:
        findings.append(
            _finding(
                "certificate",
                "MANAGED_KEY_CUSTODY_NOT_ATTESTED",
                "Hardware-backed, non-exportable, or equivalently controlled key custody requires operator attestation.",
                "MEDIUM",
            )
        )

    certificate = {
        "store": str(item.get("store") or "UNKNOWN"),
        "has_private_key": has_private_key,
        "code_signing_eku": code_signing_eku,
        "trusted_chain": trusted_chain,
        "not_before_utc": not_before_text or None,
        "not_after_utc": not_after_text or None,
        "remaining_valid_days": remaining_days,
    }
    return {
        **base,
        "status": _status_for_findings(findings),
        "matches": 1,
        "certificate": certificate,
        "findings": findings,
    }


def capture_timestamp_configuration(timestamp_url: str) -> dict:
    findings: list[dict] = []
    try:
        parsed = urlparse(timestamp_url)
        parsed.port
    except ValueError:
        parsed = urlparse("")
    valid = bool(
        parsed.scheme.lower() == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )
    if not valid:
        findings.append(
            _finding(
                "timestamp",
                "TIMESTAMP_URL_INVALID",
                "The Authenticode timestamp URL must be an HTTPS endpoint without embedded credentials.",
                "HIGH",
            )
        )
    return {
        "status": _status_for_findings(findings),
        "configured": valid,
        "scheme": parsed.scheme.lower() if valid else None,
        "host": parsed.hostname.lower() if valid and parsed.hostname else None,
        "findings": findings,
    }


def _normalized_findings(components: dict[str, dict]) -> list[dict]:
    normalized: list[dict] = []
    for component_name, component in components.items():
        findings = component.get("findings") or []
        for item in findings:
            normalized.append(
                {
                    "component": str(item.get("component") or component_name),
                    "code": str(item.get("code") or "SIGNING_READINESS_FINDING"),
                    "detail": str(
                        item.get("detail")
                        or "Code-signing readiness review is required."
                    ),
                    "severity": str(item.get("severity") or "HIGH").upper(),
                }
            )
        if str(component.get("status") or "").upper() == "FAIL" and not findings:
            normalized.append(
                _finding(
                    component_name,
                    "SIGNING_READINESS_COMPONENT_FAILED",
                    f"{component_name} failed without a diagnostic finding.",
                    "HIGH",
                )
            )
    return normalized


def capture_signing_readiness(
    *,
    python_path: Path | None = None,
    thumbprint: str | None = None,
    timestamp_url: str = DEFAULT_TIMESTAMP_URL,
    minimum_valid_days: int = DEFAULT_MINIMUM_VALID_DAYS,
    managed_key_attested: bool = False,
    python_probe: Callable[[], dict | None] | None = None,
    sign_tool_resolver: Callable[[], Path | None] = _resolve_sign_tool,
    inno_resolver: Callable[[], Path | None] = _resolve_inno_setup,
    certificate_probe: Callable[[str], list[dict]] = _probe_windows_certificate,
    now: datetime | None = None,
) -> dict:
    components = {
        "python_runtime": _capture_component(
            "python_runtime",
            lambda: capture_python_runtime(
                python_path=python_path,
                probe=python_probe,
            ),
        ),
        "sign_tool": _capture_component(
            "sign_tool",
            lambda: capture_sign_tool(resolver=sign_tool_resolver),
        ),
        "installer_compiler": _capture_component(
            "installer_compiler",
            lambda: capture_inno_setup(resolver=inno_resolver),
        ),
        "certificate": _capture_component(
            "certificate",
            lambda: capture_certificate(
                thumbprint=thumbprint,
                minimum_valid_days=minimum_valid_days,
                managed_key_attested=managed_key_attested,
                now=now,
                probe=certificate_probe,
            ),
        ),
        "timestamp": _capture_component(
            "timestamp",
            lambda: capture_timestamp_configuration(timestamp_url),
        ),
    }
    findings = _normalized_findings(components)
    statuses = {
        str(component.get("status") or "FAIL").upper()
        for component in components.values()
    }
    status = _status_for_findings(findings)
    if "FAIL" in statuses:
        status = "FAIL"
    elif status == "PASS" and "REVIEW" in statuses:
        status = "REVIEW"
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "thresholds": {
            "minimum_certificate_valid_days": minimum_valid_days,
            "required_python_major_minor": "3.11",
            "required_python_architecture_bits": 64,
            "required_certificate_eku": CODE_SIGNING_EKU,
        },
        "components": components,
        "finding_count": len(findings),
        "findings": findings,
    }


def write_report(report: dict, destination: Path) -> Path:
    resolved = destination.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, resolved)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return resolved


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only original Phase 5 code-signing readiness gate."
    )
    parser.add_argument("--python-path", type=Path)
    parser.add_argument(
        "--certificate-thumbprint",
        default=os.getenv("MTO_CODE_SIGNING_CERT_THUMBPRINT", ""),
    )
    parser.add_argument("--timestamp-url", default=DEFAULT_TIMESTAMP_URL)
    parser.add_argument(
        "--minimum-valid-days",
        type=_positive_int,
        default=DEFAULT_MINIMUM_VALID_DAYS,
    )
    parser.add_argument("--confirm-managed-key-custody", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    report = capture_signing_readiness(
        python_path=args.python_path,
        thumbprint=args.certificate_thumbprint,
        timestamp_url=args.timestamp_url,
        minimum_valid_days=args.minimum_valid_days,
        managed_key_attested=args.confirm_managed_key_custody,
    )
    report["require_ready"] = bool(args.require_ready)
    destination = write_report(report, args.output)

    print("ORIGINAL PHASE 5 CODE-SIGNING READINESS")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    certificate = report["components"]["certificate"]
    print(
        "- Selected certificate: "
        f"{certificate.get('thumbprint_short') or 'NOT SELECTED'}"
    )
    print(
        "- Managed key custody attested: "
        f"{'YES' if certificate.get('managed_key_custody_attested') else 'NO'}"
    )
    print(f"- Overall status: {report['status']}")
    print(f"- Findings: {report['finding_count']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(
            f"  - [{item['severity']}] {item['component']}/{item['code']}: "
            f"{item['detail']}"
        )

    if report["status"] == "PASS":
        print("  ORIGINAL PHASE 5 CODE-SIGNING READINESS PASSED")
        return 0
    if report["status"] == "REVIEW" and not args.require_ready:
        print("  ORIGINAL PHASE 5 CODE-SIGNING READINESS REQUIRES REVIEW")
        return 4
    print("  ORIGINAL PHASE 5 CODE-SIGNING READINESS BLOCKED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
