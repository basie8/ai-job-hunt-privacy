@echo off
REM Read candles and print them. Pushes nothing. Safe to run any time.
title AURUM bridge test
cd /d "%~dp0"
python mt5_export.py --repo "%CD%"
echo.
echo Nothing was pushed. Check the bar ages above.
echo During an open market the m15 bar should be a few minutes old.
pause
