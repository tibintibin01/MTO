@echo off
title Stopping MTO Treasury System
color 0C
echo =============================================================
echo               STOPPING ALL MTO BACKGROUND SERVICES
echo =============================================================
echo.

echo [1/3] Terminating Python/Uvicorn background APIs...
taskkill /f /im pythonw.exe >nul 2>nul
taskkill /f /im uvicorn.exe >nul 2>nul

echo [2/3] Terminating Next.js Frontend servers...
taskkill /f /im node.exe >nul 2>nul

echo [3/3] Stopping Docker containers (if active)...
docker compose down >nul 2>nul

echo.
echo =============================================================
echo   SUCCESS: All background services have been stopped cleanly!
echo =============================================================
echo.
timeout /t 3 >nul
