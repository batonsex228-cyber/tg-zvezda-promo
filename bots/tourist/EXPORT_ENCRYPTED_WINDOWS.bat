@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo First run SETUP_WINDOWS.bat & pause & exit /b 1)
echo Creates an encrypted, portable .tbackup copy of the current SQLite DB.
echo Save it to a separate disk or secure offsite storage afterwards.
set /p FILE=New destination path (e.g. D:\tourist-copy.tbackup): 
if "%FILE%"=="" (echo No destination provided & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.encrypted_backup export "%FILE%"
if errorlevel 1 (echo Export failed & pause & exit /b 1)
pause
