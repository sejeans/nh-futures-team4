@echo off
title NH week06 trading - DO NOT CLOSE
rem Task Scheduler runs this Mon-Fri 08:50 (task NH_trade06). watchdog06.py also starts it if trade06.py stops updating heartbeat.json.
rem trade06.py exit codes: 0 normal end, 2 needs manual check (do not restart), other = crash -> restart up to 5 times, 1 min apart.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=..\.venv\Scripts\python.exe
if not exist %PY% set PY=python
echo [%date% %time%] start, %PY% >> results\trade_console.log
set /a tries=0
:run
%PY% trade06.py >> results\trade_console.log 2>&1
set code=%errorlevel%
if %code%==0 goto end
if %code%==2 goto end
set /a tries+=1
echo [%date% %time%] trade06.py exit %code%, restart %tries%/5 >> results\trade_console.log
if %tries% geq 5 goto end
ping -n 61 127.0.0.1 > nul
goto run
:end
echo [%date% %time%] end, exit %code% >> results\trade_console.log
rem Account window for the screenshots/ capture (read-only). Stays open.
start "NH account" cmd /k %PY% -X utf8 show_account06.py
