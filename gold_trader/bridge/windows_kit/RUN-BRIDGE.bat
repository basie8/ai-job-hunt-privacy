@echo off
REM AURUM bridge - reads XAUUSD candles from MT5 and pushes them.
REM This is the command Task Scheduler runs every 15 minutes.
REM Add --server-offset-hours N here if SETUP.bat's detection was wrong.
cd /d "%~dp0"

REM Everything this prints is captured. Under Task Scheduler there is no
REM console, so without this a failed run says nothing anywhere -- which is
REM exactly how the bridge went silent for seven hours on 2026-09-18.
python mt5_export.py --repo "%CD%" --push >> "%~dp0bridge-console.log" 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] bridge run FAILED >> "%~dp0bridge-console.log"
  exit /b 1
)
