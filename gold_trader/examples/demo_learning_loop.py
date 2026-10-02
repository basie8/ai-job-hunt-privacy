"""Show the feedback loop closing, with no API calls and no market data.

Feeds a journal a stream of outcomes in which one setup works and another does
not, then prints what the pipeline would tell the analyst and what the risk
engine would enforce, at three points along the way.

    python gold_trader/examples/demo_learning_loop.py
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from datetime import datetime, timedelta, timezone

from gold_trader.journal import Journal
from gold_trader.learning import learn

random.seed(11)
START = datetime(2026, 6, 1, tzinfo=timezone.utc)

# bos_continuation wins 58% at +2R / -1R; range_fade wins 25% at +2R / -1R.
PROFILE = {"bos_continuation": 0.58, "range_fade": 0.25}
CHECKPOINTS = (10, 30, 90)


def main() -> None:
    journal = Journal()
    for i in range(max(CHECKPOINTS)):
        setup = "bos_continuation" if i % 2 == 0 else "range_fade"
        won = random.random() < PROFILE[setup]
        ts = START + timedelta(hours=8 * i)
        record = journal.new_signal(
            direction="long",
            setup_type=setup,
            # The model is consistently overconfident, by construction.
            conviction=0.85,
            entry=2400.0,
            stop=2390.0,
            target=2420.0,
            ts=ts.isoformat(timespec="seconds"),
        )
        journal.update_outcome(
            record,
            status="won" if won else "lost",
            r_multiple=2.0 if won else -1.0,
            exit_ts=(ts + timedelta(hours=4)).isoformat(timespec="seconds"),
        )

        if (i + 1) in CHECKPOINTS:
            state = learn(journal, min_samples=20)
            print("=" * 78)
            print(f"After {i + 1} closed trades  (status: {state.status()})")
            print("=" * 78)
            print(state.lessons_block())
            print("\nClamps the risk engine would apply:")
            print(f"  conviction multiplier      {state.conviction_multiplier():.2f}")
            for name in sorted(state.setups):
                print(f"  size multiplier [{name:<15}] {state.size_multiplier(name):.2f}")
            print(f"  blocked setups             {state.blocked_setups() or 'none'}\n")


if __name__ == "__main__":
    main()
