@echo off
setlocal
title AURUM bridge - install the 15 minute schedule
cd /d "%~dp0"

REM ===============================================================
REM   Creates the Task Scheduler entry that runs the bridge every
REM   15 minutes, and verifies Windows actually stored it.
REM
REM   The work is in install-task.ps1, because the two settings
REM   that matter -- what happens to a wedged run, and how long a
REM   run may take -- cannot be set from the schtasks command line.
REM   An earlier version of this file described both in comments
REM   and set neither, and a wedged run duly stopped the bridge
REM   dead on 2026-09-21 with nothing else wrong.
REM ===============================================================

echo.
echo Registering the scheduled task...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-task.ps1" -Folder "%~dp0."

if errorlevel 1 (
  echo.
  echo   The schedule was NOT installed correctly. Nothing is running
  echo   on a timer. If it refused for permissions, right-click this
  echo   file and choose Run as administrator.
  echo.
  pause
  exit /b 1
)

echo ===============================================================
echo   Installed and verified.
echo.
echo   State should be Ready. Running means a job is in progress;
echo   that is now self-healing -- a stuck run is replaced at the
echo   next tick rather than blocking everything behind it, and no
echo   run may take more than 10 minutes.
echo.
echo   Wait 15 minutes, then open bridge-run.log in this folder.
echo   A line lands there whatever happens, success or failure.
echo ===============================================================
echo.
pause
