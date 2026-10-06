#!/usr/bin/env python3
"""
check_structural_stop.py — guard the 2026-10-05 structural-stop change.

Why this exists: the change is justified by a MECHANICAL property, not by P&L. The
stop must never sit inside the 20-bar level the entry was anchored to. Before the
change it did, in 68.6% of the 0.75R master book (218/318), and 69.1% of SL exits
were that class - a stop-out needed no structural break at all. That property is
checkable on any ledger, cost-free, and it is the FIRST thing to verify after a
deploy: if it fails, the code is wrong (or the log/replay join is), and no expectancy
number in docs/ANALYSIS-2026-10-05-stop-loss-geometry.md can be judged yet.

Reads trades.csv + forward_test_log.csv, joins each entry to its DECISION bar
(entry price == that bar's close; the engine logs a row per closed candle and the
floor/ceiling in it exclude the current bar), and reports for each era:

  1. level-bound share   how many trades got a stop WIDER than ATR_SL_MULT*ATR
                         (replay prediction under the new rule: ~80%)
  2. stop-inside-level    how many have the SL between the entry and the level, i.e.
                         the stop prints without the level breaking (must be 0 now;
                         it was 68.6% of the 0.75R master book before 2026-10-05)
  3. clearance            median ATR by which the stop sits BEYOND the level (>= 0 for
                         every trade, >= SL_CLEAR_ATR = 0.5 whenever the level bound it)
  4. recall               trades whose decision bar was found at all (the join check)

Sells need the 20-bar CEILING, which forward_test_log.csv does not carry, so it is
recomputed from the bar series exactly as engine.evaluate_candle does (min/max of the
previous LOOKBACK_PERIOD lows/highs, excluding the current bar; validated against the
logged Dynamic_Floor at 99.9% on the BUY side).

Usage: python3 tools/check_structural_stop.py [--root DIR] [--since YYYY-MM-DD]
Exit code 1 if any post-cutover trade has a stop inside its level.
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_lab as SL  # noqa: E402  (canonical replay math: bars, Lab, engine params)

LOOKBACK = SL.LOOKBACK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--since", default=None, help="only judge trades entered at/after this date")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    since = datetime.strptime(a.since, "%Y-%m-%d") if a.since else None

    bars = SL.load_bars(os.path.join(root, "forward_test_log.csv"))
    lab = SL.Lab(bars)
    by_ts = {t: i for i, t in enumerate(lab.ts)}
    # The engine logs the row for a bar with the wall-clock time it was PROCESSED, while
    # trades.csv Entry_Time is also wall-clock -> they agree to the minute for most rows,
    # but fall back to a price match when they do not (entry price == signal-bar close).
    by_px = defaultdict(list)
    for i, (t, o, h, l, c, v) in enumerate(bars):
        by_px[round(c, 2)].append(i)

    T = SL.load_ledger(os.path.join(root, "trades.csv"))
    rows, unmatched = [], []
    for tr in T:
        if since and tr["et"] < since:
            continue
        i = by_ts.get(tr["et"].replace(second=0))
        if i is None or abs(bars[i][4] - tr["ep"]) > 0.05:
            cands = [j for j in by_px.get(round(tr["ep"], 2), [])
                     if abs((lab.ts[j] - tr["et"]).total_seconds()) <= 240]
            i = cands[-1] if cands else None
        if i is None:
            unmatched.append(tr)
            continue
        atr = lab.atr[i]
        lvl = lab.floor[i] if tr["side"] == "BUY" else lab.ceil[i]
        if not atr or lvl is None:
            unmatched.append(tr)
            continue
        d = 1 if tr["side"] == "BUY" else -1
        # ratcheted (BE) rows have the logged SL overwritten with entry -> recover the
        # ORIGINAL stop from the reward leg, which the ratchet never touches (TP = 1.5*risk)
        sl0 = tr["sl"]
        if abs(sl0 - tr["ep"]) < 1e-9 or tr["reason"] == "BE":
            sl0 = tr["ep"] - d * abs(tr["tp"] - tr["ep"]) / SL.RR_TARGET
        # Sign convention: d=+1 BUY (level below the entry, stop below the level),
        # d=-1 SELL (level above the entry, stop above it). "Clearance" > 0 means the
        # stop is BEYOND the level, so the level must break for the stop to print.
        # Logged prices carry 2-dp rounding, so 3 cents of slack is noise, not signal.
        clearance = d * (lvl - sl0)
        rows.append(dict(tr=tr, i=i, atr=atr, lvl=lvl, sl=sl0,
                         dist=abs(tr["ep"] - lvl) / atr,
                         risk=abs(tr["ep"] - sl0) / atr,
                         clr=clearance / atr,
                         inside=clearance < -0.03,
                         bound=(abs(tr["ep"] - sl0) - SL.ATR_SL_MULT * atr) > 0.03))

    print(f"structural-stop check — {len(T)} ledger trades "
          f"({len(rows)} joined, {len(unmatched)} unjoinable) in {root}")
    if since:
        print(f"filtered to entries >= {since.date()}")
    if not rows:
        print("\nNO trades to judge yet (era just started?). Nothing to say.")
        return 0

    eras = [("all", None), ("0.75R master", SL.ERA_RATCHET_075), ("max-hold", SL.ERA_MAXHOLD),
            ("struct-stop cutover", SL.LIVE_CUTOVER)]
    bad = 0
    for nm, frm in eras:
        sel = [r for r in rows if frm is None or r["tr"]["et"] >= frm]
        if not sel:
            print(f"  {nm:20s} (no trades)")
            continue
        bound = [r for r in sel if r["bound"]]
        inside = [r for r in sel if r["inside"]]
        clr = sorted(r["clr"] for r in sel)
        med = clr[len(clr) // 2]
        print(f"  {nm:20s} n={len(sel):3d}  level-bound {100*len(bound)/len(sel):5.1f}%  "
              f"stop INSIDE level {len(inside):3d} ({100*len(inside)/len(sel):4.1f}%)  "
              f"median clearance {med:+.2f} ATR  median |entry-level| {sorted(r['dist'] for r in sel)[len(sel)//2]:.2f} ATR")
        sls = [r for r in sel if r["tr"]["reason"] == "SL"]
        sl_in = [r for r in sls if r["inside"]]
        tps = [r for r in sel if r["tr"]["reason"] == "TP"]
        tp_in = [r for r in tps if r["inside"]]
        if sls:
            print(f"  {'':20s}   exits: SL {len(sl_in)}/{len(sls)} printed with the stop still "
                  f"inside the level ({100*len(sl_in)/len(sls):.1f}%) | TP {len(tp_in)}/{len(tps)} won from inside")
        if frm is not None and frm >= SL.LIVE_CUTOVER and inside:
            bad = len(inside)
    print(f"\n  Pre-cutover trades are historical proof that the OLD geometry was inside the")
    print(f"  level; from {SL.LIVE_CUTOVER:%Y-%m-%d %H:%M} UTC the count must be ZERO.")
    if bad:
        print(f"FAIL: {bad} post-cutover trade(s) have a stop inside the tested level - "
              f"the shipped change is not doing what the model says.")
        return 1
    print("PASS: no post-cutover stop sits inside its level.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
