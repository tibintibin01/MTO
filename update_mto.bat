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

REM Client machines should not keep local dependency-lock changes. npm install
REM can rewrite this file and block future pulls, so restore only this generated
REM lockfile before updating. Do not touch office data or other source files.
git diff --quiet -- frontend/package-lock.json
if %errorlevel% neq 0 (
    echo Local frontend package-lock drift detected. Restoring tracked lockfile...
    git restore -- frontend/package-lock.json
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

echo [2/5] Installing/updating Python dependencies...
call venv\Scripts\activate
pip install -r requirements.txt -q
echo Done.
echo.

echo [3/5] Rebuilding frontend...
cd C:\MTO\frontend
call npm ci --silent
call npm run build
if %errorlevel% neq 0 (
    echo ERROR: Frontend build failed.
    pause
    exit /b 1
)
echo Done.
echo.

echo [4/5] Stopping old services...
taskkill /f /fi "WINDOWTITLE eq MTO Backend" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq MTO Frontend" >nul 2>&1
timeout /t 3 >nul
echo Done.
echo.

echo [5/5] Starting updated services...
cd C:\MTO
call venv\Scripts\activate
start "MTO Backend" cmd /k "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001"
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
