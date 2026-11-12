@echo off
rem One-click launcher for EGX Flow (this computer only). Double-click to start and open it in your browser.
title EGX Flow
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
  echo.
  echo Something went wrong. See the messages above.
  pause
  exit /b 1
)
timeout /t 6 >nul
