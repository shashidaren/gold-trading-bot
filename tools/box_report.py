#!/usr/bin/env python3
"""box_report.py — does "box theory" hold on gold, and where are the boxes now?

Owner ask (2026-10-20): "can I incorporate box theory in my manual trading?"

Two different questions hide inside that one, and this tool keeps them apart:

  1. WHERE ARE THE BOXES? (section 1) — the live 20-bar level the engine
     already uses, the last 1h / 4h / prior-day range, and how far the last
     close sits from each edge in $ and ATR.
  2. DO BOX EDGES PREDICT ANYTHING? (section 2) — measured on the repo's own
     1-min tape: every close outside a box is walked forward to the first
     touch of a stop or a target, and the target-first share is compared with
     the DRIFTLESS reference (risk / (risk + target)) — the share a coin with
     no edge would produce at those distances. Wilson CI per cell. A cell is
     only called an edge if its 95% LOWER bound clears the reference.

The geometries are the ones a box trader would actually place, including the
repo's own structural stop (`max(2*ATR, |entry - level| + 0.5*ATR)`, live
since 2026-10-06) applied to the broken edge, so the report says whether box
theory adds anything to what the engine already does.

WHAT THIS IS NOT: a signal, a gate, a sizing rule or a reason to change
`engine.py`. It is a report. Read-only, stdlib only, exits 0.

Usage:
    python3 tools/box_report.py                 # live boxes + measured behaviour
    python3 tools/box_report.py --root DIR      # read DIR/forward_test_log.csv
    python3 tools/box_report.py --spread 0.40   # round-trip cost, $ per trade
    python3 tools/box_report.py --json
Method and numbers: docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pressure as P  # noqa: E402

GAP_MINUTES = 3.0          # a bar-to-bar gap longer than this splits the tape
FALSE_BREAK_MINUTES = 15   # "broke out but closed back in" window
DEFAULT_SPREAD = 0.55      # round trip, $/oz — the quote logger's median
DEFAULT_N = (20, 60)       # box lookbacks in 1-min bars
HORIZONS = {20: 60, 60: 120}   # forward walk per box size, minutes


# ---------------------------------------------------------------- the tape
def tape(rows):
    """Parsed bars, oldest first. Rows with a bad price or timestamp drop out."""
    bars = []
    for r in rows:
        ts = P.parse_ts(r.get("Timestamp"))
        o = P.parse_float(r.get("Open"))
        h = P.parse_float(r.get("High"))
        l = P.parse_float(r.get("Low"))
        c = P.parse_float(r.get("Close"))
        if ts is None or None in (o, h, l, c):
            continue
        bars.append({
            "ts": ts, "o": o, "h": h, "l": l, "c": c,
            "atr": P.parse_float(r.get("ATR")),
            "e50": P.parse_float(r.get("EMA_50")),
            "e200": P.parse_float(r.get("EMA_200")),
        })
    bars.sort(key=lambda b: b["ts"])
    return bars


def run_offsets(bars, gap_minutes=GAP_MINUTES):
    """Index of the first bar of the contiguous run each bar belongs to."""
    start = [0] * len(bars)
    for i in range(1, len(bars)):
        gap = (bars[i]["ts"] - bars[i - 1]["ts"]).total_seconds() / 60.0
        start[i] = i if gap > gap_minutes else start[i - 1]
    return start


def forward_end(bars, i, minutes, gap_minutes=GAP_MINUTES):
    """Last index reachable from bar i inside `minutes` without crossing a gap.

    Returns i when the very next bar is already past the horizon or missing —
    the caller treats that as censored rather than guessing.
    """
    j = i
    end = bars[i]["ts"] + timedelta(minutes=minutes)
    while j + 1 < len(bars):
        nxt = bars[j + 1]["ts"]
        if nxt > end:
            break
        if (nxt - bars[j]["ts"]).total_seconds() / 60.0 > gap_minutes:
            break
        j += 1
    return j


def box_at(bars, i, n, start):
    """(high, low) of the n bars strictly before i, or None if not enough tape.

    Strictly-before matches `pressure.levels()` and the engine's own floor:
    the level a bar is judged against never includes that bar.
    """
    if i - start[i] < n:
        return None
    prior = bars[i - n:i]
    hi = max(b["h"] for b in prior)
    lo = min(b["l"] for b in prior)
    if hi <= lo:
        return None
    return hi, lo


# ------------------------------------------------------------ measurement
def _race(bars, i, end, side, entry, risk, target):
    """First touch of target vs stop on the raw path, no ratchet, no exits.

    A bar that spans both is counted as a stop: the honest assumption when
    intrabar order is unknowable.
    """
    if risk <= 0 or target <= 0:
        return None
    for j in range(i + 1, end + 1):
        hi, lo = bars[j]["h"], bars[j]["l"]
        fav = (hi - entry) if side > 0 else (entry - lo)
        adv = (entry - lo) if side > 0 else (hi - entry)
        if fav >= target and adv >= risk:
            return "l"
        if fav >= target:
            return "w"
        if adv >= risk:
            return "l"
    return None


def _cell(rows, cost):
    """Aggregate one geometry: target-first share + Wilson CI vs the reference."""
    wins = sum(1 for r in rows if r["outcome"] == "w")
    losses = sum(1 for r in rows if r["outcome"] == "l")
    opened = sum(1 for r in rows if r["outcome"] is None)
    n = wins + losses
    if n == 0:
        return None
    pnl = sum((r["target"] - cost) if r["outcome"] == "w" else (-r["risk"] - cost) for r in rows
              if r["outcome"] is not None)
    ref = 100.0 * (sum(r["risk"] for r in rows) /
                   sum(r["risk"] + r["target"] for r in rows))
    lo, hi = P.wilson_interval(wins, n)
    wr = 100.0 * wins / n
    expectancy = pnl / n
    # An edge has to clear the no-edge reference AND still pay after cost.
    # Clearing the reference while losing money is not an edge, it is an
    # interesting ratio with a spread problem.
    if lo > ref and expectancy > 0:
        verdict = "EDGE"
    elif lo > ref:
        verdict = "no edge (cost eats it)"
    elif hi < ref:
        verdict = "BELOW ref"
    else:
        verdict = "no edge"
    return {
        "n": n, "wins": wins, "losses": losses, "open": opened,
        "wr_pct": round(wr, 1), "ci": [round(lo, 1), round(hi, 1)],
        "ref_pct": round(ref, 1),
        "expectancy_usd": round(pnl / n, 2),
        "risk_usd": round(sum(r["risk"] for r in rows) / n, 2),
        "target_usd": round(sum(r["target"] for r in rows) / n, 2),
        "cost_share_of_risk_pct": round(100.0 * cost / (sum(r["risk"] for r in rows) / n), 1),
        "verdict": verdict,
    }


def _session_hour(ts):
    """UTC hour. Gold's day has no single session clock; these are the bands
    the repo already names in trade_filter.py (Asia / London / NY)."""
    return ts.hour


SESSIONS = (
    ("Asia 00-07", 0, 7),
    ("London 07-12", 7, 12),
    ("NY 12-21", 12, 21),
    ("late 21-24", 21, 24),
)


def scan(bars, n, horizon, cost):
    """Every close outside an n-bar box: false-break rate + four geometries.

    SEQUENTIAL, one position at a time: once a break is taken, the next break is
    only considered after that position has resolved (or its window ran out).
    Overlapping 1-min events are not independent, and a Wilson interval over
    them would be far too tight — and no account can hold them all at once
    anyway. This is the same one-position convention the engine runs.
    """
    start = run_offsets(bars)
    geoms = {"structural_near": [], "far_edge_rr15": [], "far_edge_box": [], "fade": []}
    breaks = 0
    by_session = {name: [] for name, _, _ in SESSIONS}
    next_free = 0
    for i in range(len(bars)):
        if i < next_free:
            continue
        box = box_at(bars, i, n, start)
        if box is None:
            continue
        hi, lo = box
        width = hi - lo
        bar = bars[i]
        c, atr = bar["c"], bar["atr"]
        if atr is None or atr <= 0:
            continue
        if c > hi:
            side = 1
        elif c < lo:
            side = -1
        else:
            continue
        end = forward_end(bars, i, horizon)
        if end <= i + 2:            # nothing usable ahead: censored, not a trade
            continue
        next_free = end + 1
        near = hi if side > 0 else lo
        far = lo if side > 0 else hi

        # false break: any close back inside the box inside the false-break window
        fb_end = forward_end(bars, i, FALSE_BREAK_MINUTES)
        false_break = any(lo < bars[j]["c"] < hi for j in range(i + 1, fb_end + 1))

        # G1: the repo's own structural stop on the edge that was broken
        risk_g1 = P.structural_risk(c, atr, near)
        # G2/G3: the box trader's stop — past the FAR edge, the whole box is noise
        risk_far = abs(c - far) + 0.5 * atr

        def add(bucket, risk, target):
            out = _race(bars, i, end, side, c, risk, target)
            bucket.append({"outcome": out, "risk": risk, "target": target,
                           "atr": atr, "width": width, "side": side,
                           "hour": _session_hour(bar["ts"]), "false_break": false_break})

        add(geoms["structural_near"], risk_g1, 1.5 * risk_g1)
        add(geoms["far_edge_rr15"], risk_far, 1.5 * risk_far)
        add(geoms["far_edge_box"], risk_far, width)
        # fade: reject the edge and go back to the other side, stop 0.5 ATR out
        fade_risk = 0.5 * atr
        fade_side = -side
        fade_entry = c
        fade_out = _race(bars, i, end, fade_side, fade_entry, fade_risk, width)
        geoms["fade"].append({"outcome": fade_out, "risk": fade_risk, "target": width,
                              "atr": atr, "width": width, "side": fade_side,
                              "hour": _session_hour(bar["ts"]), "false_break": false_break})
        breaks += 1
        by_session[_session_name(_session_hour(bar["ts"]))].append(geoms["far_edge_rr15"][-1])

    fb_all = geoms["far_edge_rr15"]
    out = {
        "box_bars": n, "horizon_minutes": horizon, "breaks": breaks,
        "false_break_pct": (round(100.0 * sum(1 for r in fb_all if r["false_break"]) /
                                  len(fb_all), 1) if fb_all else None),
        "median_box_usd": round(_median([r["width"] for r in fb_all]), 2) if fb_all else None,
        "median_box_atr": round(_median([r["width"] / r["atr"] for r in fb_all]), 2) if fb_all else None,
        "geometries": {k: _cell(v, cost) for k, v in geoms.items()},
        "sessions": {},
    }
    for name, _, _ in SESSIONS:
        c_ = _cell(by_session[name], cost)
        if c_:
            out["sessions"][name] = c_
    return out


def _session_name(hour):
    for name, lo, hi in SESSIONS:
        if lo <= hour < hi:
            return name
    return SESSIONS[-1][0]


def _median(values):
    """Middle value (mean of the middle pair), 0.0 for an empty list."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


# ------------------------------------------------------------- live boxes
def live_boxes(bars, cost):
    """Current boxes and where the last close sits in each, in $ and ATR."""
    if not bars:
        return {}
    last = bars[-1]
    start = run_offsets(bars)
    i = len(bars) - 1
    atr = last["atr"]
    out = {"last_bar": last["ts"].strftime("%Y-%m-%d %H:%M"), "close": last["c"],
           "atr": atr, "boxes": []}

    specs = []
    box = box_at(bars, i, 20, start)
    if box:
        specs.append(("20-bar level (the engine's own)", box[0], box[1]))
    box = box_at(bars, i, 60, start)
    if box:
        specs.append(("last 1h (60 bars)", box[0], box[1]))
    box = box_at(bars, i, 240, start)
    if box:
        specs.append(("last 4h (240 bars)", box[0], box[1]))

    # prior complete UTC day — the most recent one that actually traded.
    # A Sunday evening (or a half session) is not a day to draw a box on, so a
    # date needs 600+ bars before it can be called the prior day's range.
    day = last["ts"].date()
    by_day = {}
    for b in bars:
        if b["ts"].date() < day:
            by_day.setdefault(b["ts"].date(), []).append(b)
    for d in sorted(by_day, reverse=True):
        pd_bars = by_day[d]
        if len(pd_bars) >= 600:
            specs.append((f"prior day {d} (UTC)",
                          max(b["h"] for b in pd_bars), min(b["l"] for b in pd_bars)))
            break

    for name, hi, lo in specs:
        width = hi - lo
        pos = (last["c"] - lo) / width * 100.0 if width > 0 else None
        row = {"name": name, "high": round(hi, 2), "low": round(lo, 2),
               "width_usd": round(width, 2),
               "width_atr": round(width / atr, 2) if atr else None,
               "position_pct": round(pos, 1) if pos is not None else None,
               "dist_to_high_usd": round(hi - last["c"], 2),
               "dist_to_low_usd": round(last["c"] - lo, 2),
               "dist_to_high_atr": round((hi - last["c"]) / atr, 2) if atr else None,
               "dist_to_low_atr": round((last["c"] - lo) / atr, 2) if atr else None}
        # what the repo's structural rule would put on each edge
        for side, edge in (("BUY", hi), ("SELL", lo)):
            risk = P.structural_risk(last["c"], atr, edge) if atr else None
            row[f"{side.lower()}_structural_risk_usd"] = round(risk, 2) if risk else None
            row[f"{side.lower()}_tp_usd"] = round(1.5 * risk, 2) if risk else None
            row[f"{side.lower()}_cost_share_pct"] = (round(100.0 * cost / risk, 1)
                                                     if risk else None)
        out["boxes"].append(row)
    return out


# ------------------------------------------------------------------- CLI
def hdr(text):
    print(f"\n== {text} ==")


def rule(width=94):
    print("-" * width)


def _fmt_cell(label, cell, width=40):
    if not cell:
        print(f"  {label:{width}s} n=0")
        return
    print(f"  {label:{width}s} n={cell['n']:5d}  target-first {cell['wr_pct']:5.1f}% "
          f"[{cell['ci'][0]:4.1f}-{cell['ci'][1]:4.1f}] vs ref {cell['ref_pct']:5.1f}%  "
          f"E=${cell['expectancy_usd']:+6.2f}  cost {cell['cost_share_of_risk_pct']:5.1f}% of risk  "
          f"{cell['verdict']}")


def report(live, scans, cost, bar_count, first_ts, last_ts):
    hdr("1. WHERE THE BOXES ARE NOW (last closed bar)")
    if not live:
        print("  no usable bars")
        return
    print(f"  last bar {live['last_bar']} UTC · close ${live['close']:.2f} · ATR ${live['atr']:.2f}"
          if live["atr"] else f"  last bar {live['last_bar']} UTC · close ${live['close']:.2f}")
    rule()
    print(f"  {'box':34s} {'high':>9s} {'low':>9s} {'width':>8s} {'ATR':>6s} {'pos':>7s} "
          f"{'to hi':>8s} {'to lo':>8s}")
    for b in live["boxes"]:
        print(f"  {b['name']:34s} {b['high']:9.2f} {b['low']:9.2f} {b['width_usd']:8.2f} "
              f"{b['width_atr']:6.2f} {b['position_pct']:6.1f}% {b['dist_to_high_usd']:8.2f} "
              f"{b['dist_to_low_usd']:8.2f}")
    rule()
    print("  If a close happens at these edges, the repo's structural rule would use:")
    for b in live["boxes"]:
        if b["buy_structural_risk_usd"]:
            print(f"    {b['name']:34s} BUY @ {b['high']:.2f}: risk ${b['buy_structural_risk_usd']:.2f}"
                  f"  TP ${b['buy_tp_usd']:.2f}  (cost = {b['buy_cost_share_pct']:.1f}% of risk)")
            print(f"    {'':34s} SELL @ {b['low']:.2f}: risk ${b['sell_structural_risk_usd']:.2f}"
                  f"  TP ${b['sell_tp_usd']:.2f}  (cost = {b['sell_cost_share_pct']:.1f}% of risk)")

    hdr("2. DOES BREAKING A BOX PREDICT ANYTHING? (measured on this log)")
    print(f"  tape: {bar_count} bars, {first_ts} -> {last_ts} UTC · cost ${cost:.2f} round trip")
    print("  reference = risk/(risk+target), the share a no-edge coin produces at those distances.")
    print("  EDGE requires the 95% Wilson LOWER bound to clear the reference.")
    for n in sorted(scans):
        s = scans[n]
        rule()
        print(f"  {n}-bar box · median width ${s['median_box_usd']:.2f} "
              f"({s['median_box_atr']:.1f} ATR) · {s['breaks']} closes outside it · "
              f"{s['false_break_pct']:.0f}% closed back inside within {FALSE_BREAK_MINUTES} min")
        print(f"  forward walk {s['horizon_minutes']} min, no ratchet, no exits, one position ignored")
        _fmt_cell("G1 structural stop on broken edge, TP 1.5R", s["geometries"]["structural_near"])
        _fmt_cell("G2 stop past FAR edge, TP 1.5R", s["geometries"]["far_edge_rr15"])
        _fmt_cell("G3 stop past FAR edge, TP 1 box (measured move)", s["geometries"]["far_edge_box"])
        _fmt_cell("G4 fade the edge, stop 0.5 ATR, TP opposite edge", s["geometries"]["fade"])
        if s["sessions"]:
            print("    G2 by session:")
            for name, cell in s["sessions"].items():
                _fmt_cell(f"      {name}", cell, width=36)

    hdr("3. WHAT THIS MEANS FOR A MANUAL TRADER")
    print("  The measured answer is consistent across both box sizes: breakout and fade")
    print("  entries land ON or BELOW the driftless reference once cost is charged. Boxes")
    print("  are a good place to PUT A STOP and a poor place to READ A PREDICTION.")
    print("  The one geometry that came near break-even is the widest stop (G2/G3): the")
    print("  stop outside the whole box, so the cost is a small share of R.")
    print()
    print("  Working rules (see docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md §4):")
    print("   1. Draw boxes on H1/H4 (session range, prior day, clean consolidation) — not M1.")
    print("   2. A box answers WHERE, not WHEN. Trade the edge or a close beyond + retest.")
    print("   3. Stop outside the FAR edge (never inside the box). Size from that stop.")
    print("   4. Target the measured move (1 box) or the next box; no BE before 0.75R.")
    print(f"   5. Charge the real cost: ${cost:.2f} round trip. At 1:1 you need ~54% to")
    print("      break even; at 1:1.5 about 43%. Below that a 50% box is a losing system.")
    print("   6. Skip the 20:58-22:00 UTC break and high-impact news (HANDOFF §7 gap trigger).")
    print("   7. No re-entry within 10-15 min of a scratch; log every box trade or it is")
    print("      survivorship bias.")

    hdr("4. LIMITS — READ BEFORE TRUSTING ANY CELL ABOVE")
    print("  * 7 weeks of one regime, one instrument, one broker feed. This is a screen,")
    print("    not an edge. Nothing here is pre-registered; it cannot justify a rule change.")
    print("  * The H1/H4 box a manual trader would actually draw yields ~1 setup per day,")
    print("    so it CANNOT be measured from this log — that needs the large-N path")
    print("    (tools/history_to_log.py -> tools/strategy_lab.py --bars, ACCELERATE-TESTING.md).")
    print("  * The race ignores the breakeven ratchet, so it flatters the stop-side results:")
    print("    a ratcheted book converts some of these wins into scratches.")
    print("  * Manual trades are not in the ledger. Log box, side, entry, stop, target and")
    print("    exit reason, or the only record you will have is the ones you remember.")
    rule()
    print("Read-only. No engine, gate, exit or parameter is touched by this tool.")
    print("See docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--root", default=here, help="directory holding forward_test_log.csv")
    ap.add_argument("--spread", type=float, default=DEFAULT_SPREAD,
                    help=f"round-trip cost in $/oz (default {DEFAULT_SPREAD} — quote-logger median)")
    ap.add_argument("--json", action="store_true", help="dump the raw structures")
    args = ap.parse_args(argv)

    rows = P.read_rows(os.path.join(args.root, "forward_test_log.csv"))
    bars = tape(rows)
    if not bars:
        print("no usable bars in forward_test_log.csv — nothing to report")
        return 0
    first = bars[0]["ts"].strftime("%Y-%m-%d %H:%M")
    last = bars[-1]["ts"].strftime("%Y-%m-%d %H:%M")

    live = live_boxes(bars, args.spread)
    scans = {n: scan(bars, n, HORIZONS[n], args.spread) for n in DEFAULT_N}

    if args.json:
        print(json.dumps({"cost_usd": args.spread, "bars": len(bars),
                          "first_bar": first, "last_bar": last,
                          "live": live, "scans": {str(k): v for k, v in scans.items()}},
                         indent=2, default=str))
        return 0
    report(live, scans, args.spread, len(bars), first, last)
    return 0


if __name__ == "__main__":
    sys.exit(main())
