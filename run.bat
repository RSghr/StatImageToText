@echo off
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% discord_inbox.py
%PY% hd2stats.py To_Process --recursive %*
if errorlevel 1 goto end
%PY% make_report.py -i output
if not exist htmlReport mkdir htmlReport
copy /y "output\report.html" "htmlReport\index.html" >nul
if exist "output\players.html" copy /y "output\players.html" "htmlReport\players.html" >nul
if exist "output\units.html" copy /y "output\units.html" "htmlReport\units.html" >nul
if exist "output\chart.umd.js" copy /y "output\chart.umd.js" "htmlReport\chart.umd.js" >nul
if exist "output\raids.html" (copy /y "output\raids.html" "htmlReport\raids.html" >nul) else (if exist "htmlReport\raids.html" del "htmlReport\raids.html")
echo.
echo Done.
echo   Web report:           output\report.html  (+ players.html, units.html)
echo   History:              history\deployments.csv  (every deployment so far)
echo   Put it online:        publish_site.bat  (or "Publish online" in Stats UI)
echo   Discord announcement: output\discord_post.txt
echo   Spreadsheets:         output\HD2_stats.xlsx, output\report_data.xlsx
start "" "output\report.html"
:end
echo.
pause
