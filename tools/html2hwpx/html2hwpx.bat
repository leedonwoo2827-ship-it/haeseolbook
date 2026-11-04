@echo off
setlocal
chcp 65001 >nul 2>&1
rem html2hwpx - drop one or more .html files on this file -> .hwpx next to each
rem   options (template etc.): python html2hwpx.py input.html --template form.hwpx --page keep
rem   if form.hwpx sits next to this .bat it is used automatically
set PYTHONUTF8=1
set PY=python
where py >nul 2>&1 && set PY=py -3
if "%~1"=="" (
  echo Drop .html files on this .bat
  pause
  exit /b 1
)
set TPL=
if exist "%~dp0form.hwpx" set TPL=--template "%~dp0form.hwpx" --page keep
for %%F in (%*) do %PY% "%~dp0html2hwpx.py" "%%~fF" %TPL%
pause
