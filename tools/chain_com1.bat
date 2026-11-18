@echo off
rem NOTE: .bat files must stay ASCII + CRLF.
rem com1 (2027 ComHwal 1-gup pilgi) full run, one window, fastest first (user 2026-11-18):
rem   [1/7] part 2 rounds 1-5  : com1-m01..m05 p1-p3 (15 videos, ~12 min each)
rem   [2/7] part 2 rounds 6-10 : com1-m06..m10 p1-p3 (15 videos)
rem   [3/7] part 3 lectures    : com1-L01..L21 (rounds 11-15 grouped by lecture)
rem   [4/7] re-bake parts 2-3  : only videos whose voice was fixed meanwhile (others skip in seconds)
rem   [5/7] part 1 lecture     : longform make --job com1-27 (21 lectures x 40 min, ~2 h each)
rem   [6/7] re-bake parts 2-3  : fixes saved while part 1 was running
rem   [7/7] part 1 again       : only sections whose pronunciation was fixed
rem While this runs you may listen (Drive review html, also at home) and SAVE fixes anytime;
rem the re-bake steps pick them up. Avoid pressing bake buttons for the same videos meanwhile.
rem Each step starts after the previous one ends (GPU 8GB: one TTS model at a time).
rem A failed step does not stop the next one. Progress log: logs\chain-com1.log
setlocal
cd /d "%~dp0.."
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY=.venv\Scripts\python
title com1 chain - keep this window open
echo [%date% %time%] start [1/7] part 2 rounds 1-5 >> logs\chain-com1.log
echo === [1/7] part 2 rounds 1-5 ===
%PY% -m studio queue --items com1-m01-p1,com1-m01-p2,com1-m01-p3,com1-m02-p1,com1-m02-p2,com1-m02-p3,com1-m03-p1,com1-m03-p2,com1-m03-p3,com1-m04-p1,com1-m04-p2,com1-m04-p3,com1-m05-p1,com1-m05-p2,com1-m05-p3 --stages s0,s1,s2,s3,s4,s5
echo [%date% %time%] end [1/7] part 2 rounds 1-5 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [2/7] part 2 rounds 6-10 >> logs\chain-com1.log
echo === [2/7] part 2 rounds 6-10 ===
%PY% -m studio queue --items com1-m06-p1,com1-m06-p2,com1-m06-p3,com1-m07-p1,com1-m07-p2,com1-m07-p3,com1-m08-p1,com1-m08-p2,com1-m08-p3,com1-m09-p1,com1-m09-p2,com1-m09-p3,com1-m10-p1,com1-m10-p2,com1-m10-p3 --stages s0,s1,s2,s3,s4,s5
echo [%date% %time%] end [2/7] part 2 rounds 6-10 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [3/7] part 3 lectures L01-L21 >> logs\chain-com1.log
echo === [3/7] part 3 lectures L01-L21 ===
%PY% -m studio queue --items com1-L01,com1-L02,com1-L03,com1-L04,com1-L05,com1-L06,com1-L07,com1-L08,com1-L09,com1-L10,com1-L11,com1-L12,com1-L13,com1-L14,com1-L15,com1-L16,com1-L17,com1-L18,com1-L19,com1-L20,com1-L21 --stages s0,s1,s2,s3,s4,s5
echo [%date% %time%] end [3/7] part 3 lectures L01-L21 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [4/7] re-bake fixed voice, parts 2-3 >> logs\chain-com1.log
echo === [4/7] re-bake fixed voice, parts 2-3 ===
%PY% -m studio queue --items com1-m01-p1,com1-m01-p2,com1-m01-p3,com1-m02-p1,com1-m02-p2,com1-m02-p3,com1-m03-p1,com1-m03-p2,com1-m03-p3,com1-m04-p1,com1-m04-p2,com1-m04-p3,com1-m05-p1,com1-m05-p2,com1-m05-p3,com1-m06-p1,com1-m06-p2,com1-m06-p3,com1-m07-p1,com1-m07-p2,com1-m07-p3,com1-m08-p1,com1-m08-p2,com1-m08-p3,com1-m09-p1,com1-m09-p2,com1-m09-p3,com1-m10-p1,com1-m10-p2,com1-m10-p3,com1-L01,com1-L02,com1-L03,com1-L04,com1-L05,com1-L06,com1-L07,com1-L08,com1-L09,com1-L10,com1-L11,com1-L12,com1-L13,com1-L14,com1-L15,com1-L16,com1-L17,com1-L18,com1-L19,com1-L20,com1-L21 --stages s3,s4,s5
echo [%date% %time%] end [4/7] re-bake fixed voice, parts 2-3 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [5/7] part 1 lecture com1-27 >> logs\chain-com1.log
echo === [5/7] part 1 lecture com1-27 ===
%PY% -m longform make --job com1-27
echo [%date% %time%] end [5/7] part 1 lecture com1-27 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [6/7] re-bake fixed voice, parts 2-3 >> logs\chain-com1.log
echo === [6/7] re-bake fixed voice, parts 2-3 ===
%PY% -m studio queue --items com1-m01-p1,com1-m01-p2,com1-m01-p3,com1-m02-p1,com1-m02-p2,com1-m02-p3,com1-m03-p1,com1-m03-p2,com1-m03-p3,com1-m04-p1,com1-m04-p2,com1-m04-p3,com1-m05-p1,com1-m05-p2,com1-m05-p3,com1-m06-p1,com1-m06-p2,com1-m06-p3,com1-m07-p1,com1-m07-p2,com1-m07-p3,com1-m08-p1,com1-m08-p2,com1-m08-p3,com1-m09-p1,com1-m09-p2,com1-m09-p3,com1-m10-p1,com1-m10-p2,com1-m10-p3,com1-L01,com1-L02,com1-L03,com1-L04,com1-L05,com1-L06,com1-L07,com1-L08,com1-L09,com1-L10,com1-L11,com1-L12,com1-L13,com1-L14,com1-L15,com1-L16,com1-L17,com1-L18,com1-L19,com1-L20,com1-L21 --stages s3,s4,s5
echo [%date% %time%] end [6/7] re-bake fixed voice, parts 2-3 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] start [7/7] re-render fixed sections, part 1 >> logs\chain-com1.log
echo === [7/7] re-render fixed sections, part 1 ===
%PY% -m longform make --job com1-27
echo [%date% %time%] end [7/7] re-render fixed sections, part 1 (exit %errorlevel%) >> logs\chain-com1.log
echo [%date% %time%] chain done >> logs\chain-com1.log
echo chain done
pause
