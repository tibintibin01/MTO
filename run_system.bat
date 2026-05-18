@echo off
title MTO Treasury System Launcher
color 0B
echo =============================================================
echo               MTO TREASURY PORTAL ONE-CLICK LAUNCHER
echo =============================================================
echo.

:: Check if Docker is installed and running
docker info >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [DOCKER ACTIVE] Starting API & Database via Docker Compose...
    docker compose up -d
) else (
    echo [LOCAL FALLBACK] Docker not running. Starting local native API...
    start "MTO FastAPI Backend Server" cmd /k "title MTO Backend (Port 8001) && VENV\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8001"
)

echo [2/3] Starting Next.js Frontend Portal...
start "MTO Next.js Frontend Server" cmd /k "title MTO Frontend (Port 3000) && cd frontend && npm run dev"

echo [3/3] Warming up server environment (waiting 6 seconds)...
timeout /t 6 /nobreak > nul

echo.
echo Starting MTO Desktop Cashier App...
VENV\Scripts\python.exe clients/desktop/main.py

echo.
echo =============================================================
echo  - To view logs: Check command windows or run 'docker compose logs -f'.
echo  - To close the system: Close server windows or run 'docker compose down'.
echo =============================================================
echo.
pause
