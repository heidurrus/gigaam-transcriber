@echo off
title GigaAM Transcriber - First-time Setup
cd /d "%~dp0"

echo.
echo  GigaAM Transcriber - First-time Setup
echo  ----------------------------------------
echo  Installs the small base layer. PyTorch, GigaAM, ffmpeg and the speech
echo  model are installed by the app itself on first launch, with progress.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python was not found on PATH.
    echo  Please install Python 3.10 or newer from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo  [1/2] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo  [2/2] Installing app base layer...
python -m pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo  ----------------------------------------
echo  Done! Start the app; it finishes setup on first launch.
echo  ----------------------------------------
echo.
pause
