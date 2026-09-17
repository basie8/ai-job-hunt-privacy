# Development plan

A lot has been specified across several conversations. This is that material
organised into phases, each with an **entry gate**, a **defined scope**, and an
**exit gate that is machine-checkable**. A phase does not end because it feels
finished; it ends when its gate verifies.

Current position: **Phase 1, blocked.**

| Phase | Name | Gate to exit | State |
|---|---|---|---|
| 0 | Foundation | `selfcheck` green, suites pass | ✅ complete |
| 1 | First data | ≥1 candle from the live bridge | 🔴 blocked on you |
| 2 | Cold start | 20 closed trades journalled | ⏸ waiting |
| 3 | Learning active | Clamps engaged, calibration measured | ⏸ waiting |
| 4 | Validation | 60 trades, H1–H6 tested | ⏸ waiting |
| 5 | Refinement | Backtest + hillclimb against a real sample | ⏸ waiting |

---

## Phase 0 — Foundation ✅

Four-stage pipeline, deterministic risk engine, SMC structure detection, session
and killzone context, macro blackouts, hash-chained audit log, journal with
calibration and per-setup clamps, MT5 bridge, self-verifying roadmap audit,
component self-check.

**Exit gate:** `python -m gold_trader selfcheck` → 20/20; `tests_gold` 221 pass;
`tests` 44 pass. **Verified.**

## Phase 1 — First data 🔴

**Entry gate:** Phase 0 complete.

**Scope:** get real XAUUSD candles flowing from your MT5 terminal into the
pipeline. Nothing else in this phase.

**Note:** the MT5 account balance is irrelevant. The bridge only reads market
data, so a £0 balance or a demo account works exactly the same. The terminal
just has to be running and logged in to the broker's server.

**Yours:**
1. `pip install MetaTrader5` on the Windows box
2. Enable *Allow algorithmic trading* in MT5
3. Dry-run `mt5_export.py`, **check the reported bar ages** — this is where the
   broker server-time offset gets caught
4. Add the Task Scheduler entry, every 15 minutes
5. Copy `examples/calendar.example.json` → `state/calendar.json`, fill the CPI
   and PCE dates
6. Tell me the **paper** account notional and risk-per-trade percent to size against
   (it scales the dollar figures only — performance is measured in R, which does not
   care what the notional is)

**Mine:** nothing. This phase is entirely on your side, which is why it is the
critical path.

**Exit gate:** `python -m gold_trader pull-data` exits 0 with a bar under 90
minutes old. Roadmap row DAT-04 flips to done on its own.

**What unblocks:** SMC-03, LRN-03, LRN-04, LRN-05, MAC-02, EVL-02.

## Phase 2 — Cold start ⏸

**Entry gate:** DAT-04 verified.

**Scope:** accumulate the first real sample. The learning loop deliberately does
nothing during this phase — no clamps, no blocks, no conviction shrinkage. It is
data collection, and it should feel uneventful.

**Mine, in the first week of live data:**
- Validate the SMC detectors against real gold. The open question is **zone
  count**: if a live session generates 40 order blocks and FVGs, the prompt
  becomes noise and the detectors need a significance filter. Synthetic data
  cannot answer this.
- Re-check the swing `lookback=2` fractal on real M15. It may be too sensitive.
- Confirm real ATR values sit sensibly inside the 0.6x–3.0x stop band on $4300
  gold rather than at an edge.

**Yours:** the weekly review, every week, from the first one. Especially the
loss post-mortems — thesis / level / variance.

**Exit gate:** `journal:20`. Roughly 3–5 weeks at 4 signals/day maximum and the
observed refusal rate.

**Risk in this phase:** the temptation to change rules off 3 trades. The sample
floor exists to stop that, and the weekly review has the same rule written into
it. If I propose a change with n<20, push back.

## Phase 3 — Learning active ⏸

**Entry gate:** `learning:active` (20 closed trades).

**Scope:** the clamps switch on. Conviction shrinkage from measured calibration,
per-setup size multipliers, the first setup blocks if any setup has earned one.

**Mine:**
- First real calibration reading. H5 predicts overconfidence; this tests it.
- Per-setup expectancy separating, or not (H3). If every setup has the same
  expectancy, the taxonomy is not carving reality and needs rethinking.
- First `LEARNING_LOG.md` entry backed by evidence rather than design intent.

**Exit gate:** clamps demonstrably engaged, calibration curve recorded, at least
one hypothesis confirmed or contradicted in the learning log.

## Phase 4 — Validation ⏸

**Entry gate:** 60 closed trades.

**Scope:** test the six hypotheses in `LEARNING_LOG.md` against the record.

| Hypothesis | Test |
|---|---|
| H1 stop band | MAE distribution in R |
| H2 reward:risk floor | Fraction of signals refused on RR alone |
| H3 taxonomy carves reality | Per-setup expectancy separation |
| H4 blackout width | Adverse excursion through releases |
| H5 overconfidence | Calibration curve |
| H6 alignment predicts | Win rate split by `smc_alignment` |

**Exit gate:** each of H1–H6 marked confirmed, contradicted, or still open with
a stated reason.

**Likely outcome, stated in advance so it is not a disappointment:** some
hypotheses will be contradicted. That is the phase working.

## Phase 5 — Refinement ⏸

**Entry gate:** Phase 4 complete.

**Scope:** EVL-01 backtest harness (score setups over historical candles without
risking money) and EVL-02 prompt hillclimb against the journal as an eval set.
Both are pointless earlier — a hillclimb against 10 trades fits noise.

---

## The weekly cycle

Runs from Phase 2 onward, every week, regardless of phase.

| Step | Who | What |
|---|---|---|
| 1 | Automatic | `selfcheck` + `progress` in the 12-hourly audit |
| 2 | You | Fill `docs/WEEKLY_REVIEW.md` and paste it in |
| 3 | Me | Flag signals you would have skipped; look for the pattern behind them |
| 4 | Me | Apply improvements: bugs, rule changes with evidence, doc drift |
| 5 | Me | Append to `LEARNING_LOG.md` **only if something was learned** |
| 6 | Me | Update `ROADMAP.md`; never weaken a verify predicate to make a row green |
| 7 | Me | Report back: what changed, what did not, what I refused to change and why |

**Standing constraints on step 4**, so "apply improvements weekly" does not
become drift:

- No rule change on a sample below the floor. Evidence or it waits.
- Never weaken a risk limit, a learning guard, or a verify predicate to make
  progress look better. That single rule is what keeps the audit meaningful.
- Bug fixes and doc-drift corrections are always in scope, any week.
- Anything larger than a small in-scope fix goes on the roadmap and gets raised,
  not done unasked.

## How to tell if this is working

Not by the signal count, and not by the roadmap percentage. By these:

1. **Calibration converging** — stated conviction approaching realised win rate.
2. **Expectancy separating by setup** — evidence the taxonomy is real.
3. **Stale claims staying at zero** — the audit staying honest.
4. **The learning log staying short** — entries only when something was genuinely
   learned. A padded log means the discipline slipped.

A system that trades rarely, refuses often, and has an honest record of both is
the target. Activity is not the metric.
