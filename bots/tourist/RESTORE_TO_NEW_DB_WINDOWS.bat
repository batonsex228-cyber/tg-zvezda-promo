@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo Run SETUP_WINDOWS.bat first & pause & exit /b 1)
echo RESTORE TO NEW FILE ONLY. Existing database will NEVER be overwritten.
set /p "SRC=Full path to verified source backup: "
set /p "DST=Full path to a NEW .sqlite3 file (must not exist): "
.venv\Scripts\python.exe -m scripts.recover_to_new_db "%SRC%" "%DST%"
pause
