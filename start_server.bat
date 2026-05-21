@echo off
title MTO Treasury Backend Server
echo Starting MTO Treasury Backend API...
echo -----------------------------------
cd /d %~dp0
VENV\Scripts\python.exe backend\main.py
pause
