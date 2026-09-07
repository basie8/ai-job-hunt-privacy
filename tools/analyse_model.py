#!/usr/bin/env python3
"""
Read a stored SMC agent model and say whether its learning means anything.

    python3 tools/analyse_model.py smc_agent_model_XAUUSD_PERIOD_M15.csv

The model file is not just weights - every resolved setup is kept in the
replay memory as its full 17-feature vector plus the outcome. That is the
training set, and it is enough to answer the only question that matters:
do setups the model rates highly actually win more often than the ones it
rates poorly? A model that cannot separate them is an expensive way of
using the research priors.
"""
import sys, math
from collections import Counter

FACTORS = ["HTF structure","Mid structure","Entry structure","Liquidity raid",
           "Order block","Imbalance","Premium/discount","Displacement","Session",
           "Volatility regime","Execution cost","Reward:risk","Key levels",
           "Confirmation","Participation","News context","Inducement"]

def sigmoid(z): return 1/(1+math.exp(-max(-30.0,min(30.0,z))))

def parse(path):
    head, W, P, S = {}, {}, {}, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            f = line.split(";") if ";" in line else line.split("\t")
            if f[0] == "SMC_AGENT_MODEL" and len(f) >= 5:
                head = {"version":f[1], "n":int(f[2]), "bias":float(f[3]),
                        "updates":int(f[4]),
                        "acc":float(f[5]) if len(f) > 5 else None,
                        "logloss":float(f[6]) if len(f) > 6 else None}
            elif f[0] == "W" and len(f) >= 3:
                i = int(f[1]); W[i] = float(f[2])
                if len(f) >= 4: P[i] = float(f[3])
            elif f[0] == "S" and len(f) >= 4:
                xs = [float(v) for v in f[3].split(",")]
                # 5th column is the SMC_META_* structural bitfield. Files
                # written before it existed simply do not have one.
                meta = int(f[4]) if len(f) >= 5 and f[4].strip() else 0
                S.append((xs, float(f[1]), float(f[2]), meta))
    return head, W, P, S


# --- structural context flags, mirroring Defs.mqh -------------------
META = [(1,  "CHoCH confirmed by BOS"),
        (2,  "CHoCH unconfirmed (no BOS)"),
        (4,  "zone carried an inducement"),
        (8,  "inducement had been run"),
        (16, "triggered by a liquidity raid"),
        (32, "higher timeframe aligned"),
        (64, "post-news"),
        (128,"failed CHoCH (inducement sweep)")]


def wilson(k, n):
    """95% interval for a win rate. Small samples look decisive; this says otherwise."""
    if n == 0: return (0.0, 1.0)
    p, z = k/n, 1.96
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0.0, c-h), min(1.0, c+h))


def structural_split(S):
    """Does a structural flag separate winners from losers? The question the
    logging exists to answer - and the honest answer is usually 'not yet'."""
    print("\n" + "-"*76)
    print("  STRUCTURAL CONTEXT vs OUTCOME")
    print("-"*76)
    tagged = [r for r in S if len(r) > 3 and r[3] != 0]
    if not tagged:
        print("  No structural context recorded yet. These flags are written by")
        print("  builds from 2026-09 onward; older observations carry none.")
        print("  Keep running - the split appears once tagged setups resolve.")
        return
    print(f"  {len(tagged)} of {len(S)} stored setups carry structural context.\n")
    print(f"    {'flag':<32}{'n':>5}{'won':>6}{'rate':>8}{'95% interval':>18}")
    for bit, name in META:
        grp = [r for r in tagged if r[3] & bit]
        if not grp: continue
        k = sum(1 for r in grp if r[1] > 0.5)
        lo, hi = wilson(k, len(grp))
        print(f"    {name:<32}{len(grp):>5}{k:>6}{k/len(grp)*100:>7.0f}%"
              f"{lo*100:>10.0f}%-{hi*100:.0f}%")

    # the specific claim: a failed CHoCH is inducement, so it should
    # resolve BETTER than the ordinary confirmed-reversal case
    fail = [r for r in tagged if r[3] & 128]
    norm = [r for r in tagged if not (r[3] & 128)]
    if len(fail) >= 10 and len(norm) >= 10:
        kf, kn = sum(1 for r in fail if r[1] > 0.5), sum(1 for r in norm if r[1] > 0.5)
        rf, rn = kf/len(fail), kn/len(norm)
        lo_f, hi_f = wilson(kf, len(fail))
        lo_n, hi_n = wilson(kn, len(norm))
        print(f"\n  Failed CHoCH {rf*100:.0f}% (n={len(fail)}) vs everything else"
              f" {rn*100:.0f}% (n={len(norm)}), {rf*100-rn*100:+.0f} points")
        if hi_f < lo_n or hi_n < lo_f:
            print("  Intervals separate - the inducement reading is supported.")
        else:
            print("  Intervals overlap - not evidence yet. Keep collecting.")

    conf = [r for r in tagged if r[3] & 1]
    unc  = [r for r in tagged if r[3] & 2]
    if len(conf) >= 10 and len(unc) >= 10:
        kc, ku = sum(1 for r in conf if r[1] > 0.5), sum(1 for r in unc if r[1] > 0.5)
        rc, ru = kc/len(conf), ku/len(unc)
        lo_c, hi_c = wilson(kc, len(conf))
        lo_u, hi_u = wilson(ku, len(unc))
        print(f"\n  Confirmed {rc*100:.0f}% vs unconfirmed {ru*100:.0f}%"
              f" ({rc*100-ru*100:+.0f} points)")
        if hi_c < lo_u or hi_u < lo_c:
            print("  The intervals do NOT overlap - this separation is real. Worth")
            print("  promoting to a model feature, accepting that it resets the model.")
        else:
            print("  The intervals overlap, so this is not yet evidence of anything.")
            print("  Do not act on it. Collect more before drawing a conclusion.")
    else:
        print("\n  Fewer than 10 in one arm - no comparison attempted. Both arms need")
        print("  at least 10 resolved setups before the split says anything at all.")

def corr(a, b):
    n = len(a)
    if n < 3: return 0.0
    ma, mb = sum(a)/n, sum(b)/n
    va = sum((x-ma)**2 for x in a); vb = sum((y-mb)**2 for y in b)
    if va <= 0 or vb <= 0: return 0.0
    return sum((a[i]-ma)*(b[i]-mb) for i in range(n))/math.sqrt(va*vb)

def auc(scores, labels):
    """Probability a random winner is scored above a random loser. 0.50 = coin flip."""
    pos = [s for s,l in zip(scores,labels) if l > 0.5]
    neg = [s for s,l in zip(scores,labels) if l <= 0.5]
    if not pos or not neg: return None
    wins = ties = 0
    for p in pos:
        for q in neg:
            if p > q: wins += 1
            elif p == q: ties += 1
    return (wins + 0.5*ties)/(len(pos)*len(neg))

def bar(v, lo, hi, width=22):
    if hi <= lo: return " "*width
    zero = int(round((0-lo)/(hi-lo)*(width-1)))
    pos  = int(round((v-lo)/(hi-lo)*(width-1)))
    cells = [" "]*width
    if 0 <= zero < width: cells[zero] = "|"
    a, b = sorted((zero, pos))
    for i in range(a, b+1):
        if 0 <= i < width and cells[i] == " ": cells[i] = "="
    if 0 <= pos < width: cells[pos] = "#"
    return "".join(cells)

def main(path):
    head, W, P, S = parse(path)
    if not head:
        print("Not a model file, or the header row is missing."); return 1

    print("="*76)
    print(f"  {path}")
    print("="*76)
    print(f"  features {head['n']}   updates {head['updates']}   bias {head['bias']:+.3f}")
    if head["acc"] is not None:
        print(f"  self-reported accuracy {head['acc']*100:.1f}%   log loss {head['logloss']:.3f}")
    print(f"  replay memory holds {len(S)} resolved setups")

    if abs(head["bias"]) > 0.85:
        print("\n  !! bias is near its clamp - the model is giving up rather than")
        print("     discriminating. Suspect a skewed label stream.")

    # ---- weights against the priors they started from ----------------
    print("\n" + "-"*76)
    print("  WEIGHTS versus the research priors they started from")
    print("-"*76)
    drift = []
    for i in range(head["n"]):
        w, p = W.get(i, 0.0), P.get(i, 0.0)
        drift.append((abs(w-p), i, w, p))
    lo = min(min(W.values(), default=0), min(P.values(), default=0), -0.5)
    hi = max(max(W.values(), default=0), max(P.values(), default=0), 0.5)
    print(f"  {'factor':<20}{'prior':>7}{'now':>8}{'drift':>8}   {'-':^10}0{'+':^10}")
    for d, i, w, p in sorted(drift, reverse=True):
        name = FACTORS[i] if i < len(FACTORS) else f"factor {i}"
        print(f"  {name:<20}{p:>7.2f}{w:>8.2f}{w-p:>+8.2f}   {bar(w, lo, hi)}")
    moved = sum(1 for d,_,_,_ in drift if d > 0.05)
    print(f"\n  {moved} of {head['n']} weights have moved more than 0.05 from their prior.")
    if head["updates"] < 50:
        print("  With fewer than 50 outcomes that number means very little either way.")

    # ---- what the stored outcomes actually say ------------------------
    if len(S) < 20:
        print("\n" + "-"*76)
        print(f"  Only {len(S)} resolved setups stored - too few to test anything.")
        print("  Come back at 50, and treat 100+ as the point where it starts to mean")
        print("  something. Nothing below is worth computing yet.")
        tagged = sum(1 for r in S if len(r) > 3 and r[3] != 0)
        # not inference, just proof the plumbing works
        print(f"  ({tagged} of them carry structural context)")
        print("-"*76)
        return 0

    xs = [s[0] for s in S]; ys = [s[1] for s in S]
    base = sum(ys)/len(ys)
    print("\n" + "-"*76)
    print("  WHAT THE STORED OUTCOMES SAY")
    print("-"*76)
    print(f"  {len(S)} setups, {int(sum(ys))} reached target, {len(ys)-int(sum(ys))} stopped out")
    print(f"  base win rate {base*100:.1f}%")
    if base < 0.15 or base > 0.85:
        print("  !! a stream this one-sided cannot train a useful model. Something")
        print("     upstream is mislabelling outcomes.")

    print("\n  Per-factor correlation with the outcome (-1..+1):")
    cs = []
    for i in range(head["n"]):
        col = [x[i] if i < len(x) else 0.0 for x in xs]
        cs.append((abs(corr(col, ys)), corr(col, ys), i))
    for a, c, i in sorted(cs, reverse=True):
        name = FACTORS[i] if i < len(FACTORS) else f"factor {i}"
        flag = "  <- carries signal" if a > 0.20 else ("  (noise)" if a < 0.05 else "")
        print(f"    {name:<20}{c:>+7.3f}{flag}")

    scores = [sum(W.get(i,0.0)*(x[i] if i < len(x) else 0.0)
                  for i in range(head["n"])) + head["bias"] for x in xs]
    a = auc(scores, ys)
    print("\n  Model ranking power (AUC): ", end="")
    if a is None:
        print("cannot compute - outcomes are all one class")
    else:
        print(f"{a:.3f}")
        verdict = ("no better than a coin flip - the model adds nothing" if a < 0.55 else
                   "weak but real separation" if a < 0.62 else
                   "genuine separation" if a < 0.72 else
                   "strong separation - verify it is not overfitting")
        print(f"    0.50 is chance. This model: {verdict}.")

    print("\n  Calibration - does a stated probability mean what it says?")
    buckets = {}
    for sc, y in zip(scores, ys):
        b = min(int(sigmoid(sc)*10), 9)
        buckets.setdefault(b, []).append(y)
    print(f"    {'model says':<14}{'n':>5}{'actually won':>15}")
    for b in sorted(buckets):
        v = buckets[b]
        if len(v) < 3: continue
        print(f"    {b*10:>3}-{b*10+10:<9}{len(v):>5}{sum(v)/len(v)*100:>14.0f}%")
    structural_split(S)
    print("\n  Well calibrated means those two columns track each other. A model that")
    print("  says 70% and wins 40% of the time is confidently wrong, and the")
    print("  expectancy gate will size positions on that error.")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[1]))
