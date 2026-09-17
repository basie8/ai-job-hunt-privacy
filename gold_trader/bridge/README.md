# MT5 → repo bridge

Your machine has the prices; this environment cannot reach any market data host.
The bridge closes that gap: it pulls XAUUSD candles from your local MetaTrader 5
terminal, writes them as CSVs, and pushes them to a dedicated `market-data`
branch. The scheduled session pulls that branch and runs the pipeline.

```
  your PC                          GitHub                     scheduled session
  ┌──────────────┐                 ┌──────────────┐           ┌────────────────┐
  │ MT5 terminal │──mt5_export.py─▶│ market-data  │──pull────▶│ gold_trader    │
  │              │   (Task Sched.) │ branch       │  -data    │ signal → alert │
  └──────────────┘                 └──────────────┘           └────────────────┘
                                          ▲                            │
                                          └────── journal ─────────────┘
                                                (working branch)
```

## Why a separate branch

The bridge builds its commit with git plumbing — `hash-object`, `mktree`,
`commit-tree` — and pushes the object directly. It **never checks out, stashes,
or switches branches**, so running on a schedule cannot disturb the branch you
are on or the edits you have in flight. There is a test for exactly that.

The branch holds nothing but `data/`, so a bridge push and a journal push from
the scheduled session can never conflict.

## Setup (Windows, where MT5 runs)

1. **Install the package** (Windows-only):
   ```
   pip install MetaTrader5
   ```

2. **Enable the API** in MT5: *Tools → Options → Expert Advisors →
   "Allow algorithmic trading"*. Leave the terminal running and logged in — the
   bridge reads through the running terminal, not a separate connection.

3. **Clone the repo** somewhere on that machine and make sure `git push` works
   without an interactive prompt (SSH key or a credential helper).

4. **Dry run**, no push:
   ```
   python gold_trader\bridge\mt5_export.py --repo C:\path\to\ai-job-hunt-privacy
   ```
   Check the output. It prints the symbol it picked, the detected server offset,
   and each series' last bar with its age:
   ```
   Symbol: XAUUSD.m | server offset: UTC+3.0h
     m15   500 bars, last 2026-09-17T14:45:00+00:00 (3min old, close 4312.55) updated
     h1    500 bars, last 2026-09-17T14:00:00+00:00 (48min old, close 4311.20) updated
     h4    400 bars, last 2026-09-17T12:00:00+00:00 (168min old, close 4309.80) updated
   ```

5. **Check the server offset.** This is the one setting that silently corrupts
   everything if it is wrong. MT5 stamps bars in *broker server* time (usually
   UTC+2 or UTC+3), and the bridge detects the offset from the broker's own tick
   clock. If the ages above look wrong — an m15 bar that should be minutes old
   reading as hours — override it:
   ```
   --server-offset-hours 3
   ```

6. **Push for real**:
   ```
   python gold_trader\bridge\mt5_export.py --repo C:\path\to\repo --push
   ```

7. **Schedule it.** Task Scheduler → Create Task:
   - *Triggers*: daily, repeat every 15 minutes, for a duration of 1 day
   - *Action*: `python.exe` with arguments
     `C:\path\to\repo\gold_trader\bridge\mt5_export.py --repo C:\path\to\repo --push`
   - *Conditions*: untick "Start only if on AC power" if it is a laptop
   - Run it whether or not the user is logged on

   Identical candles produce no commit, so a 15-minute cadence does not fill the
   branch with noise.

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--repo` | required | Your clone of this repository |
| `--symbol` | auto | Override the broker's gold symbol (`XAUUSD.m`, `GOLD`, …) |
| `--timeframes` | `m15,h1,h4` | Which series to export |
| `--bars` | 500 / 400 | Bars per timeframe |
| `--server-offset-hours` | auto | Broker server time minus UTC |
| `--push` | off | Commit and push to `market-data` |
| `--from-dir` | — | Skip MT5 and push an existing CSV directory (macOS/Linux) |

## Not on Windows?

`--from-dir` pushes a directory you fill by other means — a TradingView export,
a cTrader/Dukascopy download, or your own broker API script. The only contract is
the filename (`XAUUSD_h1.csv`) and that the CSV has time/open/high/low/close
columns; the parser aliases the usual spellings, so exports rarely need editing.

## Verifying the other end

From the scheduled session, or here:

```bash
python -m gold_trader pull-data
```

It fetches the branch, reports each series' age, and **exits non-zero if
everything is older than 90 minutes** — so a stalled bridge fails loudly instead
of the pipeline quietly signalling on yesterday's prices.

## Safety note

The bridge is read-only with respect to MT5. It calls `copy_rates_from_pos` and
`symbol_info_tick` and nothing else — there is no order function anywhere in this
repository.

**Your account balance is irrelevant.** The bridge only reads market data, so a
£0 balance or a demo account works identically to a funded one. The terminal just
has to be running and logged in to the broker's server. The system runs a **paper
book**: signals are journalled and resolved against the candles that follow, and
no order is ever placed anywhere.
