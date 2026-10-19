#!/usr/bin/env python3
"""
check_gap_rides.py — make the §7 "extra revert trigger (gap risk)" measurable.

WHY THIS EXISTS
---------------
`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 registers a REVERT
condition that no tool counts:

    | Extra revert trigger (gap risk) | 2 or more post-cutover trades found
      open across a daily/weekly closure with an unenforceable stop — that is
      the §6 cost of longer holds materialising; revert and take the gap guard
      first |

The structural stop made holds ~2x longer (§6 of that analysis), so a position
can still be open when the broker shuts the market. While it is shut the stop
cannot be enforced, and in LIVE a stop is NOT broker-protected across a gap:
it fills at the open, not at the stop price (REVIEW-2026-10-05 §2a and §5b,
where the weekend hold #476 is the reference case). The trigger is a RISK
trigger — it exists so a gap risk that materialises is caught early, not only
at the n=150 confirmatory judgement.

Until now the count was eyeballed (the "0 rides" note at n=78 on 2026-10-13
used `check_data.py`'s span test). This tool computes it and prints the
evidence for every ride.

TWO QUESTIONS, PRINTED SEPARATELY
---------------------------------
The registered sentence leaves one thing open, so the tool refuses to settle it
by omission and prints both parts for every count:

  * the TRIGGER count — post-cutover trades open across a scheduled daily or
    weekly closure. Read literally, the stop of such a position is
    unenforceable *while the market is shut*, so every such ride qualifies.
  * the DAMAGE facts — did the reopen gap THROUGH the stop, or did the exit
    print worse than the stop? These do not change the trigger count; they say
    what the ride actually cost.

The judgement session must record which reading it used.

READ-ONLY. No engine, filter, parameter, ledger or log file is touched.

Usage:
    python3 tools/check_gap_rides.py [--root DIR] [--since YYYY-MM-DD] [--json]
    python3 tools/check_gap_rides.py --strict      # exit 1 when the trigger is reached

`--since` narrows the era (default: the structural-stop cutover, i.e. the §7
window). Exit code is 0 by default; `--strict` exits 1 when the registered
trigger count reaches the registered threshold of 2.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_lab as SL  # noqa: E402  (canonical bar/ledger loaders, LIVE_CUTOVER)

GAP_MIN_SECONDS = 300          # same threshold as check_data.py's span test
TRIGGER_THRESHOLD = 2          # §7 "2 or more post-cutover trades ..."
DAILY_BREAK_START = (20.0, 22.0)   # UTC hours the broker daily break starts in
DAILY_BREAK_MIN = (30.0, 180.0)    # minutes a daily break may last
WEEKEND_MIN = 24 * 60.0            # minutes; longer than this is the weekly close
EPS = 1e-9


def classify_gap(start, end):
    """Which kind of hole in the price log is this?  'weekend' | 'daily-break' | 'outage'.

    A scheduled market closure is either the weekly close (Fri ~20:57 -> Sun ~22:00
    UTC, > 24 h) or the broker's daily maintenance break (a time-of-day signature:
    it starts between 20:00 and 22:00 UTC and lasts 30-180 min — 20:58 -> 22:00 in
    the current era, 20:00 -> 21:11 in the old one, and it also runs on Sunday
    evening after the weekend reopen, so the day of week is not part of the rule).
    Anything else is a feed outage, not a closure: that is a different risk (the
    price is stale, not the market shut) and must not be counted as a gap ride.
    """
    mins = (end - start).total_seconds() / 60.0
    if mins >= WEEKEND_MIN:
        return "weekend"
    tod = start.hour + start.minute / 60.0
    if (DAILY_BREAK_START[0] <= tod <= DAILY_BREAK_START[1]
            and DAILY_BREAK_MIN[0] <= mins <= DAILY_BREAK_MIN[1]):
        return "daily-break"
    return "outage"


def is_closure(kind):
    """A scheduled market closure (the §7 wording) vs a feed outage."""
    return kind in ("daily-break", "weekend")


def find_gaps(bars):
    """[(start, end, minutes, kind)] for every hole in the bar series > 5 min."""
    gaps = []
    for a, b in zip(bars, bars[1:]):
        secs = (b[0] - a[0]).total_seconds()
        if secs > GAP_MIN_SECONDS:
            gaps.append((a[0], b[0], secs / 60.0, classify_gap(a[0], b[0])))
    return gaps


def gapped_through_stop(side, stop, reopen_open):
    """True when the market reopened BEYOND the stop, so the stop could not be filled."""
    return reopen_open < stop if side == "BUY" else reopen_open > stop


def exit_beyond_stop(side, stop, exit_price):
    """True when the position printed WORSE than its stop (a real gap loss)."""
    return exit_price < stop if side == "BUY" else exit_price > stop


def adverse_excursion(side, stop, bars_between):
    """How far the price went past the stop after the reopen, in $ (>= 0)."""
    if not bars_between:
        return 0.0
    if side == "BUY":
        return max(0.0, stop - min(b[3] for b in bars_between))
    return max(0.0, max(b[2] for b in bars_between) - stop)


def ride_for_trade(tr, gaps, bars, index):
    """Every gap this trade was open across, as evidence dicts."""
    out = []
    for g_start, g_end, mins, kind in gaps:
        if not (tr["et"] <= g_start and tr["xt"] >= g_end):
            continue
        reopen = bars[index[g_end]]
        after = [b for b in bars[index[g_end]:] if b[0] <= tr["xt"]]
        stop = tr["sl"]
        out.append(dict(
            trade=tr["num"], side=tr["side"],
            entry=str(tr["et"]), exit=str(tr["xt"]),
            gap_start=str(g_start), gap_end=str(g_end), gap_min=round(mins, 1), gap_kind=kind,
            entry_price=tr["ep"], stop=stop, target=tr["tp"], exit_price=tr["xp"],
            reason=tr["reason"], pnl=tr["pnl"],
            reopen_open=reopen[1],
            reopen_headroom=round((reopen[1] - stop) if tr["side"] == "BUY"
                                  else (stop - reopen[1]), 2),
            stop_at_entry=abs(stop - tr["ep"]) < EPS,
            gapped_through_stop=gapped_through_stop(tr["side"], stop, reopen[1]),
            exit_beyond_stop=exit_beyond_stop(tr["side"], stop, tr["xp"]),
            adverse=round(adverse_excursion(tr["side"], stop, after), 2),
            hold_min=round((tr["xt"] - tr["et"]).total_seconds() / 60.0, 1),
        ))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--since", default=None,
                    help="era start (YYYY-MM-DD); default = the structural-stop cutover")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the registered trigger count reaches %d" % TRIGGER_THRESHOLD)
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    bars = SL.load_bars(os.path.join(root, "forward_test_log.csv"))
    if not bars:
        print("no bars in %s - nothing to judge" % root)
        return 0
    index = {b[0]: i for i, b in enumerate(bars)}
    gaps = find_gaps(bars)
    ledger = SL.load_ledger(os.path.join(root, "trades.csv"))

    since = SL.LIVE_CUTOVER
    if a.since:
        since = datetime.strptime(a.since, "%Y-%m-%d")

    rides = []
    for tr in ledger:
        rides.extend(ride_for_trade(tr, gaps, bars, index))
    rides.sort(key=lambda r: r["entry"])

    era_rides = [r for r in rides if datetime.strptime(r["entry"], "%Y-%m-%d %H:%M:%S") >= since]
    era_closures = [r for r in era_rides if is_closure(r["gap_kind"])]
    damage = [r for r in era_closures if r["gapped_through_stop"] or r["exit_beyond_stop"]]
    reached = len(era_closures) >= TRIGGER_THRESHOLD

    if a.json:
        print(json.dumps(dict(
            root=root, since=str(since), threshold=TRIGGER_THRESHOLD,
            rides=rides, era_rides=era_rides, era_closure_rides=era_closures,
            damage_rides=damage, trigger_reached=reached,
        ), indent=2, default=str))
        return 1 if (a.strict and reached) else 0

    print("gap-ride check — %d ledger trades, %d bars, %d gaps > %d min in %s"
          % (len(ledger), len(bars), len(gaps), GAP_MIN_SECONDS // 60, root))
    print("  era under test: entries >= %s%s"
          % (since.strftime("%Y-%m-%d %H:%M"),
             "" if a.since else "  (the structural-stop cutover, strategy_lab.LIVE_CUTOVER)"))
    closures = [g for g in gaps if is_closure(g[3])]
    print("  price-log holes: %d scheduled closures (%d daily, %d weekend), %d feed outages"
          % (len(closures), sum(1 for g in closures if g[3] == "daily-break"),
             sum(1 for g in closures if g[3] == "weekend"),
             sum(1 for g in gaps if not is_closure(g[3]))))

    print("\n== every trade open across a price-log hole (whole book) ==")
    if not rides:
        print("  none")
    for r in rides:
        era = "era" if r in era_rides else "   "
        print("  %s #%-4d %-4s %s -> %s  hole %s -> %s (%.0f min, %s)"
              % (era, r["trade"], r["side"], r["entry"], r["exit"],
                 r["gap_start"], r["gap_end"], r["gap_min"], r["gap_kind"]))
        print("        entry %s  stop %s%s  target %s  exit %s %s %+.2f  hold %.0f min"
              % (r["entry_price"], r["stop"],
                 " (== entry, ratcheted scratch)" if r["stop_at_entry"] else "",
                 r["target"], r["exit_price"], r["reason"], r["pnl"], r["hold_min"]))
        print("        reopen open %s  |  headroom over the stop at the reopen: %s%.2f"
              % (r["reopen_open"], "+" if r["reopen_headroom"] >= 0 else "-",
                 abs(r["reopen_headroom"])))
        print("        stop gapped through at the reopen: %s   |  exit printed worse than "
              "the stop: %s" % ("YES" if r["gapped_through_stop"] else "no",
                                "YES" if r["exit_beyond_stop"] else "no"))
        print("        worst adverse move past the stop after the reopen: $%.2f" % r["adverse"])

    print("\n== §7 EXTRA REVERT TRIGGER (gap risk) ==")
    print("  registered text: \"2 or more post-cutover trades found open across a daily/weekly")
    print("                    closure with an unenforceable stop ... revert and take the gap")
    print("                    guard first\"")
    print("  post-cutover rides over a scheduled daily/weekly closure : %d   (threshold %d)  -> %s"
          % (len(era_closures), TRIGGER_THRESHOLD, "REACHED" if reached else "not reached"))
    print("     of which the reopen gapped THROUGH the stop          : %d" % damage_gap_count(damage))
    print("     of which the exit printed worse than the stop         : %d" % damage_exit_count(damage))
    print("     of which the stop sat at entry (scratch, $0 exposure) : %d"
          % sum(1 for r in era_closures if r["stop_at_entry"]))
    wk = [r for r in era_closures if r["gap_kind"] == "weekend"]
    print("     of which a WEEKEND closure (the #476 failure mode)   : %d" % len(wk))
    if era_closures:
        tight = min(era_closures, key=lambda r: r["reopen_headroom"])
        print("     tightest reopen (least headroom over the stop)     : #%d %s $%+.2f"
              % (tight["trade"], tight["side"], tight["reopen_headroom"]))
    if reached:
        print("  => the registered count is AT its threshold. The registered action is a")
        print("     single-commit revert of the structural stop, gap guard first (§7). The damage")
        print("     rows above are evidence for the judgement session, not a replacement count.")
    else:
        print("  => the registered count is below its threshold.")
    print("  (the trigger count and the damage rows are two different questions; the review")
    print("   must record which reading it used - see docs/REVIEW-2026-10-19-struct-stop-screen.md)")

    return 1 if (a.strict and reached) else 0


def damage_gap_count(damage):
    return sum(1 for r in damage if r["gapped_through_stop"])


def damage_exit_count(damage):
    return sum(1 for r in damage if r["exit_beyond_stop"])


if __name__ == "__main__":
    sys.exit(main())
