#!/usr/bin/env python3
"""Generates staged Strategy Tester optimisation .set files from the EA source.

Parsing the inputs out of the .mq5 rather than hand-writing the files means
names and defaults cannot drift out of sync with the code.

DESIGN: why staged files and not one big sweep
----------------------------------------------
Optimising every interesting parameter at once is combinatorially impossible
and statistically worthless. Sweeping just the 11 confluence weights at 5
values each is 48 million passes, and any "best" result from it is a curve
fit to noise. Instead each stage optimises a small group that shares a
purpose, in order of how much the outcome depends on it, and each stage's
winner is frozen into the next.
"""
import re, os, sys, math

EA   = 'MQL5/Experts/XAUUSD_FTMO/XAUUSD_FTMO_Confluence_EA.mq5'
INC  = 'MQL5/Experts/XAUUSD_FTMO/Include'
OUT  = 'MQL5/Presets'

# ---------------------------------------------------------------- enums
TIMEFRAME = {  # ENUM_TIMEFRAMES has non-contiguous values - see docs
 'PERIOD_M1':1,'PERIOD_M5':5,'PERIOD_M15':15,'PERIOD_M30':30,
 'PERIOD_H1':16385,'PERIOD_H2':16386,'PERIOD_H4':16388,'PERIOD_D1':16408,
}

def parse_custom_enums():
    """Read our own enums so their integer values are never guessed."""
    vals={}
    for fn in os.listdir(INC):
        src=open(os.path.join(INC,fn)).read()
        for m in re.finditer(r'enum\s+(\w+)\s*\{(.*?)\}', src, re.S):
            body=re.sub(r'//[^\n]*','',m.group(2))
            nxt=0
            for item in body.split(','):
                item=item.strip()
                if not item: continue
                if '=' in item:
                    name,v=item.split('=',1)
                    nxt=int(v.strip()); name=name.strip()
                else:
                    name=item.split()[0]
                vals[name]=nxt; nxt+=1
    return vals

ENUMS = parse_custom_enums(); ENUMS.update(TIMEFRAME)

# ---------------------------------------------------------------- inputs
def parse_inputs():
    out=[]
    for line in open(EA):
        m=re.match(r'^input\s+(\S+)\s+(\w+)\s*=\s*([^;]+);', line)
        if not m: continue
        typ,name,default = m.group(1), m.group(2), m.group(3).strip()
        if typ=='group': continue
        out.append((typ,name,default.strip('"')))
    return out

INPUTS = parse_inputs()
TYPES  = {n:t for t,n,_ in INPUTS}
DEFAULTS = {n:d for _,n,d in INPUTS}

def literal(name):
    """Default rendered the way a .set file needs it."""
    t,d = TYPES[name], DEFAULTS[name]
    if t.startswith('ENUM_'):
        if d not in ENUMS: raise SystemExit(f"unknown enum constant {d} for {name}")
        return str(ENUMS[d])
    if t=='bool':   return d
    if t=='string': return d
    return d

# ---------------------------------------------------------------- stages
# (name, {param: (start, step, stop)}, rationale)
STAGES = [
 ("Stage1_Signal", {
    'InpScoreThreshold' : (62, 2, 82),
    'InpDominanceMargin': (18, 2, 40),
    'InpAdxMin'         : (16, 2, 30),
  }, "The signal gate. Everything downstream is shaped by which bars qualify, "
     "so this is optimised first and on the widest data."),

 ("Stage2_Exits", {
    'InpSlAtrMult'   : (0.8, 0.2, 2.0),
    'InpTp2R'        : (1.5, 0.25, 3.5),
    'InpTrailStartR' : (0.8, 0.2, 2.0),
    'InpTrailAtrMult': (0.8, 0.2, 2.4),
  }, "Exit geometry, and the stage that matters most right now. A backtest "
     "showed every winner exiting at breakeven behind its partial and NO runner "
     "reaching a 3R target - a 3R target measured against a 1.6 ATR stop needs "
     "4.8 ATR of favourable excursion, which M15 gold rarely delivers. These "
     "ranges deliberately reach into shorter stops and nearer targets."),

 ("Stage3_Volatility", {
    'InpAtrMinRelative' : (0.3, 0.1, 1.0),
    'InpAtrMaxRelative' : (1.5, 0.25, 4.0),
    'InpMaxExtensionAtr': (1.4, 0.3, 3.2),
  }, "The volatility regime filter, in RELATIVE mode - ATR against its own "
     "long-run average. The old absolute dollar band is what silently switched "
     "the EA off for eight months of a backtest when gold re-rated; a relative "
     "band cannot do that. Widen these only if the veto histogram shows ATR "
     "rejections dominating."),

 ("Stage4_EntryQuality", {
    'InpVolumeFactor' : (0.9, 0.1, 1.5),
    'InpSwingLookback': (8, 2, 20),
    'InpPartialPct'   : (30, 10, 70),
    'InpTp1R'         : (0.8, 0.2, 1.6),
  }, "Entry confirmation and how the position is scaled out."),

 ("Stage5_Cadence", {
    'InpMinMinutesBetween': (15, 15, 120),
    'InpMaxTradesPerDay'  : (1, 1, 5),
  }, "Trade cadence. Run last - it interacts with the FTMO minimum trading "
     "days and the daily-quota behaviour, not with the edge itself."),
]

# Timeframes cannot be swept: ENUM_TIMEFRAMES values are not contiguous
# (M30=30 but H1=16385), so a step would iterate thousands of invalid values.
# They are compared as discrete runs instead. ATR bounds scale with sqrt(time).
# The three phase presets. Only the values that DELIBERATELY differ from the
# compiled defaults are listed; everything else tracks the EA automatically.
#
# These used to be hand-maintained, and they drifted: after the exit geometry
# was retuned the presets still pinned the old stop and target, so loading
# Phase 1 silently restored the configuration that produced a losing backtest.
# Deriving them here makes that impossible.
PHASE_PRESETS = [
 ("Phase1_Challenge", {
    'InpProfitTargetPct':'10.0', 'InpRiskPercent':'0.5', 'InpStopAtTarget':'true',
    'InpSoftDailyLossPct':'2.0', 'InpHardDailyLossPct':'3.0',
    'InpSoftTotalLossPct':'5.0', 'InpHardTotalLossPct':'7.0',
    'InpMaxTradesPerDay':'3', 'InpUseDailyQuota':'true', 'InpScoreThreshold':'72.0',
  }, "FTMO Challenge, phase 1. 10% target, 0.5% risk per trade."),

 ("Phase2_Verification", {
    'InpProfitTargetPct':'5.0', 'InpRiskPercent':'0.4', 'InpStopAtTarget':'true',
    'InpSoftDailyLossPct':'1.8', 'InpHardDailyLossPct':'2.8',
    'InpSoftTotalLossPct':'4.0', 'InpHardTotalLossPct':'6.0',
    'InpMaxTradesPerDay':'3', 'InpUseDailyQuota':'true', 'InpScoreThreshold':'72.0',
  }, "FTMO Verification, phase 2. Lower 5% target, so less risk is needed."),

 ("Funded_Conservative", {
    'InpProfitTargetPct':'100.0', 'InpRiskPercent':'0.3', 'InpStopAtTarget':'false',
    'InpSoftDailyLossPct':'1.5', 'InpHardDailyLossPct':'2.5',
    'InpSoftTotalLossPct':'4.0', 'InpHardTotalLossPct':'6.0',
    'InpMaxTradesPerDay':'2', 'InpUseDailyQuota':'false', 'InpScoreThreshold':'70.0',
  }, "Funded account. No auto-stop, smallest risk, fewer trades, quota off - "
     "on a live payout account there is no deadline to chase."),

 # ---- FTMO SWING variants ---------------------------------------------
 # A Swing account differs in three ways that matter here: leverage is 1:30
 # rather than 1:100, positions may be held over the weekend, and there is
 # no restriction on trading around news. The first is a hard constraint -
 # gold margin per lot roughly triples, so the default free-margin cap
 # starts rejecting ordinary trades unless it is raised.
 ("Phase1_Swing", {
    'InpProfitTargetPct':'10.0', 'InpRiskPercent':'0.5', 'InpStopAtTarget':'true',
    'InpSoftDailyLossPct':'2.0', 'InpHardDailyLossPct':'3.0',
    'InpSoftTotalLossPct':'5.0', 'InpHardTotalLossPct':'7.0',
    'InpMaxTradesPerDay':'3', 'InpUseDailyQuota':'true', 'InpScoreThreshold':'72.0',
    'InpMaxMarginPct':'85.0', 'InpFlatBeforeWeekend':'false', 'InpFridayCutoff':'20:00',
  }, "FTMO SWING Challenge phase 1. Margin cap raised for 1:30, weekend "
     "flattening off, Friday traded in full."),

 ("Phase2_Swing", {
    'InpProfitTargetPct':'5.0', 'InpRiskPercent':'0.4', 'InpStopAtTarget':'true',
    'InpSoftDailyLossPct':'1.8', 'InpHardDailyLossPct':'2.8',
    'InpSoftTotalLossPct':'4.0', 'InpHardTotalLossPct':'6.0',
    'InpMaxTradesPerDay':'3', 'InpUseDailyQuota':'true', 'InpScoreThreshold':'72.0',
    'InpMaxMarginPct':'85.0', 'InpFlatBeforeWeekend':'false', 'InpFridayCutoff':'20:00',
  }, "FTMO SWING Verification phase 2."),

 ("Funded_Swing", {
    'InpProfitTargetPct':'100.0', 'InpRiskPercent':'0.3', 'InpStopAtTarget':'false',
    'InpSoftDailyLossPct':'1.5', 'InpHardDailyLossPct':'2.5',
    'InpSoftTotalLossPct':'4.0', 'InpHardTotalLossPct':'6.0',
    'InpMaxTradesPerDay':'2', 'InpUseDailyQuota':'false', 'InpScoreThreshold':'70.0',
    'InpMaxMarginPct':'80.0', 'InpFlatBeforeWeekend':'false', 'InpFridayCutoff':'20:00',
  }, "FTMO SWING funded account."),
]

# Diagnostic runs that bisect "why has the EA stopped trading".
# Each one opens one more gate than the last. Whichever run restores a normal
# trade count identifies the culprit. A bound of 0 disables a filter in BOTH
# the old and new code, so these work even against a binary that has not been
# recompiled with the newer inputs.
DIAGNOSTIC_RUNS = [
 ("Diagnose_1_NoVolFilter", {
    'InpMinAtrPrice':'0', 'InpMaxAtrPrice':'0',
    'InpAtrMinRelative':'0', 'InpAtrMaxRelative':'0',
  }, "Volatility band fully disabled, everything else as Phase 1. If the trade "
     "count jumps, the ATR gate was switching the EA off - which is what a "
     "2025-2026 backtest suggested when it traded on 8 days out of 253."),

 ("Diagnose_2_NoVolNoNews", {
    'InpMinAtrPrice':'0', 'InpMaxAtrPrice':'0',
    'InpAtrMinRelative':'0', 'InpAtrMaxRelative':'0',
    'InpNewsSource':'0',
  }, "Volatility band AND news filter off. Isolates the calendar as a cause. "
     "Not FTMO compliant - a diagnostic only, never a trading configuration."),

 ("Diagnose_3_AllGatesOpen", {
    'InpMinAtrPrice':'0', 'InpMaxAtrPrice':'0',
    'InpAtrMinRelative':'0', 'InpAtrMaxRelative':'0',
    'InpNewsSource':'0', 'InpAdxMin':'5.0',
    'InpScoreThreshold':'40.0', 'InpDominanceMargin':'5.0',
    'InpMaxExtensionAtr':'0', 'InpMaxSpreadPrice':'5.0',
    'InpMinMinutesBetween':'0', 'InpMaxTradesPerDay':'10',
    'InpUseAsiaSession':'true', 'InpVolumeFactor':'0.1',
  }, "Every gate opened as far as it goes. This is the CEILING on how many "
     "trades the setup can produce - not a strategy. If even this stops "
     "trading, the cause is not a filter: look at history data, the session "
     "clock, or a risk guard."),
]

EXIT_RUNS = [
 ("Exit_A_Scaled",  {'InpUsePartial':'true',  'InpPartialPct':'40', 'InpTp1R':'1.0',
                     'InpTp2R':'2.2', 'InpSlAtrMult':'1.10', 'InpTrailStartR':'1.05',
                     'InpTrailAtrMult':'1.2', 'InpBreakevenLockR':'0.05'},
  "Scaled exit, retuned. 40% off at 1R, runner to 2.2R, trail engages right "
  "after the partial so the runner is not left sitting at breakeven."),

 ("Exit_B_Runner",  {'InpUsePartial':'false', 'InpTp1R':'1.0', 'InpTp2R':'2.5',
                     'InpSlAtrMult':'1.10', 'InpTrailStartR':'1.0',
                     'InpTrailAtrMult':'1.5', 'InpBreakevenLockR':'0.05'},
  "No scale-out at all. The whole position runs behind a trail. Removes the "
  "drag of always banking half the trade at 1R, which is what capped the "
  "average win at 0.5R in the backtest."),

 ("Exit_C_Tight",   {'InpUsePartial':'true',  'InpPartialPct':'50', 'InpTp1R':'0.8',
                     'InpTp2R':'1.8', 'InpSlAtrMult':'0.90', 'InpTrailStartR':'0.85',
                     'InpTrailAtrMult':'1.0', 'InpBreakevenLockR':'0.05'},
  "Tight and fast. Nearer targets and a shorter stop, betting that a higher "
  "hit rate beats a larger but rarely-reached target."),
]

TF_RUNS = [
 ("TF_M5",  'PERIOD_M5',  'PERIOD_M30', 'PERIOD_H4'),
 ("TF_M15", 'PERIOD_M15', 'PERIOD_H1',  'PERIOD_H4'),
 ("TF_M30", 'PERIOD_M30', 'PERIOD_H4',  'PERIOD_D1'),
]

# What makes any run a SWING run. Applied to a parallel copy of every
# optimisation stage and comparison, because tuning against the normal-account
# base and then trading a Swing account fits the parameters to a configuration
# you will not use: weekend holding and the Friday cutoff both change results.
def load_frozen():
    """Winners carried forward from earlier stages. Hand-maintained, because
    it is the one thing a human decides; everything else is generated."""
    path='tools/frozen_params.txt'
    out={}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k,v=line.split('=',1)
        out[k.strip()]=v.strip()
    return out

FROZEN = load_frozen()

SWING_BASE = {
 'InpFlatBeforeWeekend':'false',
 'InpFridayCutoff':'20:00',
 'InpMaxMarginPct':'85.0',
}

# Never optimised, and the file says why.
LOCKED = {
 'InpRiskPercent':'risk is a decision, not a fitted parameter - optimising it only finds the largest number',
 'InpSoftDailyLossPct':'FTMO compliance guard', 'InpHardDailyLossPct':'FTMO compliance guard',
 'InpSoftTotalLossPct':'FTMO compliance guard', 'InpHardTotalLossPct':'FTMO compliance guard',
 'InpFtmoDailyLossPct':'the rule itself', 'InpFtmoMaxLossPct':'the rule itself',
 'InpNewsMinutesBefore':'compliance, not performance', 'InpNewsMinutesAfter':'compliance, not performance',
}
WEIGHTS = [n for _,n,_ in INPUTS if n.startswith('InpW')]

def fmt(v):
    return f"{v:g}"

def write_set(path, header, opt, overrides):
    # every generated file names its own diagnostics output, so a batch of
    # comparison runs leaves one file per run instead of overwriting one
    # --check writes to '<name>.set.tmp', so strip that too or the tag - and
    # therefore the comparison - differs between writing and checking
    tag = os.path.basename(path).replace('.set.tmp','').replace('.set','')
    overrides = dict(overrides)
    overrides.setdefault('InpRunTag', tag)
    lines=[]
    for h in header.split('\n'):
        lines.append('; '+h if h else ';')
    lines.append(';')
    for typ,name,_ in INPUTS:
        if name in opt:
            start,step,stop = opt[name]
            val = overrides.get(name, literal(name))
            # keep the seed value inside the swept range
            try:
                fv=float(val)
                if not (float(start) <= fv <= float(stop)): val=fmt(start)
            except ValueError: pass
            lines.append(f"{name}={val}||{fmt(start)}||{fmt(step)}||{fmt(stop)}||Y")
        else:
            lines.append(f"{name}={overrides.get(name, literal(name))}")
    open(path,'w').write('\n'.join(lines)+'\n')

def passes(opt):
    n=1
    for start,step,stop in opt.values():
        n *= int(round((stop-start)/step))+1
    return n

CHECK = ('--check' in sys.argv)
STALE = []

_real_write = write_set
def write_set(path, header, opt, overrides):
    if CHECK:
        import io as _io
        before = open(path).read() if os.path.exists(path) else None
        _real_write(path+'.tmp', header, opt, overrides)
        after = open(path+'.tmp').read()
        os.remove(path+'.tmp')
        if before != after:
            STALE.append(path)
        return
    _real_write(path, header, opt, overrides)

os.makedirs(OUT, exist_ok=True)
print("Checking generated sets are up to date\n" if CHECK else "Generated optimisation sets\n")

for name, ov, why in PHASE_PRESETS:
    hdr=(f"XAUUSD FTMO Confluence EA - {name}\n\n{why}\n\n"
         "Generated from the EA's compiled defaults plus the deliberate\n"
         "per-phase overrides. Do not hand-edit: regenerate with\n"
         "  python3 tools/make_optimisation_sets.py")
    write_set(f"{OUT}/{name}.set", hdr, {}, ov)
    _sw = ("   SWING: margin cap %s%%, holds weekends" % ov['InpMaxMarginPct']) if 'Swing' in name else ""
    print(f"  {name}.set  target {ov['InpProfitTargetPct']}%  risk {ov['InpRiskPercent']}%{_sw}")
print()
total=0
frozen={}
for i,(name,opt,why) in enumerate(STAGES, 1):
    p=passes(opt); total+=p
    hdr = (f"XAUUSD FTMO Confluence EA - OPTIMISATION {name}\n"
           f"\n{why}\n\n"
           f"Optimising {len(opt)} parameter(s), {p:,} passes.\n"
           "Sweeps only the lines ending ||Y. Everything else is fixed at the\n"
           "value shown, including every risk and compliance setting.\n"
           "\nRun order matters: freeze this stage's winner into the next stage's\n"
           "file before running it.")
    base_over = dict(frozen); base_over.update(FROZEN)
    write_set(f"{OUT}/Optimise_{name}.set", hdr, opt, base_over)

    swing_over = dict(base_over); swing_over.update(SWING_BASE)
    write_set(f"{OUT}/Optimise_{name}_Swing.set",
              hdr + "\n\nSWING variant: 1:30 margin cap, holds over weekends,\n"
                    "Friday traded in full. Use this one on a Swing account.",
              opt, swing_over)

    rng=", ".join(f"{k.replace('Inp','')} {v[0]}->{v[2]}" for k,v in opt.items())
    print(f"  Optimise_{name}[_Swing].set   {p:>6,} passes   {rng}")

print()
for name,tf,mid,hi in TF_RUNS:
    hdr=(f"XAUUSD FTMO Confluence EA - TIMEFRAME COMPARISON {name}\n\n"
         "ENUM_TIMEFRAMES values are not contiguous (M30=30, H1=16385), so a\n"
         "step-based sweep would iterate thousands of invalid values. Timeframes\n"
         "are therefore compared as discrete single runs, not optimised.\n\n"
         "No ATR bounds are set here. In RELATIVE mode the band is ATR against\n"
         "its own average, which is dimensionless - it needs no rescaling when\n"
         "the timeframe changes, and none when the gold price changes either.\n"
         "That is the whole reason relative mode is the default.")
    base=dict(FROZEN)
    base.update({'InpTfTrade':str(ENUMS[tf]), 'InpTfMid':str(ENUMS[mid]),
                 'InpTfHigh':str(ENUMS[hi])})   # the TF run owns the timeframe
    write_set(f"{OUT}/Compare_{name}.set", hdr, {}, base)
    sb=dict(base); sb.update(SWING_BASE)
    write_set(f"{OUT}/Compare_{name}_Swing.set", hdr + "\n\nSWING variant.", {}, sb)
    print(f"  Compare_{name}[_Swing].set  single run   {tf[7:]}/{mid[7:]}/{hi[7:]}"
          f"  (relative ATR band, no rescaling needed)")

for name,ov,why in DIAGNOSTIC_RUNS:
    hdr=(f"XAUUSD FTMO Confluence EA - DIAGNOSTIC {name}\n\n{why}\n\n"
         "Run over the SAME period as your Phase 1 test and compare the trade\n"
         "count and the number of trading days. Do not trade these settings.")
    write_set(f"{OUT}/{name}.set", hdr, {}, ov)
    print(f"  {name}.set")
print()

for name,ov,why in EXIT_RUNS:
    hdr=(f"XAUUSD FTMO Confluence EA - EXIT STRUCTURE {name}\n\n{why}\n\n"
         "Single run, not an optimisation. Run all three Exit_* files over the\n"
         "same period and compare profit factor and the payoff ratio (avg win\n"
         "divided by avg loss). The payoff is the number that was broken:\n"
         "the backtest delivered 0.50 where roughly 1.6 is needed at a 46%\n"
         "win rate.")
    write_set(f"{OUT}/Compare_{name}.set", hdr, {}, ov)
    sb=dict(ov); sb.update(SWING_BASE)
    write_set(f"{OUT}/Compare_{name}_Swing.set", hdr + "\n\nSWING variant.", {}, sb)
    print(f"  Compare_{name}[_Swing].set  single run   {why.split('.')[0]}")
print()

if FROZEN:
    print(f"\nfrozen and carried into every downstream file ({len(FROZEN)} value(s)):")
    for k,v in sorted(FROZEN.items()):
        print(f"   {k} = {v}")
else:
    print("\nnothing frozen yet - edit tools/frozen_params.txt after each step")

print(f"\ntotal optimisation passes across all stages: {total:,}")
print(f"locked from optimisation: {len(LOCKED)} risk/compliance inputs, "
      f"{len(WEIGHTS)} confluence weights")
print("\ndegrees of freedom:")
for name,opt,_ in STAGES:
    need=len(opt)*40
    print(f"  {name:<20} {len(opt)} params -> want >= {need} trades in the sample")

if CHECK:
    if STALE:
        print("\nSTALE - these files no longer match the generator:")
        for f in STALE: print(f"   {f}")
        print("Run: python3 tools/make_optimisation_sets.py")
        sys.exit(1)
    print("\nall generated .set files are up to date")
