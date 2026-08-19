#!/usr/bin/env python3
"""Ranks a batch of XFC_diag_*.csv files on the metrics that actually decide.

    python3 tools/compare_runs.py <folder-with-the-diag-files>

Equity curves cannot show payoff ratio, and they mislead badly when a run
terminates early - a config that hits the profit target after ten weeks looks
better than one that traded twelve months, purely because it stopped.
"""
import csv, glob, os, sys

folder = sys.argv[1] if len(sys.argv) > 1 else '.'
rows = []
for f in sorted(glob.glob(os.path.join(folder, 'XFC_diag*.csv'))):
    d = {}
    for r in csv.reader(open(f)):
        if len(r) >= 3 and r[0] in ('run', 'metrics'):
            d[r[1]] = r[2]
    if d:
        d['_file'] = os.path.basename(f)
        rows.append(d)

if not rows:
    print(f"no XFC_diag*.csv found in {folder}")
    sys.exit(1)

def num(d, k, default=0.0):
    try:    return float(d.get(k, default))
    except ValueError: return default

print(f"{'run':<34}{'trades':>7}{'win%':>7}{'payoff':>8}{'PF':>7}{'net%':>8}{'maxDD%':>8}  ending")
print("-" * 110)
for d in sorted(rows, key=lambda x: -num(x, 'payoff_ratio')):
    ending = d.get('ended', '?')
    short = 'EARLY STOP' if 'STOPPED' in ending else 'full run'
    print(f"{d.get('run_tag', d['_file'])[:33]:<34}"
          f"{int(num(d,'trades_closed')):>7}"
          f"{num(d,'win_rate_pct'):>7.1f}"
          f"{num(d,'payoff_ratio'):>8.2f}"
          f"{num(d,'profit_factor'):>7.2f}"
          f"{num(d,'final_profit_pct'):>8.2f}"
          f"{num(d,'max_total_dd_pct'):>8.2f}  {short}")

print()
print("Rank on PAYOFF and PROFIT FACTOR. Ignore net% when 'ending' is an early")
print("stop - that run covered less time than the others and is not comparable.")
print()
full = [d for d in rows if 'STOPPED' not in d.get('ended', '')]
if full:
    best = max(full, key=lambda d: num(d, 'profit_factor'))
    wr = num(best, 'win_rate_pct') / 100.0
    need = 1.35 * (1 - wr) / wr if wr > 0 else 0
    print(f"best full run: {best.get('run_tag','?')}  "
          f"PF {num(best,'profit_factor'):.2f}, payoff {num(best,'payoff_ratio'):.2f}")
    print(f"  at a {wr*100:.1f}% win rate it needs a payoff of {need:.2f} for PF 1.35")
