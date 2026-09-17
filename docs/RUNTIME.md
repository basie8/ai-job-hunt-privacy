# Where this actually runs

Four separate places, none of them a server you rent. Worth knowing precisely,
because the failure modes differ per box.

```
  ┌─────────────────────────┐        ┌──────────────────────────┐
  │  YOUR WINDOWS PC        │        │  GITHUB                  │
  │                         │        │                          │
  │  MetaTrader 5 terminal  │        │  basie8/                 │
  │  mt5_export.py          │──push─▶│  ai-job-hunt-privacy     │
  │  Task Scheduler /15min  │        │                          │
  │                         │        │  branch market-data      │
  │  ⚠ must be powered on   │        │    └ data/*.csv          │
  └─────────────────────────┘        │                          │
                                     │  branch claude/four-...  │
  ┌─────────────────────────┐        │    ├ code                │
  │  ANTHROPIC CLOUD        │        │    ├ gold_trader/state/  │
  │  env_01YVG1nS92a8...    │◀─pull──│    │   journal.jsonl     │
  │                         │        │    │   audit.jsonl       │
  │  Routine: signal  /2h   │──push─▶│    └ docs/               │
  │  Routine: audit   /12h  │        │                          │
  │                         │        │  ⚠ THE ONLY DURABLE STORE│
  │  fresh container each   │        └──────────────────────────┘
  │  fire, then destroyed   │
  └───────────┬─────────────┘        ┌──────────────────────────┐
              │                      │  YOUR PHONE / INBOX      │
              └─────notify──────────▶│  push + email            │
                                     └──────────────────────────┘
```

## 1. Your Windows PC — the bridge

**Runs:** `gold_trader/bridge/mt5_export.py`, via Task Scheduler, every 15 minutes.
**Needs:** MT5 running and logged in; `git push` working without a prompt.
**Produces:** `XAUUSD_{m15,h1,h4}.csv` pushed to the `market-data` branch.

This is the only always-on requirement in the whole system, and the only part
that runs on hardware you control. If the PC sleeps, the laptop lid closes, or
MT5 logs out, candles stop arriving.

**When it stops:** nothing breaks loudly. The scheduled runs pull stale data, the
staleness gate refuses to signal, and the 12-hourly audit notices and tells you
— once a day, not every two hours.

## 2. Anthropic cloud — the scheduled runs

**Runs:** two Routines in environment `env_01YVG1nS92a8YQdHPQ97wi8E`.

| Routine | ID | Schedule (UTC) |
|---|---|---|
| XAUUSD signal run | `trig_01D5MB5sgfneCfBgVGrjACfb` | `23 7-21/2 * * 1-5` |
| AURUM progress audit | `trig_01E3UHbtVvSfi1DyFiUQdpZs` | `41 6,18 * * *` |

Each firing spins up a **fresh, ephemeral container**, clones the repo, does its
work, pushes, notifies if warranted, and is destroyed. Nothing persists on that
box between runs — no memory, no cache, no state. Continuity comes entirely from
what got committed.

Minimum schedule interval is one hour, so two-hourly is a deliberate choice
rather than a technical floor; hourly is available if you want it.

**Cost:** ~8 signal runs/day × ~$0.35 ≈ $14/week, plus the audits. Billed to your
Anthropic account.

## 3. GitHub — the state

**The repository is the only durable store in this system.** Containers are
reclaimed; your PC could be replaced tomorrow. Everything that must survive is
committed:

| What | Where |
|---|---|
| Candles | branch `market-data`, `data/` |
| Trade journal | branch `claude/four-stage-llm-investment-uy6cw4`, `gold_trader/state/journal.jsonl` |
| Audit log | same branch, `gold_trader/state/audit.jsonl` |
| Roadmap, learning log, AURUM doc | same branch, `docs/` |
| Code | same branch |

Two branches on purpose: a bridge push and a journal push can never conflict.

**Implication worth internalising:** if a run produces a signal and fails to push
the journal, that signal never happened as far as the learning loop is concerned.
The push is the commit, in both senses.

## 4. Your phone and inbox — the output

Push notification plus email, fired by the Routines on completion. Both are
configured to stay quiet unless there is something to act on: an actionable
signal, a resolved trade, a stale claim in the audit, or a blocker that needs a
decision.

## What does *not* run anywhere

- **No broker connectivity.** Nothing in this repository can place, modify or
  close an order. Stage 3 emits an order *intent*; you place it by hand.
- **No daemon, no VPS, no always-on service** beyond your own PC.
- **This chat session.** It is ephemeral like any other container. Nothing
  long-running lives here — when it ends, the Routines carry on because they are
  server-side, and the state carries on because it is in git.

## Failure modes by location

| If this stops | Symptom | Who notices |
|---|---|---|
| Your PC / MT5 | Candles go stale | 12-hourly audit, then you, once a day |
| A Routine | No signals, no audits | `gold_trader runs` — every run records a heartbeat, so a run that never happened is visible as a gap |
| Account usage limit | A run is rejected in seconds and does nothing | Same — this is the case the heartbeat was built for |
| GitHub push | Journal silently loses a signal | The next audit sees a gap between audit log and journal |
| Anthropic API | Run errors | The Routine reports the error text — that one always notifies |

The weakest link is the PC, and it fails quietly. That is why the audit runs
twice a day and why the staleness gate is a hard block rather than a warning.

### Runs that never happen

A Routine run can die before it reaches any of this code — the account usage
limit is rejected in seconds, a container may fail to provision, the API may be
down. Such a run writes no commit, sends no alert and leaves no trace. On
2026-09-17 a signal run was rejected for hitting the usage limit and nothing
anywhere said so.

So every run now records a line in `gold_trader/state/heartbeat.jsonl` before it
finishes, **on every path including the ones that produce nothing else** — a flat
read, a hard block, a stale-data early stop. A quiet run and a missing run must
never look the same.

```
python -m gold_trader runs           # gaps in the last 26 hours, exits non-zero on any
python -m gold_trader runs --hours 168 --json-out
```

Detection compares the schedule against the record and needs nothing but a clock
and a file — deliberately, because a detector that called the Routines API would
go blind in exactly the sessions where it matters. The API is still worth
consulting for *why* a run failed, and the audit Routine does so when it can.

Two properties keep it honest. A run inside its 25-minute grace window is not yet
missed, because runs are staggered and take minutes. And the detector reports
"not armed" rather than a wall of failures for any period before its first
recorded heartbeat: it cannot speak for a time it was not watching, and a false
alarm on day one is how a real alert gets learned into background noise.
