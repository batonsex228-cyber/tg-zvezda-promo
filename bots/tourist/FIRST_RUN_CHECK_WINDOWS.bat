@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo TOURIST v0.14.0 - First live run preflight
if not exist .venv\Scripts\python.exe (echo [ERROR] Run SETUP_WINDOWS.bat first. & pause & exit /b 1)
if not exist .env (echo [ERROR] Copy .env.example to .env and fill in BOT_TOKEN. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.doctor --live
if errorlevel 1 (echo [ERROR] Offline check failed. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.check_port
if errorlevel 1 (echo [ERROR] Stop the other app running on port 8000. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.verify_telegram
if errorlevel 1 (echo [ERROR] Telegram preflight failed. & pause & exit /b 1)
echo.
echo [OK] Ready to try START_WINDOWS.bat or START_TUNNEL_WINDOWS.bat.
echo [NOTE] No messages were sent to users during this check.
pause
