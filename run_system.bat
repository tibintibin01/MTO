@echo off
cd /d "%~dp0"
title MTO Treasury System Launcher
color 0B
echo =============================================================
echo               MTO TREASURY PORTAL ONE-CLICK LAUNCHER
echo =============================================================
echo.

:: ---------------------------------------------------------------
:: AUTO-DETECT SERVER IP
:: Gets the first non-loopback IPv4 address on this machine so the
:: portal URL is always correct regardless of which PC runs this.
:: ---------------------------------------------------------------
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set SERVER_IP=%%a
    goto :ip_found
)
:ip_found
:: Strip the leading space that ipconfig puts before the address
set SERVER_IP=%SERVER_IP: =%

echo [AUTO] Detected server IP: %SERVER_IP%

:: Configure the public portal without discarding existing environment values.
:: A shared lookup secret is created only when it is missing.
set PORTAL_CONFIG_OK=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_local_portal.ps1" -ServerIp "%SERVER_IP%"
if %ERRORLEVEL% NEQ 0 (
    set PORTAL_CONFIG_OK=0
    echo [WARNING] Public portal snapshot configuration failed.
    echo [WARNING] Cashier and backend startup will continue; public lookup may be unavailable.
)
echo [AUTO] Updated local portal configuration for: http://%SERVER_IP%:3000

:: Write CORS_ORIGIN to .env so the backend allows requests from this
:: machine's IP without needing a code change.
:: We use a temp file to preserve all existing .env lines except CORS_ORIGIN,
:: then append the new value.
set ENV_FILE=.env
set TEMP_ENV=%TEMP%\mto_env_tmp.txt
if exist "%ENV_FILE%" (
    findstr /v /i "^CORS_ORIGIN=" "%ENV_FILE%" > "%TEMP_ENV%"
    echo CORS_ORIGIN=http://%SERVER_IP%:3000 >> "%TEMP_ENV%"
    copy /y "%TEMP_ENV%" "%ENV_FILE%" >nul
    del "%TEMP_ENV%"
) else (
    echo CORS_ORIGIN=http://%SERVER_IP%:3000 > "%ENV_FILE%"
)
echo [AUTO] Updated .env CORS_ORIGIN: http://%SERVER_IP%:3000

echo.
echo =============================================================
echo  ACCESS URL FOR OTHER PCs:  http://%SERVER_IP%:3000
echo =============================================================
echo.

:: Check if Docker is installed and running
docker info >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [DOCKER ACTIVE] Starting API ^& Database via Docker Compose...
    docker compose up -d
    if "%PORTAL_CONFIG_OK%"=="1" (
        start "MTO Portal Snapshot Refresh" /min cmd /c "docker compose exec -T api python scripts/refresh_local_portal_snapshot.py --max-age-hours 24"
    )
) else (
    echo [LOCAL FALLBACK] Docker not running. Starting local native API...
    start "MTO FastAPI Backend Server" cmd /k "title MTO Backend (Port 8001) && VENV\Scripts\python.exe scripts\run_api_supervisor.py"
    if "%PORTAL_CONFIG_OK%"=="1" (
        start "MTO Portal Snapshot Refresh" /min cmd /c "VENV\Scripts\python.exe scripts\refresh_local_portal_snapshot.py --max-age-hours 24"
    )
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
echo  - Portal URL: http://%SERVER_IP%:3000
echo =============================================================
echo.
pause
