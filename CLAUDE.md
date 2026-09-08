# Working agreements for this repository

## "Audit" means every component, with nothing skipped

When an audit is requested, it covers **every module in the codebase**, not a
selection. Enumerate the files first, work through all of them, and report
coverage explicitly — including any module where nothing was found.

This is written down because it was got wrong. An audit was delivered in
September 2026 covering five of eleven modules, presented as complete, with the
gaps only surfaced when the user asked whether anything had been missed. The two
most valuable findings in the whole exercise then came out of the skipped
modules:

- `CTradeExec` recorded the *planned* entry rather than the *filled* price, so
  break-even settled on a price the position had never traded at — a small loss
  on every trade after adverse slippage.
- The panel's SCORE row implied a probability up to **54 points** away from the
  one the agent was acting on during warm-up.

Skipping did not merely leave gaps. It deferred the findings that mattered most
and made the user chase them one module at a time.

### The checklist

Before reporting an audit complete:

1. `wc -l` every source file; every one gets read.
2. State the finding count per module, **including the zeros**. "No defects in
   X" is a result, not an omission.
3. Sweep for: placeholders and stubs, empty bodies, declared-but-never-produced
   constants, declared-but-never-called functions, array bounds, reads of the
   forming bar (index 0), and int-used-as-boolean.
4. Re-run `tools/verify_sizing.py`.
5. Check display code against its data sources — a panel that shows the wrong
   number corrupts the user's judgement rather than the agent's, which can be
   worse than a logic bug.
6. Say plainly what was **not** verified. Nothing here is ever executed: all
   checks are static reads, structural balance, and Python replicas of the
   logic — and a replica tests the algorithm as understood, not the MQL5 as
   written. The user's compiler and live runs are the only execution evidence.

## Verify, do not assert

Every claim about this codebase is checked against source before it is stated.
Read the function rather than recalling it. When a result is quantitative,
compute it. Several conclusions in this project's history were reversed by doing
this — a 17-of-17 result that was 6 episodes, an AUC of 0.917 that was one
saturated feature, a "far targets fail" finding that was mostly a measurement
artefact.

## Distinguish measurement changes from trading changes

Some work changes what the agent *learns from*; some changes what it *trades*.
Never blur the two when reporting. A change to the observation book alters no
order the broker ever sees.

## The strategy is unvalidated

Say so whenever performance is discussed. No clean dataset has been gathered.
Verified engineering is not a validated edge, and the distinction must never be
softened.
