@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
if not exist .env (copy .env.example .env >nul)
echo TOURIST BOT v0.14.0 - preflight...
.venv\Scripts\python.exe -m scripts.doctor --live
if errorlevel 1 (echo Fix .env, then retry. & pause & exit /b 1)
echo TOURIST BOT: http://127.0.0.1:8000
.venv\Scripts\python.exe -m app.main
if errorlevel 1 pause
