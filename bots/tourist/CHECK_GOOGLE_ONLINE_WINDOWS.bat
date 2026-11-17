@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo First run SETUP_WINDOWS.bat & pause & exit /b 1)
echo TOURIST v0.14.0 - GOOGLE SHEETS READ-ONLY CONNECTIVITY CHECK
echo This does NOT change spreadsheet cells. Credentials stay on this PC.
.venv\Scripts\python.exe -m scripts.check_google_online
if errorlevel 1 (echo [FAILED] Check Google service account, sharing and network. & pause & exit /b 1)
echo [DONE] This was only a metadata read; real write/sync still requires a separate test.
pause
