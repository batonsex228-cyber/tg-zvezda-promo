@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo First run SETUP_WINDOWS.bat & pause & exit /b 1)
echo TOURIST v0.14.0 - SIGNED TELEGRAM INTEGRATION TEST (OFFLINE)
echo Uses synthetic signatures, temporary database, NO REAL MESSAGES.
.venv\Scripts\python.exe -m scripts.telegram_flow_smoke
if errorlevel 1 (echo [FAILED] Synthetic Telegram integration test. & pause & exit /b 1)
echo [PASS] API / Mini App auth / SQLite / booking / moderation / outbox.
echo Optional interactive Chromium check: python -m scripts.telegram_mode_browser_smoke
pause
