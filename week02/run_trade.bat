@echo off
rem Task Scheduler runs this Tue-Fri 08:50. Output goes to results\trade_console.log
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python trade.py >> results\trade_console.log 2>&1
