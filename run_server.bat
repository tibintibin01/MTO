@echo off
echo Starting MTO Treasury API Server...
set PYTHONPATH=%~dp0
.\venv\Scripts\python.exe backend\main.py
pause
