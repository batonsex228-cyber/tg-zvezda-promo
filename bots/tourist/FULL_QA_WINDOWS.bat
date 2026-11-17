@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
echo TOURIST v0.14.0: tests, server smoke, configuration check
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 (echo Tests failed. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.telegram_flow_smoke
if errorlevel 1 (echo Signed Telegram integration FAILED. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.local_smoke
if errorlevel 1 (echo Server smoke failed. & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.doctor --demo
if errorlevel 1 (echo Check dependencies and local settings. & pause & exit /b 1)
echo QA PASSED. For live Telegram run CHECK_WINDOWS.bat and CHECK_TELEGRAM_ONLINE_WINDOWS.bat.
pause
