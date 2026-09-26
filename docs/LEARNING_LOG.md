# Learning log

Append-only record of what has actually been learned and what changed as a
result. Distinct from the journal (per-trade outcomes) and the roadmap (task
status). This is the *why*.

Rules for entries:

- Every change cites its evidence — a sample size, a statistic, or a named observation.
- "Felt wrong" is not evidence. It can be a hypothesis, logged as such.
- Hypotheses stay hypotheses until a sample tests them.
- Nothing is removed. Superseded entries are marked, not deleted.

---

## Current state

**Closed trades: 11** (need 20 to exit Phase 2, 40+ for any setup-level rule
change). Phase 2 of `DEVELOPMENT_PLAN.md` — the bridge is live as of
2026-09-17 and signals are now accumulating. The learning loop is at cold
start; no clamp has engaged. Every statement below is a hypothesis carried in
from design, not a measured finding. Nothing here has earned its place yet.

---

## 2026-09-17 — Baseline established

**What was built:** four-stage pipeline, deterministic risk engine, SMC structure
detection, session/killzone context, macro blackouts, journal with calibration
and per-setup clamps.

**Design hypotheses now in force** (all untested against real gold):

| # | Hypothesis | How it will be tested |
|---|---|---|
| H1 | Stops between 0.6x and 3.0x ATR avoid both noise-stops and unjustifiable risk | Distribution of MAE in R across 40+ closed trades |
| H2 | A 1.5 minimum reward:risk is achievable on gold without starving the sample | Fraction of signals refused on RR alone |
| H3 | The stated setup taxonomy maps to real, distinguishable edges | Per-setup expectancy separating after 40+ trades |
| H4 | 60min/30min event blackout is the right width for gold | Adverse excursion on trades held through releases |
| H5 | The analyst will be overconfident and need shrinking | Calibration curve after 20+ trades |
| H6 | Structural alignment across H4/H1/M15 predicts better outcomes | Win rate split by `smc_alignment` at entry |

**Known weaknesses, stated now so they are not discovered as surprises:**

- SMC detectors have only run on synthetic random walks. Their behaviour on real
  gold — particularly how many order blocks and FVGs a live session generates —
  is unknown. If they produce 40 zones per run, the prompt becomes noise.
- The swing `lookback=2` fractal is arbitrary. It may be too sensitive on M15.
- Session ranges assume the loaded candles cover the session. With 240 M15 bars
  (~60 hours) that holds; with fewer it silently returns nothing.
- `event_fade` and `range_fade` may prove undetectable without discretion.

**Corrections made during the build** (found by tests, not by review):

1. Snapshot staleness measured against wall clock rather than the run clock —
   made replays non-reproducible.
2. Data-freshness check compared file sizes; a new bar usually has the same byte
   count, so real updates reported as "already current".
3. The bridge's first implementation left the user's repo checked out on the data
   branch. Rewritten to use git plumbing and touch nothing.
4. The roadmap auditor recursed into its own test suite — 447 processes spawned
   before it was caught. Guarded.
5. Tasks marked done with an unverifiable predicate vanished from the audit report
   entirely. Now surfaced in their own section.

---

## 2026-09-17 — Component audit: three defects, all the same shape

**Evidence:** static analysis plus a probe of every documented entry point. No
trades involved — this is a code audit, not a trading finding.

**Observation:** three defects, and all three shared a failure pattern worth
naming, because it will recur.

| # | Defect | Why it mattered |
|---|---|---|
| 1 | With no ATR available, the stop-width check silently disappeared | A 10-cent stop on $4305 gold was **approved at 5000oz**. Spread alone would have taken it out. The least reliable input path had the fewest checks. |
| 2 | A malformed `state/calendar.json` raised `JSONDecodeError` and killed the whole run | That file is hand-edited weekly, so it *will* be malformed eventually. A typo would have silently stopped every scheduled signal. |
| 3 | An event row missing a key raised `KeyError` | Same cause, same consequence, from one bad line in an otherwise fine file. |

**The pattern:** *degraded input reduced scrutiny instead of increasing it.* Less
data meant fewer gates, and a hand-edited file was trusted to be well-formed.
Both are backwards.

**Change:**
- Stop width now falls back to a percent-of-spot band (0.12%–0.60%) when ATR is
  unavailable, and is a **hard block** when neither ATR nor spot exists.
- Calendar loading degrades per-row: a bad event is dropped and recorded, the
  derived NFP/claims events survive, confidence reports `invalid`, and the parse
  errors reach the analyst prompt, the risk engine and the audit log.
- Added `gold_trader/selfcheck.py` (20 checks) and `config_checks.py` to catch
  this class mechanically: placeholders in shipped source, limits that contradict
  each other, and cross-artifact drift between code and docs.
- 25 regression tests in `tests_gold/test_degradation.py`.

**Hypothesis affected:** none of H1–H6. This was a robustness finding, not a
market one. H1's stop band is now enforced through two measures rather than one,
which makes it *more* testable, not less.

**Also found and fixed:** the self-check flagged itself (it grepped for the word
`NotImplementedError`, which its own source contains); dead code in
`build_features`; eight unused imports.

**Standing lesson for future audits:** probe the *degraded* paths, not the happy
one. All three defects sat on paths that only execute when something is already
missing — which is exactly when a wrong answer does the most damage.

---

## 2026-09-17 — First real gold data. Two bugs, one hypothesis contradicted.

**Evidence:** 500 H1 bars (2026-08-19 to 2026-09-17), 400 H4, 500 M15, from
Pieter's live MT5 feed. Spot 4362.10. Still zero closed trades — this is a
measurement of the *detectors*, not of any edge.

### The bridge worked, then didn't

The `market-data` branch appeared on the first attempt, with paths
`"data\r/XAUUSD_h1.csv\r"`. Carriage returns baked into the git tree.

**Cause:** `subprocess.run(..., text=True)` translates `\n` to `\r\n` when
writing a child's stdin **on Windows**. `git mktree` reads one entry per line and
took the stray `\r` as part of each filename. Every Linux test passed; the bug
only exists on the platform the bridge actually runs on.

**Change:** stdin is now sent as raw bytes, `_mktree` refuses any entry
containing a line break, and three regression tests assert the call shape rather
than the platform behaviour. The already-pushed branch was repaired from here.

**Lesson worth keeping:** a test suite that runs only on the developer's platform
cannot cover a cross-platform boundary. The guard had to move from *the output*
to *the call*.

### H-SMC-1 (zone count) — CONTRADICTED, and that is good news

The open worry was that live gold would generate so many order blocks and fair
value gaps that the analyst's prompt would become noise. Measured:

| TF | bars | FVGs found | unmitigated | OBs found | unmitigated |
|---|---|---|---|---|---|
| H4 | 400 | 97 | **5** | 131 | **0** |
| H1 | 500 | 115 | **5** | 183 | **13** |
| M15 | 500 | 104 | **5** | 181 | **7** |

The mitigation filter does the whole job: ~100 zones collapse to a handful, and
the display cap of 6 is rarely reached. **No significance filter is needed for
zones.** The concern was misplaced.

### New concern: structure events are far too frequent

183 BOS/CHoCH events across 500 H1 bars is **one structural break every 2.7
bars**. Structure that changes every three candles is not structure. This traces
to swing sensitivity: `lookback=2` produces 24–27 swings per 100 bars on every
timeframe, so the break detector re-arms almost immediately.

**Consequence for H6** (structural alignment predicts outcomes): both alignment
readings currently say "conflicted", and with breaks this frequent that may be
noise rather than signal. H6 is not yet testable in a meaningful way.

**Change:** none to the detector — that is a larger change than a live-data
observation justifies, and there are no closed trades to validate it against.
Logged as roadmap **SMC-04**.

### Bug: duplicate order blocks

Consecutive structure breaks often resolve to the same preceding candle, so the
same zone was emitted twice — visible in the prompt as the identical OB listed
back to back. One zone reading as two confirmations is worse than a wasted line.
Deduplicated on (kind, direction, top, bottom).

### H1 (stop band) — partially answered, and a mis-calibration found

Real ATR by timeframe, with the stop range the 0.6x–3.0x band permits:

| TF | ATR14 | as % of spot | permitted stop | as % of spot |
|---|---|---|---|---|
| M15 | $8.81 | 0.202% | $5.29–$26.43 | 0.121%–0.606% |
| H1 | $20.40 | 0.468% | $12.24–$61.20 | 0.281%–1.403% |
| H4 | $41.54 | 0.952% | $24.92–$124.61 | 0.571%–2.857% |

The ATR band itself looks sane. But the **percent-of-spot fallback** — added last
audit for when ATR is unavailable — was set to 0.12%–0.60%, calibrated against
synthetic data whose ATR was tiny. That ceiling happens to match M15 almost
exactly and would have **refused every legitimate H1 stop**, and every H4 one.

**Change:** fallback band widened to 0.12%–1.50%, covering M15 through H1. H4
swing stops stay outside it deliberately — a multi-day stop should not be set
from a screenshot, which is the only path where the fallback applies.

This is a widened bound, so stating the reasoning explicitly: the ATR band is the
primary check and is unchanged; the fallback exists to *approximate* it when ATR
is missing, and it demonstrably did not. Correcting an approximation to match its
target is not the same as relaxing a limit.

**Hypotheses affected:** H-SMC-1 contradicted (no filter needed). H1 still open —
the band looks plausible but needs MAE data from closed trades. H6 now doubtful
for the reason above.

---

## 2026-09-17 — Fixed-fractional sizing, and a whole CLI that never ran

**Evidence:** 0 closed trades. Two configuration changes and one defect found
while making them.

**Change 1 — sizing is now a percent of current equity.** Risk per trade moved to
1.00% of *equity* (starting notional plus realised P&L), from a flat percent of
the starting notional. After a loss the next trade risks slightly less; after a
win, slightly more. R is untouched: every trade still risks exactly 1R by
definition, so the journal's arithmetic and the whole track record are unaffected
— only the cash figures compound.

This needed a companion. Fixed-fractional sizing never mathematically reaches
zero: a ruined book keeps trading forever in ever-smaller size, and the record
fills with trades that mean nothing. Added a hard `EQUITY_FLOOR` breach at 60% of
the starting notional. It is a *hard* breach, not a warning, because the failure
it prevents is a slow one that nobody notices.

**Change 2 — GBPUSD comes from MT5 now.** The rate was hardcoded with a dated
provenance string and a line in the weekly review asking Pieter to refresh it.
The terminal already had the number. The bridge now reads GBPUSD at the same time
as the candles and writes `data/fx.json`; the pipeline prefers it.

Three ways that can go wrong, all handled as *visible* fallbacks rather than
silent ones: no file (bridge not running) → static rate plus `FX WARNING`; a rate
more than 15% from the static one → refused as a misread symbol, because MT5
symbol resolution landing on the wrong instrument would silently rescale the
entire book; a rate older than 36h → used anyway, but warned about, since an old
real rate still beats a hardcoded one.

**Defect found: `_config()` in the CLI raised `TypeError` on every single
command.** Last session's rename turned `account_usd` from a field into a
property. The CLI still passed it as a constructor keyword. Every command —
`signal`, `status`, `learn`, `doctor`, `calendar` — crashed on the first line.
290 tests were green throughout.

The tests exercised the pipeline and the risk engine directly, never through the
entry point a human actually types. The whole system was unusable and the suite
reported perfect health. Two guards added: a test that every `cmd_*` function can
build its config, and a self-check on the same. The self-check matters more — it
runs on the schedule, against the shipped code.

The recurring lesson gets a second clause. Degraded input must increase scrutiny
— and *a test that never crosses the boundary a human crosses is not testing the
system they use*.

**Hypotheses affected:** none. No trading evidence in this entry.

---

## 2026-09-17 — A run that never happened

**Evidence:** one Routine run, rejected in five seconds.

The 17:23 signal run failed with `You've hit your session limit · resets 5:30pm
(UTC)`. Not a code fault — the account's usage limit, hit while a foreground
session was working. It was found by hand, while answering a question about
whether notifications were configured. Nothing in the system had noticed.

**Why it was invisible.** The run died before `git pull`. It wrote no journal
entry, no audit-log line, no commit, and produced nothing to notify about. The
only trace it left anywhere was the absence of a trace. The dashboard would have
aged past 26 hours and turned red eventually, but only if the outage lasted a
day; a handful of lost runs inside a day would have gone unremarked entirely.

Every failure detector in this system to date watches *output*: a stale claim, a
failing check, an old candle. None of them could see a run that produced no
output at all. Absence has to be measured against an expectation, and the
expectation — the schedule — lived only on the Routine, outside the repo.

**Change.** Every run now records a heartbeat before it finishes, on every path,
including the paths that produce nothing else. The detector compares the
schedule against the record; a scheduled slot with no beat inside its grace
window is a run that never happened.

Two design decisions are worth stating because both were tempting to get wrong:

*Detection reads the repo, not the API.* The Routines API knows **why** a run
failed and is genuinely better evidence — but a detector that depended on it
would go blind in exactly the sessions where the tool might be unavailable.
Expected-versus-recorded needs a clock and a file. The API is an enrichment, and
the audit prompt says to note its absence rather than guess.

*The detector refuses to speak about time it was not watching.* The first
implementation reported every scheduled run since the beginning of the window as
missed, because none of them had heartbeats — nine false alarms on the first
run. A detector that cries wolf on day one is worse than no detector: it teaches
you to ignore the channel before it has ever been right. It now reports "not
armed" until the first heartbeat lands.

**The general lesson**, and the third clause on the standing one: *a system can
only detect failures in the things it produces. To detect a failure to produce
anything, something must independently know what was expected.*

### Found the same day: the state directory was gitignored

Chasing the first defect turned up a worse one. `gold_trader/state/*.jsonl` was
in `.gitignore`, so the journal, the audit log and the brand-new heartbeat could
never be committed. Every `git add gold_trader/state/` in both scheduled
Routines had been a silent no-op since the day they were written.

Containers are ephemeral. `RUNTIME.md` states it plainly — "the repository is
the only durable store in this system" — and the `.gitignore` quietly
contradicted it. Nothing failed, nothing warned. The first signal would have
been journalled, committed to nothing, and gone. The journal would have read
zero trades forever; the learning loop could never have left cold start no
matter how many months it ran; LRN-03 was unreachable by construction. The
system would have looked healthy the entire time, because every check it had
was measuring things that were working.

It was invisible for the same reason as the missed run: **the absence of an
effect looks exactly like a thing that has not happened yet.** An empty journal
during cold start is the expected state, so an empty journal that can never fill
is indistinguishable from it — until something asks whether the write could have
worked at all, which nothing did.

Removed the pattern, with the reasoning written into `.gitignore` itself so
nobody re-adds it in good faith. Guarded by a self-check and a test that run
`git check-ignore` against every state path.

**Hypotheses affected:** none. No trading evidence in this entry.

---

## 2026-09-17 — The pipeline has never run

**Evidence:** the 19:23 signal run, which reported `no Anthropic credentials in
env` and recorded an `error` heartbeat.

The four stages call the Anthropic API directly. That needs a credential of
their own, and a Claude Code session does not provide one: the session
authenticates through the claude.ai subscription, which covers the agent
*driving* the run but is invisible to the pipeline it invokes. Every scheduled
signal run since the Routines were created has failed at the first model call.

**So the journal is empty for two reasons, not one.** It is early — but also the
pipeline has never once completed. I had been attributing the empty journal and
empty audit log entirely to cold start, which was the available explanation and
happened to be true on its own terms. It was not the whole truth, and nothing
distinguished the two until a run finally reported why it stopped.

That is the same shape as the two defects found earlier today, for the third
time: **an expected-looking absence concealing a different cause.** An empty
journal during cold start looks exactly like an empty journal that can never
fill — whether the cause is a gitignore rule, a run that never started, or a
pipeline that cannot authenticate. The run record is what separated them here,
which is the first return on having built it.

**Two fixes, neither of which supplies the key** — that part needs a human:

*The failure now arrives early and explains itself.* The SDK constructs happily
without credentials and raises `TypeError` from inside `_validate_headers` on
the first request, so the error surfaced late and named a header problem rather
than a missing key. `signal` now checks the resolved credential before doing any
feature work and prints what to do about it.

*Verified rather than assumed.* The failing run reported the TypeError as coming
from "client construction before any model call". It does not — construction
succeeds. Writing the guard against that description would have put it in the
wrong place, and it would have passed review while catching nothing. There is
now a test that asserts the SDK constructs without credentials, so if a future
version starts failing earlier, the guard's placement is re-examined rather than
silently redundant.

**Also worth recording:** the run that found this reported it. Push reached the
phone with the error text. The heartbeat it wrote was lost, because that run
predated the gitignore fix by six minutes — but the alert arrived, which is the
first time the notification path has done its actual job.

**Hypotheses affected:** none. Still no trading evidence, and now a documented
reason why there is none.

---

## 2026-09-17 — Gold is not open all the time

**Evidence:** Pieter, unprompted: *"XAUUSD closed between 21:00 - 22:00 UTC."*

Domain knowledge the system did not have, and it invalidated three things at
once.

**The last scheduled run of the day fired inside the close.** The signal Routine
ran at 21:23 UTC, in the middle of the daily rollover. It could never have
produced a tradeable signal. Worse, once the run detector shipped this
afternoon, that slot would have been reported as a missed run *every single
evening* — a false alarm on a schedule, which is precisely how a real alert gets
learned into background noise. Schedule now ends at 19:23.

**The weekend was advice, not a rule.** `is_weekend` existed and fed a line into
the analyst's prompt. The risk engine — the part that actually enforces — had no
concept of a closed market at all. Nothing but the analyst's judgement stopped a
signal being issued into a shut market. That is backwards for this system, whose
whole design is that models advise and code decides. `MARKET_CLOSED` is now a
hard breach covering both closures.

**And candle freshness was judged against the wall clock.** Over a weekend a
perfectly healthy bridge delivers nothing for 48 hours, so DAT-04 and SMC-03
would have reported as stale claims every Saturday. Freshness is not judged
while the market is shut; a bridge that dies during a closure is undetectable
until the reopen anyway, because no candle is expected either way.

**The correction I made to the correction.** 21:00–22:00 UTC is right today and
wrong from November: the close is anchored to 17:00–18:00 *New York*, so the UTC
hour shifts with US daylight saving. Implemented in ET through `zoneinfo`, like
the killzones already were, and the self-check verifies the schedule clears the
break in both summer and winter. Taking the reported UTC hours literally would
have produced a bug that surfaced once, in November, and looked like nothing.

**The pattern, for the fourth time today:** *an absence that looks expected.* No
signals in the evening looked like a quiet market. No candles at the weekend
looked like a quiet market. Neither was — one was a run that could never work,
the other a detector about to cry wolf. Every instance today has been something
the system could not distinguish from normal, and every one was found by
something outside the system: a user's domain knowledge, a failed run's error
text, a dirty git tree.

**Worth stating plainly:** this came from Pieter, not from the code, the tests or
the audits. None of them could have found it — they all encode the same
assumption. The weekly review exists for exactly this, and this is the first
time it has paid.

**Hypotheses affected:** none directly. H1 (stop band) gains a caveat: ATR
computed across a rollover gap spans a discontinuity, so evening H1 readings may
overstate volatility. Worth checking once there are closed trades.

---

## 2026-09-17 — Telling a dead feed from a quiet one

**Evidence:** a four-hour gap in the `market-data` branch (18:39 to 22:43 UTC)
with the Windows PC on throughout, and no way to say what caused it.

The bridge only commits when candle content changes. So a terminal that has
dropped its broker connection and a market that simply is not moving produce the
identical artefact: a bridge that runs every fifteen minutes, finds nothing new,
and pushes nothing. From GitHub the two are indistinguishable. I guessed at the
cause in conversation, which was the wrong thing to do — the right thing was to
make the system able to answer.

**Change:** the bridge now writes `data/bridge.json` every run, carrying the
terminal's connection state, server, ping and build.

**The design decision worth recording: the bridge reports and the pipeline
judges.** The obvious implementation puts the verdict in the bridge — it has the
connection state right there. But whether a disconnection matters depends on
gold's trading hours, and the bridge runs on Windows where `zoneinfo` falls back
to a `tzdata` package that may not be installed. A verdict computed there would
be wrong in exactly the timezone-sensitive way this project has already been bitten
by twice today. Facts travel; judgement stays where the domain knowledge is.

**And the judgement needed Pieter's correction to be right at all.** My first
instinct was that a disconnected terminal is a fault. He said: *"terminal
disconnects from broker when market is closed."* Under the obvious rule this
system would have paged him every single evening and twice at weekends — a false
alarm on a schedule, for the third time today. Disconnection is only a finding
while the market is open.

One further distinction fell out of it: a *stale status file* means the bridge
process is not running, which is a different failure from a dropped link and
outranks it, because a stale file's `connected` flag describes a moment that has
passed. That also gives the bridge a liveness proof independent of whether any
candle moved — the file is rewritten every run regardless.

**The running lesson, fifth instance:** every defect today has been an absence
that looked expected. What is new here is the fix's shape. The earlier ones were
answered by recording more (a heartbeat, a run record). This one needed
recording *and* a rule for reading it, and the rule came from the user, not the
code. A system cannot infer which absences are normal in a domain it only sees
through data.

**Hypotheses affected:** none. No trading evidence.

---

## 2026-09-18 — First closed trade

**Evidence:** 1 closed trade (paper). Long `ob_retest`, entry 4353.00, stop
4339.50, target 4374.00 (R:R 1.56), conviction 0.30 (cold-start clamp).
Signalled 00:37 UTC, filled 00:45, stopped out 03:15 at 4339.50. Result
-1.00R. MFE +0.94R before reversing; MAE -1.39R (the simulated fill's
intra-candle excursion ran past the eventual stop print, which is normal for
worst-case-in-candle resolution and not itself a defect). This is a paper
result — no order was placed, and the fill and stop-out are both simulated
against the candles that followed the signal.

**Observation:** the trade got most of the way to target (+0.94R) before
giving it back and hitting the stop. One trade proves nothing about whether
that pattern (a good excursion that reverses) is real or noise — it needs a
real sample.

Calibration on this single trade: stated conviction 0.30 vs realized outcome
0 (loss), Brier 0.090, nominally "overconfident by 0.30." This is n=1 and is
recorded only because the dashboard and `gold_trader learn` compute it either
way — it is not evidence for or against H5 and must not be read as such
until the 20-trade floor.

**Change:** none. LRN-03 (first 20 closed trades) is now at 1/20 and
genuinely accumulating — this is the first evidence Phase 2 is moving, not
just configured to move.

**Hypotheses affected:** none confirmed or contradicted. Sample is 1;
the floor for any read is 20 (H1-H6) or 40-60 (setup-level, hillclimb). Noted
here only because "first closed trade" is itself the milestone.

---

## 2026-09-21 — Second and third closed trades

**Evidence:** 3 closed trades (paper) total.

- Trade 2: short `ob_retest`, entry 4355.50, stop 4364.50, target 4340.00
  (R:R 1.72), conviction 0.38. Filled 08:15 UTC, target hit 09:30 UTC.
  Result **+1.72R**. MFE +1.73R, MAE -0.26R — a clean run with almost no
  drawdown against the position.
- Trade 3: long `bos_continuation`, entry 4357.00, stop 4346.50, target
  4380.00 (R:R 2.19), conviction 0.50. Filled 13:30 UTC, stopped out 13:45
  UTC — 15 minutes later. Result **-1.00R**. MFE +0.74R, MAE -1.04R.

This is a paper book. No order was placed for either trade; both the fill
and the exit are simulated against the candles that followed the signal, so
these are simulated outcomes, not real ones.

**Observation:** by setup, `ob_retest` is now 2 trades, 1 win, expectancy
+0.36R; `bos_continuation` is 1 trade, 0 wins, expectancy -1.00R. Overall
calibration across all 3 trades: mean stated conviction 0.39 vs realized win
rate 0.33 (Brier 0.241) — nominally overconfident by 0.06, in the direction
H5 predicts. None of this is a finding. n=2 and n=1 per setup, and n=3
overall, are far below the 20-trade floor for any general read and the
40-trade floor for a setup-level one; `gold_trader learn` says as much on
every run and no clamp has moved off 1.00.

Trade 3's speed is worth a note, not a conclusion: 15 minutes from fill to
stop is a fast invalidation on a `bos_continuation` setup, and one data
point cannot say whether that is normal variance or a sign the setup enters
before the continuation is confirmed.

**Change:** none. Sample is below every threshold that licenses a change.
LRN-03 (first 20 closed trades) is now 3/20.

**Hypotheses affected:** none confirmed or contradicted. Recorded because
`gold_trader learn` computes these numbers regardless of sample size, and
the discipline is to log the evidence as it arrives rather than wait for it
to be large enough to be interesting.

---

## 2026-09-22 — Fourth and fifth closed trades: bos_continuation now 0-for-3

**Evidence:** 5 closed trades (paper) total.

- Trade 4: short `bos_continuation`, entry 4330.5, stop 4348.5, target 4303.0
  (R:R 1.53), conviction 0.47. Filled 08:45 UTC, stopped out 17:45 UTC.
  Result **-1.00R**.
- Trade 5: short `bos_continuation`, entry 4333.0, stop 4347.9, target 4308.0
  (R:R 1.66), conviction 0.42. Filled 09:45 UTC, stopped out 17:45 UTC.
  Result **-1.00R**.

Both resolved within the same daily-loss-limit event: the two losses together
hit the -2.0R daily stop, which correctly hard-blocked a subsequent long
setup the risk engine had otherwise approved that day (breach code
`DAILY_LOSS_LIMIT`, recorded in `state/audit.jsonl`). This is a paper book —
no order was placed for either trade; both fills and exits are simulated
against the candles that followed the signal.

**Observation:** `bos_continuation` is now 0 wins from 3 trades, expectancy
-1.00R (every trade in this setup so far has been a full stop-out).
`ob_retest` is unchanged at 2 trades, 1 win, +0.36R expectancy. Overall
calibration across all 5 trades: mean stated conviction 0.41 vs realized win
rate 0.20 (Brier 0.224) — overconfident by 0.21, wider than the 0.06 gap
recorded at n=3. Both directions are consistent with H5 (overconfidence) but
n=3 for the setup and n=5 overall are still far below the 40-trade floor for
any setup-level rule change and the 20-trade floor for a general one. No
clamp has moved off 1.00 and none should yet.

**Change:** none. Recorded because the pattern (`bos_continuation` 0-for-3)
is worth watching, not because it has earned a conclusion — three losses in
the same setup can easily be noise at this sample size, and the daily-loss
hard block worked exactly as designed.

**Hypotheses affected:** none confirmed or contradicted. LRN-03 (first 20
closed trades) is now 5/20.

---

## 2026-09-23 — Sixth closed trade: bos_continuation's first win

**Evidence:** 6 closed trades (paper) total.

- Trade 6: short `bos_continuation`, entry 4313.0, stop 4324.6, target 4294.8
  (R:R 1.60), conviction 0.28. Filled 13:30 UTC, target hit 13:30 UTC same
  bar. Result **+1.569R** (mfe_r 2.306, mae_r -0.0552 — essentially no
  drawdown before it ran). This is a paper book — no order was placed; the
  fill and exit are both simulated against the candles that followed the
  signal.

**Observation:** breaks `bos_continuation`'s 0-for-3 losing streak noted on
2026-09-22. The setup is now 1 win from 4 trades (25%), expectancy -0.36R —
still net negative, since the one win (+1.569R) does not offset three full
stop-outs (-1.00R each). `ob_retest` unchanged at 2 trades, 1 win, +0.36R
expectancy. Overall calibration across 6 trades: mean stated conviction 0.39
vs realized win rate 0.33 (Brier 0.273) — overconfident by 0.06, essentially
unchanged from the n=3 reading.

**Change:** none. n=4 for the setup and n=6 overall are both far below the
40-trade floor for a setup-level change and the 20-trade floor for a general
one. Recorded because a single win after three straight losses is exactly
the kind of swing that invites premature rule changes — it does not, on its
own, contradict the 2026-09-22 observation that `bos_continuation` may be
weaker than `ob_retest`; one data point either way is noise at this sample
size.

**Hypotheses affected:** none confirmed or contradicted. LRN-03 (first 20
closed trades) is now 6/20.

---

## 2026-09-24 — Resolver defect found and fixed; trades 7-9, `fvg_fill` debuts

**Evidence:** 9 closed trades (paper) total. A PC outage froze the MT5 feed
at 12:45 UTC on 2026-09-24, twenty minutes after three signal windows had
already closed at 12:24. That timing accident is the only reason the first
scored prices were anywhere near right, and it exposed two defects in the
outcome resolver:

1. The forward walk had no deadline — it kept checking fill/stop/target over
   every candle after the signal, past `valid_until`, and only fell back to
   an expiry check if the walk ran off the end of the feed. A setup declared
   dead at 12:24 could still fill, run to target, and book a win hours later.
2. When a trade did expire, it was priced at `forward[-1]` — whatever candle
   happened to be newest when `resolve` ran — not the last candle at or
   before the deadline. The same trade could score differently depending on
   what time of day the resolver happened to execute.

Both are fixed: the walk is now bounded by `valid_until`, and expiry prices
at the last candle at or before the deadline (a feed that is merely behind
expires nothing). A `gold_trader rescore` command was added to re-run the
resolver over closed trades after a fix — dry by default, `--apply` writes a
`correction` record ahead of the new outcome rather than silently overwriting
the original, so the journal keeps both verdicts and the reason for the
change.

Applied to the two trades the old resolver had mispriced:
- `3dceb5ac0d43` (`fvg_fill`): -0.39R → **-0.16R**
- `fdc6e55311ff` (`fvg_fill`): -0.38R → **-0.19R**

Both were originally priced off the 12:45 candle (the last one the feed
delivered before the outage) instead of the 12:15 candle actually inside
their windows. A third trade, `42fedd4fe995`, was checked by hand and
correctly stayed `cancelled` — its window's highest high (4287.76) never
reached its entry (4294.50); an earlier hand calculation that called it a
missed win had made exactly the fill-gate error the gate exists to prevent.

New trades since the sixth:
- Trade 7: `ob_retest`, **+1.531R**. `ob_retest` is now 3 trades, 2 wins
  (67%), expectancy +0.75R — the strongest setup so far, though n=3 is far
  below any floor.
- Trades 8 and 9: the corrected `fvg_fill` pair above, both losses. `fvg_fill`
  debuts at 0-for-2, expectancy -0.17R. First data for this setup type;
  meaningless at n=2.

Updated overall picture at n=9: 3 wins (33%), total +0.47R, expectancy
+0.05R. Calibration: mean stated conviction 0.399 vs realized win rate 0.333
(Brier 0.262) — overconfident by 0.07, essentially unchanged from n=6.

**Change:** resolver code fixed (deadline-bound walk, deadline-bound expiry
price); regression tests added (`test_expiry_closes_at_the_last_close` now
asserts the correct behavior instead of the bug). No learning-rule or
risk-limit change — all setup and overall samples remain far below the
20/40-trade floors, and a resolver bug is a code defect, not evidence about
the strategy.

**Hypotheses affected:** none confirmed or contradicted. LRN-03 (first 20
closed trades) is now 9/20.

---

## 2026-09-25 — Trades 10-11, both losses; walk-forward split now visible in `learn`

**Evidence:** 11 closed trades total.
- Trade 10, `c97eb65ac0c4` (`bos_continuation`, short): stopped out -1.0R.
  MFE before the reversal was **+2.06R** — price ran most of the way to
  target, then fully round-tripped back through entry and the stop. Single
  occurrence; not evidence of anything at n=1, but worth watching for a
  pattern of giving back open profit, since the system currently has no
  partial-exit or trail.
- Trade 11, `c90402bfd6e6` (`fvg_fill`, short): stopped out -1.0R, MFE only
  +0.28R — a clean invalidation, nothing unusual.

Both losses landed in the same run (2026-09-25 08:45 UTC exit), which is why
`status` shows -2.00R realized and the daily stop tripped that session.
That's the daily-loss guard doing its job, not a defect.

`bos_continuation` is now 5 closed trades overall (1 win, 20%), not the
"4 trades, 25%" `learn` prints — that command's by-setup table is the
**train** half of the walk-forward split (oldest 70%, currently 7 of 11
trades), not the full journal; the newest 4 trades are held out and reported
separately as the out-of-sample check. Confirmed by tracing `learning.py`
(`walk_forward_split`, `train_frac=0.7`) — this is the intended design, not
a bug, so no code change.

That out-of-sample check is worth flagging on its own: the 4 most recent
trades are 0-for-4 (0% realized), against an in-sample bos_continuation win
rate of 25% and ob_retest of 67%. `learn` already surfaces this as "earlier
lessons are not generalising" — at n=4 that's not actionable (both the
20-trade and 40-trade floors are far off), but it's the first time the
holdout has read meaningfully worse than train, and worth checking again
once the holdout window grows.

**Change:** none. Sample remains far below both floors; no rule, clamp, or
risk-limit changed.

**Hypotheses affected:** none confirmed or contradicted. LRN-03 (first 20
closed trades) is now 11/20.

---

## 2026-09-26 — Two audit-artifact drifts, both the same shape as before

**Evidence:** 11 closed trades total, unchanged since 2026-09-25 (weekend,
market closed — no new signals were possible). No trading evidence in this
entry; this is a code audit.

**Defect 1 — `progress` couldn't tell "the bridge is dead" from "nobody has
synced yet".** `data/` is gitignored on this branch by design: candles live
on `origin/market-data` and only reach the working tree once something pulls
them (`gold_trader/sync.py`). The 12-hourly audit runs `progress` before
`pull-data`, and every fresh container starts with `data/` empty — so
`progress` read DAT-04 and SMC-03 as a **STALE CLAIM** ("no candles in data/
— the bridge has not delivered") on every single run, even on runs where the
bridge was delivering candles fine and 11 trades had already closed from
them. The previous two audits (2026-09-25T18:46Z, 2026-09-26T06:46Z) both
hit this and just noted it as "expected, clears after `pull-data`" rather
than fixing it — the false alarm had already started being tuned out, which
is exactly the failure mode this project's own standing lesson warns about.

**Fix:** the `data:` predicate in `gold_trader/progress.py` now attempts a
best-effort `pull_data_branch()` sync before reading `data/`, the same pull
`pull-data` performs, wrapped so a sync failure (offline, no such remote, not
a git checkout) falls through to whatever is already on disk unchanged.
Regression test added (`test_the_bridge_predicate_syncs_before_declaring_the_bridge_dead`
in `tests_gold/test_progress.py`) that clones a real bare repo carrying a
`market-data` branch, checks out a fresh working copy with no `data/` at
all, and asserts the predicate now reads OK rather than STALE. Verified live:
removing `data/` entirely and re-running `progress` now reports 0 stale
claims instead of 2.

**Defect 2 — the dashboard's candle-freshness check didn't know about
market hours.** `pull-data` and `progress`'s `data:` predicate both already
skip judging candle age while gold is closed (weekday evenings, all
weekend) — that exception was added 2026-09-17 specifically because a
healthy bridge delivers nothing when there is nothing to deliver, and
alarming on it trains the reader to ignore the channel. `dashboard.py`'s own
"Newest candle is N minutes old" critical never got that exception, so the
live dashboard read **health: critical** for a reason that would recur every
evening and all weekend regardless of whether the bridge was actually
healthy — found live today (Saturday), where it was firing on stale weekend
candles the market simply hadn't produced.

**Fix:** the same `market_closed()` check used by `pull-data` now gates this
one critical in `gold_trader/dashboard.py`. The bridge-process-liveness
critical (`bridge.json` older than 45 minutes) is deliberately **not**
gated by market hours — that one is documented in `RUNTIME.md` as checking
whether the always-on Task Scheduler task itself is running, independent of
whether the market is open — and stays as is; it is in fact the thing that
fired live today (see below). Two regression tests added in
`tests_gold/test_dashboard.py` (`CandleStalenessRespectsMarketHours`) proving
the critical still fires on stale candles during market hours and is
suppressed over a weekend.

**Live finding while fixing this:** `data/bridge.json` was 51 minutes old at
audit time (2026-09-26 ~18:50 UTC, a Saturday) — the Task Scheduler task on
Pieter's PC has not run recently. No practical effect right now (the market
is shut, so no candle would arrive either way), but worth a PC check before
Monday's reopen. This is the bridge-liveness check working as designed, not
a code defect, and not reported as a stale claim or a code finding.

**The recurring lesson, restated for the third context it's shown up in:**
the same computation — "is this candle fresh enough, given the market can be
legitimately closed" — is implemented three times (`pull-data`, `progress`,
`dashboard`), and it only takes one of the three skipping the exception to
reintroduce the exact false-alarm-on-a-schedule failure the other two exist
to prevent. Cross-artifact drift doesn't require two docs disagreeing; three
copies of the same rule are three chances for one to fall behind the other
two.

**Hypotheses affected:** none. No trading evidence; two robustness findings,
both fixed with regression tests, neither weakening a check.

---

## Template for future entries

```markdown
## YYYY-MM-DD — <short title>

**Evidence:** n closed trades, <statistic>
**Observation:** what the data actually showed
**Change:** what was altered in code/prompt/limits, or "none — sample too small"
**Hypothesis affected:** H<n>, confirmed / contradicted / still open
```
