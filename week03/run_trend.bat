@echo off
rem Task Scheduler runs this Mon-Fri 08:10 KST (CME opens 08:00, yesterday's daily bar is complete). Output: results\trend_console.log
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Get the latest pushed code first. If pull fails (network, local changes), run the code already here
echo [%date% %time%] git pull >> results\trend_console.log
git pull --ff-only >> results\trend_console.log 2>&1
git log -1 --oneline >> results\trend_console.log 2>&1
python trend_live.py --yes >> results\trend_console.log 2>&1
