@echo off
setlocal enabledelayedexpansion
title AURUM bridge setup
cd /d "%~dp0"

echo.
echo ===============================================================
echo   AURUM bridge setup
echo   Reads XAUUSD candles from MetaTrader 5 and pushes them up.
echo   Read-only: it never places an order and never reads balance.
echo ===============================================================
echo.

REM ---------- 1. Python ----------
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo   ERROR: Python is not on your PATH.
  echo   Install it from https://www.python.org/downloads/
  echo   and TICK "Add python.exe to PATH" on the first installer screen.
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo       found %%v

REM ---------- 2. Git ----------
echo [2/5] Checking Git...
git --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo   ERROR: Git is not on your PATH.
  echo   Install it from https://git-scm.com/download/win
  echo   Accept the defaults; they are fine.
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('git --version 2^>^&1') do echo       found %%v

REM ---------- 3. The one package ----------
echo [3/5] Installing the MetaTrader5 package...
python -m pip install --quiet --upgrade pip >nul 2>&1
python -m pip install --quiet MetaTrader5
if errorlevel 1 (
  echo.
  echo   ERROR: could not install MetaTrader5.
  echo   This package is Windows-only. If you are on 64-bit Windows and
  echo   it still fails, try:  python -m pip install MetaTrader5
  echo   and read the error it prints.
  echo.
  pause
  exit /b 1
)
echo       MetaTrader5 installed

REM ---------- 4. Local git repo (only needs a remote, not the project) ----------
echo [4/5] Preparing the local git repository...
if not exist ".git" (
  git init --quiet
  git remote add origin https://github.com/basie8/ai-job-hunt-privacy.git
  echo       initialised and pointed at the repository
) else (
  echo       already initialised
)
git config user.name  "AURUM bridge"
git config user.email "pietervas@gmail.com"

REM ---------- 5. Dry run ----------
echo [5/5] Reading candles from MetaTrader 5 ^(no push yet^)...
echo.
python mt5_export.py --repo "%CD%"
if errorlevel 1 (
  echo.
  echo   The read failed. Most common causes:
  echo     - MetaTrader 5 is not running, or not logged in
  echo     - Tools ^> Options ^> Expert Advisors ^> "Allow algorithmic trading" is unticked
  echo     - XAUUSD is not in Market Watch ^(right-click ^> Show All^)
  echo   Fix it and run SETUP.bat again.
  echo.
  pause
  exit /b 1
)

echo.
echo ===============================================================
echo   CHECK THE BAR AGES PRINTED ABOVE BEFORE CONTINUING.
echo.
echo   MetaTrader stamps bars in your BROKER'S server time, usually
echo   UTC+2 or UTC+3. The script works the offset out from the
echo   broker's own clock, but if it got it wrong every candle is
echo   shifted and the whole system reads the wrong prices.
echo.
echo   During an open market the m15 bar should be a FEW MINUTES old.
echo   If it says hours, re-run with the right offset, e.g.:
echo       python mt5_export.py --repo "%CD%" --server-offset-hours 3
echo.
echo   If the ages look right, run  RUN-BRIDGE.bat  to push for real.
echo ===============================================================
echo.
pause
