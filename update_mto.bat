@echo off
title MTO System Updater
color 0A
echo ================================================
echo   MTO TREASURY SYSTEM - AUTO UPDATER
echo   Bayan ng Dipaculao, Aurora
echo ================================================
echo.

echo [1/5] Pulling latest code from GitHub...
cd /d C:\MTO

REM Frontend installs/builds can rewrite tracked generated artifacts and block
REM the next pull. Restore only these known-safe files before updating. This
REM never touches MariaDB, backups, .env, server_config.json, or office records.
for %%F in (frontend/package-lock.json frontend/public/sw.js frontend/public/workbox-6747d6ad.js) do (
    git diff --quiet -- "%%F"
    if errorlevel 1 (
        echo Local generated-file drift detected: %%F
        git restore -- "%%F"
    )
)

git pull --ff-only origin master
if %errorlevel% neq 0 (
    echo ERROR: Git pull failed.
    echo This is usually caused by local source changes, a stuck Git process, or network trouble.
    echo Run: git status --short
    pause
    exit /b 1
)
echo Done.
echo.

echo [2/5] Stopping old services safely...
set "MTO_API_TASK_INSTALLED="
schtasks /Query /TN "MTO Treasury API" >nul 2>&1
if %errorlevel% equ 0 (
    set "MTO_API_TASK_INSTALLED=1"
    schtasks /End /TN "MTO Treasury API" >nul 2>&1
)
taskkill /f /fi "WINDOWTITLE eq MTO Backend" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq MTO Frontend" >nul 2>&1
timeout /t 3 >nul
echo Done.
echo.

echo [3/5] Installing/updating Python dependencies...
call venv\Scripts\activate
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo ERROR: Python dependency update failed. Services were not restarted.
    pause
    exit /b 1
)
echo Done.
echo.

echo [4/5] Rebuilding frontend...
cd C:\MTO\frontend
call npm ci --silent
if %errorlevel% neq 0 (
    echo ERROR: Frontend dependency update failed. Services were not restarted.
    pause
    exit /b 1
)
call npm run build
if %errorlevel% neq 0 (
    echo ERROR: Frontend build failed.
    pause
    exit /b 1
)
echo Done.
echo.

echo [5/5] Starting updated services...
cd C:\MTO
call venv\Scripts\activate
if defined MTO_API_TASK_INSTALLED (
    schtasks /Run /TN "MTO Treasury API" >nul
    if errorlevel 1 (
        echo ERROR: The automatic API recovery task could not be started.
        echo Run this updater as Administrator and check Task Scheduler.
        pause
        exit /b 1
    )
) else (
    start "MTO Backend" cmd /k "python scripts\run_api_supervisor.py"
)
timeout /t 5 >nul
cd C:\MTO\frontend
start "MTO Frontend" cmd /k "npm start"
echo Done.
echo.

echo ================================================
echo   UPDATE COMPLETE! System is now running.
echo   Backend:  http://localhost:8001
echo   Frontend: http://localhost:3000
echo ================================================
echo.
pause
