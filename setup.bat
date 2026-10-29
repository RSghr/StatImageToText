@echo off
cd /d "%~dp0"
echo Creating virtual environment in .venv ...
python -m venv .venv || (echo Python not found - install it from python.org and tick "Add to PATH" & pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" echo.& echo NOTE: Tesseract not found in C:\Program Files\Tesseract-OCR - install it from https://github.com/UB-Mannheim/tesseract/wiki
echo.
echo Setup done. Double-click "Stats UI.bat", drop the Drive zip and the form file on it, then Run report.
pause
