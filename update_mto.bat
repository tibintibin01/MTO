@echo off
setlocal
title MTO Immutable Release Updater
color 0A

cd /d "%~dp0"

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
if not "%~3"=="" if /I not "%~3"=="--internal-only" goto :usage
if /I "%~3"=="--internal-only" if "%~4"=="" goto :usage

echo ================================================
echo   MTO TREASURY SYSTEM - IMMUTABLE UPDATER
echo   Bayan ng Dipaculao, Aurora
echo ================================================
echo.
echo Release tag: %~1
echo Release package: %~2
echo.

REM The PowerShell implementation runs phase5_supply_chain_preflight, verifies
REM release-manifest.json, calls capture_remediation_baseline, retains a
REM rollback ref, installs requirements.lock with hashes, and invokes
REM wait_for_mto_api.ps1 before declaring success.
if /I "%~3"=="--internal-only" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\apply_immutable_release.ps1" ^
    -Apply ^
    -ReleaseTag "%~1" ^
    -Distribution "%~2" ^
    -InternalOnlyUnsignedRisk ^
    -RiskAcceptance "%~4" ^
    -ProjectRoot "%~dp0"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\apply_immutable_release.ps1" ^
    -Apply ^
    -ReleaseTag "%~1" ^
    -Distribution "%~2" ^
    -ProjectRoot "%~dp0"
)

set "MTO_UPDATE_RESULT=%ERRORLEVEL%"
if not "%MTO_UPDATE_RESULT%"=="0" (
    echo.
    echo ERROR: Immutable release update did not complete.
    echo Review the protected update evidence before approving recovery or rollback.
    pause
    exit /b %MTO_UPDATE_RESULT%
)

echo.
echo Immutable MTO release activation completed successfully.
pause
exit /b 0

:usage
echo Usage: update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z
echo    or: update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z --internal-only C:\path\risk-acceptance.json
echo.
echo The release must be an approved immutable tag and the package must contain
echo release-manifest.json and sbom.cdx.json. Signatures are mandatory unless
echo the explicit, unexpired internal-only risk exception is selected.
exit /b 2
