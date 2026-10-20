@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem Opens Chrome with this folder's profile (profiles\dekman). Log in to Google and pick the channel once.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python" -m studio login
echo.
echo After logging in (and checking the channel), you can close this window. Keep Chrome open or closed - both are fine.
pause
