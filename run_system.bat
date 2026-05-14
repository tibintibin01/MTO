@echo off
setlocal
set PYTHONPATH=%~dp0
set API_URL=https://localhost:8001/

echo ========================================
echo   MUNICIPAL REVENUE SYSTEM
echo ========================================

:: Check if API is already running
curl -k -s %API_URL% >nul
if %ERRORLEVEL% NEQ 0 (
    echo Starting local API server...
    start /B "MTO API Server" .\venv\Scripts\python.exe backend\main.py
)

echo Waiting for API server...
for /L %%i in (1,1,30) do (
    curl -k -s %API_URL% >nul
    if not errorlevel 1 goto api_ready
    timeout /t 1 >nul
)

echo ERROR: API server did not become ready at %API_URL%.
echo Check the backend console output and logs\system.log.
pause
exit /b 1

:api_ready

echo Launching Desktop Interface...
.\venv\Scripts\python.exe main.py

echo.
echo Closing system...
exit /b
