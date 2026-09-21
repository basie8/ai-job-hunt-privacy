@echo off
setlocal
REM Pull the newest bridge script AND launchers from the repository.
REM
REM This used to fetch mt5_export.py alone, so every .bat in this folder
REM stayed at whatever version was in the zip you first downloaded. When
REM INSTALL-TASK.bat was added -- the file that fixes the schedule -- there
REM was no way to receive it short of downloading the kit again.
REM
REM Note for anyone tempted: do NOT run `git pull` in this folder. It is not
REM a clone of the project, only a folder with a remote, and a pull would
REM check the entire repository out on top of your bridge.
title AURUM bridge update
cd /d "%~dp0"
set BRANCH=claude/four-stage-llm-investment-uy6cw4

echo Fetching the latest bridge from the repository...
git fetch origin %BRANCH%
if errorlevel 1 (
  echo Could not reach the repository. Check your connection.
  pause
  exit /b 1
)

REM --worktree, not `git checkout <tree> -- <path>`: that form writes to the
REM index as well, which is how data/ kept becoming tracked on the other side
REM of this system. Same mistake, same fix.
git restore --source origin/%BRANCH% --worktree -- gold_trader/bridge/mt5_export.py gold_trader/bridge/windows_kit
if errorlevel 1 (
  echo Could not read the new files from the repository.
  pause
  exit /b 1
)

echo Updating the bridge script...
copy /Y gold_trader\bridge\mt5_export.py mt5_export.py >nul

echo Updating the launchers...
for %%F in (gold_trader\bridge\windows_kit\*.bat) do (
  REM Skip this file: overwriting a .bat while it is running makes cmd
  REM read the rest of the new file from the old byte offset.
  if /I not "%%~nxF"=="UPDATE.bat" (
    copy /Y "%%F" "%%~nxF" >nul
    echo       %%~nxF
  )
)
copy /Y gold_trader\bridge\windows_kit\UPDATE.bat UPDATE.bat.new >nul

REM Tidy the checkout back out of the way.
rmdir /S /Q gold_trader >nul 2>&1

echo.
echo ===============================================================
echo   Updated. The schedule keeps running; nothing to restart.
echo.
if exist UPDATE.bat.new (
  echo   UPDATE.bat itself could not replace itself while running.
  echo   A new copy is here as UPDATE.bat.new -- rename it over
  echo   UPDATE.bat when you get a moment.
  echo.
)
echo   Run AFTER-RESTART.bat to confirm everything still reports
echo   healthy, or TEST-BRIDGE.bat to read candles without pushing.
echo ===============================================================
echo.
pause
