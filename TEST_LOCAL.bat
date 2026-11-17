@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run START_TELEGRAM.bat once to install dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\local_self_test.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\telegram_flow_test.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\telegram_social_reply_test.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\semantic_regression_test.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\context_20_test.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\telegram_semantic_flow_test.py
if errorlevel 1 goto failed
echo.
echo [OK] ALL TELEGRAM OFFLINE TESTS PASSED
pause
exit /b 0
:failed
echo.
echo [FAILED] Tests failed; see output above.
pause
exit /b 1
