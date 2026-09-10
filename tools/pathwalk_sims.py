#!/usr/bin/env python3
"""
Sequence-aware trade replay (path-walk).

Walks each trade bar-by-bar through forward_test_log.csv and lets a
hypothetical exit rule play out in correct time order. When a single
1-min bar spans both the stop and the target, the STOP is assumed to
hit first (conservative).

Clock skew note: bar feed can lag trades.csv by ~1 min, so the walk
starts from the entry bar and runs to actual exit + 2 min. Entry bar
itself is skipped (its range contains the entry print).

Read-only: prints a table, writes nothing.
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
    t["path"] = [b for b in bars
                 if t["et"] + timedelta(minutes=1) <= b[0] <= t["xt"] + timedelta(minutes=2)]

def walk(t, tp_R, be_trigger=None, partial_R=None):
    """Simulate:
    - SL as logged; TP at tp_R * risk (direction-aware)
    - once price reaches +be_trigger R, SL ratchets to entry (BE-stop)
    - partial_R: if set, take 50% off at partial_R; returned $ blends outcomes
    Returns (outcome, pnl_in_R). outcome in W/L/BE/P(artial-only exit at BE)."""
    d = 1 if t["type"] == "BUY" else -1
    e, risk = t["entry"], t["risk"]
    sl = t["sl"]
    tp = e + d * tp_R * risk
    be_armed = False
    half_banked = None
    active_risk = risk  # full size until partial
    for _, o, h, l, c in t["path"]:
        hi_r = d * (h - e) / risk
        lo_r = d * (l - e) / risk
        # arm BE-trigger (conservative: require bar HIGH over trigger first)
        if be_trigger is not None and not be_armed and hi_r >= be_trigger:
            be_armed = True
            sl = e  # ratchet to breakeven
        # partial profit
        if partial_R is not None and half_banked is None and hi_r >= partial_R:
            half_banked = partial_R
            sl = max(sl, e) if d == 1 else min(sl, e)
            active_risk = risk / 2
        # stop check FIRST (conservative when both hit same bar)
        stop_r = d * (e - sl) / risk
        if lo_r <= -stop_r - 1e-9:
            if be_armed and abs(sl - e) < 1e-9:
                # stopped at breakeven (keep banked half if partial taken)
                return ("BE" if half_banked is None else "P",
                        (half_banked or 0) / 2)
            loss = d * (sl - e) / risk  # negative: full-R loss in R units
            return ("L", (half_banked or 0) / 2 + loss * (0.5 if half_banked else 1.0))
        # TP check
        if hi_r >= tp_R - 1e-9:
            win = tp_R
            return ("W", (half_banked or 0) / 2 + win * (0.5 if half_banked else 1.0))
    # neither hit within window: fall back to actual outcome
    if t["reason"] == "TP":
        return ("W", (half_banked or 0) / 2 + tp_R * (0.5 if half_banked else 1.0) if tp_R <= 1.5 else 1.5 * 0.97)
    return ("L", -1.0)

n = len(T)
print(f"{'strategy':50s} {'W':>3} {'L':>3} {'BE/P':>4} {'win%':>6} {'noBars':>6} {'estP/L$':>9}")

def run(name, **kw):
    W = L = BE = nobars = 0
    pnl = 0.0
    for t in T:
        if not t["path"]:
            nobars += 1
            pnl += t["profit"]
            if t["reason"] == "TP": W += 1
            else: L += 1
            continue
        out, r_mult = walk(t, **kw)
        pnl += r_mult * t["oneR_money"] * 0.985
        if out == "W": W += 1
        elif out in ("BE", "P"): BE += 1
        else: L += 1
    tot = n - nobars
    print(f"{name:50s} {W:3d} {L:3d} {BE:4d} {(W/(W+L+BE) if W+L+BE else 0)*100:5.1f}% {nobars:6d} {pnl:9.2f}")

print("--- pure TP levels ---")
run("TP 0.33R", tp_R=0.33)
run("TP 0.50R", tp_R=0.50)
run("TP 0.75R", tp_R=0.75)
run("TP 1.00R", tp_R=1.00)
run("TP 1.50R (should ~= actual)", tp_R=1.50)
print("--- BE-stop ratchet, TP 1.5R ---")
for trig in (0.2, 0.25, 0.33, 0.5):
    run(f"BE-stop armed at +{trig:.2f}R", tp_R=1.5, be_trigger=trig)
print("--- partial 50% + BE runner ---")
for p in (0.33, 0.5):
    run(f"50% at +{p:.2f}R, BE runner to 1.5R", tp_R=1.5, partial_R=p)
print("--- combined: BE trig 0.25R + TP 1.0R ---")
run("BE +0.25R, TP 1.0R", tp_R=1.0, be_trigger=0.25)
run("BE +0.25R, TP 0.75R", tp_R=0.75, be_trigger=0.25)

w = sum(1 for t in T if t["reason"] == "TP")
print(f"\nActual baseline: {w}W/{n-w}L = {w/n*100:.1f}%, P/L {sum(t['profit'] for t in T):+.2f}")
