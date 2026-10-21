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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pressure as P  # noqa: E402

GAP_MINUTES = 3.0          # a bar-to-bar gap longer than this splits the tape
FALSE_BREAK_MINUTES = 15   # "broke out but closed back in" window
DEFAULT_SPREAD = 0.55      # round trip, $/oz — the quote logger's median
DEFAULT_N = (20, 60)       # box lookbacks in 1-min bars
HORIZONS = {20: 60, 60: 120}   # forward walk per box size, minutes
ALERT_SCAN_DAYS = 7        # --alert-scan replays this many days (it is not free)
ALERT_SCAN_WINDOW = 1600   # trailing bars per replayed read (a prior day can sit ~1400 back)


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
def live_boxes(rows, cost):
    """Current boxes and where the last close sits in each, in $ and ATR.

    The geometry lives in pressure.box_geometry() so the dashboard panel and
    this report can never disagree about where a box is.
    """
    geom = P.box_geometry(rows, spread=cost)
    if not geom.get("ok"):
        return {}
    out = {"last_bar": geom["as_of"].strftime("%Y-%m-%d %H:%M"), "close": geom["close"],
           "atr": geom["atr"], "boxes": []}
    for b in geom["boxes"]:
        out["boxes"].append({
            "name": b["name"], "high": round(b["high"], 2), "low": round(b["low"], 2),
            "width_usd": round(b["width"], 2), "width_atr": round(b["width_atr"], 2),
            "position_pct": round(b["pos_pct"], 1) if b["pos_pct"] is not None else None,
            "dist_to_high_usd": round(b["dist_up_usd"], 2),
            "dist_to_low_usd": round(b["dist_down_usd"], 2),
            "dist_to_high_atr": round(b["dist_up_atr"], 2),
            "dist_to_low_atr": round(b["dist_down_atr"], 2),
            "buy_structural_risk_usd": round(b["buy"]["engine_risk"], 2) if b["buy"]["engine_risk"] else None,
            "buy_tp_usd": round(b["buy"]["engine_tp"], 2) if b["buy"]["engine_tp"] else None,
            "buy_cost_share_pct": (round(b["buy"]["cost_share_engine_pct"], 1)
                                   if b["buy"]["cost_share_engine_pct"] else None),
            "sell_structural_risk_usd": round(b["sell"]["engine_risk"], 2) if b["sell"]["engine_risk"] else None,
            "sell_tp_usd": round(b["sell"]["engine_tp"], 2) if b["sell"]["engine_tp"] else None,
            "sell_cost_share_pct": (round(b["sell"]["cost_share_engine_pct"], 1)
                                    if b["sell"]["cost_share_engine_pct"] else None),
        })
    return out


# ---------------------------------------------------- alert-volume replay
def _scan_rows(bars, lo, hi):
    """A trailing slice of the tape as the row dicts pressure.box_geometry wants."""
    return [{"Timestamp": b["ts"].strftime("%Y-%m-%d %H:%M:%S"), "Open": f"{b['o']:.2f}",
             "High": f"{b['h']:.2f}", "Low": f"{b['l']:.2f}", "Close": f"{b['c']:.2f}",
             "ATR": (f"{b['atr']:.2f}" if b["atr"] else "")} for b in bars[lo:hi + 1]]


def _fresh_break_indexes(bars, start, sizes=(20, 60, 240)):
    """Bars where a FRESH close-beyond exists for some box size.

    A replay of every bar is pointless: only a fresh break can ever turn the panel
    into a candidate, and `box_geometry` requires a close inside that box within
    BOX_FRESH_BARS bars for the crossing to count as an event. (A prior-day box
    trigger is not in this superset — it needs a full prior day of tape — so the
    count below is very slightly LOW on Mondays.)
    """
    out = set()
    for n in sizes:
        for i in range(n, len(bars)):
            bounds = box_at(bars, i, n, start)
            if bounds is None:
                continue
            hi, lo = bounds
            atr = bars[i]["atr"]
            if not atr or atr <= 0:
                continue
            c = bars[i]["c"]
            inside_hi = any(bars[i - k]["c"] <= hi for k in range(1, P.BOX_FRESH_BARS + 1))
            inside_lo = any(bars[i - k]["c"] >= lo for k in range(1, P.BOX_FRESH_BARS + 1))
            if (c >= hi + P.BOX_BREAK_ATR * atr and inside_hi) or \
               (c <= lo - P.BOX_BREAK_ATR * atr and inside_lo):
                out.add(i)
    return sorted(out)


def alert_scan(bars, cost, days=ALERT_SCAN_DAYS, window=ALERT_SCAN_WINDOW,
               cooldown_minutes=None, daily_cap=None, global_cooldown_minutes=None):
    """How many Telegram notices would today's rule have sent?

    Replays the LIVE decision (pressure.box_status -> pressure.box_alert) and the
    LIVE rate limiter (pressure.box_alert_suppressed / box_alert_record — the same
    pure functions tools/box_alert.py wraps) over the last `days` of tape, so the
    number printed here is the code the sidecar runs, not a re-implementation.

    Two honesty notes, printed with the result:
      * the portfolio state (SL cooldown, daily breaker) is not in the tape, so the
        replay assumes neither is active and the feed is fresh: this is an UPPER
        BOUND on real messages;
      * the count says nothing about profitability. The measured base rate is still
        0 of 8 geometries clearing the no-edge reference.
    """
    cooldown = cooldown_minutes or P.BOX_ALERT_COOLDOWN_MINUTES
    cap = daily_cap or P.BOX_ALERT_DAILY_CAP
    gap = global_cooldown_minutes or P.BOX_ALERT_GLOBAL_COOLDOWN_MINUTES
    cutoff = bars[-1]["ts"] - timedelta(days=days)
    start = run_offsets(bars)
    idx = [i for i in _fresh_break_indexes(bars, start) if bars[i]["ts"] >= cutoff]
    if not idx:
        return {"ok": False, "reason": "no fresh breaks in the window"}

    portfolio = {"cooldown_minutes_left": 0, "breaker_on": False}
    feed = {"ok": True, "age_seconds": 0}
    state = {"sent": {}, "day": None, "count": 0, "history": []}
    sent, blocked_cooldown, blocked_cap, blocked_gap, declined = [], 0, 0, 0, {}
    for i in idx:
        rows = _scan_rows(bars, max(0, i - window + 1), i)
        geom = P.box_geometry(rows, spread=cost)
        if not geom.get("ok"):
            continue
        status = P.box_status(geom, portfolio=portfolio, feed=feed, now=bars[i]["ts"],
                              spread=cost, regime=P.box_regime(rows))
        decision = status.get("alert") or {}
        if not decision.get("fire"):
            why = (decision.get("blockers") or ["no candidate"])[0].split(":")[0]
            declined[why] = declined.get(why, 0) + 1
            continue
        decision["cooldown_minutes"], decision["daily_cap"] = cooldown, cap
        decision["global_cooldown_minutes"] = gap
        why = P.box_alert_suppressed(decision, state, now=bars[i]["ts"])
        if why:
            if "daily cap" in why:
                blocked_cap += 1
            elif "minimum spacing" in why:
                blocked_gap += 1
            else:
                blocked_cooldown += 1
            continue
        P.box_alert_record(state, decision, now=bars[i]["ts"])
        sent.append({"ts": bars[i]["ts"], "side": decision["side"], "box": decision["box"],
                     "edge": round(decision["edge"], 2)})

    by_day = {}
    for s_ in sent:
        by_day.setdefault(s_["ts"].date(), 0)
        by_day[s_["ts"].date()] += 1
    span_days = (bars[-1]["ts"] - cutoff).total_seconds() / 86400.0
    per_day = sorted(by_day.values())
    return {
        "ok": True, "days": round(span_days, 1), "evaluated": len(idx),
        "sent": len(sent), "per_day": round(len(sent) / span_days, 1) if span_days else None,
        "median_per_day": per_day[len(per_day) // 2] if per_day else 0,
        "max_per_day": max(per_day) if per_day else 0,
        "days_with_alerts": len(by_day),
        "blocked_cooldown": blocked_cooldown, "blocked_daily_cap": blocked_cap,
        "blocked_global_spacing": blocked_gap,
        "declined": declined, "messages": sent,
        "by_side": {sd: sum(1 for m in sent if m["side"] == sd) for sd in ("BUY", "SELL")},
        "cooldown_minutes": cooldown, "daily_cap": cap, "global_cooldown_minutes": gap,
        "cost": cost,
    }


def report_regime(regime):
    """The chop + retest read the dashboard shows, printed — with its own verdict."""
    hdr("4b. IS THE TAPE CHOPPY RIGHT NOW? (measured, and measured NOT to predict)")
    chop, retest = regime.get("chop") or {}, regime.get("retest") or {}
    rule()
    if chop.get("ok"):
        print(f"  {chop['headline']}")
        print(f"    {chop['detail']}")
        eff = ("n/a" if chop.get("eff_60") is None else f"{chop['eff_60']:.2f}")
        eff2 = ("n/a" if chop.get("eff_240") is None else f"{chop['eff_240']:.2f}")
        print(f"    efficiency ratio (|net| / path): 60 bars {eff} · 240 bars {eff2}"
              "   (low = sideways, high = trending)")
        if chop.get("box_width_atr"):
            print(f"    20-bar box width now {chop['box_width_atr']:.1f} ATR vs its "
                  f"{chop['box_width_median_atr']:.1f} ATR median in view")
        m = chop["measured"]
        print(f"    MEASURED, and it does NOT separate outcomes: over {m['sequential_breaks']}")
        print(f"      sequential breaks, 'clean prior day' gave {m['prior_day_chop_clean_tf_pct']}%")
        print(f"      target-first vs a {m['prior_day_chop_clean_ref_pct']}% reference and 'choppy prior")
        print(f"      day' gave {m['prior_day_chop_choppy_tf_pct']}% vs {m['prior_day_chop_choppy_ref_pct']}% —")
        print("      the wrong way round, inside noise. Context, never a filter.")
    else:
        print(f"  chop read unavailable: {chop.get('reason')}")
    rule()
    if retest.get("state") in (None, "none"):
        print(f"  retest: {retest.get('detail', 'no retest read')}")
    else:
        print(f"  retest of the {retest.get('side')} break: {retest['state'].upper()}")
        print(f"    {retest['detail']}")
        print(f"    frozen box {retest['box_low']:.2f}-{retest['box_high']:.2f} "
              f"(broke at {retest['break_ts'].strftime('%m-%d %H:%M')} UTC)")
    m = retest.get("measured") or P.BOX_RETEST_MEASURED
    print(f"    MEASURED: {m['retested_within_30_bars_pct']:.0f}% of breaks are retested within 30 bars "
          f"(median {m['median_wait_bars']}); entering the HELD retest returned")
    print(f"      {m['entry_on_hold_tf_pct']}% vs a {m['entry_on_hold_ref_pct']}% reference — the same "
          f"${m['entry_on_hold_e_usd']}/trade as entering the break. Not a filter.")


def report_alert_scan(res):
    hdr(f"5. HOW LOUD IS THE TELEGRAM ALERT? (replay of the last {res['days']} days)")
    if not res.get("ok"):
        print(f"  {res.get('reason', 'no replay')}")
        return
    rule()
    print(f"  {res['evaluated']} fresh-break bars replayed · rule: fresh close beyond an edge, "
          f"every check green,")
    print(f"  spread ≤ {P.BOX_COST_SHARE_OK:.0f}% of R, no chase, ≥{res['global_cooldown_minutes']:.0f} min "
          f"between any two messages,")
    print(f"  1 per {res['cooldown_minutes']:.0f} min per box edge, {res['daily_cap']}/day cap")
    print(f"  → {res['sent']} messages = {res['per_day']}/day "
          f"(median {res['median_per_day']}, busiest day {res['max_per_day']}, "
          f"{res['days_with_alerts']} days with at least one)")
    print(f"  suppressed: {res['blocked_global_spacing']} by the {res['global_cooldown_minutes']:.0f}-min spacing, "
          f"{res['blocked_cooldown']} by the per-edge cooldown, "
          f"{res['blocked_daily_cap']} by the daily cap")
    print(f"  sides: BUY {res['by_side']['BUY']} · SELL {res['by_side']['SELL']}")
    if res["declined"]:
        top = sorted(res["declined"].items(), key=lambda kv: -kv[1])[:6]
        print("  declined because: " + " · ".join(f"{k} {v}" for k, v in top))
    print("  last few messages it would have sent:")
    for m in res["messages"][-6:]:
        print(f"    {m['ts'].strftime('%m-%d %H:%M')} UTC  {m['side']:4s} {m['box']} "
              f"edge {m['edge']:.2f}")
    print()
    print("  Read this number as NOISE CONTROL, not as quality: the portfolio gates")
    print("  (SL cooldown, daily breaker) are not in the tape, so the replay assumes")
    print("  neither is active and the feed is fresh — an UPPER bound. And a message")
    print(f"  count says nothing about expectancy: {P.BOX_MEASURED['cells']} box geometries")
    print(f"  were measured and {P.BOX_MEASURED['cleared']} cleared the no-edge reference.")


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
    ap.add_argument("--alert-scan", action="store_true",
                    help="replay the last --alert-days and print how many Telegram "
                         "notices the current rule would have sent (slow: ~30 s)")
    ap.add_argument("--alert-days", type=float, default=ALERT_SCAN_DAYS,
                    help=f"days of tape the --alert-scan replays (default {ALERT_SCAN_DAYS})")
    args = ap.parse_args(argv)

    rows = P.read_rows(os.path.join(args.root, "forward_test_log.csv"))
    bars = tape(rows)
    if not bars:
        print("no usable bars in forward_test_log.csv — nothing to report")
        return 0
    first = bars[0]["ts"].strftime("%Y-%m-%d %H:%M")
    last = bars[-1]["ts"].strftime("%Y-%m-%d %H:%M")

    live = live_boxes(rows, args.spread)
    scans = {n: scan(bars, n, HORIZONS[n], args.spread) for n in DEFAULT_N}
    regime = P.box_regime(rows)
    alerts = alert_scan(bars, args.spread, days=args.alert_days) if args.alert_scan else None

    if args.json:
        print(json.dumps({"cost_usd": args.spread, "bars": len(bars),
                          "first_bar": first, "last_bar": last,
                          "live": live, "scans": {str(k): v for k, v in scans.items()},
                          "regime": regime, "alert_scan": alerts},
                         indent=2, default=str))
        return 0
    report(live, scans, args.spread, len(bars), first, last)
    report_regime(regime)
    if alerts:
        report_alert_scan(alerts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
