from pathlib import Path

from scripts.phase5_supply_chain_preflight import PROJECT_ROOT


def _read(relative: str) -> str:
    return (PROJECT_ROOT / Path(relative)).read_text(encoding="utf-8")


def test_batch_entrypoint_requires_explicit_tag_and_release_package():
    wrapper = _read("update_mto.bat")

    assert "apply_immutable_release.ps1" in wrapper
    assert '-ReleaseTag "%~1"' in wrapper
    assert '-Distribution "%~2"' in wrapper
    assert 'for %%I in ("%~dp0.") do set "MTO_PROJECT_ROOT=%%~fI"' in wrapper
    assert '-ProjectRoot "%MTO_PROJECT_ROOT%"' in wrapper
    assert '-ProjectRoot "%~dp0"' not in wrapper
    assert 'if not "%~5"=="" goto :usage' in wrapper
    assert ":interactive_help" in wrapper
    assert "Double-clicking it without those release arguments" in wrapper
    assert "git pull --ff-only origin master" not in wrapper.lower()


def test_unsigned_internal_release_requires_explicit_bounded_exception():
    wrapper = _read("update_mto.bat")
    updater = _read("scripts/apply_immutable_release.ps1")

    assert "--internal-only" in wrapper
    assert "-InternalOnlyUnsignedRisk" in wrapper
    assert "-RiskAcceptance" in wrapper
    assert "RiskAcceptance cannot be used without InternalOnlyUnsignedRisk" in updater
    assert "--distribution-scope', 'internal-municipal'" in updater
    assert "Assert-UnsignedInternalRiskAcceptance" in updater
    assert "--risk-acceptance', $riskEvidence" in updater
    assert "risk_acceptance_sha256" in updater
    assert "risk-acceptance.json" in updater
    assert "changed while update evidence was captured" in updater
    assert "APPLY UNSIGNED INTERNAL-ONLY MTO RELEASE $ReleaseTag" in updater
    assert "Do not disable Windows Security" in updater


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

    package_gate = updater.index("Assert-ReleasePackage `")
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
        "release runtime dependency check failed",
        "Resolve-BasePython",
    ):
        assert token in updater


def test_windows_runtime_is_built_at_its_final_path_instead_of_relocated():
    updater = _read("scripts/apply_immutable_release.ps1")

    switch_start = updater.index("function Switch-LockedRuntime")
    switch_end = updater.index("function Restore-LockedRuntime", switch_start)
    switch = updater[switch_start:switch_end]

    retain_previous = switch.index(
        "Move-Item -LiteralPath $ActiveRuntime -Destination $PreviousRuntime"
    )
    build_final = switch.index(
        "[void](New-LockedRuntime $BootstrapPython $ActiveRuntime)"
    )

    assert retain_previous < build_final
    assert "CandidateRuntime" not in switch
    assert "candidate-venv" not in updater
    assert "Windows virtual environments embed their creation path" in updater
    assert "bootstrap_python = $bootstrapPython" in updater


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
