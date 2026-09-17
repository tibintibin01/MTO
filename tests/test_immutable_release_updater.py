from pathlib import Path

from scripts.phase5_supply_chain_preflight import PROJECT_ROOT


def _read(relative: str) -> str:
    return (PROJECT_ROOT / Path(relative)).read_text(encoding="utf-8")


def test_batch_entrypoint_requires_explicit_tag_and_release_package():
    wrapper = _read("update_mto.bat")

    assert "apply_immutable_release.ps1" in wrapper
    assert '-ReleaseTag "%~1"' in wrapper
    assert '-Distribution "%~2"' in wrapper
    assert "git pull --ff-only origin master" not in wrapper.lower()


def test_updater_fetches_and_switches_only_the_selected_immutable_tag():
    updater = _read("scripts/apply_immutable_release.ps1")

    assert "refs/heads/master:refs/remotes/origin/master" in updater
    assert "refs/tags/$ReleaseTag`:refs/tags/$ReleaseTag" in updater
    assert "refs/tags/$ReleaseTag`^{commit}" in updater
    assert "git pull" not in updater.lower()
    assert "@('merge', '--ff-only', $targetCommit)" in updater
    assert "$targetCommit -ne $remoteCommit" in updater
    assert "selected immutable release is already active" in updater


def test_updater_verifies_release_before_service_interruption():
    updater = _read("scripts/apply_immutable_release.ps1")

    package_gate = updater.index("Assert-ReleasePackage $resolvedDistribution")
    confirmation = updater.index("Read-Host", package_gate)
    stop_runtime = updater.index("Stop-MtoRuntime $resolvedProject", confirmation)

    assert package_gate < confirmation < stop_runtime
    assert "release-manifest.json" in updater
    assert "Get-AuthenticodeSignature" in updater
    assert "sbom.cdx.json" in updater
    assert "ReparsePoint" in updater
    assert "must be staged outside the active checkout" in updater


def test_updater_captures_evidence_and_enforces_post_update_gates():
    updater = _read("scripts/apply_immutable_release.ps1")

    for token in (
        "scripts.capture_remediation_baseline",
        "scripts.phase5_supply_chain_preflight",
        "--require-hashes",
        "requirements.lock",
        "scripts.phase5_audit_observability_preflight",
        "wait_for_mto_api.ps1",
        "--compare-to",
        "New-LockedRuntime",
        "Switch-LockedRuntime",
        "relocated release runtime dependency check failed",
    ):
        assert token in updater


def test_updater_retains_and_exercises_bounded_code_rollback():
    updater = _read("scripts/apply_immutable_release.ps1")

    assert "refs/mto/rollback/$recordId" in updater
    assert "git' @('cat-file', '-e'" in updater
    assert "git' @('reset', '--hard', $rollbackCommit)" in updater
    assert "git' @('reset', '--hard', $previousCommit)" in updater
    assert "ROLLED_BACK_PRE_MIGRATION" in updater
    assert "ABORTED_PRE_SWITCH_RUNTIME_RESTORED" in updater
    assert "Stop-MtoRuntime $resolvedProject" in updater
    assert "Restore-LockedRuntime" in updater
    assert "previous_runtime" in updater
    assert "Database schema was not reversed." in updater
    assert "rollback_status = 'FAILED'" in updater
