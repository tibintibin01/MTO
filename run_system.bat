@echo off
setlocal
set PYTHONPATH=%~dp0

echo ========================================
echo   MTO TREASURY SYSTEM (Thin Client)
echo ========================================

:: Check if API is already running
curl -s http://localhost:8001/ >nul
if %ERRORLEVEL% NEQ 0 (
    echo Starting local API server...
    start /B "MTO API Server" .\venv\Scripts\python.exe backend\main.py
    timeout /t 3 >nul
)

echo Launching Desktop Interface...
.\venv\Scripts\python.exe main.py

echo.
echo Closing system...
exit /b
