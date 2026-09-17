@echo off
REM AURUM bridge - reads XAUUSD candles from MT5 and pushes them.
REM This is the command Task Scheduler runs every 15 minutes.
REM Add --server-offset-hours N here if SETUP.bat's detection was wrong.
cd /d "%~dp0"
python mt5_export.py --repo "%CD%" --push
if errorlevel 1 (
  echo.
  echo Bridge run failed. Run TEST-BRIDGE.bat to see why.
  exit /b 1
)
