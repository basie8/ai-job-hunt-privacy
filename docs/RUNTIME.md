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

**It also reports itself.** Every run writes `data/bridge.json` with the
terminal's connection state, server, ping and build, and pushes it with the
candles. The bridge judges none of it — deciding whether a disconnection matters
needs gold's trading hours, and `zoneinfo` on Windows depends on a `tzdata`
package that may not be installed. The pipeline does the judging:

| Terminal | Market | Verdict |
|---|---|---|
| Connected | open | fine |
| **Disconnected** | **open** | **critical — the feed is frozen** |
| Disconnected | closed | fine; it drops the link at every close and reconnects at the reopen |
| *file stale >45min* | either | critical — the bridge process itself is not running |

That last row is a different failure from the others and outranks them: a stale
file's `connected` flag describes a moment that has passed. It also means the
status file's own freshness is proof the bridge executed, independently of
whether any candle moved.

This existed because on 2026-09-17 the data branch had a four-hour gap with the
PC on throughout, and nothing could say whether the terminal had dropped its
link or the market had simply been quiet. Both produce a bridge that runs, finds
nothing new, and pushes nothing.

**When it stops:** nothing breaks loudly. The scheduled runs pull stale data, the
staleness gate refuses to signal, and the 12-hourly audit notices and tells you
— once a day, not every two hours.

## 2. Anthropic cloud — the scheduled runs

**Runs:** two Routines in environment `env_01YVG1nS92a8YQdHPQ97wi8E`.

| Routine | ID | Schedule (UTC) |
|---|---|---|
| XAUUSD signal run | `trig_01D5MB5sgfneCfBgVGrjACfb` | `23 7-19/2 * * 1-5` |
| AURUM progress audit | `trig_01E3UHbtVvSfi1DyFiUQdpZs` | `41 6,18 * * *` |

Each firing spins up a **fresh, ephemeral container**, clones the repo, does its
work, pushes, notifies if warranted, and is destroyed. Nothing persists on that
box between runs — no memory, no cache, no state. Continuity comes entirely from
what got committed.

Minimum schedule interval is one hour, so two-hourly is a deliberate choice
rather than a technical floor; hourly is available if you want it.

**Cost:** ~8 signal runs/day × ~$0.35 ≈ $14/week, plus the audits. Billed to your
Anthropic account.

**Credentials — the part that is easy to miss, twice over.**

The four stages call the Anthropic API directly and need their own key. The
session's subscription login does *not* satisfy this: the agent driving the run
is authenticated, the pipeline it invokes is not.

And the obvious variable name does not work. **`ANTHROPIC_API_KEY` is reserved
inside a Claude Code session** — the platform authenticates the session through
the account and refuses to pass that name into the sandbox, saying so in the
environment settings: *"won't be used to authenticate requests"*. Setting it
looks like it worked and changes nothing.

Use a name the platform does not claim:

```
AURUM_ANTHROPIC_API_KEY=sk-ant-...
```

`investment_pipeline.llm` reads `AURUM_ANTHROPIC_API_KEY` first, then falls back
to `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`, which work fine outside a
Claude Code session — a local shell, CI, a plain container.

Without a key the SDK constructs without complaint and raises `TypeError` from
inside `_validate_headers` on the first request, so the failure arrives late and
unexplained. `gold_trader signal` checks first, exits 3, and names the variable
that works. See `docs/INSTALL.md` part 2.

#### Checking the key without running anything

```
python -m gold_trader credentials
```

It reports which variable supplied the key, how many characters it is, and
whether the API accepts it — never the value itself. The probe is `models.list`,
which is authenticated and free, so this costs nothing and can be run as often
as you like. `--no-probe` skips the network and reports only what is set.

Exit codes match `signal`, so a Routine can branch on them without reading prose:

| code | meaning | remedy |
|------|---------|--------|
| 0 | the API accepted the key | nothing to do |
| 3 | no credential variable is set | set `AURUM_ANTHROPIC_API_KEY` |
| 5 | set, sent, and refused (401) | the value is revoked, mistyped, or from another organisation — replace it |
| 2 | the API could not be reached | the key is unjudged; try again |

The distinction between 3 and 5 is the point. A revoked key reported as "no
credentials" sends you hunting for a variable that is already set, which is
exactly what happened on 2026-09-17. Before this command existed, the only way
to learn what a scheduled container actually held was to fire a run and read the
heartbeat it pushed — ten minutes and a commit to answer a question the
container can answer in one second.

### When gold is actually open

Gold trades nearly around the clock, but not quite, and the gaps matter:

| Closure | New York | UTC (summer) | UTC (winter) |
|---|---|---|---|
| Daily rollover | 17:00–18:00, Mon–Thu | 21:00–22:00 | 22:00–23:00 |
| Weekend | Fri 17:00 → Sun 18:00 | Fri 21:00 → Sun 22:00 | Fri 22:00 → Sun 23:00 |

**The UTC hours move with US daylight saving**, so both are defined in New York
time and converted through `zoneinfo`, exactly like the killzones. Hardcoding
21:00–22:00 UTC would be correct for half the year and silently wrong for the
other half — the kind of error that only shows up in November.

Two consequences, both live in code rather than in a prompt:

- **`MARKET_CLOSED` is a hard breach.** Until 2026-09-17 the weekend was
  mentioned to the analyst and enforced nowhere, and the rollover was not
  modelled at all. An entry nobody can take is worse than no entry: it gets
  journalled, then resolved against candles that do not represent tradeable
  prices, quietly poisoning the record the learning loop is built on.
- **The signal Routine stops at 19:23 UTC.** It used to run at 21:23, inside the
  rollover. `gold_trader selfcheck` now verifies that no scheduled slot falls in
  a closure, in both summer and winter.

Candle freshness is judged **per timeframe**, against each series' own cadence
(interval + 30 minutes' grace): 45 minutes for m15, 90 for h1, 270 for h4. A
single flat threshold is a category error — at 90 minutes an h4 bar read STALE
for roughly two thirds of its perfectly normal life, and a reader who sees that
every evening stops believing the word. It cut the other way too: 90 minutes was
far too lax for m15.

Candle freshness is not judged at all while the market is shut. A healthy bridge
delivers nothing over a weekend because there is nothing to deliver, and a
bridge that dies during a closure is undetectable until the reopen either way —
the first run after it catches the gap.

## 3. GitHub — the state

**The repository is the only durable store in this system.** Which means
anything under `gold_trader/state/` must be committable, and a `.gitignore`
rule there is not a tidiness preference — it silently deletes the system's
memory. One such rule was live until 2026-09-17; `gold_trader selfcheck` now
fails if any state path becomes ignored again.
 Containers are
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

`data/` is gitignored on the code branch and **must stay untracked there**. Every
run calls `pull-data`, which checks the directory out of `market-data` into the
working tree; if those files are also tracked here, each run leaves a dirty tree
and each commit duplicates market data onto the code branch, which is precisely
the conflict the two-branch split exists to prevent. They were tracked until
2026-09-17. Nothing needs them committed here: the freshness predicates, the
dashboard and the pipeline all read the working tree that `pull-data` fills.

**Implication worth internalising:** if a run produces a signal and fails to push
the journal, that signal never happened as far as the learning loop is concerned.
The push is the commit, in both senses.

## 4. Your phone — the output

Both Routines carry `notifications: {push: true, email: true}` and stay quiet
unless there is something to act on: an actionable paper signal, a resolved paper
position, a failed check, a missed run, a stale claim, or a blocker that needs a
decision.

**Verified 2026-09-17:** push reaches the Claude app on Android. Email did not
arrive, in any folder, for three runs that fired and succeeded. Push is therefore
the channel this system relies on; email is redundancy that is not currently
working. Since push and email are configured together and only one of them
arrives, the cause is email-specific rather than account-wide — most likely an
email notification preference on the claude.ai account, or an address that
differs from the one being watched. Not a defect in this repository, and not
something a run can detect or fix.

**What this means operationally:** an alert that matters reaches the phone. The
dashboard remains the pull channel and states its own age, turning red past 26
hours. If push ever stops too, the run record (`gold_trader runs`) still shows
whether the runs themselves happened, which separates "nothing to report" from
"nothing is running" without depending on any notification at all.

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
