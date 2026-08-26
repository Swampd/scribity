@echo off
setlocal
title Scribity Server
echo ============================================
echo        SCRIBITY - Starting Up...
echo ============================================
echo.

cd /d "%~dp0"

rem Prefer the Windows Python launcher, but also support a normal Python install.
py -3 --version >nul 2>&1
if not errorlevel 1 goto run_with_py

python -c "import sys; sys.exit(sys.version_info[0] != 3)" >nul 2>&1
if not errorlevel 1 goto run_with_python

echo ERROR: Python 3 was not found.
echo Install Python 3, then double-click scribity.bat again.
echo https://www.python.org/downloads/windows/
echo.
pause
endlocal
exit /b 1

:run_with_py
set "SCRIBITY_PYTHON=py -3"
goto start_scribity

:run_with_python
set "SCRIBITY_PYTHON=python"

:start_scribity
echo Starting server at http://localhost:8000
echo Press Ctrl+C to stop the server.
echo.

rem Wait a moment, then open Scribity in the default browser.
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

rem Run the current Scribity server from this folder.
%SCRIBITY_PYTHON% scribity_server.py
set "SCRIBITY_EXIT=%ERRORLEVEL%"

if "%SCRIBITY_EXIT%"=="0" goto scribity_stopped

echo.
echo ERROR: Scribity stopped with an error.
echo The message above should explain what went wrong.
pause
endlocal
exit /b %SCRIBITY_EXIT%

:scribity_stopped
echo.
echo Scribity stopped.
pause
endlocal
exit /b 0
