@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem Share the ebook on the office LAN: other PCs/phones open http://<this PC IP>:8080
rem Login = email only (review mode). Do NOT expose this port to the internet.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set HSB_CONFIG=%~dp0server\config.lan.php
set PORT=8080
if not exist "tools\php\php.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist "apps\web\dist\index.html" (
  echo Web app is not built. Run setup.bat first.
  pause
  exit /b 1
)

rem Firewall rule (private/domain networks only) - asks for admin once
netsh advfirewall firewall show rule name="haeseolbook-%PORT%" >nul 2>&1
if errorlevel 1 (
  echo Adding firewall rule for TCP %PORT% ^(admin permission^) ...
  powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=haeseolbook-%PORT% dir=in action=allow protocol=TCP localport=%PORT% profile=private,domain'"
)

echo.
echo ==============================================================
echo   Haeseolbook ebook viewer - office LAN share
echo   [Office LAN] open on another PC or phone:
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '      http://' + $_.IPAddress + ':%PORT%/' }"`) do echo %%a
echo.
echo   Login: type any email (each person keeps own notes).
echo   Closing this window stops the share.
echo ==============================================================
echo.
title haeseolbook LAN share - close this window to stop
"tools\php\php.exe" -S 0.0.0.0:%PORT% -t apps\web\dist server\public\lan-router.php
