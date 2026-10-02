@echo off
title AURUM bridge - what environment am I running in
cd /d "%~dp0"
REM Reports the environment, touches nothing, pushes nothing.
REM Run this by hand, and let the scheduled task run it too: the
REM difference between the two outputs is the fault.
python mt5_export.py --repo "%CD%" --check
echo.
pause
