@echo off
cd /d "%~dp0"
title 505th Stat Department - browser panel
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% stats_web.py
if errorlevel 1 pause
