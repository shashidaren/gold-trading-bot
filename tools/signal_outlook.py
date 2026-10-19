#!/usr/bin/env python3
"""signal_outlook.py — given a very strong signal, where has price headed?

Owner ask (2026-10-19): reading direction off 1-min candle patterns by eye is
extremely difficult; can we have a rough estimate of where price is headed
when the signal is very strong?

This tool answers with the only estimate this repo can defend: what price
ACTUALLY did after the bot's own full signals. Every closed trade in
`trades.csv` is a "very strong signal" by the engine's definition (all funnel
gates + the risk layer passed), so the report walks `forward_test_log.csv`
forward from each entry and prints, per side and era:

  * how often price closed the trade's way after 15/30/60/240 min (Wilson CI),
    and how often by more than the assumed round-trip cost;
  * the typical move and the middle-50% cone, in R (reward-leg risk) and ATR;
  * how far price travelled BOTH ways on the way (median MFE/MAE);
  * which barrier printed first on the raw path, +1.5R (target) vs -1R
    (stop), against the 40% driftless reference for those distances;
  * a trend-anywhere baseline, so the signal rows have something to beat.

Section 1 applies those base rates to the LAST logged bar when (and only
when) a side passes all 8 gates there: today's entry/stop/target plus the
historical cone in $ prices. That is a transfer of past frequencies onto
today's risk — an assumption, stated wherever it is printed.

What this is NOT: a forecast, a new signal, or a reason to size/veto/hold.
The core lives in `pressure.py` (`signal_outlook` / `outlook_now`), the same
read-only layer the dashboard renders; this CLI is its printed form. Full
method, numbers and limits: docs/ANALYSIS-2026-10-19-signal-outlook.md.

Usage:
    python3 tools/signal_outlook.py                  # struct-stop era (live rule)
    python3 tools/signal_outlook.py --era 075        # bigger sample, older stop rule
    python3 tools/signal_outlook.py --root DIR       # read DIR/{forward_test_log,trades}.csv
    python3 tools/signal_outlook.py --json
Exit code 0 always (it is a report, not a gate). Read-only by construction.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P  # noqa: E402

ERAS = {
    "structstop": ("struct-stop era (live rule)", P.STRUCT_STOP_CUTOVER),
    "075": ("0.75R era (>= 2026-09-15 06:00)", datetime(2026, 9, 15, 6, 0)),
    "all": ("whole book (exit geometry changed across it — read with care)", datetime(2020, 1, 1)),
}


def hdr(text):
    print(f"\n== {text} ==")


def ci(pair):
    return "—" if not pair or pair[0] is None else f"{pair[0]:.0f}-{pair[1]:.0f}"


def num(v, fmt="{:+.2f}"):
    return "—" if v is None else fmt.format(v if v != 0 else 0.0)  # no "-0.00"


def print_group(label, g, horizons, ref_pct):
    if not g["n"]:
        print(f"\n-- {label}: no trades in sample --")
        return
    o = g["outcomes"]
    print(f"\n-- {label} (n={g['n']} taken signals; ledger "
          f"{o['TP']}W/{o['SL']}L/{o['BE']}BE/{o['TIME']}TIME) --")
    for h in horizons:
        c = g["horizons"][h]
        if not c.get("n"):
            print(f"  {h:>3}m  no uncensored windows (censored {c.get('censored', g['n'])})")
            continue
        print(f"  {h:>3}m  n={c['n']:>3} (censored {c['censored']:>2})"
              f"  closed trade's way {c['fav_pct']:5.1f}% [{ci(c['fav_ci'])}]"
              f"  by >cost {c['fav_cost_pct']:5.1f}% [{ci(c['fav_cost_ci'])}]")
        print(f"       drift median {num(c['drift_r_median'])}R  mean {num(c['drift_r_mean'])}R"
              f"  middle-50% cone [{num(c['drift_r_q25'])}R, {num(c['drift_r_q75'])}R]"
              f"  median {num(c['drift_atr_median'])} ATR"
              f"  travelled MFE {num(c['mfe_r_median'], '{:.2f}')}R / MAE {num(c['mae_r_median'], '{:.2f}')}R")
        tp = "—" if c["tp_first_pct"] is None else f"{c['tp_first_pct']:.1f}% [{ci(c['tp_first_ci'])}]"
        print(f"       barrier race  target-first {c['race_tp']:>3}  stop-first {c['race_sl']:>3}"
              f"  neither {c['race_none']:>3}  same-bar {c['race_amb']}"
              f"  -> target-first share {tp}  (driftless reference {ref_pct:.0f}%)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="directory holding forward_test_log.csv / trades.csv")
    ap.add_argument("--era", default="structstop", choices=sorted(ERAS),
                    help="sample era for the base rates (default: structstop, the live rule)")
    ap.add_argument("--spread", type=float, default=P.OUTLOOK_COST_USD,
                    help="assumed round-trip cost in $ for the 'by >cost' column (default 0.40)")
    ap.add_argument("--json", action="store_true", help="dump the raw structures instead of the report")
    args = ap.parse_args(argv)

    if args.root:
        root = os.path.abspath(args.root)
        P.LOG_FILE_PATH = os.path.join(root, "forward_test_log.csv")
        P.TRADES_FILE_PATH = os.path.join(root, "trades.csv")

    log_rows = P.read_rows(P.LOG_FILE_PATH)
    trades = P.read_rows(P.TRADES_FILE_PATH)
    era_label, cutover = ERAS[args.era]
    outlook = P.signal_outlook(log_rows, trades, cutover, cost=args.spread)
    setup = P.setup_read(log_rows[-400:] if len(log_rows) > 400 else log_rows)
    now = P.outlook_now(setup, outlook)

    if args.json:
        print(json.dumps({"outlook": outlook, "now": now}, default=str, indent=2))
        return 0

    print(f"Signal outlook — where did full signals head?  ({len(log_rows)} log bars, "
          f"{len(trades)} closed trades)")
    print("Historical frequencies over the bot's own taken signals. NOT a forecast, "
          "NOT an entry condition.")
    if not outlook.get("ok"):
        print(f"\nunavailable — {outlook.get('reason')}")
        return 0
    ref = outlook["barrier_reference_pct"]

    hdr("1. NOW — last closed bar, applied base rates")
    if not setup.get("ok"):
        print(f"  setup read unavailable — {setup.get('reason')}")
    elif not now.get("ready_side"):
        print(f"  bar {setup['as_of']}  close ${setup['close']:.2f}  ATR {setup['atr']:.2f}"
              f"  RSI {setup['rsi']:.1f}")
        for side in ("BUY", "SELL"):
            miss = setup["nearest_miss"].get(side)
            print(f"  {side}: {now['passed'][side]}/{now['total'][side]} gates — NO strong signal"
                  + (f"  (first gap: {miss})" if miss else ""))
        print("  The estimate in §2 applies only when a side prints 8/8. An 'almost' "
              "setup has no measured base rate here.")
    else:
        side = now["ready_side"]
        print(f"  bar {now['as_of']}  —  {side} passes ALL 8 gates (very strong signal)")
        print(f"  entry ${now['entry']:.2f}  ->  stop ${now['stop']:.2f}  target ${now['target']:.2f}"
              f"  risk ${now['risk']:.2f}  (level ${now['level']:.2f})")
        print(f"  Rough estimate from {era_label} {side} signals like this "
              f"(cone = entry ± historical drift-R x today's risk):")
        for a in now["applied"]:
            tp = "—" if a["tp_first_pct"] is None else f"{a['tp_first_pct']:.0f}% [{ci(a['tp_first_ci'])}]"
            print(f"    +{a['horizon']:>3}m  median ${a['cone_median']:.2f}"
                  f"  middle-50% ${a['cone_lo']:.2f}-${a['cone_hi']:.2f}"
                  f"  closed {side}'s way {a['fav_pct']:.0f}% [{ci(a['fav_ci'])}] (n={a['n']})"
                  f"  target-before-stop {tp}")
        print("  Read the cone, not the median: the median says 'about nowhere', the cone "
              "says how wide 'nowhere' is.")

    hdr(f"2. BASE RATES — {era_label} ({outlook['era_label']}, cost ${args.spread:.2f})")
    print(f"  sample n={outlook['n']} taken signals (excluded {outlook['excluded']} unusable rows)"
          f"  ·  ledger hold: median {num(outlook['hold_median_min'], '{:.0f}')} min,"
          f" p90 {num(outlook['hold_p90_min'], '{:.0f}')} min")
    print("  Path stats ignore exits (drift = close at horizon vs entry); the race uses the")
    print("  trade's own +1.5R target / -1R stop distances, no BE ratchet. Side split first,")
    print("  pooled last — pooled direction claims are the §8 trap.")
    for side in ("BUY", "SELL"):
        print_group(f"{side} signals", outlook["sides"][side], outlook["horizons"], ref)
    print_group("POOLED (signed the trade's way)", outlook["pooled"], outlook["horizons"], ref)

    hdr("3. BASELINE — 'follow the EMA trend anywhere' (same era, non-overlapping bars)")
    for h in outlook["horizons"]:
        b = outlook["baseline"][h]
        if not b["n"]:
            print(f"  {h:>3}m  no usable baseline windows")
            continue
        print(f"  {h:>3}m  n={b['n']:>4}  closed trend's way {b['fav_pct']:5.1f}% [{ci(b['fav_ci'])}]"
              f"  median drift {num(b['drift_atr_median'])} ATR")
    print("  If §2 does not clearly beat this, the candle pattern added no measured direction.")

    hdr("4. HOW TO READ THIS (limits)")
    print("  * Frequencies, not forecasts: '49% [41-57]' means this sample cannot tell the")
    print("    direction from a coin flip — trade the stop/target geometry, not a heading.")
    print(f"  * The target is 1.5x further than the stop, so even a driftless path hits the")
    print(f"    target first only ~{ref:.0f}% of decisive races. Compare shares to {ref:.0f}%, not 50%.")
    print("  * Windows crossing a >5-min log gap or falling short of the horizon are")
    print("    censored (counted above), never guessed across. 1-min bars cannot order a")
    print("    same-bar double touch ('same-bar' column).")
    print("  * Sample = signals the bot took (one position at a time); skipped signals")
    print("    carry no logged side and are excluded by design.")
    print("  * No gate, sizing or hold rule may be derived from this without a")
    print("    pre-registered bar (docs/HANDOFF.md §11). Method + verdict:")
    print("    docs/ANALYSIS-2026-10-19-signal-outlook.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
