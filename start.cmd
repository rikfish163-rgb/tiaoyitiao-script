@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
    echo Run install.cmd first.
    exit /b 1
)
".venv\Scripts\python.exe" jump.py %*
exit /b %errorlevel%
