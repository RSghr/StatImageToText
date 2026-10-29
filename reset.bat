@echo off
title 505th Stat Department - reset
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset.ps1"
if errorlevel 1 pause
