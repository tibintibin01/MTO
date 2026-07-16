@echo off
title MTO Treasury Backend Server
echo Starting MTO Treasury Backend API...
echo -----------------------------------
cd /d %~dp0
VENV\Scripts\python.exe scripts\run_api_supervisor.py
pause
