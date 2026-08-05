@echo off
chcp 65001 > nul
title Trap Monitor

echo.
echo  ====================================
echo   Illegal Trap Online Monitor v1.0
echo  ====================================
echo.

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set PYTHON=".venv\Scripts\python.exe"
) else (
    set PYTHON=python
)

%PYTHON% -c "import openpyxl, schedule, dotenv" 2>nul
if errorlevel 1 (
    echo [Installing required packages...]
    %PYTHON% -m pip install beautifulsoup4 openpyxl python-dotenv requests schedule --quiet
    echo [Done]
    echo.
)

echo [Server] Starting at http://localhost:8000
echo [Server] Close this window to stop the program.
echo.

start "" "http://localhost:8000"

%PYTHON% app.py

pause
