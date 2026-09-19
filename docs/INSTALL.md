# Going live — full installation

Start to finish. Everything you need to do is in Part 1; the rest is already
running or is reference.

**What "live" means here:** a **paper** book. MT5 supplies candles, the pipeline
produces signals, outcomes are resolved against the candles that follow, and the
journal accumulates a track record. **No order is ever placed.** There is no
execution code in this repository and no setting that adds any — `mode` is
`paper` and the configuration check rejects anything else.

Your MT5 account balance is irrelevant. The bridge only reads market data, so a
£0 balance or a demo account works identically to a funded one.

---

## Part 1 — Your Windows PC (about 20 minutes, once)

This is the only machine you have to touch, and the only Python installation the
project needs from you.

### The short version: use the zip

Download `AURUM-bridge.zip`, unzip it to `C:\AURUM`, and double-click
**SETUP.bat**. It checks Python and Git, installs the one package, prepares the
local repository and does a dry run. Then read the bar ages it prints (§1.5 —
that is the step that matters), and run **RUN-BRIDGE.bat** to push for real.

The kit deliberately does **not** contain the project. The bridge pushes using
git plumbing, so a folder holding just the script, a `data/` directory and a
`.git` is enough — `SETUP.bat` does `git init` and `git remote add` and nothing
more. There is a test asserting this stays true.

The sections below are the same steps done by hand, and the reference for when
something goes wrong.

### 1.1 Python

If `python --version` in Command Prompt doesn't print 3.9 or newer, install it
from [python.org/downloads](https://www.python.org/downloads/). **Tick "Add
python.exe to PATH"** on the first screen of the installer.

### 1.2 The one package

```
pip install MetaTrader5
```

That is the complete dependency list for your side. The bridge script uses
nothing else — no `anthropic`, no API key, no model calls. It reads candles and
runs `git`.

### 1.3 Git

Install [Git for Windows](https://git-scm.com/download/win) if `git --version`
fails. Then clone and confirm you can push without a prompt:

```
git clone https://github.com/basie8/ai-job-hunt-privacy.git C:\aurum
cd C:\aurum
git config user.name "Pieter"
git config user.email "pietervas@gmail.com"
```

Test the push path now, not later — a scheduled task cannot answer a password
prompt:

```
git commit --allow-empty -m "bridge connectivity test"
git push origin claude/four-stage-llm-investment-uy6cw4
```

If it asks for credentials, let Git Credential Manager store them, or set up an
SSH key. If it fails, stop here and fix it — everything downstream depends on it.

### 1.4 MT5

1. Open MetaTrader 5 and log in to your broker's server.
2. **Tools → Options → Expert Advisors → tick "Allow algorithmic trading"**.
3. Make sure XAUUSD (or whatever your broker calls gold) is in Market Watch. If
   you can't see it: right-click Market Watch → Show All.
4. Leave the terminal running. The bridge reads through the running terminal.

### 1.5 First run — dry, no push

```
cd C:\aurum
python gold_trader\bridge\mt5_export.py --repo C:\aurum
```

Expected:

```
Symbol: XAUUSD.m | server offset: UTC+3.0h
  m15   500 bars, last 2026-09-17T14:45:00+00:00 (3min old, close 4312.55) updated
  h1    500 bars, last 2026-09-17T14:00:00+00:00 (48min old, close 4311.20) updated
  h4    400 bars, last 2026-09-17T12:00:00+00:00 (168min old, close 4309.80) updated
```

**Check the bar ages. This is the one step that silently corrupts everything if
it's wrong.** MT5 stamps bars in broker *server* time, usually UTC+2 or UTC+3.
The bridge detects the offset from your broker's tick clock, but if the m15 bar
reads hours old during an active session, the detection was wrong:

```
python gold_trader\bridge\mt5_export.py --repo C:\aurum --server-offset-hours 3
```

Other things that can go wrong here:

| Symptom | Cause | Fix |
|---|---|---|
| `Could not connect to MT5` | Terminal closed, or algo trading disabled | Open it, tick the box |
| `Could not auto-pick a gold symbol` | Broker uses an unusual name | It prints the candidates — pass `--symbol <name>` |
| `MT5 returned no h4 data` | Symbol not in Market Watch | Right-click Market Watch → Show All |
| Ages are negative | Offset over-corrected | Pass `--server-offset-hours` with the right value |

### 1.6 First push

```
python gold_trader\bridge\mt5_export.py --repo C:\aurum --push
```

Expected: `Pushed data/ (3 files) to origin/market-data as a1b2c3d4e5`

This creates the `market-data` branch. It holds nothing but `data/`, so it can
never collide with anything else. The bridge builds its commit with git plumbing
and **never checks out, stashes or switches branches** — running it on a schedule
cannot disturb whatever you're working on.

### 1.7 Schedule it

**Run `INSTALL-TASK.bat`.** `SETUP.bat` now calls it as its last step, so if
you ran setup the task already exists. It registers "AURUM bridge" to run every
15 minutes and then prints back what Windows actually stored, so you can see
the schedule took rather than assume it did.

Two lines in that output are the ones that matter:

- **Next Run Time** — should be within the next 15 minutes. Blank means the
  schedule did not take.
- **Status** — should be **Ready**. **Running** means a previous run is wedged,
  and by default Windows will not start another while one is running, so every
  run behind it is blocked indefinitely.

Building this by hand is what failed on 2026-09-18: the bridge ran perfectly
when launched manually and Windows never started it on its own, for seven
hours, on an open market. Setup checked Python, checked Git, installed the
package, prepared the repository and did a dry run — everything except the one
step that makes it run. Use the script.

<details>
<summary>The hand-built equivalent, if you ever need it</summary>

Task Scheduler → **Create Task** (not "Create Basic Task"):

- **General**: name it `AURUM bridge`. Select *Run whether user is logged on or
  not*. Tick *Run with highest privileges* if the task won't start otherwise.
- **Triggers** → New: *Daily*, *Repeat task every 15 minutes* for *1 day*, and
  set *Indefinitely* where the duration dropdown offers it.
- **Actions** → New: *Start a program*
  - Program: `python.exe` (or the full path from `where python`)
  - Arguments: `C:\aurum\gold_trader\bridge\mt5_export.py --repo C:\aurum --push`
  - Start in: `C:\aurum`
- **Conditions**: untick *Start the task only if the computer is on AC power* if
  it's a laptop. Untick *Stop if the computer switches to battery power*.
- **Settings**: tick *Run task as soon as possible after a scheduled start is
  missed*.

</details>

Identical candles produce no commit, so a 15-minute cadence does not fill the
branch with noise.

### 1.7b What environment is the task actually running in?

`CHECK-BRIDGE.bat` reports it: the account, the Python that resolved, where git
was found, whether the remote is reachable. Run it by hand, then let the
scheduled task run the same thing. **The difference between the two outputs is
the fault** — almost always a different account with a different PATH, or git
credentials the scheduled user cannot see.

The usual one: Git for Windows offers *"Use Git from Git Bash only"*, which
keeps git off the system PATH deliberately. Git Bash then works perfectly and
Task Scheduler cannot find git at all, so the read succeeds and only the push
fails. The bridge now looks in the standard install locations before giving up,
and says exactly this if it still cannot find one.

### 1.7a When it runs by hand but not on schedule

This happened on 2026-09-18 and it is the common failure, so it is worth
knowing how to split it in two. Every run appends a line to `C:\aurum\bridge-run.log`
whatever the outcome, and that file is never pushed — when the push is what
is broken, a pushed log cannot report it. Open it first:

- **No entries for the last hour** → Windows is not starting the task. The
  script is fine; the trigger or the run context is not.
- **Entries saying `error`** → the task *is* starting and something downstream
  is failing. Read the message on the line.

For the first case, in order of how often each one is the answer:

1. **The repetition was not saved.** In Triggers → New, "Repeat task every: 15
   minutes" lives under *Advanced settings*, and the *for a duration of* box
   beside it defaults to something short. Set it to **Indefinitely**. Check
   the task's **Next Run Time** column afterwards — if it is blank or a day
   away, the trigger is not what you think it is.
2. **A previous instance is still marked running.** Settings → *If the task is
   already running* → "Do not start a new instance" is the default, so one
   hung run blocks every run after it, forever, silently. The task list shows
   Status **Running** rather than Ready. End it, then set *Stop the task if it
   runs longer than* to 10 minutes so it can never wedge again.
3. **"Run whether user is logged on or not" without usable credentials.**
   Windows needs the account password, and a password change since the task
   was created invalidates it. Last Run Result shows `0x4` or a permission
   error. Re-enter it, or switch to *Run only when user is logged on* if the
   PC stays signed in.
4. **Conditions.** On a laptop, untick *Start the task only if the computer is
   on AC power* and *Stop if the computer switches to battery power*.

For the second case — the task runs but nothing arrives — the usual cause is
**git credentials**. Your own session reads the Windows Credential Manager; a
task running as another account or as SYSTEM may not see it, so the push fails
with an authentication error while everything else works. Run the task under
your own user account, or configure a credential helper that does not depend
on the interactive session.

The cloud side notices either way: `bridge.json` stops being rewritten, and
the dashboard says the bridge is late after 20 minutes and dead after 45. But
the log is what says *why*.

### 1.8 The paper book, as configured

Both numbers are now set, so there is nothing to reply with:

- **Notional** — GBP 10,000. It scales the displayed cash only; performance is
  measured in R, which doesn't care.
- **Risk per trade** — 1.00% of *current equity*, not of the starting notional.
  The book opens risking GBP 100 (about $134); after a losing trade the next one
  risks slightly less, after a winner slightly more. Every trade still risks
  exactly 1R by definition, so the track record is unaffected.
- **Ruin floor** — trading halts entirely if equity falls to 60% of the starting
  notional. Fixed-fractional sizing never mathematically reaches zero, so without
  a floor a ruined book would trade forever in meaningless size.
- **GBPUSD** — read from your MT5 terminal by the bridge, alongside the candles,
  and written to `data\fx.json`. Nothing to maintain. If your terminal has no
  GBPUSD symbol the bridge says so and the system falls back to a documented
  static rate with a visible `FX WARNING` on every run.

What is still worth sending: the CPI / PCE / PPI release dates for the next few
weeks (BLS and BEA publish them). Those go in `state/calendar.json` and make the
event blackouts accurate instead of `derived_only`.

---

## Part 2 — Already running, nothing to install

| Component | Where | Schedule |
|---|---|---|
| Signal pipeline | Anthropic cloud, fresh container per run | 2-hourly, weekdays 07:23–21:23 UTC |
| Progress + component audit | Same | 06:41 and 18:41 UTC daily |
| Dashboard | Published artifact, republished by both runs | — |
| Alerts | Push to your phone + email | Only when there's something to act on |

Python, the `anthropic` SDK and the repository are installed fresh in each cloud
container. You never touch them.

### One thing the cloud side does need from you: an API key

The four stages call the Anthropic API directly, and that needs a credential of
its own. A Claude Code session authenticates through your claude.ai
subscription, which covers the agent *driving* the run but is not visible to the
pipeline it invokes — so a scheduled run has credentials for one and none for
the other. Discovered the hard way on 2026-09-17: `signal` failed with a
`TypeError` from inside the SDK.

To fix, add the key to the cloud environment the Routines use:

1. Create a key at [console.anthropic.com](https://console.anthropic.com) →
   API keys. This is **separate from the claude.ai subscription** and bills
   pay-as-you-go.
2. At [claude.ai/code](https://claude.ai/code), click the **cloud icon above the
   message box** → hover the environment (**PIM**) → **gear** → **Environment
   variables**, and add one line:

   ```
   AURUM_ANTHROPIC_API_KEY=sk-ant-...
   ```

   **Not `ANTHROPIC_API_KEY`.** That name is reserved inside a Claude Code
   session: the platform authenticates the session through your account and
   drops it, warning *"won't be used to authenticate requests"*. It looks like
   it worked and does nothing.
3. The next scheduled run picks it up. Nothing to redeploy.

**Cost:** roughly $0.35 per signal run at the configured model tiers, so about
8 runs a weekday ≈ $14/week, plus the audits. Reduce it by widening the signal
Routine's interval if that is more than you want to spend while the book is
still on paper.

Until the key is in place, everything that does not call a model still works —
`resolve`, `status`, `learn`, `runs`, `progress`, `selfcheck`, `dashboard`,
`pull-data`. The bridge keeps delivering candles and the journal keeps its
integrity; only the four stages are blocked, so no signal can be produced.

---

## Part 3 — Confirming it worked

Once the bridge has pushed once, the next scheduled run picks it up. To check
immediately rather than waiting, ask me in a session and I'll run it, or watch
for these:

**Within 15 minutes of 1.6** — the `market-data` branch exists on GitHub with
three CSVs in `data/`.

**Within one scheduled cycle** — the dashboard's "Candle feed" panel changes from
a dashed *No candles yet* block to a table of bar counts and ages, and the amber
`bridge` warning disappears from the problems list.

**Within a day** — the roadmap's `DAT-04` row flips from blocked to done on its
own, because its check is `journal:1` and the audit verifies rather than trusts.
Phase 1's gate verifies and the plan advances to Phase 2.

**Then nothing much, for three to five weeks.** Phase 2 is deliberately
uneventful: signals accumulate, the learning loop stays inert below 20 closed
trades, and most runs will correctly produce no trade at all. A quiet system at
this stage is a working system.

---

## Part 4 — When something breaks

The design rule is that nothing fails silently, so the failure usually finds you.

| What you'll see | What it means | What to do |
|---|---|---|
| Dashboard ribbon red, "data stale" | No fresh candles for 26h+ | Check the PC is on, MT5 is logged in, the task ran |
| Amber `bridge` warning | Bridge hasn't pushed yet, or is behind | Run 1.5 by hand and read the output |
| Push alert about a failing check | A component regressed | It's already being fixed by the audit run; read its report |
| Push alert about a stale claim | The roadmap claims something untrue | Same — the audit fixes or corrects it |
| No alerts at all for >24h | Either quiet markets or the Routines stopped | Ask me to run `progress` and `pull-data` |

Diagnostics you can run yourself from a session with me:

```bash
python -m gold_trader doctor      # what data is reachable
python -m gold_trader pull-data   # is the bridge delivering? exits non-zero if stale
python -m gold_trader selfcheck   # 20 component checks
python -m gold_trader progress    # roadmap audit, verified not asserted
python -m gold_trader status      # open paper positions and budgets
python -m gold_trader learn       # the measured track record
```

---

## Part 5 — Stopping

- **Pause the bridge:** disable the Task Scheduler entry. Runs will go quiet on
  stale data rather than signalling on old prices.
- **Pause the signals:** ask me to disable the Routines. They stay stored.
- **Stop entirely:** ask me to delete the Routines. The journal and audit log
  stay in the repository as a permanent record.

Nothing here has any connection to your money. The account balance is never read,
no order function exists in the codebase, and every result is a simulation
resolved against candles.
