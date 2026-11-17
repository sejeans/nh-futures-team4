@echo off
rem Task Scheduler runs this Mon-Fri 08:50 KST on this PC (single PC from 11/16, no git pull/push). Output: results\live_console.log
rem live.py enters at 09:00 (if yesterday intraday move >= 0.11), checks the stop every minute, exits at 15:30, then exits 0. If it crashes, restart up to 5 times (1 min apart).
rem On restart live.py compares the broker position with results\live_state.json and stops without ordering if they differ.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem "python" on this PC is the Store stub -> use the repo venv (uv, Python 3.12). Fall back to python if the venv is missing
set PY=..\.venv\Scripts\python.exe
if not exist %PY% set PY=python
echo [%date% %time%] start, %PY% >> results\live_console.log
set /a tries=0
:run
%PY% live.py --yes >> results\live_console.log 2>&1
if %errorlevel%==0 goto end
set /a tries+=1
echo [%date% %time%] live.py exit %errorlevel%, restart %tries%/5 >> results\live_console.log
if %tries% geq 5 goto end
rem timeout fails without console input ("Input redirection is not supported", 11/09 test) -> ping waits ~60 s
ping -n 61 127.0.0.1 > nul
goto run
:end
echo [%date% %time%] end >> results\live_console.log
rem Open a new console with today's fills, position and deposit for the screenshots/ capture (read-only, no orders).
rem The window stays open (cmd /k). Task runs only while logged on, so the window appears on the desktop.
start "NH account" cmd /k %PY% -X utf8 show_account.py
