@echo off
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw app.py
) else (
    start "" python app.py
)
