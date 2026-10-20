@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem Haeseolbook studio setup - run once (safe to run again).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo [1/6] Python venv + packages
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv || (echo Python 3.11+ is required. & pause & exit /b 1)
)
".venv\Scripts\python" -m pip install -q --upgrade pip
".venv\Scripts\python" -m pip install -q -r studio\requirements.txt || (echo pip install failed & pause & exit /b 1)

echo [2/6] SuperTonic3 voice models (about 400MB, first time only)
".venv\Scripts\python" -m studio tts-setup || (echo model download failed & pause & exit /b 1)

echo [3/6] Portable PHP 8.3 (tools\php)
if not exist "tools\php\php.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; $z=Join-Path $env:TEMP 'hsb-php.zip';" ^
    "Invoke-WebRequest 'https://windows.php.net/downloads/releases/latest/php-8.3-nts-Win32-vs16-x64-latest.zip' -OutFile $z;" ^
    "Expand-Archive $z -DestinationPath 'tools\php' -Force; Remove-Item $z"
  if errorlevel 1 (echo PHP download failed & pause & exit /b 1)
)
if not exist "tools\php\php.ini" (
  powershell -NoProfile -Command ^
    "(Get-Content 'tools\php\php.ini-development') -replace '^;extension_dir = \"ext\"','extension_dir = \"ext\"' -replace '^;extension=(pdo_sqlite|pdo_mysql|curl|mbstring|openssl|zip)$','extension=$1' | Set-Content -Encoding ascii 'tools\php\php.ini'"
)

echo [4/6] Web app build (npm)
call npm install --no-audit --no-fund || (echo npm install failed - Node 20+ required & pause & exit /b 1)
call npm run build:shared || (pause & exit /b 1)
set VITE_BASE=/
set VITE_API_URL=/api
call npm run build -w @hsb/web || (pause & exit /b 1)

echo [5/6] Local ebook server config + database
if not exist "server\config.lan.php" (
  powershell -NoProfile -Command ^
    "$t=Get-Content 'server\config.lan.example.php' -Raw -Encoding UTF8; while($t -match '__RANDOM__'){ $r=-join ((1..48) | %% { '{0:x}' -f (Get-Random -Max 16) }); $t=([regex]'__RANDOM__').Replace($t,$r,1) }; [IO.File]::WriteAllText((Join-Path (Get-Location) 'server\config.lan.php'), $t, (New-Object Text.UTF8Encoding $false))"
)
if not exist "server\var" mkdir "server\var"
set HSB_CONFIG=%~dp0server\config.lan.php
"tools\php\php.exe" server\bin\hsb.php migrate || (pause & exit /b 1)

echo [6/6] Check
".venv\Scripts\python" -m studio doctor
echo.
echo Done. Next: youtube-login.bat (once), then run.bat
pause
