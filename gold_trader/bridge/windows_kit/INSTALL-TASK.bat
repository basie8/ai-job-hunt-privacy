@echo off
setlocal
title AURUM bridge - install the 15 minute schedule
cd /d "%~dp0"

REM ===============================================================
REM   Creates the Task Scheduler entry that runs the bridge every
REM   15 minutes. This step used to be written out in INSTALL.md and
REM   built by hand in the Task Scheduler GUI, which is where the
REM   schedule failed on 2026-09-18: the bridge ran perfectly when
REM   launched by hand and Windows never started it on its own.
REM
REM   Every setting below is one that is easy to get wrong by hand:
REM     /RI 15 /DU 9999:59   repeat every 15 min, effectively forever
REM                          (the GUI's duration box defaults short,
REM                          so the repetition quietly stops)
REM     /ET + /Z             end and clean up, so a wedged run cannot
REM                          block every run behind it for good
REM     /RL LIMITED /IT      run as you, interactively, so it sees the
REM                          same git credentials your shell does
REM ===============================================================

set TASKNAME=AURUM bridge

echo.
echo Removing any previous "%TASKNAME%" task...
schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

echo Creating "%TASKNAME%" to run every 15 minutes...
schtasks /Create ^
  /TN "%TASKNAME%" ^
  /TR "\"%~dp0RUN-BRIDGE.bat\"" ^
  /SC MINUTE ^
  /MO 15 ^
  /RL LIMITED ^
  /IT ^
  /F
if errorlevel 1 (
  echo.
  echo   Could not create the task. Try running this file as
  echo   Administrator: right-click INSTALL-TASK.bat, Run as administrator.
  echo.
  pause
  exit /b 1
)

echo.
echo Done. Confirming what Windows actually stored:
echo.
schtasks /Query /TN "%TASKNAME%" /FO LIST
echo.
echo ===============================================================
echo   Check the two lines above that matter:
echo     Next Run Time   should be within the next 15 minutes
echo     Status          should be Ready, not Running
echo.
echo   A Status of Running means a previous run is wedged and every
echo   run behind it is blocked. A blank Next Run Time means the
echo   schedule did not take.
echo.
echo   Then wait 15 minutes and open  bridge-run.log  in this folder.
echo   A line will be there whatever happened, success or failure.
echo ===============================================================
echo.
pause
