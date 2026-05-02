@echo off
title Scribity Server
echo ============================================
echo        SCRIBITY - Starting Up...
echo ============================================
echo.

cd /d "%~dp0"

echo Starting server at http://localhost:8000
echo Press Ctrl+C to stop the server.
echo.

:: Wait a moment then open the browser
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start the Flask server
py scribity_server.py

pause
