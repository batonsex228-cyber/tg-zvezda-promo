@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
set "BOT_TOKEN="
set "OWNER_TELEGRAM_ID=900001"
set "DEMO_MODE=true"
set "DATABASE_PATH=data/demo.sqlite3"
set "WEBAPP_URL="
.venv\Scripts\python.exe -m scripts.doctor --demo
if errorlevel 1 (pause & exit /b 1)
echo TOURIST LOCAL DEMO: http://127.0.0.1:8000
.venv\Scripts\python.exe -m app.main
if errorlevel 1 pause
