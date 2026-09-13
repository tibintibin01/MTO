"""Fail closed when dependency manifests, locks, or install gates drift."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXACT_RUNTIME_MINIMUMS = {
    "cryptography": "50.0.1",
    "fastapi": "0.141.1",
    "pillow": "12.3.0",
    "pyjwt": "2.13.0",
    "pymysql": "1.2.0",
    "python-dotenv": "1.2.3",
    "python-multipart": "0.0.32",
    "requests": "2.34.2",
    "sentry-sdk": "2.69.1",
    "uvicorn": "0.52.4",
}
EXACT_FRONTEND_MINIMUMS = {
    "@serwist/next": "9.5.12",
    "eslint-config-next": "16.3.4",
    "next": "16.3.4",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "serwist": "9.5.12",
}
FORBIDDEN_PYTHON = {"python-jose"}
FORBIDDEN_FRONTEND = {"next-pwa", "workbox-webpack-plugin"}
LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
ACTION_USE = re.compile(r"\buses:\s*([^\s#]+)")
IMMUTABLE_ACTION_REF = re.compile(r"[^@\s]+@[0-9a-f]{40}")


def finding(code: str, path: Path, detail: str) -> dict[str, str]:
    return {"code": code, "path": str(path), "detail": detail}


def parse_direct_requirements(
    path: Path,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    packages: dict[str, str] = {}
    findings: list[dict[str, str]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "git+", "http://", "https://")):
            findings.append(
                finding(
                    "PYTHON_UNSAFE_SOURCE",
                    path,
                    f"line {line_number} is not an index pin",
                )
            )
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            findings.append(
                finding(
                    "PYTHON_INVALID_REQUIREMENT", path, f"line {line_number}: {exc}"
                )
            )
            continue
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==" or requirement.url:
            findings.append(
                finding(
                    "PYTHON_NOT_EXACTLY_PINNED",
                    path,
                    f"line {line_number}: {requirement}",
                )
            )
            continue
        name = canonicalize_name(requirement.name)
        if name in packages:
            findings.append(
                finding(
                    "PYTHON_DUPLICATE_DIRECT_PIN",
                    path,
                    f"duplicate direct dependency: {name}",
                )
            )
        packages[name] = specifiers[0].version
    return packages, findings


def parse_hash_lock(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    packages: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = LOCK_LINE.match(lines[index])
        if not match:
            index += 1
            continue
        name = canonicalize_name(match.group(1))
        packages[name] = match.group(2)
        block = lines[index]
        while block.rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            block += "\n" + lines[index]
        if "--hash=sha256:" not in block:
            findings.append(
                finding(
                    "LOCK_ENTRY_WITHOUT_SHA256",
                    path,
                    f"{name} has no SHA-256 artifact hash",
                )
            )
        index += 1
    if not packages:
        findings.append(finding("LOCK_EMPTY", path, "no locked packages were found"))
    return packages, findings


def _check_minimums(
    packages: dict[str, str], minimums: dict[str, str], path: Path, ecosystem: str
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for name, minimum in minimums.items():
        actual = packages.get(name)
        if actual is None:
            findings.append(
                finding(f"{ecosystem}_REQUIRED_PACKAGE_MISSING", path, name)
            )
            continue
        try:
            if Version(actual) < Version(minimum):
                findings.append(
                    finding(
                        f"{ecosystem}_SECURITY_FLOOR",
                        path,
                        f"{name} {actual} is below {minimum}",
                    )
                )
        except ValueError:
            findings.append(
                finding(f"{ecosystem}_INVALID_VERSION", path, f"{name}: {actual}")
            )
    return findings


def validate_workflow_action_pins(
    root: Path,
) -> tuple[list[dict[str, str]], int]:
    """Require third-party workflow actions to use immutable commit SHAs."""
    findings: list[dict[str, str]] = []
    action_count = 0
    workflows = root / ".github" / "workflows"
    for path in sorted(workflows.glob("*.y*ml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = ACTION_USE.search(line)
            if not match:
                continue
            action_ref = match.group(1)
            if action_ref.startswith("./"):
                continue
            action_count += 1
            if not IMMUTABLE_ACTION_REF.fullmatch(action_ref):
                findings.append(
                    finding(
                        "WORKFLOW_ACTION_NOT_IMMUTABLE",
                        path,
                        f"line {line_number}: {action_ref}",
                    )
                )
    return findings, action_count


def validate_repository(
    root: Path = PROJECT_ROOT,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    findings: list[dict[str, str]] = []
    runtime_path = root / "requirements.txt"
    dev_path = root / "dev-requirements.txt"
    runtime_lock_path = root / "requirements.lock"
    dev_lock_path = root / "dev-requirements.lock"

    runtime, runtime_findings = parse_direct_requirements(runtime_path)
    dev, dev_findings = parse_direct_requirements(dev_path)
    findings.extend(runtime_findings)
    findings.extend(dev_findings)
    findings.extend(
        _check_minimums(runtime, EXACT_RUNTIME_MINIMUMS, runtime_path, "PYTHON")
    )
    for forbidden in sorted(FORBIDDEN_PYTHON & runtime.keys()):
        findings.append(finding("PYTHON_FORBIDDEN_PACKAGE", runtime_path, forbidden))

    runtime_lock, runtime_lock_findings = parse_hash_lock(runtime_lock_path)
    dev_lock, dev_lock_findings = parse_hash_lock(dev_lock_path)
    findings.extend(runtime_lock_findings)
    findings.extend(dev_lock_findings)
    for name, version in runtime.items():
        if runtime_lock.get(name) != version:
            findings.append(
                finding(
                    "RUNTIME_LOCK_DRIFT",
                    runtime_lock_path,
                    f"{name}: manifest={version}, lock={runtime_lock.get(name)}",
                )
            )
        if dev_lock.get(name) != version:
            findings.append(
                finding(
                    "DEV_LOCK_RUNTIME_DRIFT",
                    dev_lock_path,
                    f"{name}: manifest={version}, lock={dev_lock.get(name)}",
                )
            )
    for name, version in dev.items():
        if dev_lock.get(name) != version:
            findings.append(
                finding(
                    "DEV_LOCK_DRIFT",
                    dev_lock_path,
                    f"{name}: manifest={version}, lock={dev_lock.get(name)}",
                )
            )

    pyproject_path = root / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    if project.get("requires-python") != ">=3.11":
        findings.append(
            finding(
                "PYTHON_RUNTIME_CONTRACT",
                pyproject_path,
                "requires-python must be >=3.11",
            )
        )
    if project.get("dynamic") != ["dependencies"] or "dependencies" in project:
        findings.append(
            finding(
                "PYTHON_DUPLICATE_MANIFEST",
                pyproject_path,
                "dependencies must load only from requirements.txt",
            )
        )
    dynamic = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    if dynamic.get("dependencies", {}).get("file") != ["requirements.txt"]:
        findings.append(
            finding(
                "PYTHON_DYNAMIC_MANIFEST",
                pyproject_path,
                "setuptools must load requirements.txt",
            )
        )

    package_path = root / "frontend" / "package.json"
    package_lock_path = root / "frontend" / "package-lock.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
    frontend = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    non_exact = sorted(
        name
        for name, version in frontend.items()
        if not re.fullmatch(r"\d+(?:\.\d+){2}(?:[-+][0-9A-Za-z.-]+)?", version)
    )
    if non_exact:
        findings.append(
            finding("FRONTEND_NOT_EXACTLY_PINNED", package_path, ", ".join(non_exact))
        )
    findings.extend(
        _check_minimums(frontend, EXACT_FRONTEND_MINIMUMS, package_path, "FRONTEND")
    )
    for forbidden in sorted(FORBIDDEN_FRONTEND & frontend.keys()):
        findings.append(finding("FRONTEND_FORBIDDEN_PACKAGE", package_path, forbidden))
    if package.get("engines", {}).get("node") != ">=20.9.0":
        findings.append(
            finding("NODE_RUNTIME_CONTRACT", package_path, "Node.js must be >=20.9.0")
        )

    lock_root = package_lock.get("packages", {}).get("", {})
    locked_frontend = {
        **lock_root.get("dependencies", {}),
        **lock_root.get("devDependencies", {}),
    }
    for name, version in frontend.items():
        if locked_frontend.get(name) != version:
            findings.append(
                finding(
                    "FRONTEND_LOCK_DRIFT",
                    package_lock_path,
                    f"{name}: manifest={version}, lock={locked_frontend.get(name)}",
                )
            )
    locked_paths = package_lock.get("packages", {})
    for forbidden in FORBIDDEN_FRONTEND:
        if f"node_modules/{forbidden}" in locked_paths:
            findings.append(
                finding("FRONTEND_FORBIDDEN_TRANSITIVE", package_lock_path, forbidden)
            )

    sw_path = root / "frontend" / "app" / "sw.ts"
    sw_text = sw_path.read_text(encoding="utf-8")
    if not all(token in sw_text for token in ("NetworkOnly", "'/api/'", "'/admin'")):
        findings.append(
            finding(
                "SERVICE_WORKER_SENSITIVE_CACHE_POLICY",
                sw_path,
                "API and admin routes must be network-only",
            )
        )
    next_config_text = (root / "frontend" / "next.config.js").read_text(
        encoding="utf-8"
    )
    if "next-pwa" in next_config_text or "@serwist/next" not in next_config_text:
        findings.append(
            finding(
                "SERVICE_WORKER_PROVIDER",
                root / "frontend" / "next.config.js",
                "Serwist must be the configured provider",
            )
        )

    required_text = {
        root / "update_mto.bat": ["--require-hashes -r requirements.lock"],
        root / "Dockerfile": ["--require-hashes", "requirements.lock"],
        root
        / ".github"
        / "workflows"
        / "ci.yml": [
            "dev-requirements.lock",
            "pip-audit -r requirements.lock",
            "npm audit --audit-level=moderate",
        ],
        root
        / ".github"
        / "workflows"
        / "deploy.yml": ["dev-requirements.lock", "pip-audit -r requirements.lock"],
    }
    for path, tokens in required_text.items():
        content = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in content:
                findings.append(finding("DEPENDENCY_GATE_MISSING", path, token))
    ci_text = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    audit_section = ci_text[
        ci_text.find("Audit dependencies for CVEs") : ci_text.find(
            "Run unit + integration"
        )
    ]
    if "continue-on-error" in audit_section:
        findings.append(
            finding(
                "DEPENDENCY_AUDIT_NON_BLOCKING",
                root / ".github" / "workflows" / "ci.yml",
                "Python audit must fail CI",
            )
        )

    action_findings, workflow_action_count = validate_workflow_action_pins(root)
    findings.extend(action_findings)

    counts = {
        "runtime_direct": len(runtime),
        "runtime_locked": len(runtime_lock),
        "development_direct": len(dev),
        "development_locked": len(dev_lock),
        "frontend_direct": len(frontend),
        "frontend_locked": max(len(locked_paths) - 1, 0),
        "workflow_actions": workflow_action_count,
    }
    return findings, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional privacy-safe JSON report")
    args = parser.parse_args(argv)
    findings, counts = validate_repository()
    status = "PASS" if not findings else "FAIL"
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "counts": counts,
        "findings": findings,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"PHASE 4 DEPENDENCY POLICY: {status}")
    for key, value in counts.items():
        print(f"- {key}: {value}")
    for item in findings:
        print(f"- [{item['code']}] {item['path']}: {item['detail']}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
