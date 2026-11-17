@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PWSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
echo.
echo ===========================================================
echo  TOURIST CLUB - ONE CLICK - Telegram Bot + Mini App
 echo  Version 0.18.3 / Windows 10-11 x64
 echo ===========================================================
echo.
if not exist "%PWSH%" (
  echo [ERROR] Windows PowerShell not found. Please install Windows PowerShell 5.1.
  pause
  exit /b 1
)
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_one_click.ps1"
set "EXIT_CODE=%errorlevel%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] TOURIST stopped with code %EXIT_CODE%. See the message above.
) else (
  echo [INFO] TOURIST stopped normally.
)
echo To start again, double-click START_TOURIST.bat.
pause
exit /b %EXIT_CODE%
