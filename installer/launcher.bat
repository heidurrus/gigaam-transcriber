@echo off
cd /d "%~dp0"

rem launcher.py checks dependencies on every start and opens the Setup
rem screen in the app window when something is missing (spec FR-PLAT-04/05).
where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw launcher.py
) else (
    start "" python launcher.py
)
