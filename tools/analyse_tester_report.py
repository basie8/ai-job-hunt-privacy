#!/usr/bin/env python3
"""Reconstructs closed trades from a Strategy Tester equity-curve export and
reports the numbers that decide whether the exit design can work at all.

Usage: python3 tools/analyse_tester_report.py <testergraph.report.csv>

The tester's graph CSV records a balance step for every closed deal, so a
scaled-out trade shows as two steps. They are grouped back into trades here.
"""
import sys, io, re

def load(path):
    raw=open(path,'rb').read()
    for enc in ('utf-16','utf-16-le','utf-8-sig','utf-8'):
        try:
            txt=raw.decode(enc)
            if '<DATE>' in txt or 'DATE' in txt[:200]: return txt
        except UnicodeError: continue
    return raw.decode('utf-8','replace')

rows=[]
for line in load(sys.argv[1]).split('\n'):
    p=[c.strip() for c in line.split('\t')]
    if len(p)<3 or not re.match(r'^\d{4}\.\d{2}\.\d{2}', p[0]): continue
    rows.append((p[0], float(p[1]), float(p[2])))

# split into separate tester runs (balance resets to the initial deposit)
runs=[]; cur=[]
for r in rows:
    # a run boundary is the balance returning EXACTLY to the initial deposit
    # with equity equal to it - it can jump down as well as up
    if cur and abs(r[1]-rows[0][1])<0.005 and abs(r[2]-r[1])<0.005 and len(cur)>2:
        runs.append(cur); cur=[]
    cur.append(r)
runs.append(cur)

print(f"{len(runs)} tester run(s) in this file\n")
grand=[]
for ri,run in enumerate(runs,1):
    start_bal=run[0][1]
    # Balance steps = closed deals. MT5 books commission as its own tiny step
    # when a position OPENS, which makes those rows a reliable delimiter: every
    # trade begins at a fee row and ends at the last step before the next one.
    #
    # Grouping by "a small step follows a large one" was WRONG. Under the retuned
    # exits the runner banks MORE than the partial (40% at 1R vs 60% at 2.2R), so
    # that rule split single trades into two and inflated both the trade count and
    # the win rate.
    raw=[]
    for i in range(1,len(run)):
        d=run[i][1]-run[i-1][1]
        if abs(d)>0.005: raw.append((run[i][0], d))
    mags=sorted(abs(d) for _,d in raw)
    med=mags[len(mags)//2] if mags else 0
    fee_cut=max(0.05*med, 0.5)

    trades=[]; cur=None; legs=0
    for t,d in raw:
        if abs(d)<fee_cut:                 # commission -> a new position opened
            if cur is not None: trades.append((cur[0], cur[1], 'scaled' if legs>1 else 'single'))
            cur=[t, d]; legs=0
        else:
            if cur is None: cur=[t, 0.0]
            cur[1]+=d; legs+=1
    if cur is not None and legs>0:
        trades.append((cur[0], cur[1], 'scaled' if legs>1 else 'single'))

    wins=[p for _,p,_ in trades if p>0]; losses=[-p for _,p,_ in trades if p<0]
    net=sum(p for _,p,_ in trades)
    aw=sum(wins)/len(wins) if wins else 0
    al=sum(losses)/len(losses) if losses else 0
    pf=sum(wins)/sum(losses) if losses else float('inf')
    wr=len(wins)/len(trades)*100 if trades else 0
    days=sorted({t.split()[0] for t,_,_ in trades})

    print(f"--- RUN {ri}:  {run[0][0]}  ->  {run[-1][0]} ---")
    print(f"  trades {len(trades)}   wins {len(wins)}  losses {len(losses)}   win rate {wr:.1f}%")
    print(f"  net {net:+.2f} on {start_bal:.0f}  ({net/start_bal*100:+.2f}%)   profit factor {pf:.2f}")
    print(f"  avg win {aw:.2f}   avg loss {al:.2f}   payoff {aw/al if al else 0:.2f}")
    print(f"  trading days {len(days)}: {days[0]} .. {days[-1]}")
    # the silence test
    span_days=set()
    for t,_,_ in trades: span_days.add(t.split()[0])
    print(f"  LAST TRADE {max(t for t,_,_ in trades)}   RUN ENDS {run[-1][0]}")
    grand+=trades
    # runner analysis
    runners=[(t,p) for t,p,k in trades if k=='scaled']
    if runners:
        print(f"  scaled-out trades: {len(runners)}")
    print()

wins=[p for _,p,_ in grand if p>0]; losses=[-p for _,p,_ in grand if p<0]
aw=sum(wins)/len(wins); al=sum(losses)/len(losses)
wr=len(wins)/len(grand)
print("=== COMBINED ===")
print(f"  {len(grand)} trades, win rate {wr*100:.1f}%, avg win {aw:.2f}, avg loss {al:.2f}")
print(f"  payoff ratio {aw/al:.2f}   profit factor {sum(wins)/sum(losses):.2f}")
print(f"  expectancy {sum(p for _,p,_ in grand)/len(grand):+.2f} per trade")
print()
payoff=aw/al
be_wr=1/(1+payoff)
print(f"  With a payoff of {payoff:.2f}, break-even needs a {be_wr*100:.1f}% win rate.")
print(f"  Observed win rate is {wr*100:.1f}%.  Shortfall {be_wr*100-wr*100:+.1f} points.")
