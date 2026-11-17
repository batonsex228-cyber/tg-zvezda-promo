@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
echo TOURIST - Owner setup (optional; requires /id in Telegram)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_set_owner.ps1"
set "EXIT_CODE=%errorlevel%"
pause
exit /b %EXIT_CODE%
