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

BE-era note (ratchet live 2026-09-10 ~12:34 UTC): BE rows log the RATCHETED
stop (Stop_Loss == Entry_Price), so the original 2xATR risk geometry is
reconstructed from ATR_At_Entry and 1R of money is estimated as 2xATR.
Trades with no bar path fall back to their ACTUAL outcome (incl. BE).
Rows whose logged SL equals entry are ratchet-armed winners too (BE armed, then
TP printed) - reconstruction is keyed on the geometry, not the exit reason.

For any "what if the exit were LOOSER" question (e.g. no BE ratchet) pass
horizon_min to run(): a BE scratch died ~2 min after entry, so the default
exit-bounded window cannot show where it would have gone. Extended-horizon rows
are cascade-ignorant - a trade held for hours would have displaced later
entries - so read their DIRECTION as evidence and their MAGNITUDE as an upper
bound.

Read-only: prints a table, writes nothing.
"""
import csv
from datetime import datetime, timedelta

def load():
    T = []
    with open("trades.csv", newline="") as f:
        for r in csv.DictReader(f):
            side = r["Trade_Type"]
            entry = float(r["Entry_Price"])
            reason = r["Exit_Reason"]
            atr = float(r["ATR_At_Entry"])
            sl, tp = float(r["Stop_Loss"]), float(r["Take_Profit"])
            # Ratchet-armed rows log SL == entry: BE scratches AND winners the
            # ratchet armed before TP printed. Detect geometrically so 1R math
            # never divides by zero.
            if reason == "BE" or abs(entry - sl) < 1e-9:
                if side == "BUY":
                    sl, tp = entry - 2 * atr, entry + 3 * atr
                else:
                    sl, tp = entry + 2 * atr, entry - 3 * atr
            T.append(dict(
                type=side,
                et=datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                xt=datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S"),
                entry=entry, sl=sl, tp=tp,
                profit=float(r["Profit"]), reason=reason, atr=atr))
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
    if t["reason"] == "SL":
        t["oneR_money"] = abs(t["profit"])
    elif t["reason"] == "TP":
        t["oneR_money"] = abs(t["profit"]) / 1.5
    else:  # BE scratch: no realized R; original risk was 2xATR ($1/unit)
        t["oneR_money"] = 2 * t["atr"]
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
        # Direction-aware bar extremes. `hi_r` must be the bar's MOST FAVORABLE
        # excursion and `lo_r` its MOST ADVERSE one. For a BUY those are the
        # high and the low; for a SELL they are the LOW (price down = profit)
        # and the HIGH. Using d*(h-e) / d*(l-e) unconditionally mirrors them
        # onto the wrong side of the bar for every short - which silently
        # under-detected SELL TPs and BE arms and made shorts fall back to
        # their logged outcome (i.e. the sim appeared to validate itself).
        hi_r = max(d * (h - e), d * (l - e)) / risk
        lo_r = min(d * (h - e), d * (l - e)) / risk
        # arm BE-trigger (conservative: require the bar to CLEAR the trigger on
        # its favourable side first; for a SELL that extreme is the LOW)
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
                        (half_banked or 0) / 2, False)
            loss = d * (sl - e) / risk  # negative: full-R loss in R units
            return ("L", (half_banked or 0) / 2 + loss * (0.5 if half_banked else 1.0), False)
        # TP check
        if hi_r >= tp_R - 1e-9:
            win = tp_R
            return ("W", (half_banked or 0) / 2 + win * (0.5 if half_banked else 1.0), False)
    # neither hit within window: fall back to actual outcome
    if t["reason"] == "TP":
        return ("W", (half_banked or 0) / 2 + tp_R * (0.5 if half_banked else 1.0) if tp_R <= 1.5 else 1.5 * 0.97, True)
    if t["reason"] in ("BE", "TIME"):
        # TIME = the entry survived ~240 min without a touch: neutral like BE
        # (its P&L stays in trades.csv; inventing a full -1R loss would lie).
        return ("BE", 0.0, True)
    return ("L", -1.0, True)

n = len(T)
print(f"{'strategy':50s} {'W':>3} {'L':>3} {'BE/P':>4} {'win%':>6} {'noBars':>6} {'timeout':>7} {'estP/L$':>9}")

def run(name, horizon_min=None, **kw):
    """horizon_min: re-cut every walk to a FIXED window measured from entry
    instead of stopping at the actual exit. Needed whenever the hypothetical
    rule is looser than what actually ran - a BE scratch exited ~2 min after
    entry, so with the default (exit-bounded) window a "no BE" sim can never
    reach the original stop/target and silently returns the actual outcome.
    Trades whose horizon ends with neither level touched fall back to their
    actual result and are counted in the 'timeout' column."""
    W = L = BE = nobars = timeout = 0
    pnl = 0.0
    for t in T:
        if horizon_min is None:
            cand = t
        else:
            end = t["et"] + timedelta(minutes=horizon_min)
            cand = dict(t, path=[b for b in bars
                                 if t["et"] + timedelta(minutes=1) <= b[0] <= end])
        if not cand["path"]:
            nobars += 1
            pnl += t["profit"]
            if t["reason"] == "TP": W += 1
            elif t["reason"] == "SL": L += 1
            else: BE += 1  # BE and TIME are both neutral
            continue
        out, r_mult, fell_back = walk(cand, **kw)
        timeout += bool(fell_back)
        pnl += r_mult * t["oneR_money"] * 0.985
        if out == "W": W += 1
        elif out in ("BE", "P"): BE += 1
        else: L += 1
    tot = W + L + BE
    print(f"{name:50s} {W:3d} {L:3d} {BE:4d} {(W / tot if tot else 0) * 100:5.1f}% "
          f"{nobars:6d} {timeout:7d} {pnl:9.2f}")

print("--- pure TP levels ---")
run("TP 0.33R", tp_R=0.33)
run("TP 0.50R", tp_R=0.50)
run("TP 0.75R", tp_R=0.75)
run("TP 1.00R", tp_R=1.00)
run("TP 1.50R (should ~= actual)", tp_R=1.50)
print("--- BE-stop ratchet, TP 1.5R ---")
for trig in (0.2, 0.25, 0.30, 0.33, 0.5):
    tag = " <-- ADOPTED 2026-09-10" if abs(trig - 0.30) < 1e-9 else ""
    run(f"BE-stop armed at +{trig:.2f}R{tag}", tp_R=1.5, be_trigger=trig)
print("--- extended horizon (240 min from entry): does the ratchet cost runs it saves? ---")
print("    (rows may re-use the ACTUAL result when the horizon ends flat -> see 'timeout')")
run("TP 1.5R, NO BE ratchet at all", tp_R=1.5, horizon_min=240)
for trig in (0.30, 0.50, 0.75, 1.00, 1.25):
    tag = " <-- ADOPTED" if abs(trig - 0.30) < 1e-9 else ""
    run(f"TP 1.5R, BE at +{trig:.2f}R{tag}", tp_R=1.5, be_trigger=trig, horizon_min=240)
print("--- extended horizon, TP variants with NO ratchet ---")
for tp in (0.75, 1.00, 1.25, 1.50, 2.00):
    run(f"TP {tp:.2f}R, no BE", tp_R=tp, horizon_min=240)
print("--- partial 50% + BE runner ---")
for p in (0.33, 0.5):
    run(f"50% at +{p:.2f}R, BE runner to 1.5R", tp_R=1.5, partial_R=p)
print("--- combined: BE trig 0.25R + TP 1.0R ---")
run("BE +0.25R, TP 1.0R", tp_R=1.0, be_trigger=0.25)
run("BE +0.25R, TP 0.75R", tp_R=0.75, be_trigger=0.25)

w = sum(1 for t in T if t["reason"] == "TP")
l = sum(1 for t in T if t["reason"] == "SL")
b = sum(1 for t in T if t["reason"] == "BE")
tm = sum(1 for t in T if t["reason"] == "TIME")
dec = w + l
print(f"\nActual baseline: {w}W/{l}L/{b}BE" + (f"/{tm}TIME" if tm else "") +
      f" = {w / dec * 100 if dec else 0:.1f}% decisive, "
      f"P/L {sum(t['profit'] for t in T):+.2f}")
