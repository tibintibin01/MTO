@echo off
echo Starting Municipal Revenue System API Server...
set PYTHONPATH=%~dp0
.\venv\Scripts\python.exe scripts\run_api_supervisor.py
pause
