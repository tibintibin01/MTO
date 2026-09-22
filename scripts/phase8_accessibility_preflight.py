"""Read-only code-quality and desktop accessibility gate for Phase 8."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


def _resolve_project_root(
    script_file: str | os.PathLike[str] = __file__,
    environment: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    configured = str(environment.get("MTO_PROJECT_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(script_file).resolve().parents[1]


PROJECT_ROOT = _resolve_project_root()
DEFAULT_REPORT = PROJECT_ROOT / "logs" / "remediation-original-phase-8-assessment.json"
FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_8_ACCESSIBILITY"

TARGET_FILES = (
    "clients/desktop/main.py",
    "clients/desktop/dashboard.py",
    "clients/desktop/theme_manager.py",
    "ui/accessibility.py",
    "ui/navigation.py",
    "ui/help_page.py",
)


def _finding(component: str, code: str, detail: str, severity: str = "HIGH") -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _status(findings: list[dict]) -> str:
    return "FAIL" if findings else "PASS"


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if completed.returncode != 0:
        raise RuntimeError("Git source inspection failed.")
    return completed.stdout.strip()


def capture_source_identity(root: Path = PROJECT_ROOT) -> dict:
    findings: list[dict] = []
    try:
        branch = _git(root, "branch", "--show-current")
        commit = _git(root, "rev-parse", "HEAD").lower()
        changes = _git(root, "status", "--porcelain", "--untracked-files=all")
    except Exception as exc:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    "source",
                    "SOURCE_INSPECTION_FAILED",
                    f"Source inspection failed with {type(exc).__name__}.",
                )
            ],
        }
    if branch != "master":
        findings.append(
            _finding("source", "SOURCE_BRANCH_NOT_MASTER", "Source is not on master.")
        )
    if changes:
        findings.append(
            _finding(
                "source",
                "SOURCE_WORKTREE_DIRTY",
                "Source contains tracked or untracked changes.",
            )
        )
    return {
        "status": _status(findings),
        "branch": branch,
        "commit": commit,
        "clean": not bool(changes),
        "findings": findings,
    }


def capture_python_syntax(root: Path = PROJECT_ROOT) -> dict:
    findings: list[dict] = []
    checked: list[str] = []
    for relative_name in TARGET_FILES:
        path = root / relative_name
        if not path.is_file():
            findings.append(
                _finding(
                    "python_syntax",
                    "ACCESSIBILITY_MODULE_MISSING",
                    f"Required Phase 8 source is missing: {relative_name}.",
                )
            )
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative_name)
            checked.append(relative_name)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(
                _finding(
                    "python_syntax",
                    "UI_SOURCE_INVALID",
                    f"{relative_name} failed syntax validation with {type(exc).__name__}.",
                )
            )
    return {
        "status": _status(findings),
        "checked_files": checked,
        "findings": findings,
    }


def _read_sources(root: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for relative_name in TARGET_FILES:
        path = root / relative_name
        sources[relative_name] = (
            path.read_text(encoding="utf-8") if path.is_file() else ""
        )
    return sources


def capture_ui_contracts(root: Path = PROJECT_ROOT) -> dict:
    sources = _read_sources(root)
    requirements = (
        (
            "clients/desktop/main.py",
            "from mto_version import PRODUCT_VERSION",
            "RELEASE_VERSION_NOT_AUTHORITATIVE",
            "The login screen must use the authoritative product version.",
        ),
        (
            "clients/desktop/main.py",
            "self.peek_btn",
            "PASSWORD_CONTROL_NOT_BUTTON",
            "Password visibility must use a labeled button.",
        ),
        (
            "clients/desktop/main.py",
            "bind_keyboard_activation(",
            "LOGIN_KEYBOARD_ACTIVATION_MISSING",
            "The password control must support keyboard activation.",
        ),
        (
            "clients/desktop/main.py",
            "self.after(100, self.ue.focus_set)",
            "LOGIN_INITIAL_FOCUS_MISSING",
            "Login must place initial focus on the username field.",
        ),
        (
            "clients/desktop/dashboard.py",
            'self.bind("<F1>", self._open_help_from_keyboard)',
            "HELP_SHORTCUT_MISSING",
            "F1 must open the in-application Help guide.",
        ),
        (
            "ui/navigation.py",
            "ModernTheme.PRIMARY_SURFACE",
            "NAVIGATION_CONTRAST_TOKEN_MISSING",
            "Active navigation must use the approved contrast-safe surface.",
        ),
        (
            "ui/navigation.py",
            "Language:",
            "LANGUAGE_CONTROL_LABEL_MISSING",
            "The language control requires a visible text label.",
        ),
        (
            "ui/help_page.py",
            "Tab / Shift + Tab",
            "KEYBOARD_GUIDANCE_INCOMPLETE",
            "Help must document keyboard focus navigation.",
        ),
        (
            "ui/accessibility.py",
            "def bind_keyboard_activation(",
            "SHARED_KEYBOARD_ADAPTER_MISSING",
            "A shared keyboard and focus adapter is required.",
        ),
    )
    findings: list[dict] = []
    for relative_name, required_text, code, detail in requirements:
        if required_text not in sources[relative_name]:
            findings.append(_finding("ui_contracts", code, detail))
    navigation_binding_count = sources["ui/navigation.py"].count(
        "bind_keyboard_activation("
    )
    login_binding_count = sources["clients/desktop/main.py"].count(
        "bind_keyboard_activation("
    )
    if login_binding_count < 4:
        findings.append(
            _finding(
                "ui_contracts",
                "LOGIN_KEYBOARD_COVERAGE_INCOMPLETE",
                "Password, remember-me, login, and theme controls require keyboard support.",
            )
        )
    if navigation_binding_count < 4:
        findings.append(
            _finding(
                "ui_contracts",
                "NAVIGATION_KEYBOARD_COVERAGE_INCOMPLETE",
                "Navigation, theme, language, and logout controls require keyboard support.",
            )
        )
    for forbidden, code, detail in (
        (
            "v2.1.0",
            "STALE_VISIBLE_VERSION",
            "The login shell still contains a stale visible release version.",
        ),
        (
            "self.peek_lbl",
            "MOUSE_ONLY_PASSWORD_CONTROL",
            "The mouse-only password visibility label is still present.",
        ),
    ):
        if forbidden in sources["clients/desktop/main.py"]:
            findings.append(_finding("ui_contracts", code, detail))
    return {
        "status": _status(findings),
        "login_keyboard_binding_count": login_binding_count,
        "navigation_keyboard_binding_count": navigation_binding_count,
        "findings": findings,
    }


def _theme_constants(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ModernTheme":
            values: dict[str, str] = {}
            for statement in node.body:
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target = statement.targets[0]
                if isinstance(target, ast.Name) and isinstance(
                    statement.value, ast.Constant
                ):
                    if isinstance(statement.value.value, str):
                        values[target.id] = statement.value.value
            return values
    return {}


def _linear_channel(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("invalid RGB color")
    channels = [int(value[index : index + 2], 16) for index in (0, 2, 4)]
    red, green, blue = (_linear_channel(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: str, second: str) -> float:
    first_luminance, second_luminance = _luminance(first), _luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def capture_contrast_policy(root: Path = PROJECT_ROOT) -> dict:
    path = root / "clients" / "desktop" / "theme_manager.py"
    try:
        constants = _theme_constants(path)
    except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "ratios": {},
            "findings": [
                _finding(
                    "contrast",
                    "CONTRAST_POLICY_UNREADABLE",
                    f"Contrast policy failed with {type(exc).__name__}.",
                )
            ],
        }
    pairs = {
        "active_navigation": ("#ffffff", constants.get("PRIMARY_SURFACE"), 4.5),
        "destructive_action": ("#ffffff", constants.get("DANGER_SURFACE"), 4.5),
        "login_secondary_text": (
            constants.get("TEXT_SUB_DARK"),
            "#0a1628",
            4.5,
        ),
        "login_error_text": (
            constants.get("DANGER_TEXT_DARK"),
            "#0a1628",
            4.5,
        ),
        "keyboard_focus_ring": (constants.get("FOCUS_RING"), "#1e293b", 3.0),
    }
    findings: list[dict] = []
    ratios: dict[str, dict] = {}
    for name, (foreground, background, minimum) in pairs.items():
        try:
            ratio = _contrast(str(foreground), str(background))
        except (TypeError, ValueError):
            ratio = 0.0
        ratios[name] = {
            "ratio": round(ratio, 2),
            "minimum": minimum,
            "status": "PASS" if ratio >= minimum else "FAIL",
        }
        if ratio < minimum:
            findings.append(
                _finding(
                    "contrast",
                    "WCAG_CONTRAST_THRESHOLD_NOT_MET",
                    f"{name} does not meet its approved contrast threshold.",
                )
            )
    return {"status": _status(findings), "ratios": ratios, "findings": findings}


def capture_phase8_assessment(root: Path = PROJECT_ROOT) -> dict:
    components = {
        "source": capture_source_identity(root),
        "python_syntax": capture_python_syntax(root),
        "ui_contracts": capture_ui_contracts(root),
        "contrast": capture_contrast_policy(root),
    }
    findings = [
        finding
        for component in components.values()
        for finding in component.get("findings", [])
    ]
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY",
        "status": _status(findings),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the read-only original Phase 8 accessibility gate."
    )
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = capture_phase8_assessment()
    destination = write_report(report, args.output)
    print("ORIGINAL PHASE 8 CODE QUALITY AND ACCESSIBILITY PREFLIGHT")
    print("- Mode: READ ONLY")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Gate status: {report['status']}")
    print(f"- Findings: {report['finding_count']}")
    print(f"- Privacy-safe report: {destination}")
    for finding in report["findings"]:
        print(f"  - [{finding['severity']}] {finding['code']}: {finding['detail']}")
    if report["status"] == "PASS":
        print("  ORIGINAL PHASE 8 PREFLIGHT PASSED")
        return 0
    print("  ORIGINAL PHASE 8 PREFLIGHT BLOCKED")
    return 2 if args.require_ready else 4


if __name__ == "__main__":
    raise SystemExit(main())
