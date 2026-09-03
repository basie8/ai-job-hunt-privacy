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
                S.append((xs, float(f[1]), float(f[2])))
    return head, W, P, S

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
    print("\n  Well calibrated means those two columns track each other. A model that")
    print("  says 70% and wins 40% of the time is confidently wrong, and the")
    print("  expectancy gate will size positions on that error.")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    sys.exit(main(sys.argv[1]))
