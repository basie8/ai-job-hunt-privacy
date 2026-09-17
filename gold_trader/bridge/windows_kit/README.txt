================================================================================
 AURUM BRIDGE - Windows setup
================================================================================

 WHAT THIS IS
 ------------
 A small script that reads XAUUSD candles from your MetaTrader 5 terminal and
 pushes them to GitHub, where the analysis pipeline picks them up.

 It is READ-ONLY with respect to MetaTrader. It calls two functions: one to read
 candles, one to read the clock. There is no order function in this kit or in
 the wider project, and your account balance is never read or used. A GBP 0.00
 balance or a demo account works exactly the same - the terminal only has to be
 running and logged in.

 The whole system runs a PAPER book. Signals are recorded and scored against the
 candles that follow them. No order is ever placed anywhere.


 BEFORE YOU START
 ----------------
 1. Python 3.9 or newer    https://www.python.org/downloads/
    TICK "Add python.exe to PATH" on the first installer screen.
 2. Git for Windows        https://git-scm.com/download/win
    Accept the defaults.
 3. MetaTrader 5, running and logged in to your broker.
    In MT5: Tools > Options > Expert Advisors > tick "Allow algorithmic trading"
    In MT5: make sure XAUUSD appears in Market Watch
            (if not: right-click Market Watch > Show All)


 SETUP - three steps
 -------------------
 1. Put this folder somewhere sensible, for example  C:\AURUM
    (Unzip it so that SETUP.bat sits directly inside C:\AURUM.)

 2. Double-click  SETUP.bat
    It checks Python and Git, installs the one package it needs, prepares the
    local repository, and reads candles without pushing anything.

 3. READ THE BAR AGES IT PRINTS. This is the step that matters.

    You should see something like:

      Symbol: XAUUSD.m | server offset: UTC+3.0h
        m15   500 bars, last 2026-09-17T14:45:00+00:00 (3min old, close 4312.55)
        h1    500 bars, last 2026-09-17T14:00:00+00:00 (48min old, close 4311.20)
        h4    400 bars, last 2026-09-17T12:00:00+00:00 (168min old, close 4309.80)

    During an open market the m15 bar should be a FEW MINUTES old. MetaTrader
    stamps bars in your broker's server time (usually UTC+2 or UTC+3), and the
    script works the offset out from the broker's own clock. If it gets that
    wrong, every candle is shifted and the system reads the wrong prices while
    looking perfectly healthy. If the ages are wrong, open a Command Prompt here
    and run it with the offset stated explicitly:

        python mt5_export.py --repo "%CD%" --server-offset-hours 3

    Then put that same flag into RUN-BRIDGE.bat.

 4. When the ages look right, double-click  RUN-BRIDGE.bat
    The first push may ask for your GitHub credentials. Let Git Credential
    Manager save them - a scheduled task cannot answer a password prompt.

    Expect:  Pushed data/ (3 files) to origin/market-data as a1b2c3d4e5


 SCHEDULE IT - every 15 minutes
 ------------------------------
 Open Task Scheduler, choose "Create Task" (NOT "Create Basic Task"):

   General    Name: AURUM bridge
              Select "Run whether user is logged on or not"

   Triggers   New > Daily
              Tick "Repeat task every: 15 minutes"
              For a duration of: Indefinitely

   Actions    New > Start a program
              Program/script:   C:\AURUM\RUN-BRIDGE.bat
              Start in:         C:\AURUM

   Conditions On a laptop, UNTICK "Start the task only if the computer is on
              AC power" and "Stop if the computer switches to battery power"

   Settings   Tick "Run task as soon as possible after a scheduled start is
              missed"

 Identical candles produce no commit, so running every 15 minutes does not fill
 the repository with noise.


 THE FILES IN THIS FOLDER
 ------------------------
   SETUP.bat              Run this first. One-time setup.
   TEST-BRIDGE.bat        Read candles and print them. Pushes nothing. Safe.
   RUN-BRIDGE.bat         The real thing. This is what Task Scheduler runs.
   UPDATE.bat             Fetch a newer version of the bridge script.
   mt5_export.py          The bridge itself. ~250 lines, readable.
   calendar.example.json  Template for the economic calendar (see below).
   INSTALL.md             The fuller guide, including what runs in the cloud.


 IF SOMETHING GOES WRONG
 -----------------------
   "Could not connect to MT5"
       The terminal is closed, not logged in, or algorithmic trading is off.

   "Could not auto-pick a gold symbol"
       Your broker uses an unusual name. The script prints the candidates it
       found - re-run with  --symbol <thatname>

   "MT5 returned no h4 data"
       The symbol is not in Market Watch. Right-click Market Watch > Show All.

   Bar ages are negative
       The offset over-corrected. Pass --server-offset-hours with the right
       value.

   The push asks for a password every time
       Git Credential Manager did not save. Run:
           git config --global credential.helper manager
       then push once by hand and let it store the credentials.


 OPTIONAL - the economic calendar
 --------------------------------
 calendar.example.json holds the two remaining 2026 FOMC dates, taken from
 federalreserve.gov. The CPI and PCE entries are deliberately left blank because
 I could not verify them. Fill them in from the BLS and BEA release schedules
 and send the file back, and the event blackout windows become accurate instead
 of incomplete. Until then the system knows about payrolls and jobless claims
 (it derives those) and warns that the rest of the diary is unknown.


 WHAT HAPPENS AFTER THIS
 -----------------------
 Nothing you need to do. Every two hours on weekdays the pipeline wakes up in
 the cloud, pulls your candles, produces a signal or (more often) correctly
 decides not to, and updates the dashboard. You get a phone notification only
 when there is an actual signal or a position resolved.

 Expect it to be quiet. A system that refuses most setups is working.
================================================================================
