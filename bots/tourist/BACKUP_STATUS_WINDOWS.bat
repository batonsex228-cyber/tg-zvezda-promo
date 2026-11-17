@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo First run SETUP_WINDOWS.bat
  pause
  exit /b 1
)
echo TOURIST v0.14.0 - verify scheduled backup
.venv\Scripts\python.exe -m scripts.backup_ops --run
if errorlevel 1 (
  echo Backup check needs attention. See logs above.
  pause
  exit /b 1
)
echo Backup status OK.
pause
