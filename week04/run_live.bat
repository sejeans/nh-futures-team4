@echo off
rem Task Scheduler runs this Mon-Fri 08:50 KST on the always-on PC. Output: results\live_console.log
rem live.py ticks every minute until the 15:30 signal, then exits 0. If it crashes, restart up to 5 times (1 min apart).
rem On restart live.py compares broker positions with results\live_state.json and stops without ordering if they differ.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Get the latest pushed code first. If pull fails (network, local changes), run the code already here
echo [%date% %time%] git pull >> results\live_console.log
git pull --ff-only >> results\live_console.log 2>&1
git log -1 --oneline >> results\live_console.log 2>&1
set /a tries=0
:run
python live.py --yes >> results\live_console.log 2>&1
if %errorlevel%==0 goto :eof
set /a tries+=1
echo [%date% %time%] live.py exit %errorlevel%, restart %tries%/5 >> results\live_console.log
if %tries% geq 5 goto :eof
rem timeout fails without console input ("Input redirection is not supported", 11/09 test) -> ping waits ~60 s
ping -n 61 127.0.0.1 > nul
goto run
