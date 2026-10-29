@echo off
REM Opens the 505th Stat Department control panel.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "stats_ui.pyw"
) else (
  start "" pythonw "stats_ui.pyw"
)
