@echo off
setlocal EnableExtensions
title MTO Immutable Release Updater
color 0A

REM Normalize the batch directory before passing it to PowerShell.  %~dp0 always
REM ends in a backslash; quoting that value directly can leave a stray quote in
REM the native PowerShell argument and make GetFullPath reject ProjectRoot.
for %%I in ("%~dp0.") do set "MTO_PROJECT_ROOT=%%~fI"
set "MTO_UPDATER=%MTO_PROJECT_ROOT%\scripts\apply_immutable_release.ps1"

cd /d "%MTO_PROJECT_ROOT%" || goto :project_root_error

if not exist "%MTO_UPDATER%" goto :missing_script

if "%~1"=="" goto :interactive_help
if "%~2"=="" goto :usage
if not "%~5"=="" goto :usage

if /I "%~3"=="--internal-only" goto :run_internal
if not "%~3"=="" goto :usage
if not "%~4"=="" goto :usage
goto :run_signed

:run_signed
echo ================================================
echo   MTO TREASURY SYSTEM - IMMUTABLE UPDATER
echo   Bayan ng Dipaculao, Aurora
echo ================================================
echo.
echo Release tag: %~1
echo Release package: %~2
echo Update mode: Signed production release
echo.

REM The PowerShell implementation runs phase5_supply_chain_preflight, verifies
REM release-manifest.json, calls capture_remediation_baseline, retains a
REM rollback ref, installs requirements.lock with hashes, and invokes
REM wait_for_mto_api.ps1 before declaring success.
powershell -NoProfile -ExecutionPolicy Bypass -File "%MTO_UPDATER%" ^
  -Apply ^
  -ReleaseTag "%~1" ^
  -Distribution "%~2" ^
  -ProjectRoot "%MTO_PROJECT_ROOT%"
goto :check_result

:run_internal
if "%~4"=="" goto :usage

echo ================================================
echo   MTO TREASURY SYSTEM - IMMUTABLE UPDATER
echo   Bayan ng Dipaculao, Aurora
echo ================================================
echo.
echo Release tag: %~1
echo Release package: %~2
echo Update mode: Unsigned internal-only release
echo Risk acceptance: %~4
echo.
echo WARNING: This mode is permitted only for controlled municipal computers.
echo WARNING: Do not distribute the package publicly or disable Windows Security.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%MTO_UPDATER%" ^
  -Apply ^
  -ReleaseTag "%~1" ^
  -Distribution "%~2" ^
  -InternalOnlyUnsignedRisk ^
  -RiskAcceptance "%~4" ^
  -ProjectRoot "%MTO_PROJECT_ROOT%"
goto :check_result

:check_result
set "MTO_UPDATE_RESULT=%ERRORLEVEL%"
if not "%MTO_UPDATE_RESULT%"=="0" (
  echo.
  echo ERROR: Immutable release update did not complete.
  echo Exit code: %MTO_UPDATE_RESULT%
  echo Review the protected update evidence before approving recovery or rollback.
  echo.
  pause
  exit /b %MTO_UPDATE_RESULT%
)

echo.
echo ================================================
echo IMMUTABLE MTO RELEASE ACTIVATION COMPLETED
echo ================================================
echo.
pause
exit /b 0

:interactive_help
echo.
echo This updater requires an approved immutable release tag and staged package.
echo It must be run once from an Administrator Command Prompt for each release.
echo Double-clicking it without those release arguments will not install anything.
echo.
echo Example for the approved internal-only process:
echo   call update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z --internal-only C:\mto\governance\accepted-risks\original-phase-5-unsigned-internal-only.json
echo.
pause
exit /b 2

:missing_script
echo.
echo ERROR: Required updater implementation was not found:
echo   %MTO_UPDATER%
echo Synchronize the approved repository before attempting an update.
echo.
pause
exit /b 2

:project_root_error
echo.
echo ERROR: The MTO project directory could not be opened:
echo   %MTO_PROJECT_ROOT%
echo.
pause
exit /b 2

:usage
echo Usage: update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z
echo    or: update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z --internal-only C:\path\risk-acceptance.json
echo.
echo The release must be an approved immutable tag and the package must contain
echo release-manifest.json and sbom.cdx.json. Signatures are mandatory unless
echo the explicit, unexpired internal-only risk exception is selected.
exit /b 2
