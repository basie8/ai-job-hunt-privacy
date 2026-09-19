@echo off
REM Pull the newest version of the bridge script from the repository.
title AURUM bridge update
cd /d "%~dp0"
set BRANCH=claude/four-stage-llm-investment-uy6cw4
echo Fetching the latest bridge script...
git fetch origin %BRANCH%
if errorlevel 1 (
  echo Could not reach the repository. Check your connection.
  pause
  exit /b 1
)
git checkout origin/%BRANCH% -- gold_trader/bridge/mt5_export.py
if errorlevel 1 (
  echo Could not read the script from the repository.
  pause
  exit /b 1
)
copy /Y gold_trader\bridge\mt5_export.py mt5_export.py >nul
echo Updated. Run TEST-BRIDGE.bat to confirm it still reads correctly.
pause
