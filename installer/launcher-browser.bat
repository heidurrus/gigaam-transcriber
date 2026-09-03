@echo off
title GigaAM Transcriber (Browser Mode)
cd /d "%~dp0"
echo Starting GigaAM Transcriber in browser mode...
echo Open http://localhost:5000 in Chrome or Edge.
echo Close this window to stop the server.
echo.
python app.py --browser
