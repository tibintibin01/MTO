@echo off
title MTO Treasury System Launcher
color 0B
echo =============================================================
echo               MTO TREASURY PORTAL ONE-CLICK LAUNCHER
echo =============================================================
echo.

echo [1/3] Starting FastAPI Backend on Port 8001...
start "MTO FastAPI Backend Server" cmd /k "title MTO Backend (Port 8001) && VENV\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8001"

echo [2/3] Starting Next.js Frontend Portal...
start "MTO Next.js Frontend Server" cmd /k "title MTO Frontend (Port 3000) && cd frontend && npm run dev"

echo [3/3] Warming up server environment (waiting 6 seconds)...
timeout /t 6 /nobreak > nul

echo.
echo Starting MTO Desktop Cashier App...
VENV\Scripts\python.exe clients/desktop/main.py

echo.
echo =============================================================
echo  - To view logs: Check the two newly opened cmd windows.
echo  - To close the system: Simply close both cmd server windows.
echo =============================================================
echo.
pause
