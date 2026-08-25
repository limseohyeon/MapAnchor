@echo off
chcp 65001 >nul
title DWG Map
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_app.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo Failed with exit code %EXITCODE%
  pause
  exit /b %EXITCODE%
)
echo Stopped. You can close this window.
pause