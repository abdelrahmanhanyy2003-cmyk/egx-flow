@echo off
title Stop EGX Flow
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
timeout /t 3 >nul
