@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem run.bat            -> studio dashboard (http://127.0.0.1:5300) + local ebook (http://127.0.0.1:8080)
rem run.bat <command>  -> studio CLI, e.g. run.bat make --job 2025-g9-computer / run.bat batch --years 2018-2025
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HSB_CONFIG=%~dp0server\config.lan.php
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not "%~1"=="" (
  ".venv\Scripts\python" -m studio %*
  exit /b %errorlevel%
)
rem local ebook server - skipped when lan-run.bat already serves port 8080
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 start "haeseolbook-ebook (close to stop)" /min "tools\php\php.exe" -S 127.0.0.1:8080 -t apps\web\dist server\public\lan-router.php
rem the dashboard opens in the browser; the ebook is linked from its header ("local ebook")
title haeseolbook studio - keep this window open while the dashboard is in use
".venv\Scripts\python" -m studio ui
