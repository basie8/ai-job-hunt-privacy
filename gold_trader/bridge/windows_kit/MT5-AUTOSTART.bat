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

echo.
echo Looking for the MetaTrader 5 terminal...

set TERMINAL=
for %%D in (
  "C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
  "C:\Program Files\MetaTrader 5\terminal64.exe"
  "C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
) do (
  if exist %%D set TERMINAL=%%D
)

if "!TERMINAL!"=="" (
  echo.
  echo   Could not find terminal64.exe in the usual places.
  echo   Find it yourself: right-click your MetaTrader 5 shortcut,
  echo   Properties, and copy the Target. Then run:
  echo.
  echo       MT5-AUTOSTART.bat "C:\path\to\terminal64.exe"
  echo.
  if not "%~1"=="" set TERMINAL="%~1"
)
if not "%~1"=="" set TERMINAL="%~1"
if "!TERMINAL!"=="" ( pause & exit /b 1 )

echo   found !TERMINAL!
echo.
echo Creating a Startup shortcut...

powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'MetaTrader 5 (AURUM).lnk')); $s.TargetPath=%TERMINAL%; $s.Save()"
if errorlevel 1 (
  echo   Could not create the shortcut.
  pause
  exit /b 1
)

echo.
echo ===============================================================
echo   Done. MetaTrader 5 will open when you log in.
echo.
echo   It still has to log in to the broker by itself, so make sure
echo   "Save account and password" is ticked in the terminal's
echo   login dialog. Without that it opens to a login box and the
echo   bridge still finds nothing.
echo.
echo   To undo: press Win+R, type  shell:startup  and delete
echo   "MetaTrader 5 (AURUM)".
echo ===============================================================
echo.
pause
