@echo off
setlocal enabledelayedexpansion
title AURUM bridge - start MetaTrader 5 with Windows
cd /d "%~dp0"

REM ===============================================================
REM   The scheduled task survives a reboot. MetaTrader 5 does not:
REM   it is an ordinary desktop program and stays closed until
REM   somebody opens it. That makes a restart a silent outage --
REM   the bridge runs every 15 minutes, finds no terminal, and
REM   writes an error nobody is watching for.
REM
REM   This puts a shortcut to the terminal in your Startup folder,
REM   so it opens when you log in. It does nothing else, and you
REM   can undo it by deleting that one shortcut.
REM ===============================================================

set "TERMINAL="

REM An explicit path wins, if one was passed in.
if not "%~1"=="" set "TERMINAL=%~1"

if not defined TERMINAL (
  echo.
  echo Looking for the MetaTrader 5 terminal...
  for %%D in (
    "C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
    "C:\Program Files\MetaTrader 5\terminal64.exe"
    "C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
  ) do (
    REM %%~D strips the surrounding quotes. Keeping them would put a
    REM literal quote inside the variable and break every later use.
    if exist %%D set "TERMINAL=%%~D"
  )
)

if not defined TERMINAL (
  echo.
  echo   Could not find terminal64.exe in the usual places.
  echo   Right-click your MetaTrader 5 shortcut, choose Properties,
  echo   copy the Target, then run:
  echo.
  echo       MT5-AUTOSTART.bat "C:\path\to\terminal64.exe"
  echo.
  pause
  exit /b 1
)

if not exist "!TERMINAL!" (
  echo.
  echo   That path does not exist:
  echo       !TERMINAL!
  echo.
  pause
  exit /b 1
)

echo   found !TERMINAL!
echo.
echo Creating a Startup shortcut...

REM Single quotes inside, double quotes only around the whole thing.
REM A nested double quote ends cmd's argument early, and PowerShell then
REM reads the rest of the path as a command name -- which is precisely
REM what happened on 2026-09-21: "The term 'C:\Program' is not recognized".
REM
REM It also exits with the result of Test-Path rather than PowerShell's own
REM status. The first version reported "Done" over a failure because
REM PowerShell exited 0 after throwing, so errorlevel said nothing useful.
powershell -NoProfile -Command "$t='!TERMINAL!'; $p=Join-Path ([Environment]::GetFolderPath('Startup')) 'MetaTrader 5 (AURUM).lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath=$t; $s.WorkingDirectory=(Split-Path $t); $s.Save(); if (Test-Path $p) { Write-Output ('  created ' + $p); exit 0 } else { exit 1 }"

if errorlevel 1 (
  echo.
  echo   The shortcut was NOT created. Nothing has been changed.
  echo.
  echo   Do it by hand instead, it takes fifteen seconds:
  echo     1. Press Win+R, type  shell:startup  and press Enter.
  echo     2. Right-click inside that folder, New ^> Shortcut.
  echo     3. Paste this as the location:
  echo          !TERMINAL!
  echo     4. Call it whatever you like.
  echo.
  pause
  exit /b 1
)

echo.
echo ===============================================================
echo   Done, and verified: the shortcut exists.
echo   MetaTrader 5 will open when you log in.
echo.
echo   It still has to log in to the broker by itself, so tick
echo   "Save account and password" in the terminal's login dialog.
echo   Without that it opens to a login box and the bridge still
echo   finds nothing.
echo.
echo   To undo: press Win+R, type  shell:startup  and delete
echo   "MetaTrader 5 (AURUM)".
echo ===============================================================
echo.
pause
