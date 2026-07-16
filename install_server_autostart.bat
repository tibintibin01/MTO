@echo off
title Install MTO API Automatic Recovery
cd /d %~dp0
echo ================================================
echo   MTO API AUTOMATIC RECOVERY INSTALLER
echo ================================================
echo.
echo This must be run once on the SERVER PC as Administrator.
echo It starts the API at Windows boot and restarts it after failures.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_api_startup_task.ps1"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Automatic recovery was not installed.
    echo Right-click this file and choose Run as administrator.
    pause
    exit /b 1
)
echo.
echo Installation complete. The API recovery task is now active.
pause
