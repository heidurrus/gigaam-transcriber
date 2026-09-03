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

echo  [1/5] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo  [2/5] Detecting GPU...
nvidia-smi >nul 2>&1
if %errorlevel% == 0 (
    echo         NVIDIA GPU detected — installing PyTorch with CUDA support...
    python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126 --quiet
) else (
    echo         No NVIDIA GPU detected — installing CPU-only PyTorch...
    python -m pip install torch torchvision torchaudio --quiet
)

echo  [3/5] Installing app dependencies...
python -m pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)

echo  [4/5] Installing GigaAM...
python -m pip install "gigaam[longform] @ git+https://github.com/salute-developers/GigaAM.git" --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install GigaAM.
    echo  Make sure git is installed: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo  [5/5] Attempting to install ffmpeg via winget...
winget install --id Gyan.FFmpeg -e --silent >nul 2>&1
if errorlevel 1 (
    echo         ffmpeg not installed via winget. Install manually from https://ffmpeg.org/download.html if needed.
) else (
    echo         ffmpeg installed.
)

echo.
echo  ----------------------------------------
echo  Setup complete! Run launcher.bat to start.
echo  ----------------------------------------
echo.
pause
