from pathlib import Path

from scripts.check_dependency_policy import (
    PROJECT_ROOT,
    parse_direct_requirements,
    parse_hash_lock,
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


def test_mutable_workflow_action_is_rejected(tmp_path: Path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
    )

    findings, action_count = validate_workflow_action_pins(tmp_path)

    assert action_count == 1
    assert [item["code"] for item in findings] == ["WORKFLOW_ACTION_NOT_IMMUTABLE"]
