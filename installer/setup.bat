@echo off
title GigaAM Transcriber - First-time Setup
cd /d "%~dp0"

echo.
echo  GigaAM Transcriber - First-time Setup
echo  ----------------------------------------
echo  This will install Python dependencies.
echo  It may take several minutes on a slow connection.
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

echo  [1/4] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo  [2/4] Installing app dependencies...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)

echo  [3/4] Installing GigaAM...
python -m pip install "gigaam[torch,longform] @ git+https://github.com/salute-developers/GigaAM.git"
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install GigaAM.
    echo  Make sure git is installed: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo  [4/4] Attempting to install ffmpeg via winget...
winget install --id Gyan.FFmpeg -e --silent >nul 2>&1
if errorlevel 1 (
    echo  ffmpeg not installed via winget. If you need it, install manually from https://ffmpeg.org/download.html
) else (
    echo  ffmpeg installed.
)

echo.
echo  ----------------------------------------
echo  Setup complete! Run launcher.bat to start.
echo  ----------------------------------------
echo.
pause
