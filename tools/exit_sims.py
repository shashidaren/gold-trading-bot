#!/usr/bin/env python3
"""
Counterfactual exit-strategy simulator.

Replays every trade from trades.csv against the 1-min bars in
forward_test_log.csv (±2 min clock-skew tolerant window) and asks:
"what would P/L have been under a different exit rule?"

Read-only. Prints a comparison table.

Caveats:
- Bar timestamps can skew ~1 min vs trades.csv (different feeds), so
  TP/SL ordering inside a trade is approximate; sims credit the exit
  level when the move is unambiguous.
- Winners are capped at 97% of nominal R to reflect spread/slippage.
"""
import csv
from datetime import datetime, timedelta

def load():
    T = []
    with open("trades.csv", newline="") as f:
        for r in csv.DictReader(f):
            T.append(dict(
                type=r["Trade_Type"],
                et=datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                xt=datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S"),
                entry=float(r["Entry_Price"]), sl=float(r["Stop_Loss"]),
                tp=float(r["Take_Profit"]),
                profit=float(r["Profit"]), reason=r["Exit_Reason"]))
    bars = []
    with open("forward_test_log.csv", newline="") as f:
        for r in csv.DictReader(f):
            try:
                bars.append((datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S"),
                             float(r["Open"]), float(r["High"]),
                             float(r["Low"]), float(r["Close"])))
            except (ValueError, KeyError):
                continue
    bars.sort()
    return T, bars

T, bars = load()

for t in T:
    t["risk"] = abs(t["entry"] - t["sl"])
    t["oneR_money"] = abs(t["profit"]) if t["reason"] == "SL" else abs(t["profit"]) / 1.5
    lo, hi = t["et"] - timedelta(minutes=2), t["xt"] + timedelta(minutes=2)
    path = [b for b in bars if lo <= b[0] <= hi]
    if path:
        hs = max(b[2] for b in path); ls = min(b[3] for b in path)
        mfe = (hs - t["entry"]) if t["type"] == "BUY" else (t["entry"] - ls)
        t["mfeR"] = mfe / t["risk"]
    else:
        t["mfeR"] = 1.5 if t["reason"] == "TP" else 0.0

n = len(T)
print(f"{'strategy':52s} {'W':>3} {'L':>3} {'BE':>3} {'win%':>6} {'est P/L($)':>10}")

def report(name, results):
    w = sum(1 for x in results if x[0] == 'W')
    l = sum(1 for x in results if x[0] == 'L')
    be = sum(1 for x in results if x[0] == 'BE')
    pnl = sum(x[1] for x in results)
    print(f"{name:52s} {w:3d} {l:3d} {be:3d} {w / n * 100:5.1f}% {pnl:10.2f}")

print("--- A: closer take-profit ---")
for tpR in (0.33, 0.5, 0.75, 1.0, 1.5):
    res = [("W", tpR * t["oneR_money"] * 0.97) if t["mfeR"] >= tpR - 1e-9
           else ("L", -t["oneR_money"]) for t in T]
    report(f"TP at {tpR:.2f}R (all trades)", res)

print("--- B: breakeven-stop, keep TP 1.5R ---")
for trig in (0.25, 0.33, 0.5, 0.75):
    res = []
    for t in T:
        if t["mfeR"] >= 1.5:
            res.append(("W", 1.5 * t["oneR_money"] * 0.97))
        elif t["reason"] == "SL" and t["mfeR"] >= trig:
            res.append(("BE", 0.0))
        else:
            res.append(("L", -t["oneR_money"]))
    report(f"BE-stop at +{trig:.2f}R, TP 1.5R", res)

print("--- C: partial take-profit + runner ---")
for p in (0.33, 0.5, 0.75):
    res = []
    for t in T:
        if t["mfeR"] >= 1.5:
            res.append(("W", (0.5 * p + 0.5 * 1.5) * t["oneR_money"] * 0.97))
        elif t["mfeR"] >= p:
            res.append(("BE", 0.5 * p * t["oneR_money"] * 0.97))
        else:
            res.append(("L", -t["oneR_money"]))
    report(f"50% off at +{p:.2f}R + BE runner to 1.5R", res)

print("--- D: time-stop dead trades early ---")
for q, salvage in ((0.1, 0.75), (0.2, 0.70), (0.33, 0.65)):
    res = []
    for t in T:
        if t["mfeR"] >= 1.5:
            res.append(("W", 1.5 * t["oneR_money"] * 0.97))
        elif t["mfeR"] < q:
            res.append(("L", -salvage * t["oneR_money"]))
        else:
            res.append(("L", -t["oneR_money"]))
    report(f"Time-stop if MFE <{q:.2f}R (cut at -{salvage:.2f}R)", res)

print("--- E: combos ---")
res = []
for t in T:
    if t["mfeR"] >= 1.5:
        res.append(("W", 1.5 * t["oneR_money"] * 0.97))
    elif t["mfeR"] >= 0.33:
        res.append(("BE", 0.0))
    else:
        res.append(("L", -0.8 * t["oneR_money"]))
report("COMBO: BE-stop +0.33R & early-cut -0.8R", res)
res = []
for t in T:
    if t["mfeR"] >= 1.5:
        res.append(("W", (0.5 * 0.5 + 0.5 * 1.5) * t["oneR_money"] * 0.97))
    elif t["mfeR"] >= 0.5:
        res.append(("BE", 0.25 * t["oneR_money"] * 0.97))
    else:
        res.append(("L", -0.8 * t["oneR_money"]))
report("COMBO: 50% at +0.5R, BE runner, early-cut -0.8R", res)

w = sum(1 for t in T if t["reason"] == "TP")
print(f"\nActual baseline: {w}W/{n - w}L = {w / n * 100:.1f}% win, "
      f"P/L {sum(t['profit'] for t in T):+.2f}")
