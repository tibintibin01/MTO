@echo off
echo Starting Municipal Revenue System API Server...
set PYTHONPATH=%~dp0
.\venv\Scripts\python.exe backend\main.py
pause
