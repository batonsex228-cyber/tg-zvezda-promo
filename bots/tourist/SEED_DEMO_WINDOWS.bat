@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "BOT_TOKEN="
set "OWNER_TELEGRAM_ID=900001"
set "DEMO_MODE=true"
set "DATABASE_PATH=data/demo.sqlite3"
.venv\Scripts\python.exe -m app.cli seed-demo
pause
