# Durable state

Everything here must be committable. It is the only thing that survives a
container, and `gold_trader selfcheck` fails if a `.gitignore` rule ever makes
one of these paths unreachable again.

| File | Written by | Holds |
|---|---|---|
| `journal.jsonl` | `signal`, `resolve` | Every paper signal and what happened to it |
| `audit.jsonl` | `signal` | Hash-chained record of each pipeline run, stage by stage |
| `heartbeat.jsonl` | `heartbeat` | Proof each scheduled run happened, whatever it concluded |
| `calendar.json` | you | FOMC / CPI / PCE dates the analyst cannot look up |

## Do not run the pipeline against this directory while testing

`python -m gold_trader signal` writes a real run into `audit.jsonl` and a real
signal into `journal.jsonl`. There is no dry-run mode, deliberately — a run that
did not record itself would be the failure this system is built to refuse.

So testing the CLI from a checkout contaminates the production record. That
happened on 2026-09-17: two credential-error tests wrote four audit entries
each, were committed, and showed on the dashboard as two real pipeline runs.
The original file is kept as `audit.contaminated-by-local-tests.jsonl` rather
than deleted, because erasing a record is worse than labelling it.

Use a scratch directory instead:

    python -m gold_trader signal --csv-dir data/ --state-dir /tmp/aurum-test

`--state-dir` redirects the journal, audit log, heartbeat and calendar together.
