@echo off
setlocal
title Start MTO Treasury API
cd /d "%~dp0"

schtasks /Query /TN "MTO Treasury API" >nul 2>&1
if errorlevel 1 (
    echo ERROR: The MTO Treasury API scheduled task is not installed.
    echo Run scripts\install_api_startup_task.ps1 as Administrator.
    pause
    exit /b 1
)

echo Starting the managed MTO Treasury API supervisor...
schtasks /Run /TN "MTO Treasury API" >nul
if errorlevel 1 (
    echo ERROR: The MTO Treasury API scheduled task could not be started.
    echo Run this launcher as Administrator and check Task Scheduler.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\wait_for_mto_api.ps1" -TimeoutSeconds 90
if errorlevel 1 (
    echo ERROR: The authenticated HTTPS API did not become ready.
    echo Review %~dp0logs\api_supervisor.log.
    pause
    exit /b 1
)

echo MTO Treasury API is online with authenticated TLS.
pause
exit /b 0
