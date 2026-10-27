#!/usr/bin/env python3
"""pressure_report.py — read what the dashboard shows, and what it is worth.

Prints the same read-only layer the dashboard renders (`pressure.py`): the tape
composite, the engine's own gates on the last closed bar, the portfolio state,
the live struct-stop experiment against its pre-registered bar, the feed health —
and, the part that matters, the CALIBRATION: whether the pressure composite ever
separated outcomes in the live book, per side and per era, with the honest
verdict. It writes nothing; it never trades; it changes no rule.

Why the calibration lives here and not on a chart: the engine's trend gate keys
side on EMA50 vs EMA200, so "buy pressure" at a BUY entry is high by construction
and low at a SELL. A pooled gauge therefore measures the direction the bot is
already allowed to trade — the same trap the 2026-09-28 analysis flagged for
pooled momentum (docs/HANDOFF.md §8). The number that decides whether this
indicator is worth looking at is the WITHIN-SIDE bucket spread, and that is what
section 6 prints.

Usage:
    python3 tools/pressure_report.py                 # human report, current data
    python3 tools/pressure_report.py --root DIR      # read DIR/{forward_test_log,trades}.csv
    python3 tools/pressure_report.py --era 0.75      # calibrate on the 0.75R master era
    python3 tools/pressure_report.py --json          # machine-readable dump
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
    # the registered structstop1.5 window: its boundary is the host DEPLOY time, so it is None
    # until A2 ships. A None cutover means "not started" - never "judge the old era instead".
    "clear15": ("structstop1.5 era (registered 2026-10-27)", getattr(P, "CLEAR15_CUTOVER", None)),
    "maxhold": ("max-hold era (>= 2026-09-21 06:00)", datetime(2026, 9, 21, 6, 0)),
    "075": ("0.75R era (>= 2026-09-15 06:00)", datetime(2026, 9, 15, 6, 0)),
    "all": ("whole book", datetime(2020, 1, 1)),
}


def hdr(text):
    print(f"\n== {text} ==")


def rule(width=78):
    print("-" * width)


def _print_era_card(e):
    """One pre-registered era card: the numbers, then the registered bar rows (§5 / §7).

    Shared by the live struct-stop card and the structstop1.5 window's card, because the whole
    point of the read layer is that a session sees the SAME contract the judgement will use —
    whichever registration that window was written under.
    """
    print(f"  {e['label']} (entries >= {e['cutover']:%Y-%m-%d %H:%M} UTC)  n={e['n']}"
          f"  {e['counts']['TP']}W/{e['counts']['SL']}L/{e['counts']['BE']}BE/{e['counts']['TIME']}TIME"
          f"  ·  {e['status']}")
    print(f"  decisive WR {e['wr']:.1f}% (CI {e['wr_ci'][0]:.1f}-{e['wr_ci'][1]:.1f})"
          f"  ·  R/trade {e['r_per_trade']:+.3f} (gross: ${e['gross_per_trade']:+.2f}/trade ÷ "
          f"mean 1R ${e['mean_1r_usd']:.2f}, win_rate_report scale)"
          f"  ·  ${e['gross']:+.2f} total")
    print(f"  decisive-only R/trade {e['r_per_trade_decisive']:+.3f} (per-trade reward-leg risk — "
          f"secondary read, same sign, different denominator)")
    print(f"  SL/day {e['sl_per_day']:.1f}  ·  SL share {e['sl_share_pct']:.1f}%"
          f"  ·  scratch {e['scratch_pct']:.1f}%  ·  avg SL ${e['avg_sl_usd']:.2f}"
          f"  ·  era DD ${e['max_dd']:.2f}")
    for key, c in e["checks"].items():
        val = "—" if c["value"] is None else f"{c['value']:.2f}{c['unit']}"
        print(f"    [{'OK  ' if c['ok'] else 'FAIL'}] {key} {c['name']}: {val} {c['cmp']} "
              f"{c['bar']}{c['unit']} (baseline {c['baseline']})")
    for key, g in e["geometry"].items():
        val = "—" if g["value"] is None else f"{g['value']:.1f}"
        print(f"    [{'OK  ' if g['ok'] else 'out '}] {key} {g['name']}: {val}{g['unit']} "
              f"(target {g['lo']}-{g['hi']}, {g['baseline']})")
    for key, r in e["reverts"].items():
        print(f"    [{'FIRED' if r['fired'] else 'clear'}] {key} revert if {r['name']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="directory holding forward_test_log.csv / trades.csv / skipped_trades.csv")
    ap.add_argument("--era", default="structstop", choices=sorted(ERAS),
                    help="era used for the calibration join (default: structstop)")
    ap.add_argument("--json", action="store_true", help="dump the raw structures instead of the report")
    args = ap.parse_args(argv)

    if args.root:
        root = os.path.abspath(args.root)
        P.LOG_FILE_PATH = os.path.join(root, "forward_test_log.csv")
        P.TRADES_FILE_PATH = os.path.join(root, "trades.csv")
        P.SKIP_FILE_PATH = os.path.join(root, "skipped_trades.csv")

    log_rows = P.read_rows(P.LOG_FILE_PATH)
    trades = P.read_rows(P.TRADES_FILE_PATH)
    skip_rows = P.read_rows(P.SKIP_FILE_PATH)
    era_label, cutover = ERAS[args.era]
    started = cutover is not None
    data = P.build(log_rows=log_rows, trades=trades, skip_rows=skip_rows)
    cal = P.calibration(log_rows, trades, cutover if started else P.STRUCT_STOP_CUTOVER)

    if args.json:
        print(json.dumps({"context": data, "calibration": cal}, default=str, indent=2))
        return 0

    print(f"Market pressure report — {len(log_rows)} log bars, {len(trades)} closed trades "
          f"({P.LOG_FILE_PATH})")
    print("Display-only read: nothing printed here is an entry condition, and nothing here "
          "changes a rule.")

    hdr("1. TAPE")
    p = data["pressure"]
    if not p:
        print(f"  not enough history — needs {max(P.PRESSURE_WINDOW, P.EMA_SLOPE_LOOKBACK + 1) + 1} logged bars")
    else:
        print(f"  {p['label']}  ·  BUY {p['buy_pct']:.1f}%  /  SELL {p['sell_pct']:.1f}%"
              f"   (last {p['window']} closed bars, as of {p['as_of']})")
        for c in p["components"]:
            bar = "#" * int(round(c["buy_share"] * 20))
            print(f"    {c['label']:26s} {c['raw']:>8s} {c['unit']:28s} [{bar:<20s}] w {c['weight']:.2f}")

    hdr("2. SETUP READ (engine's gates on the last closed bar)")
    s = data["setup"]
    if not s.get("ok"):
        print(f"  unavailable — {s.get('reason')}")
    else:
        print(f"  bar {s['as_of']}  ·  close ${s['close']:.2f}  ATR {s['atr']:.2f}  RSI {s['rsi']:.1f}"
              f"  ·  floor ${s['floor']:.2f} / ceiling ${s['ceiling']:.2f}")
        if s.get("floor_mismatch"):
            print("  WARNING: recomputed floor != logged Dynamic_Floor — the level math needs a look")
        for side in ("BUY", "SELL"):
            g = s[side]
            print(f"  {side}: {g['passed']}/{g['total']} gates"
                  f"{'  -> SETUP READY' if g['ready'] else ''}"
                  f"   (level ${g['level']:.2f}, {g['level_dist_atr']:.2f} ATR away)")
            for gate in g["gates"]:
                mark = "n/a " if gate["inactive"] else ("PASS" if gate["ok"] else "FAIL")
                print(f"      [{mark}] {gate['name']:26s} {str(gate['value']):>12s}"
                      f"   vs {gate['threshold']}")

    hdr("3. LOCATION & RISK AT THIS BAR")
    loc = data["location"]
    if not loc:
        print("  unavailable")
    else:
        pos = loc["range_pos_pct"]
        print(f"  20-bar range ${loc['floor']:.2f} - ${loc['ceiling']:.2f}  ·  price ${loc['close']:.2f}"
              f"  ({'n/a' if pos is None else f'{pos:.0f}% of the range'})")
        print(f"  {loc['floor_desc']}  ·  {loc['ceiling_desc']}")
        for side in ("buy", "sell"):
            r = loc[side]
            print(f"  {side.upper():4s} entry ${loc['close']:.2f} -> stop ${loc['close'] - r['risk'] if side == 'buy' else loc['close'] + r['risk']:.2f}"
                  f"  TP ${loc['close'] + r['risk'] * P.RR_TARGET if side == 'buy' else loc['close'] - r['risk'] * P.RR_TARGET:.2f}"
                  f"  risk ${r['risk']:.2f}{' (level-bound)' if r['level_bound'] else ''}")

    hdr("4. PORTFOLIO STATE")
    pf = data["portfolio"]
    print(f"  blackout now: ", end="")
    blocked = [f"{sd} ({pf['sides_blocked'][sd]})" for sd in ("BUY", "SELL") if pf["sides_blocked"][sd]]
    print("; ".join(blocked) if blocked else "none — both sides open")
    if pf["next_window"]:
        label, sides, start = pf["next_window"]
        print(f"  next window: {label} at {start} UTC -> blocks {', '.join(sides)}")
    print(f"  SL cooldown: " + (f"{pf['cooldown_minutes_left']} min left ({pf['cooldown_note']})"
                               if pf["cooldown_minutes_left"] else "clear")
          + f"  ·  daily SLs {pf['daily_sls']}/{P.MAX_DAILY_LOSSES}"
          + ("  -> TREND-SIDE-ONLY" if pf["breaker_on"] else "")
          + f"  ·  60-min momentum side: {pf['momentum_side'] or '—'}")
    sk = data["skips"]
    if sk["total"]:
        print(f"  blocked setups, last {sk['hours']}h: {sk['total']} — "
              + ", ".join(f"{n} {c}" for n, c in sk["buckets"]))

    hdr("5. LIVE EXPERIMENT — structural stop vs its pre-registered bar")
    e = data["era"]
    if not e:
        print("  no trades in the era yet")
    else:
        _print_era_card(e)

    if args.era == "clear15" or data.get("era15") is not None:
        hdr("5b. REGISTERED NEXT WINDOW — structstop1.5 (docs/PREREG-2026-10-26-structstop1.5.md §5)")
        e15 = data.get("era15")
        if e15 is None:
            print("  NOT STARTED — no deploy time recorded (strategy_lab.CLEAR15_CUTOVER is None),")
            print("  so there is nothing to judge and no pre-deploy trade may be counted into it.")
            print("  The window opens at the host's `autosync: merge upstream` commit time of the A2 deploy.")
        else:
            _print_era_card(e15)
    if not started and args.era == "clear15":
        print("  (--era clear15: the §6 calibration join fell back to the live era because the new "
              "window has no trades; §5b says so explicitly.)")
    hdr("6. CALIBRATION — did the composite separate outcomes?")
    if not cal.get("ok"):
        print(f"  unavailable — {cal.get('reason')}")
    else:
        print(f"  {cal['era_label']}  ·  joined {cal['n']} trades to a pre-entry bar "
              f"(strictly before the entry minute)")
        print(f"  verdict: {cal['verdict']}")
        print(f"           {cal['reason']}")
        for side in ("BUY", "SELL"):
            w = cal["within_side"][side]
            if not w["n"]:
                continue
            print(f"  {side} — buy-pressure at entry spanned {w['min']:.0f}-{w['max']:.0f} "
                  f"(median {w['median']:.0f})")
            for name, b in cal["table"][side].items():
                wr = "  —  " if b["wr"] is None else f"{b['wr']:5.1f}%"
                rpt = "   —   " if b["r_per_trade"] is None else f"{b['r_per_trade']:+.3f}"
                print(f"      {name:8s} n={b['n']:3d}  decisive {b['dec']:3d}  dec WR {wr}"
                      f"  R/trade {rpt}")
            g = cal["gaps"][side]
            if g["wr_gap"] is not None:
                print(f"      aligned vs rest: WR gap {g['wr_gap']:+.1f} pp "
                      f"(aligned n={g['aligned_n']}, rest n={g['rest_n']}) — both buckets needed "
                      f"for this to mean anything")
        if cal["degenerate"]:
            print("\n  CONCLUSION: the gauge is a SIDE PROXY, not a signal. The trend gate makes")
            print("  'aligned' ~all of each side, so there is no within-side contrast to test.")
            print("  Use it to read the tape, never to size or veto a trade. Same trap as pooled")
            print("  momentum (docs/HANDOFF.md §8): always split by side.")
        else:
            print("\n  CONCLUSION: separation is " + ("worth re-testing (pre-register a bar first)."
                  if cal["verdict"].startswith("separation") else "not demonstrated."))
            print("  Either way: no gate may be added without a pre-registered bar (HANDOFF §11).")

    hdr("7. FEED & LOG HEALTH")
    fd = data["feed"]
    if not fd.get("ok"):
        print(f"  unavailable — {fd.get('reason')}")
    else:
        print(f"  last bar {fd['last_bar']} UTC  ·  {fd['bars_60m']} bars in the last 60 logged minutes"
              f"  ·  tail window {fd['rows']} rows")
        print(f"  open-market gaps >= 5 min in the window: {fd['gaps']}"
              + (f" (largest {fd['largest_gap_minutes']:.0f} open min)" if fd["gaps"] else "")
              + f"  ·  {fd['micro_gaps']} gap(s) of 2-5 min (minute jitter)")
        for g in fd.get("gap_detail", []):
            print(f"      {g['start']} -> {g['end']}   {g['open_minutes']:.0f} open min lost")
    rule()
    print("Refreshed by hand any time; the dashboard renders the same layer live.")
    print("See docs/ANALYSIS-2026-10-16-dashboard-pressure.md for the design + calibration record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
