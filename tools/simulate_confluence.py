#!/usr/bin/env python3
"""Faithful port of CConfluenceEngine::Evaluate() scoring.

Answers two questions a static read cannot:
  1. Is the configured threshold reachable at all, or is the EA mute by design?
  2. Can both sides score highly at once (which would make the margin meaningless)?
"""
import sys, random

W = dict(regime=12, mid=12, fast=10, adx=12, rsi=8, macd=10,
         stoch=8, vwap=8, bands=6, struct=8, vol=6)
ADX_MIN, THRESHOLD, MARGIN = 20.0, 72.0, 30.0
Q_THRESHOLD, Q_MARGIN = 62.0, 20.0

def score(m):
    """m = market state dict. Returns (bull, bear) normalised 0-100."""
    b = dict.fromkeys(W, 0.0); s = dict.fromkeys(W, 0.0)

    # 1 H4 regime
    if m['h4_fast'] > m['h4_slow']:
        b['regime'] = W['regime'] if m['close'] > m['h4_fast'] else W['regime']*0.6
    if m['h4_fast'] < m['h4_slow']:
        s['regime'] = W['regime'] if m['close'] < m['h4_fast'] else W['regime']*0.6
    # 2 H1 trend
    if m['h1_fast'] > m['h1_slow']:
        b['mid'] = W['mid'] if m['h1_rising'] else W['mid']*0.55
    if m['h1_fast'] < m['h1_slow']:
        s['mid'] = W['mid'] if not m['h1_rising'] else W['mid']*0.55
    # 3 trade TF + trigger
    if m['t_fast'] > m['t_slow'] and m['close'] > m['t_slow']:
        if m['close'] > m['open'] and m['close'] > m['prev_hi']: b['fast'] = W['fast']
        elif m['close'] > m['open']:                            b['fast'] = W['fast']*0.8
        else:                                                   b['fast'] = W['fast']*0.6
    if m['t_fast'] < m['t_slow'] and m['close'] < m['t_slow']:
        if m['close'] < m['open'] and m['close'] < m['prev_lo']: s['fast'] = W['fast']
        elif m['close'] < m['open']:                            s['fast'] = W['fast']*0.8
        else:                                                   s['fast'] = W['fast']*0.6
    # 4 ADX / DI
    strength = W['adx']*(0.65 if m['adx'] >= ADX_MIN+8 else 0.5)
    if m['di_plus'] > m['di_minus']: b['adx'] = strength + W['adx']*0.35
    elif m['di_minus'] > m['di_plus']: s['adx'] = strength + W['adx']*0.35
    # 5 RSI
    if 45 <= m['rsi'] <= 78: b['rsi'] = W['rsi'] if m['rsi_rising'] else W['rsi']*0.6
    if 22 <= m['rsi'] <= 55: s['rsi'] = W['rsi'] if not m['rsi_rising'] else W['rsi']*0.6
    # 6 MACD
    if m['hist'] > 0: b['macd'] = W['macd'] if m['hist_rising'] else W['macd']*0.6
    if m['hist'] < 0: s['macd'] = W['macd'] if not m['hist_rising'] else W['macd']*0.6
    # 7 Stochastic
    if m['k_cross_up'] and m['k_prev'] < 45:   b['stoch'] = W['stoch']
    elif m['k'] > m['d']:                      b['stoch'] = W['stoch']*0.5
    if m['k_cross_dn'] and m['k_prev'] > 55:   s['stoch'] = W['stoch']
    elif m['k'] < m['d']:                      s['stoch'] = W['stoch']*0.5
    # 8 VWAP
    if m['vwap'] > 0:
        if m['close'] > m['vwap']: b['vwap'] = W['vwap']
        elif m['close'] < m['vwap']: s['vwap'] = W['vwap']
    # 9 Bollinger
    if m['bb_mid'] < m['close'] < m['bb_up']: b['bands'] = W['bands']
    elif m['close'] >= m['bb_up']:            b['bands'] = W['bands']*0.2
    if m['bb_lo'] < m['close'] < m['bb_mid']: s['bands'] = W['bands']
    elif m['close'] <= m['bb_lo']:            s['bands'] = W['bands']*0.2
    # 10 structure
    if m['close'] > m['pivot']: b['struct'] += W['struct']*0.5
    else:                       s['struct'] += W['struct']*0.5
    if m['close'] > m['pd_mid']: b['struct'] += W['struct']*0.5
    else:                        s['struct'] += W['struct']*0.5
    # 11 volume
    if m['vol_ratio'] >= 1.10:
        if m['close'] > m['open']: b['vol'] = W['vol']
        elif m['close'] < m['open']: s['vol'] = W['vol']
    elif m['vol_ratio'] >= 0.80:
        if m['close'] > m['open']: b['vol'] = W['vol']*0.4
        elif m['close'] < m['open']: s['vol'] = W['vol']*0.4

    tw = sum(W.values())
    return sum(b.values())/tw*100, sum(s.values())/tw*100

def hard_gates(m):
    """The vetoes Evaluate() applies before any scoring happens."""
    if m['adx'] < ADX_MIN:                     return "ADX below floor"
    if m.get('atr',3.0) < 1.20:                return "ATR below floor"
    if m.get('atr',3.0) > 14.0:                return "ATR above ceiling"
    ext = abs(m['close']-m['t_slow'])/m.get('atr',3.0)
    if ext > 2.2:                              return "over-extended"
    return None

def ideal_bull():
    return dict(close=105, open=100, prev_hi=104, prev_lo=95,
                h4_fast=90, h4_slow=80, h1_fast=95, h1_slow=90, h1_rising=True,
                t_fast=102, t_slow=98, adx=30, di_plus=30, di_minus=10,
                rsi=60, rsi_rising=True, hist=1.0, hist_rising=True,
                k=60, d=50, k_prev=40, k_cross_up=True, k_cross_dn=False,
                vwap=100, bb_mid=100, bb_up=110, bb_lo=90,
                pivot=100, pd_mid=99, vol_ratio=1.3)

fails=0
def check(c,m):
    global fails
    print(("  PASS  " if c else "  FAIL  ")+m)
    if not c: fails+=1

print("=== 1. weights and normalisation ===")
check(sum(W.values())==100, f"default weights sum to {sum(W.values())}")
bull,bear = score(ideal_bull())
check(abs(bull-100.0)<0.01, f"a perfect bullish state scores {bull:.1f}/100")
check(bear<0.01, f"and the bearish side scores {bear:.1f}")

print("\n=== 2. the threshold is reachable ===")
check(bull>=THRESHOLD and (bull-bear)>=MARGIN,
      f"ideal bull fires: {bull:.1f} >= {THRESHOLD} with margin {bull-bear:.1f} >= {MARGIN}")

print("\n=== 3. realistic (not perfect) setups still fire ===")
m=ideal_bull(); m.update(k_cross_up=False, k=60, d=50, adx=22, rsi_rising=False,
                         hist_rising=False, vol_ratio=0.9, close=103, prev_hi=104)
bull,bear=score(m)
check(bull>=THRESHOLD and bull-bear>=MARGIN,
      f"partially-confirmed uptrend: bull {bull:.1f} bear {bear:.1f} margin {bull-bear:.1f} -> fires")

print("\n=== 4. genuinely mixed signals produce no trade ===")
# H4 up but H1 down, price above VWAP but below pivot, MACD up but stoch down,
# DI nearly tied. This is what chop actually looks like to the scorer.
m=ideal_bull(); m.update(h1_fast=90, h1_slow=95, h1_rising=False,
                         t_fast=99, t_slow=100, close=100.5, open=100.6,
                         prev_hi=102, adx=21, di_plus=21, di_minus=20,
                         rsi=52, rsi_rising=False, hist=0.05, hist_rising=False,
                         k=48, d=52, k_cross_up=False, vwap=100.2,
                         bb_mid=100.4, bb_up=104, bb_lo=97,
                         pivot=101, pd_mid=101, vol_ratio=0.6, atr=3.0)
bull,bear=score(m)
fired = (bull>=THRESHOLD and bull-bear>=MARGIN) or (bear>=THRESHOLD and bear-bull>=MARGIN)
check(not fired, f"mixed state: bull {bull:.1f} bear {bear:.1f} margin {abs(bull-bear):.1f} -> no trade")

print("\n=== 4b. hard gates veto before scoring ===")
m=ideal_bull(); m['adx']=15
check(hard_gates(m)=="ADX below floor", "ADX 15 vetoed regardless of a 100-score setup")
m=ideal_bull(); m['atr']=0.5
check(hard_gates(m)=="ATR below floor", "dead market vetoed")
m=ideal_bull(); m['atr']=3.0; m['close']=m['t_slow']+10
check(hard_gates(m)=="over-extended", "over-extended price vetoed (no chasing)")

print("\n=== 5. both sides can never be strong at once ===")
random.seed(11); worst_min=0.0
for _ in range(50000):
    m=dict(close=random.uniform(90,110), open=random.uniform(90,110),
           prev_hi=random.uniform(90,110), prev_lo=random.uniform(90,110),
           h4_fast=random.uniform(85,105), h4_slow=random.uniform(85,105),
           h1_fast=random.uniform(85,105), h1_slow=random.uniform(85,105),
           h1_rising=random.random()<.5, t_fast=random.uniform(90,110),
           t_slow=random.uniform(90,110), adx=random.uniform(10,45),
           di_plus=random.uniform(5,40), di_minus=random.uniform(5,40),
           rsi=random.uniform(10,90), rsi_rising=random.random()<.5,
           hist=random.gauss(0,1), hist_rising=random.random()<.5,
           k=random.uniform(0,100), d=random.uniform(0,100), k_prev=random.uniform(0,100),
           k_cross_up=random.random()<.2, k_cross_dn=random.random()<.2,
           vwap=random.uniform(95,105), bb_mid=100.0, bb_up=110.0, bb_lo=90.0,
           pivot=random.uniform(95,105), pd_mid=random.uniform(95,105),
           vol_ratio=random.uniform(0.3,2.0))
    b,s=score(m)
    worst_min=max(worst_min,min(b,s))
check(worst_min<THRESHOLD,
      f"across 50,000 random states the weaker side never reached {THRESHOLD} (max {worst_min:.1f})")

print("\n=== 6. signal frequency vs how aligned the indicators are ===")
random.seed(3)
def rand_state(bias, coherence, rnd):
    """Each component independently agrees with the true bias with
    probability `coherence`. coherence 0.5 = pure noise, 1.0 = textbook."""
    def agree(): return rnd.random() < coherence
    up = bias > 0
    def side(a):  return up if a else (not up)
    s_h4, s_h1, s_tf = side(agree()), side(agree()), side(agree())
    s_di, s_rsi, s_macd = side(agree()), side(agree()), side(agree())
    s_st, s_vw, s_bb = side(agree()), side(agree()), side(agree())
    s_pv, s_vol = side(agree()), side(agree())
    c = 100 + (1.0 if s_tf else -1.0)*rnd.uniform(0.3, 1.8)
    return dict(
        close=c, open=100 + (0.5 if s_vol else -0.5),
        prev_hi=100.9, prev_lo=99.1,
        h4_fast=101 if s_h4 else 99, h4_slow=100,
        h1_fast=101 if s_h1 else 99, h1_slow=100, h1_rising=s_h1,
        t_fast=101 if s_tf else 99, t_slow=100,
        adx=rnd.uniform(20, 36),
        di_plus=30 if s_di else 15, di_minus=15 if s_di else 30,
        rsi=62 if s_rsi else 38, rsi_rising=s_rsi,
        hist=0.5 if s_macd else -0.5, hist_rising=s_macd,
        k=60 if s_st else 40, d=50, k_prev=40 if s_st else 60,
        k_cross_up=s_st and rnd.random()<.5, k_cross_dn=(not s_st) and rnd.random()<.5,
        vwap=99.5 if s_vw else 100.5,
        bb_mid=99.6 if s_bb else 100.4, bb_up=104, bb_lo=96,
        pivot=99.5 if s_pv else 100.5, pd_mid=99.5 if s_pv else 100.5,
        vol_ratio=1.3 if s_vol else 0.6, atr=3.0)

BARS_PER_DAY = 32          # M15 across the London + New York windows
print(f"          {'coherence':>10} {'normal':>8} {'quota':>8}   expected signals/day")
rates={}
for coh in (0.55, 0.65, 0.75, 0.85, 0.95):
    rnd=random.Random(42); n=f=q=0
    for _ in range(20000):
        m=rand_state(rnd.choice([1,-1]), coh, rnd)
        if hard_gates(m): continue
        n+=1
        b,sc=score(m)
        if (b>=THRESHOLD and b-sc>=MARGIN) or (sc>=THRESHOLD and sc-b>=MARGIN): f+=1
        if (b>=Q_THRESHOLD and b-sc>=Q_MARGIN) or (sc>=Q_THRESHOLD and sc-b>=Q_MARGIN): q+=1
    fr, qr = f/max(n,1), q/max(n,1)
    rates[coh]=(fr,qr)
    print(f"          {coh:>10.2f} {fr*100:7.1f}% {qr*100:7.1f}%   {fr*BARS_PER_DAY:5.1f} / {qr*BARS_PER_DAY:.1f}")

check(rates[0.55][0] < rates[0.95][0],
      "fire rate rises with indicator agreement (the score means something)")
check(all(q >= f for f,q in rates.values()),
      "quota gate is never stricter than the normal gate at any coherence")
check(rates[0.85][0]*BARS_PER_DAY >= 1.0,
      f"at 0.85 coherence roughly {rates[0.85][0]*BARS_PER_DAY:.1f} signals/day clear the normal gate")
# The meaningful measure is SEPARATION - how much more often an aligned
# state fires than a noisy one. An absolute noise rate is misleading here
# because this model forces every component to commit fully to one side,
# which real correlated indicators never do.
noise, aligned = rates[0.55][0], rates[0.85][0]
separation = aligned - noise
ratio = aligned / max(noise, 1e-9)
check(separation > 0.40,
      f"separation is {separation*100:.1f} points (noise {noise*100:.1f}%, aligned {aligned*100:.1f}%)")
check(ratio > 2.5,
      f"an aligned state is {ratio:.1f}x more likely to fire than noise")

print("\nCONFLUENCE:", "PASS" if fails==0 else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
