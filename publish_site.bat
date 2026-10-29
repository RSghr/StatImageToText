@echo off
title 505th report - publish online
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_site.ps1" %*
if errorlevel 1 pause
