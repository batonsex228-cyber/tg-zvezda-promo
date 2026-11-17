@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (echo First run SETUP_WINDOWS.bat & pause & exit /b 1)
echo Restore a .tbackup archive into a NEW, non-existing SQLite file ONLY.
set /p SOURCE=Encrypted .tbackup path: 
set /p TARGET=New SQLite .sqlite3 destination path: 
if "%SOURCE%"=="" (echo No source & pause & exit /b 1)
if "%TARGET%"=="" (echo No destination & pause & exit /b 1)
.venv\Scripts\python.exe -m scripts.encrypted_backup import "%SOURCE%" "%TARGET%"
if errorlevel 1 (echo Restore failed & pause & exit /b 1)
pause
