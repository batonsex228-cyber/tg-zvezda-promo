@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo First run SETUP_WINDOWS.bat & pause & exit /b 1)
if not exist .env (echo Edit your .env before launching the Telegram bot. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.doctor --live
if errorlevel 1 (pause & exit /b 1)
echo TOURIST: Telegram Bot + temporary HTTPS Mini App
.venv\Scripts\python.exe -m scripts.run_tunnel
if errorlevel 1 pause
