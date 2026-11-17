@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ZVEZDOCHKA TELEGRAM - ONE CLICK
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_start.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] Launcher exited with code %RC%.
  echo Save screenshot WITHOUT YOUR BOT TOKEN.
  pause
)
endlocal
