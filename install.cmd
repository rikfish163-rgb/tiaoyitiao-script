@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if errorlevel 1 goto launcher
python -m venv .venv
goto dependencies
:launcher
py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11+ is required. Install Python and reopen this terminal.
    exit /b 1
)
py -3 -m venv .venv
:dependencies
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" jump.py doctor
exit /b %errorlevel%
