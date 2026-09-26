@echo off
setlocal
title AURUM bridge - after a restart
cd /d "%~dp0"

REM ===============================================================
REM   Run this after the PC has restarted, if you want to be sure
REM   the bridge picked itself back up. It changes nothing and
REM   pushes nothing -- it only reports.
REM
REM   You should not normally need it. The scheduled task survives
REM   a reboot on its own. The two things that do NOT come back by
REM   themselves are a Windows login and MetaTrader 5, and those
REM   are exactly what this checks.
REM ===============================================================

set TASKNAME=AURUM bridge

echo.
echo [1/3] Is the scheduled task still registered?
echo.
schtasks /Query /TN "%TASKNAME%" /FO LIST 2>nul | findstr /C:"Status" /C:"Next Run Time" /C:"Last Run Time" /C:"Last Result"
if errorlevel 1 (
  echo.
  echo   The task is GONE. Run INSTALL-TASK.bat to put it back.
  echo.
  pause
  exit /b 1
)
echo.
echo   Status should be Ready, and Next Run Time within 15 minutes.
echo   Status Running means a run is wedged and is blocking the rest.

echo.
echo [2/3] Can this machine reach MetaTrader 5 and GitHub?
echo.
python mt5_export.py --repo "%CD%" --check

echo.
echo [3/3] The last few runs, as the bridge itself recorded them:
echo.
if exist "%~dp0bridge-run.log" (
  powershell -NoProfile -Command "Get-Content '%~dp0bridge-run.log' -Tail 8"
) else (
  echo   No bridge-run.log yet. The task has not run since the log was added.
)

echo.
echo ===============================================================
echo   If MetaTrader 5 is closed, open it and log in. The next
echo   scheduled run is within 15 minutes and will pick up by
echo   itself -- there is nothing to restart.
echo ===============================================================
echo.
pause
