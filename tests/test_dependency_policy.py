from pathlib import Path

from scripts.check_dependency_policy import (
    PROJECT_ROOT,
    parse_direct_requirements,
    parse_hash_lock,
    validate_lock_portability,
    validate_repository,
    validate_workflow_action_pins,
)


def test_repository_dependency_policy_passes():
    findings, counts = validate_repository(PROJECT_ROOT)

    assert findings == []
    assert counts["runtime_direct"] > 0
    assert counts["frontend_locked"] > counts["frontend_direct"]


def test_unpinned_python_dependency_is_rejected(tmp_path: Path):
    manifest = tmp_path / "requirements.txt"
    manifest.write_text("fastapi>=1.0\n", encoding="utf-8")

    packages, findings = parse_direct_requirements(manifest)

    assert packages == {}
    assert [item["code"] for item in findings] == ["PYTHON_NOT_EXACTLY_PINNED"]


def test_python_lock_entry_requires_sha256(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("fastapi==1.0\n", encoding="utf-8")

    packages, findings = parse_hash_lock(lock)

    assert packages == {"fastapi": "1.0"}
    assert [item["code"] for item in findings] == ["LOCK_ENTRY_WITHOUT_SHA256"]


def test_non_universal_python_lock_is_rejected(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# generated without cross-platform resolution\n"
        "fastapi==1.0 \\\n"
        "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    findings = validate_lock_portability(lock)

    assert [item["code"] for item in findings] == ["LOCK_NOT_UNIVERSAL"]


def test_unmarked_windows_only_package_is_rejected(tmp_path: Path):
    lock = tmp_path / "dev-requirements.lock"
    lock.write_text(
        "# uv pip compile --universal\n" "pywin32==312 \\\n" "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    findings = validate_lock_portability(lock)

    assert [item["code"] for item in findings] == ["WINDOWS_ONLY_LOCK_MARKER_MISSING"]


def test_marked_windows_only_package_in_universal_lock_is_accepted(tmp_path: Path):
    lock = tmp_path / "dev-requirements.lock"
    lock.write_text(
        "# uv pip compile --universal\n"
        "pywin32==312 ; sys_platform == 'win32' \\\n"
        "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    assert validate_lock_portability(lock) == []


def test_mutable_workflow_action_is_rejected(tmp_path: Path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
    )

    findings, action_count = validate_workflow_action_pins(tmp_path)

    assert action_count == 1
    assert [item["code"] for item in findings] == ["WORKFLOW_ACTION_NOT_IMMUTABLE"]
