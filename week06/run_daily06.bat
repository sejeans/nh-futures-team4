@echo off
rem Task Scheduler runs this Mon-Fri 15:50 (task NH_daily06, 11/24-11/27): fetch bars, chart, README row. No orders.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=..\.venv\Scripts\python.exe
if not exist %PY% set PY=python
echo [%date% %time%] daily06 start >> results\daily_console.log
%PY% -X utf8 daily06.py >> results\daily_console.log 2>&1
echo [%date% %time%] daily06 exit %errorlevel% >> results\daily_console.log
