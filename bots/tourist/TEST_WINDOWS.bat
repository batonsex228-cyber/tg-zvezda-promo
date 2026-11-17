@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
.venv\Scripts\python.exe -m pytest -q
set "TEST_RESULT=%errorlevel%"
if "%TEST_RESULT%"=="0" .venv\Scripts\python.exe -m scripts.local_smoke
if errorlevel 1 set "TEST_RESULT=1"
pause
exit /b %TEST_RESULT%
