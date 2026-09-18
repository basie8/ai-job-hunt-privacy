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

It happened a second time the same evening, through a different door. The
credential test shells out to `gold_trader signal` as a subprocess, with
`cwd` set to the repository and no `--state-dir`. While it stripped only some
credential names, a valid key survived into the child and the test made real
API calls -- six of them, two completing all four stages -- all written to the
production audit log and committed. The dashboard then showed six pipeline
runs and a risk-manager approval that no operator had ever triggered.

The lesson is not "be careful". It is that **the production state directory
must never be the default for anything a test can reach**, because a test that
accidentally becomes a real run is indistinguishable from a real run after the
fact. Both cleanups kept the file, renamed, rather than deleting it.

Use a scratch directory instead:

    python -m gold_trader signal --csv-dir data/ --state-dir /tmp/aurum-test

`--state-dir` redirects the journal, audit log, heartbeat and calendar together.
