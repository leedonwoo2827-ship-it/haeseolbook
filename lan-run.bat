@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem Share the studio dashboard on the office LAN: other PCs open http://<this PC IP>:5300
rem The "local ebook" button then serves the finished ebooks on port 5301 (also on the LAN).
rem Anyone on the LAN can run jobs and uploads from the dashboard. Do NOT expose these ports to the internet.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HSB_CONFIG=%~dp0server\config.lan.php
set HSB_STUDIO_HOST=0.0.0.0
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
netstat -ano | findstr /R /C:":5300 .*LISTENING" >nul
if not errorlevel 1 (
  echo The dashboard is already running ^(run.bat window^). Close that window first, then run lan-run.bat again.
  pause
  exit /b 1
)

rem Firewall rules (private/domain networks only) - asks for admin once
for %%P in (5300 5301) do (
  netsh advfirewall firewall show rule name="haeseolbook-%%P" >nul 2>&1
  if errorlevel 1 (
    echo Adding firewall rule for TCP %%P ^(admin permission^) ...
    powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=haeseolbook-%%P dir=in action=allow protocol=TCP localport=%%P profile=private,domain'"
  )
)

title haeseolbook studio LAN share - close this window to stop
".venv\Scripts\python" -m studio ui
