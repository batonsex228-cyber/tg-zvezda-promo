@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo [ERROR] First run SETUP_WINDOWS.bat & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.local_smoke
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
