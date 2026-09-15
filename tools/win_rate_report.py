#!/usr/bin/env python3
"""
Win-rate decomposition — the "why is the win rate what it is?" report.

Read-only. Run after every data drop, next to the other analysis tools:

    python3 tools/win_rate_report.py            # from the repo root

Sections
  1. Baseline: W/L/BE, decisive win rate with a Wilson 95% CI, expectancy in $
     and in R, plus the breakeven WR implied by the live TP/SL geometry.
  2. Era split around a deploy point (default: BE ratchet, 2026-09-10 12:34
     UTC) so regime changes never get averaged into "the" win rate.
  3. Side, day and hour breakdowns (BUY and SELL are different strategies).
  4. Exit-geometry reality check: how long each outcome actually takes.
  5. BE-ratchet counterfactual: the 1-min path of every scratch re-walked with
     the ORIGINAL 2x/3xATR stop, 4h cap, SL-first tie-break. Answers "what is
     the ratchet worth?" on live data instead of a pre-BE replay.
  6. Queued entry-filter candidates scored on the CURRENT era and on all data,
     with the handoff's adoption criteria printed next to each.

Data gotchas this tool already handles (see docs/HANDOFF.md §8):
  - BE-era rows log the RATCHETED stop (Stop_Loss == Entry_Price) - that
    includes winners the ratchet armed before TP printed, so the geometry is
    reconstructed from ATR_At_Entry whenever risk would otherwise be 0.
  - trades.csv has historical Trade_Num resets - stats here are row-based.
  - bar-feed timestamps lag trades.csv by ~1 min - walks skip the entry bar and
    allow +2 min at the far end.
"""
import csv
import math
import statistics
import sys
import bisect
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
TRADES = f"{ROOT}/trades.csv"
LOG = f"{ROOT}/forward_test_log.csv"

# Deploy points that define the eras we compare (UTC).
BE_DEPLOY = datetime(2026, 9, 10, 12, 34)
WALK_CAP_MIN = 240          # counterfactual horizon from entry
ATR_SL_MULT, ATR_TP_MULT = 2.0, 3.0   # live engine geometry


def load_trades():
    out = []
    with open(TRADES, newline="") as f:
        for r in csv.DictReader(f):
            side = r["Trade_Type"].strip()
            entry = float(r["Entry_Price"])
            reason = r["Exit_Reason"].strip()
            atr = float(r["ATR_At_Entry"])
            sl, tp = float(r["Stop_Loss"]), float(r["Take_Profit"])
            if reason == "BE" or abs(entry - sl) < 1e-9:
                # Ratchet-armed row: rebuild the ORIGINAL geometry.
                d = 1 if side == "BUY" else -1
                sl, tp = entry - d * ATR_SL_MULT * atr, entry + d * ATR_TP_MULT * atr
            out.append(dict(
                num=int(r["Trade_Num"]), side=side, reason=reason, atr=atr,
                et=datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                xt=datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S"),
                entry=entry, sl=sl, tp=tp, profit=float(r["Profit"]),
                rsi=float(r["RSI_At_Entry"]),
                wick=float(r["Wick_Ratio_At_Entry"].rstrip("%")),
                ema50=float(r["EMA50_At_Entry"]), ema200=float(r["EMA200_At_Entry"]),
            ))
    return out


def load_bars():
    bars = []
    with open(LOG, newline="") as f:
        for r in csv.DictReader(f):
            try:
                bars.append((datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S"),
                             float(r["High"]), float(r["Low"]), float(r["Close"])))
            except (ValueError, KeyError):
                continue
    bars.sort()
    return bars, [b[0] for b in bars]


TRADES_L = load_trades()
BARS, BTS = load_bars()


def walk_window(t, end):
    lo = bisect.bisect_right(BTS, t["et"])          # skip the entry bar
    hi = bisect.bisect_right(BTS, end)
    return BARS[lo:hi]


def stats(ts, label, width=34):
    w = sum(1 for t in ts if t["reason"] == "TP")
    l = sum(1 for t in ts if t["reason"] == "SL")
    b = len(ts) - w - l
    pnl = sum(t["profit"] for t in ts)
    dec = w + l
    rate = w / dec * 100 if dec else float("nan")
    lo, hi = wilson(w, dec)
    rate_str = f"{rate:5.1f}% dec" if dec else "  no decisive"
    ci = f"[{lo:4.1f},{hi:4.1f}]" if dec else ""
    print(f"  {label:{width}s} n={len(ts):3d}  {w:2d}W/{l:2d}L/{b:2d}BE  "
          f"{rate_str} {ci}  P/L {pnl:+8.2f}  /trade {pnl/len(ts) if ts else 0:+.3f}")
    return w, l, b, pnl


def wilson(w, n, z=1.96):
    """95% CI on a proportion - n here is the DECISIVE count (BE = neutral)."""
    if n == 0:
        return 0.0, 0.0
    p = w / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - half) / denom * 100), min(100.0, (centre + half) / denom * 100)


def counterfactual_no_ratchet(t, cap_min=WALK_CAP_MIN):
    """Walk the trade with its ORIGINAL stop/target, direction-aware.
    Returns (outcome, R-multiple). outcome: W / L / T (flat at cap, mark to
    market) / N (no bars). SL is assumed to be touched first when one bar spans
    both levels - same conservative tie-break the engine's candle path uses."""
    d = 1 if t["side"] == "BUY" else -1
    one_r = abs(t["entry"] - t["sl"]) or 1e-9
    tp_r = abs(t["tp"] - t["entry"]) / one_r
    seg = walk_window(t, t["et"] + timedelta(minutes=cap_min))
    for _, h, l, c in seg:
        fav = (h - t["entry"]) if d == 1 else (t["entry"] - l)   # best for us
        adv = (t["entry"] - l) if d == 1 else (h - t["entry"])   # worst for us
        if adv >= one_r - 1e-9:
            return "L", -1.0
        if fav >= tp_r * one_r - 1e-9:
            return "W", tp_r
    if not seg:
        return "N", 0.0
    return "T", d * (seg[-1][3] - t["entry"]) / one_r


print(f"Win-rate report — {len(TRADES_L)} trades, {len(BARS)} bars "
      f"({BTS[0]} -> {BTS[-1]}), walk cap {WALK_CAP_MIN} min\n")

# ---------------------------------------------------------------- 1. baseline
print("== 1. BASELINE ==")
w, l, b, pnl = stats(TRADES_L, "all trades")
dec = w + l
one_r = statistics.mean(abs(t["entry"] - t["sl"]) for t in TRADES_L)
print(f"  all-in win rate {w/len(TRADES_L)*100:.1f}% ({w}/{len(TRADES_L)}) | "
      f"scratch rate {b/len(TRADES_L)*100:.1f}% ({b}/{len(TRADES_L)})")
print(f"  net P/L {pnl:+.2f}  =  {pnl/len(TRADES_L)/one_r:+.3f}R per trade "
      f"(avg 1R ${one_r:.2f})")
gross_w = sum(t["profit"] for t in TRADES_L if t["reason"] == "TP")
gross_l = sum(t["profit"] for t in TRADES_L if t["reason"] == "SL")
print(f"  gross {gross_w:+.2f} / {gross_l:+.2f}  payoff ratio "
      f"{abs(gross_w/gross_l)/(w/max(l,1)):.2f} per-win vs per-loss")
print(f"  breakeven decisive WR at 1:{ATR_TP_MULT/ATR_SL_MULT:.1f} RR = "
      f"{1/(1+ATR_TP_MULT/ATR_SL_MULT)*100:.1f}%\n")

# ------------------------------------------------------------------- 2. eras
print(f"== 2. ERAS (split at {BE_DEPLOY} = BE ratchet deploy) ==")
PRE = [t for t in TRADES_L if t["et"] < BE_DEPLOY]
NEW = [t for t in TRADES_L if t["et"] >= BE_DEPLOY]
stats(PRE, "pre-ratchet")
stats(NEW, "new regime (all gates live)")
for name, ts in (("pre-ratchet", PRE), ("new regime", NEW)):
    if ts:
        r = statistics.mean(abs(t["entry"] - t["sl"]) for t in ts)
        print(f"    {name}: expectancy {sum(t['profit'] for t in ts)/len(ts)/r:+.3f}R/trade")
print()

# ------------------------------------------------------------- 3. side/day
print("== 3. SIDE ==")
for side in ("BUY", "SELL"):
    stats([t for t in TRADES_L if t["side"] == side], f"{side} (all)")
for side in ("BUY", "SELL"):
    stats([t for t in NEW if t["side"] == side], f"{side} (new regime)")
print("\n== 3b. DAY ==")
by_day = defaultdict(list)
for t in TRADES_L:
    by_day[t["et"].date()].append(t)
for d in sorted(by_day):
    stats(by_day[d], str(d), width=12)
print("\n== 3c. HOUR (UTC, entry) — new regime ==")
by_hour = defaultdict(list)
for t in NEW:
    by_hour[t["et"].hour].append(t)
for h in sorted(by_hour):
    stats(by_hour[h], f"{h:02d}:00", width=12)
print()

# -------------------------------------------------------------- 4. durations
print("== 4. HOW LONG EACH OUTCOME TAKES (min) ==")
for reason in ("TP", "SL", "BE"):
    d = sorted((t["xt"] - t["et"]).total_seconds() / 60 for t in TRADES_L if t["reason"] == reason)
    if not d:
        continue
    print(f"  {reason:2s}: n={len(d):3d} median {statistics.median(d):6.1f}  "
          f"p90 {d[int(len(d)*0.9)]:6.1f}  max {max(d):8.1f}")
print("  (a scratch decided in ~1-2 min means the ratchet trigger is inside the "
      "noise band)")
print()

# ------------------------------------------------------- 5. BE counterfactual
print(f"== 5. BE-RATCHET COUNTERFACTUAL ({WALK_CAP_MIN}min cap, original stops, "
      "SL-first, cascade-ignorant) ==")
scr = [t for t in TRADES_L if t["reason"] == "BE"]
cw = cl = ct = cn = 0
cpnl = 0.0
for t in scr:
    k, r = counterfactual_no_ratchet(t)
    money = abs(t["entry"] - t["sl"])
    if k == "W":
        cw += 1
        cpnl += 1.5 * money
    elif k == "L":
        cl += 1
        cpnl -= money
    elif k == "T":
        ct += 1
        cpnl += r * money
    else:
        cn += 1
if scr:
    print(f"  {len(scr)} scratches as they would have run without the ratchet: "
          f"{cw}W/{cl}L ({cw/(cw+cl)*100:.0f}% decisive) + {ct} flat-at-cap, {cn} no-bars")
    print(f"  est P/L {cpnl:+.2f} vs {sum(t['profit'] for t in scr):+.2f} actual "
          f"-> the ratchet is worth {sum(t['profit'] for t in scr)-cpnl:+.2f} on this sample")
    print("  (upper bound: a held position would have displaced later entries)")
print()

# ------------------------------------------------------- 5b. ratchet trigger
print("== 5b. RATCHET TRIGGER GRID (new regime entries re-walked with the CURRENT rule) ==")
print(f"    {'trigger':>10s} {'W':>4} {'L':>4} {'BE':>4} {'dec WR':>7} {'estP/L$':>9}   note")


def walk_with_ratchet(t, trig, cap_min=WALK_CAP_MIN, tp_R=ATR_TP_MULT / ATR_SL_MULT):
    """Replay one trade under a hypothetical BE ratchet level (None = no ratchet)."""
    d = 1 if t["side"] == "BUY" else -1
    one_r = abs(t["entry"] - t["sl"]) or 1e-9
    armed = False
    for _, h, l, c in walk_window(t, t["et"] + timedelta(minutes=cap_min)):
        fav = (h - t["entry"]) if d == 1 else (t["entry"] - l)
        adv = (t["entry"] - l) if d == 1 else (h - t["entry"])
        if trig is not None and not armed and fav >= trig * one_r - 1e-9:
            armed = True
        if armed:                                   # ratcheted stop sits at entry
            if adv >= -1e-9:
                return "BE", 0.0
        elif adv >= one_r - 1e-9:
            return "L", -1.0
        if fav >= tp_R * one_r - 1e-9:
            return "W", tp_R
    if t["reason"] == "TP":
        return "W", tp_R
    if t["reason"] == "BE":
        return "BE", 0.0
    return "L", -1.0


for trig, note in ((None, "no ratchet at all"), (0.30, "<-- LIVE SINCE 09-10"),
                   (0.50, ""), (0.75, ""), (1.00, ""), (1.25, "")):
    W = L = BE = 0
    pnl = 0.0
    for t in NEW:
        k, r = walk_with_ratchet(t, trig)
        money = abs(t["entry"] - t["sl"]) * 0.985     # ~1.5% spread/slippage haircut
        if k == "W":
            W += 1
            pnl += r * money
        elif k == "BE":
            BE += 1
        else:
            L += 1
            pnl += r * money
    dec2 = W + L
    tag = f"{W/dec2*100:6.1f}%" if dec2 else "     n/a"
    print(f"    {('off' if trig is None else f'+{trig:.2f}R'):>10s} {W:4d} {L:4d} {BE:4d} "
          f"{tag:>7} {pnl:9.2f}   {note}".rstrip())
nw = sum(1 for t in NEW if t["reason"] == "TP")
nl = sum(1 for t in NEW if t["reason"] == "SL")
nb = sum(1 for t in NEW if t["reason"] == "BE")
np_ = sum(t["profit"] for t in NEW)
print(f"    {'ACTUAL':>10s} {nw:4d} {nl:4d} {nb:4d} "
      f"{(nw/(nw+nl)*100 if nw+nl else 0):6.1f}% {np_:9.2f}   <- what the engine really did")
print("    The +0.30R row should land near ACTUAL - if it does not, the walk and the\n"
      "    engine disagree (bar granularity / clock skew), so read every row here as an\n"
      "    estimate. Rows are cascade-ignorant: a held trade blocks later entries.\n")


# ------------------------------------------------- 5c. cascade-aware replay
print("== 5c. SAME GRID, CASCADE-AWARE (no overlapping trades + SL cooldown) ==")
print("    5b is optimistic: a position held for hours blocks new entries. Here an")
print("    entry is skipped if the simulated book is still busy, or while the SL")
print("    cooldown (30 min, 60 min after 2+ consecutive SLs) is running.\n")


def cascade_replay(sample, trig, cooldown_min=30, escalated_min=60):
    busy_until = None
    streak = 0
    taken = skipped = 0
    W = L = BE = 0
    pnl = 0.0
    hold = []
    for t in sorted(sample, key=lambda x: x["et"]):
        if busy_until is not None:
            cd = (escalated_min if streak >= 2 else cooldown_min) if streak else 0
            if t["et"] < busy_until + timedelta(minutes=cd):
                skipped += 1
                continue
        d = 1 if t["side"] == "BUY" else -1
        one_r = abs(t["entry"] - t["sl"]) or 1e-9
        tp_R = ATR_TP_MULT / ATR_SL_MULT
        armed = False
        out, mins = None, WALK_CAP_MIN
        seg = walk_window(t, t["et"] + timedelta(minutes=WALK_CAP_MIN))
        for k, (ts, h, l, c) in enumerate(seg):
            fav = (h - t["entry"]) if d == 1 else (t["entry"] - l)
            adv = (t["entry"] - l) if d == 1 else (h - t["entry"])
            if trig is not None and not armed and fav >= trig * one_r - 1e-9:
                armed = True                                   # ratchet to entry
            if armed and adv >= -1e-9:
                out, mins = "BE", k + 1
                break
            if not armed and adv >= one_r - 1e-9:
                out, mins = "L", k + 1
                break
            if fav >= tp_R * one_r - 1e-9:
                out, mins = "W", k + 1
                break
        if out is None:                                        # horizon ended flat
            out = {"TP": "W", "SL": "L"}.get(t["reason"], "BE")
        money = abs(t["entry"] - t["sl"]) * 0.985
        pnl += {"W": tp_R * money, "L": -money, "BE": 0.0}[out]
        W += out == "W"; L += out == "L"; BE += out == "BE"
        taken += 1
        streak = streak + 1 if out == "L" else 0
        busy_until = t["et"] + timedelta(minutes=mins)
        hold.append(mins)
    dec = W + L
    print(f"    {('off' if trig is None else f'+{trig:.2f}R'):>10s}  taken {taken:3d} (skip {skipped:3d})  "
          f"{W:3d}W/{L:3d}L/{BE:3d}BE  {(W / dec * 100 if dec else 0):5.1f}% dec  "
          f"P/L {pnl:+8.2f}  /trade {pnl / taken if taken else 0:+.3f}  "
          f"median hold {statistics.median(hold) if hold else 0:5.1f} min")


for trig in (None, 0.30, 0.50, 0.75, 1.00, 1.25):
    cascade_replay(NEW, trig)
print(f"    {'ACTUAL':>10s}  taken {len(NEW):3d} (skip   0)  "
      f"{nw:3d}W/{nl:3d}L/{nb:3d}BE  {(nw / (nw + nl) * 100 if nw + nl else 0):5.1f}% dec  "
      f"P/L {np_:+8.2f}  /trade {np_ / len(NEW):+.3f}")
print("    ACTUAL is NOT directly comparable: the live book was never blocked by a\n"
      "    held trade, so it traded ~2x the times the ratchet-off replay could.\n")
print("    Same grid on the candidate-filtered stream (RSI>=45 and ATR<2.5):")
FILTERED = [t for t in NEW if t["rsi"] >= 45 and t["atr"] < 2.5]
for trig in (None, 0.30, 0.75, 1.00):
    cascade_replay(FILTERED, trig)

# ---------------------------------------------------------- 6. filter queue
print("== 6. QUEUED ENTRY FILTERS (keep vs skip) ==")


def bucket(ts):
    w = sum(1 for t in ts if t["reason"] == "TP")
    b = sum(1 for t in ts if t["reason"] == "BE")
    l = len(ts) - w - b
    d = w + l
    return len(ts), w, l, b, (w / d * 100 if d else float("nan")), sum(t["profit"] for t in ts)


def experiment(name, keep_fn, sample, note):
    kept = [t for t in sample if keep_fn(t)]
    skip = [t for t in sample if not keep_fn(t)]
    if not kept or not skip:
        return
    k = bucket(kept)
    s = bucket(skip)
    print(f"  {name}")
    print(f"      keep   n={k[0]:3d}  {k[1]}W/{k[2]}L/{k[3]}BE  {k[4]:5.1f}% dec  {k[5]:+8.2f}")
    print(f"      skip   n={s[0]:3d}  {s[1]}W/{s[2]}L/{s[3]}BE  {s[4]:5.1f}% dec  {s[5]:+8.2f}"
          f"   ({note})")


for label, sample in (("NEW REGIME", NEW), ("ALL DATA", TRADES_L)):
    print(f"  --- {label} (n={len(sample)}) ---")
    experiment("RSI >= 45 (candidate #1)", lambda t: t["rsi"] >= 45, sample,
               "adopt if skip-bucket n>=30 and stays clearly worse")
    experiment("ATR < 2.5 (candidate: MAX_ATR tighten)", lambda t: t["atr"] < 2.5, sample,
               "skip bucket should be the bleed source")
    experiment("ATR < 2.0", lambda t: t["atr"] < 2.0, sample, "more aggressive variant")
    experiment("RSI >= 45 AND ATR < 2.5 (combo)",
               lambda t: t["rsi"] >= 45 and t["atr"] < 2.5, sample, "the pair, together")
    print()

print("Legend: 'dec' = decisive win rate (BE scratches excluded from both sides). "
      "Wilson CI covers sampling noise only - it is not a forecast.")
