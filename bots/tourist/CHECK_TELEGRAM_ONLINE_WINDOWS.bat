@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo [ERROR] First run SETUP_WINDOWS.bat & pause & exit /b 1)
echo TOURIST v0.5.0 - ONLINE verification of your Telegram BotFather bot
.venv\Scripts\python.exe -m scripts.verify_telegram
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
