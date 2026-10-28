@echo off
rem Task Scheduler runs this Tue-Fri 08:50. Output goes to results\trade_console.log
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Get the latest pushed code first. If pull fails (network, local changes), run the code already here
echo [%date% %time%] git pull >> results\trade_console.log
git pull --ff-only >> results\trade_console.log 2>&1
git log -1 --oneline >> results\trade_console.log 2>&1
python trade.py >> results\trade_console.log 2>&1
