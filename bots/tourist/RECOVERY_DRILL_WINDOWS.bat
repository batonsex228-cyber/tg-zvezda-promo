@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.recovery_drill
if errorlevel 1 (echo Test failed & pause & exit /b 1)
echo RECOVERY DRILL COMPLETE
pause
