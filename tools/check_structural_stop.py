#!/usr/bin/env python3
"""
check_structural_stop.py — guard the 2026-10-05 structural-stop change.

Why this exists: the change is justified by a MECHANICAL property, not by P&L. The
stop must never sit inside the 20-bar level the entry was anchored to. Before the
change it did, in 203/318 = 63.8% of the 0.75R master book (and 95/149 = 63.8% of its
SL exits) - a stop-out needed no structural break at all. That property is
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
                         it was 63.8% of the 0.75R master book before 2026-10-05)
  3. clearance            median ATR by which the stop sits BEYOND the level (>= 0 for
                         every trade, >= SL_CLEAR_ATR = 0.5 whenever the level bound it)
  4. recall               trades whose decision bar was found at all (the join check)

Sells need the 20-bar CEILING, which forward_test_log.csv does not carry, so it is
recomputed from the bar series exactly as engine.evaluate_candle does (min/max of the
previous LOOKBACK_PERIOD lows/highs, excluding the current bar; validated against the
logged Dynamic_Floor at 99.9% on the BUY side).

Boundary evidence (added 2026-10-13). The cutover constant is a CLAIM about when the host
started running the new code; the ledger can prove it. Every stop is classified by which rule
produced it - OLD (risk == 2.0 ATR although the level was further away), NEW (risk == level
distance + 0.5 ATR) or BOTH (the level did not bind, so the two rules are indistinguishable).
The deploy happened between the last OLD-only trade and the first NEW-only trade; the check
prints that bracket and warns when strategy_lab.LIVE_CUTOVER falls outside it. This is what
caught the 2026-10-06 mis-dating: the docs planned 10-05 21:00, the host deployed at 03:00
the next morning, and three pre-deploy trades looked like a "stop inside the level" failure.
A failure is then diagnosed as a BOUNDARY error (old-rule trades that entered before the first
new-rule trade) or a REGRESSION (an old-rule trade AFTER the first new-rule trade).

Usage: python3 tools/check_structural_stop.py [--root DIR] [--since YYYY-MM-DD]
Exit code 1 if any post-cutover trade has a stop inside its level (the message says whether
the cutover constant or the engine is the likelier culprit).
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_lab as SL  # noqa: E402  (canonical replay math: bars, Lab, engine params)

LOOKBACK = SL.LOOKBACK
GEOM_TOL = 0.03   # $: logged prices carry 2-dp rounding (same slack as the `inside` test)


def geometry_class(risk, atr, dist, tol=GEOM_TOL):
    """Which stop rule produced this trade? Pure function of the ledger row + its decision bar.

    risk = |entry - original stop| ($), atr = ATR at the decision bar, dist = |entry - level| ($).
      OLD  - risk matches ATR_SL_MULT*ATR and NOT the structural rule (decidable only when the
             level binds, i.e. the structural risk is more than `tol` larger)
      NEW  - risk matches max(ATR_SL_MULT*ATR, dist + SL_CLEAR_ATR*ATR) and NOT the old rule
      BOTH - the two rules agree within `tol` (the level did not bind): says nothing about
             which code was running
      ???  - matches neither (a join error, a third geometry, or a rounding outlier)
    """
    old = SL.ATR_SL_MULT * atr
    new = max(old, dist + SL.SL_CLEAR_ATR * atr)
    m_old, m_new = abs(risk - old) <= tol, abs(risk - new) <= tol
    if m_old and m_new:
        return "BOTH"
    if m_old:
        return "OLD"
    if m_new:
        return "NEW"
    return "???"


def boundary_evidence(rows):
    """Locate the deploy from the ledger alone.

    `rows` = dicts with `cls` (geometry_class) and `tr` (the ledger trade, `et` = entry time).
    Returns (last_old, first_new, late_old): the last OLD-only trade, the first NEW-only trade,
    and every OLD-only trade that entered AFTER the first NEW-only one. In a clean single deploy
    `late_old` is empty and the deploy sits in (last_old.et, first_new.et]. A non-empty
    `late_old` means old-rule stops reappeared after the new rule had started - a code
    regression or a rollback, never a boundary error.
    """
    olds = sorted((r for r in rows if r["cls"] == "OLD"), key=lambda r: r["tr"]["et"])
    news = sorted((r for r in rows if r["cls"] == "NEW"), key=lambda r: r["tr"]["et"])
    first_new = news[0] if news else None
    last_old = olds[-1] if olds else None
    late_old = [r for r in olds if first_new and r["tr"]["et"] > first_new["tr"]["et"]]
    return last_old, first_new, late_old


def diagnose_failure(inside_rows, last_old, first_new, late_old, cutover):
    """One line saying WHY post-cutover trades sit inside their level."""
    if late_old:
        return ("REGRESSION: %d old-rule stop(s) entered AFTER the first new-rule trade (#%s) - "
                "the engine is not running the structural stop consistently (rollback? hand-edit?)"
                % (len(late_old), first_new["tr"]["num"]))
    if first_new is None:
        return ("NO new-rule trade exists yet: either the change is not deployed or no entry has had a "
                "level that binds - the cutover cannot be evidenced, check the host's `autosync: merge "
                "upstream` commit time before reading anything into this")
    early = [r for r in inside_rows if r["tr"]["et"] < first_new["tr"]["et"]]
    if len(early) == len(inside_rows):
        return ("BOUNDARY ERROR, not a code regression: all %d failing trade(s) entered before the first "
                "new-rule trade (#%s at %s) - LIVE_CUTOVER %s is too early; move it into (%s, %s]"
                % (len(inside_rows), first_new["tr"]["num"], first_new["tr"]["et"],
                   cutover.strftime("%Y-%m-%d %H:%M"),
                   last_old["tr"]["et"] if last_old else "?", first_new["tr"]["et"]))
    return ("UNEXPLAINED: %d failing trade(s) entered after the first new-rule trade yet sit inside "
            "their level - inspect them one by one (join error vs engine)" % (len(inside_rows) - len(early)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--since", default=None, help="only judge trades entered at/after this date")
    a = ap.parse_args(argv)
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
                         bound=(abs(tr["ep"] - sl0) - SL.ATR_SL_MULT * atr) > 0.03,
                         cls=geometry_class(abs(tr["ep"] - sl0), atr, abs(tr["ep"] - lvl))))

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
    bad_rows = []
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
              f"median clearance {med:+.2f} ATR  median |entry-level| {sorted(r['dist'] for r in sel)[len(sel)//2]:.2f} ATR  "
              f"median risk {sorted(r['risk'] for r in sel)[len(sel)//2]:.2f} ATR")
        sls = [r for r in sel if r["tr"]["reason"] == "SL"]
        sl_in = [r for r in sls if r["inside"]]
        tps = [r for r in sel if r["tr"]["reason"] == "TP"]
        tp_in = [r for r in tps if r["inside"]]
        if sls:
            print(f"  {'':20s}   exits: SL {len(sl_in)}/{len(sls)} printed with the stop still "
                  f"inside the level ({100*len(sl_in)/len(sls):.1f}%) | TP {len(tp_in)}/{len(tps)} won from inside")
        if frm is not None and frm >= SL.LIVE_CUTOVER and inside:
            bad = len(inside)
            bad_rows = inside

    # ---- boundary evidence: which rule produced each stop, and where is the deploy?
    last_old, first_new, late_old = boundary_evidence(rows)
    n_old = sum(1 for r in rows if r["cls"] == "OLD")
    n_new = sum(1 for r in rows if r["cls"] == "NEW")
    n_both = sum(1 for r in rows if r["cls"] == "BOTH")
    n_unk = sum(1 for r in rows if r["cls"] == "???")
    print(f"\n  boundary evidence - which stop rule produced each trade?  "
          f"OLD-only {n_old} | NEW-only {n_new} | indistinguishable {n_both} | neither {n_unk}")

    def _fmt(r):
        t = r["tr"]
        return (f"#{t['num']} {t['side']} {t['et']} (risk {r['risk']:.2f} ATR, "
                f"level {r['dist']:.2f} ATR away)")

    print(f"    last OLD-rule trade : {_fmt(last_old) if last_old else '-'}")
    print(f"    first NEW-rule trade: {_fmt(first_new) if first_new else '- (none yet)'}")
    evidence_ok = True
    if last_old and first_new:
        lo, hi = last_old["tr"]["et"], first_new["tr"]["et"]
        if late_old:
            evidence_ok = False
            print(f"    !! {len(late_old)} OLD-rule trade(s) entered AFTER the first NEW-rule trade - "
                  f"mixed geometry (rollback / regression)")
        elif lo < SL.LIVE_CUTOVER <= hi:
            print(f"    -> the deploy happened between those two entries; LIVE_CUTOVER "
                  f"{SL.LIVE_CUTOVER:%Y-%m-%d %H:%M} is inside the bracket: OK")
        else:
            evidence_ok = False
            side = "EARLY" if SL.LIVE_CUTOVER <= lo else "LATE"
            print(f"    !! LIVE_CUTOVER {SL.LIVE_CUTOVER:%Y-%m-%d %H:%M} is too {side}: the ledger puts the "
                  f"deploy in ({lo}, {hi}] - fix tools/strategy_lab.py LIVE_CUTOVER and the docs")
    elif first_new is None:
        print("    -> no NEW-rule trade yet, so the deploy time is not evidenced by the ledger")
    print(f"\n  Pre-cutover trades are historical proof that the OLD geometry was inside the")
    print(f"  level; from {SL.LIVE_CUTOVER:%Y-%m-%d %H:%M} UTC the count must be ZERO.")
    if bad:
        print(f"FAIL: {bad} post-cutover trade(s) have a stop inside the tested level - "
              f"the shipped change is not doing what the model says.")
        print("  diagnosis: " + diagnose_failure(bad_rows, last_old, first_new, late_old, SL.LIVE_CUTOVER))
        return 1
    if not evidence_ok:
        print("FAIL: no stop is inside its level, but the cutover constant contradicts the ledger evidence above.")
        return 1
    print("PASS: no post-cutover stop sits inside its level.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
