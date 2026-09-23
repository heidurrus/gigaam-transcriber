@echo off
title GigaAM Transcriber (Browser Mode)
cd /d "%~dp0"
echo Starting GigaAM Transcriber in browser mode...
echo Open http://127.0.0.1:5000 in Chrome or Edge.
echo Close this window to stop the server.
echo.
python launcher.py --browser
