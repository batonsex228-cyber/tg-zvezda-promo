@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo TOURIST v0.14.0 - Windows Setup
echo -----------------------------------------------------
set "PY=python"
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 --version >nul 2>&1 && (set "PY=py -3.12" & goto :python_found)
  py -3.13 --version >nul 2>&1 && (set "PY=py -3.13" & goto :python_found)
  py -3.11 --version >nul 2>&1 && (set "PY=py -3.11" & goto :python_found)
)
:python_found
rem Check interpreter via the chosen command; unsupported Python must not silently create the venv.
%PY% -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), 'Required Python 3.11 through 3.13'" || (echo Install Python 3.12 x64 from python.org & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || (echo Failed to create environment & pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 (echo [ERROR] Dependencies installation failed. Check Internet and proxy. & pause & exit /b 1)
if not exist .env (copy .env.example .env >nul)
echo.
echo SETUP COMPLETE. Please edit .env before launching the live bot.
.venv\Scripts\python.exe -m scripts.local_smoke
if errorlevel 1 (echo [ERROR] Smoke test failed. & pause & exit /b 1)
pause
