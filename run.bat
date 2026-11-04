@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem run.bat            -> studio dashboard (http://127.0.0.1:5300)
rem                       "local ebook" button in its header starts the finished-ebook viewer on port 5301
rem run.bat <command>  -> studio CLI, e.g. run.bat make --job 2025-g9-computer / run.bat batch --years 2018-2025
rem lan-run.bat        -> the same dashboard, shared on the office LAN
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
title haeseolbook studio - keep this window open while the dashboard is in use
".venv\Scripts\python" -m studio ui
