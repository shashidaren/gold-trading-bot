#!/usr/bin/env python3
"""chart.py — display-only chart + placement read for the dashboard's Chart tab.

WHAT THIS IS
    The read layer behind the "🧭 Chart & Placement" tab. It answers the only
    question a beginner actually has:

      1. "What is the price doing?"            -> candles() / view()
      2. "Where would I put the entry, stop
          and target — and is that even
          worth taking?"                        -> plan_cards()
      3. "How much of my risk does the
          spread eat?"                          -> cost_ruler()

WHAT THIS IS NOT
    Not a signal, not a strategy input, not a forecast. Nothing here is imported
    by engine.py or trade_filter.py, nothing writes a file, and no number here is
    an entry condition. It is the same contract as pressure.py: display-only
    (docs/HANDOFF.md §1, docs/ANALYSIS-2026-10-16-dashboard-pressure.md).

WHY SO FEW INDICATORS
    This repo's own measurements say most "tools" do not survive contact with the
    tape: 8 box geometries across 2 sizes cleared the driftless reference 0 times
    (74-75% of breaks close back inside within 15 min), the 8/8 signal is ~50.4%
    trade-way at 30 min, and the pressure composite is collinear with side. What
    *does* survive is geometry — where the stop sits and what it costs. So the
    chart draws location, and the cost ruler carries the honest lesson. See
    docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md and
    docs/PROPOSAL-2026-10-23-manual-chart-tab.md.

    Deliberately absent: Fibonacci, pivots, round numbers (unmeasured), VWAP and
    volume profile (the feed carries MT5 *tick* volume, not traded volume — a
    VWAP built on it would be a guess in a formula), and trendlines/H&S/Elliott
    (subjective by construction). A tool is drawn only when it is deterministic
    or has been measured and its verdict travels with it.

Stdlib only. Pure functions of the rows they are given, so they are cacheable
and testable without a clock or a live CSV.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Constants — display only. The two costs are the repo's registered models:
# $0.40 round trip (HANDOFF §1) and $0.55 (the quote logger's measured median,
# docs/XM-LOGGER.md). Never invent a third.
# ─────────────────────────────────────────────────────────────────────────────
COST_USD_REGISTERED = 0.40
COST_USD_MEASURED = 0.55
# The advice rule from the box doc §4: a stop is worth taking only when the risk
# is at least 10x the round-trip cost, so spread stays under ~10% of R.
COST_MAX_SHARE_PCT = 10.0

GROUPS = (1, 5, 15)          # M1 / M5 / M15
DEFAULT_GROUP = 5
DEFAULT_LIMIT = 140

_SESSIONS = ((23, 24, "Asia"), (0, 7, "Asia"), (7, 12, "London"),
             (12, 21, "New York"), (21, 23, "Late"))

# Mirrors trade_filter.BLACKOUT_WINDOWS except the reverts; imported by value on
# purpose — Scenario U pins pressure.BLACKOUT_WINDOWS, so this copy is *cosmetic
# shading only* and is labelled as such in the template.
_BLACKOUTS = ((7 * 60 + 55, 9 * 60, "BUY"),              # London open, BUY only
              (12 * 60 + 25, 12 * 60 + 45, "BOTH"),       # NY pre-market
              (13 * 60 + 25, 15 * 60 + 15, "BOTH"),       # NY open / US data
              (21 * 60 + 45, 22 * 60 + 30, "BOTH"))       # rollover


# ── parsing ─────────────────────────────────────────────────────────────────

def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ts(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def bars(rows):
    """Normalise log rows into OHLC bars, sorted and de-duplicated by minute."""
    out = []
    for row in rows or []:
        ts = _ts(row.get("Timestamp"))
        o, h, l, c = (_f(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        if ts is None or None in (o, h, l, c):
            continue
        out.append({"ts": ts.replace(second=0, microsecond=0), "o": o, "h": h,
                    "l": l, "c": c, "atr": _f(row.get("ATR"))})
    dedup = {}
    for b in out:
        dedup[b["ts"]] = b
    return [dedup[k] for k in sorted(dedup)]


# ── aggregation ─────────────────────────────────────────────────────────────

def candles(series, group=DEFAULT_GROUP, limit=DEFAULT_LIMIT):
    """M1 bars -> N-minute candles, newest `limit` only.

    Bucketing is by wall-clock floor so a feed gap simply produces fewer
    candles; nothing is interpolated. The final bucket is flagged `partial`
    because it is still forming — a chart that hides that invites reading a
    moving candle as a closed one.
    """
    group = group if group in GROUPS else DEFAULT_GROUP
    buckets = {}
    for b in series:
        ts = b["ts"]
        start = ts.replace(minute=(ts.minute // group) * group, second=0, microsecond=0)
        cur = buckets.get(start)
        if cur is None:
            buckets[start] = {"ts": start, "o": b["o"], "h": b["h"], "l": b["l"],
                              "c": b["c"], "n": 1, "atr": b["atr"]}
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
            cur["n"] += 1
            if b["atr"] is not None:
                cur["atr"] = b["atr"]
    out = [buckets[k] for k in sorted(buckets)]
    if not out:
        return []
    last = out[-1]
    last["partial"] = last["n"] < group
    for b in out[:-1]:
        b["partial"] = False
    return out[-limit:] if limit else out


# ── levels ──────────────────────────────────────────────────────────────────

def levels_from_boxes(boxes, close):
    """Chart lines from pressure.box_geometry()['boxes'] — location, not signal.

    `kind` drives the styling: the engine's own 20-bar level is solid, the
    wider boxes are dashed, the prior day is dotted. A level that sits outside
    the plotted price range is returned with `offscreen` set so the template
    can pin a labelled arrow at the edge instead of silently dropping it —
    dropping it would hide the reason price stops where it does.
    """
    out = []
    for box in boxes or []:
        name = box.get("name") or "box"
        try:
            hi, lo = float(box["high"]), float(box["low"])
        except (KeyError, TypeError, ValueError):
            continue
        if "prior day" in name:
            kind, label = "day", name.replace("prior day ", "Prior day ")
            out.append({"label": f"{label} high", "price": hi, "kind": kind})
            out.append({"label": f"{label} low", "price": lo, "kind": kind})
        elif "20-bar" in name:
            out.append({"label": "Engine ceiling (20-bar)", "price": hi, "kind": "engine"})
            out.append({"label": "Engine floor (20-bar)", "price": lo, "kind": "engine"})
        else:
            short = name.replace("last ", "").replace(" (", " (").strip()
            out.append({"label": f"{short} high", "price": hi, "kind": "box"})
            out.append({"label": f"{short} low", "price": lo, "kind": "box"})
    # Two boxes often share an edge (the 20-bar ceiling is frequently also the
    # 1h high). Drawing both would print two labels on one line, so keep the
    # most important one and fold the other name into it.
    priority = {"engine": 0, "day": 1, "box": 2}
    out.sort(key=lambda x: priority.get(x["kind"], 3))
    seen, merged = {}, []
    for lv in out:
        key = round(lv["price"], 2)
        if key in seen:
            keep = seen[key]
            if lv["label"] not in keep["label"]:
                keep["label"] = f"{keep['label']} / {lv['label'].split(' ')[0]}"
            continue
        seen[key] = lv
        merged.append(lv)
    for lv in merged:
        lv["distance_usd"] = (lv["price"] - close) if close else None
        lv["distance_atr"] = None
    return merged


# ── the view (pixel space) ──────────────────────────────────────────────────

def _nice_step(span, target=6):
    if not span or span <= 0:
        return 1.0
    raw = span / float(target)
    exp = math.floor(math.log10(raw))
    base = raw / (10 ** exp)
    for cand in (1, 2, 2.5, 5, 10):
        if base <= cand:
            return cand * (10 ** exp)
    return 10 * (10 ** exp)


def _session_at(hour):
    for start, end, name in _SESSIONS:
        if start <= hour < end:
            return name
    return "Asia"


def _blackout_at(dt, group):
    """'both' / 'buy' / None for the minutes this candle covers.

    BUY-only windows are kept distinct from both-sides windows because telling a
    manual trader to stand aside from a short in the London open would be wrong.
    """
    start_min = dt.hour * 60 + dt.minute
    end_min = start_min + max(1, group)
    hits = set()
    for win_start, win_end, side in _BLACKOUTS:
        if start_min < win_end and end_min > win_start:
            hits.add(side.lower())
    if "both" in hits:
        return "both"
    return "buy" if "buy" in hits else None


def view(rows=None, boxes=None, group=DEFAULT_GROUP, limit=DEFAULT_LIMIT,
         width=980, height=380, series=None):
    """Everything the SVG needs, in pixel coordinates.

    Returns candles, level lines, session/BLACKOUT bands, price ticks and time
    labels. Pixel maths lives here rather than in the template so it can be
    tested without a browser — the template only draws what it is handed.
    """
    series = series if series is not None else bars(rows)
    cs = candles(series, group, limit)
    base = {"ok": False, "reason": "no bars yet", "width": width, "height": height}
    if len(cs) < 3:
        base["reason"] = "not enough bars for a chart (feed still warming up?)"
        return base

    pad = {"l": 8, "r": 86, "t": 14, "b": 26}
    plot_w = max(40.0, width - pad["l"] - pad["r"])
    plot_h = max(40.0, height - pad["t"] - pad["b"])

    lo = min(c["l"] for c in cs)
    hi = max(c["h"] for c in cs)
    span = hi - lo
    last_atr = next((c["atr"] for c in reversed(cs) if c.get("atr")), None)
    floor_span = max(span, (last_atr or 0) * 8.0, 1.0)
    pad_usd = floor_span * 0.08
    y_min, y_max = lo - pad_usd, hi + pad_usd
    if y_max - y_min <= 0:
        y_min, y_max = lo - 1, hi + 1

    def y(price):
        return pad["t"] + (y_max - price) / (y_max - y_min) * plot_h

    step = plot_w / float(len(cs))
    body_w = max(1.2, step * 0.62)

    out_candles = []
    for i, c in enumerate(cs):
        up = c["c"] >= c["o"]
        y_open, y_close = y(c["o"]), y(c["c"])
        out_candles.append({
            "x": round(pad["l"] + i * step, 2),
            "w": round(body_w, 2),
            "cx": round(pad["l"] + (i + 0.5) * step, 2),
            "bx": round(pad["l"] + i * step + (step - body_w) / 2.0, 2),
            "y_high": round(y(c["h"]), 2),
            "y_low": round(y(c["l"]), 2),
            "y_top": round(min(y_open, y_close), 2),
            "body_h": round(max(1.0, abs(y_close - y_open)), 2),
            "up": up,
            "partial": bool(c.get("partial")),
        })

    # levels: in-range lines, out-of-range edge markers
    lvls = []
    for lv in levels_from_boxes(boxes, cs[-1]["c"]):
        price = lv["price"]
        entry = {"label": lv["label"], "price": price, "kind": lv["kind"],
                 "in_range": y_min <= price <= y_max}
        if entry["in_range"]:
            entry["y"] = round(y(price), 2)
        else:
            entry["offscreen_above"] = price > y_max
        lvls.append(entry)

    # session + blackout bands, merged across contiguous candles
    bands = []
    prev_key = None
    for i, c in enumerate(cs):
        session = _session_at(c["ts"].hour)
        black = _blackout_at(c["ts"], group)
        key = (session, black)
        if bands and key == prev_key:
            bands[-1]["x1"] = round(pad["l"] + (i + 1) * step, 2)
        else:
            bands.append({"kind": "session", "session": session, "blackout": black,
                          "x0": round(pad["l"] + i * step, 2),
                          "x1": round(pad["l"] + (i + 1) * step, 2)})
        prev_key = key
    for b in bands:
        b["w"] = round(b["x1"] - b["x0"], 2)

    # price ticks
    step_usd = _nice_step(y_max - y_min, 6)
    ticks = []
    t = math.floor(y_min / step_usd) * step_usd
    guard = 0
    while t <= y_max + 1e-9 and guard < 40:
        if y_min <= t <= y_max:
            ticks.append({"price": round(t, 2), "y": round(y(t), 2),
                          "label": f"{t:,.2f}"})
        t += step_usd
        guard += 1

    # time labels (~6 across)
    times = []
    every = max(1, len(cs) // 6)
    for i in range(0, len(cs), every):
        times.append({"x": round(pad["l"] + (i + 0.5) * step, 2),
                      "label": cs[i]["ts"].strftime("%H:%M")})
    fmt = "%H:%M" if group < 60 else "%d %b"
    for t_ in times:
        t_["label"] = t_["label"] if group < 60 else t_["label"]

    return {
        "ok": True,
        "width": width, "height": height, "plot": dict(pad, w=plot_w, h=plot_h),
        "group": group, "limit": limit,
        "as_of": cs[-1]["ts"].strftime("%Y-%m-%d %H:%M"),
        "first_ts": cs[0]["ts"].strftime("%Y-%m-%d %H:%M"),
        "last_ts": cs[-1]["ts"].strftime("%Y-%m-%d %H:%M"),
        "close": cs[-1]["c"], "atr": last_atr,
        "y_min": round(y_min, 2), "y_max": round(y_max, 2),
        "close_y": round(y(cs[-1]["c"]), 2),
        "candles": out_candles, "levels": lvls, "bands": bands,
        "ticks": ticks, "times": times,
        "n_candles": len(cs), "fmt": fmt,
    }


# ── cost ruler ──────────────────────────────────────────────────────────────

def cost_ruler(atr, mults=(1.0, 1.5, 2.0, 2.5, 3.0, 4.0),
               costs=(COST_USD_REGISTERED, COST_USD_MEASURED)):
    """Spread as a share of R for a stop of N x ATR. Arithmetic, not opinion.

    This is the panel's most useful idea: at a 1-ATR stop on a quiet tape the
    spread alone is a third of the risk, before the market does anything. That
    is why tight manual gold scalps lose even when the direction is right.
    """
    atr = _f(atr)
    out = {"ok": bool(atr and atr > 0), "atr": atr, "rows": [],
           "min_mult": {}, "max_share": COST_MAX_SHARE_PCT}
    if not out["ok"]:
        return out
    for cost in costs:
        need = (100.0 * cost / COST_MAX_SHARE_PCT) / atr
        out["min_mult"][f"{cost:.2f}"] = need
    for m in mults:
        risk = m * atr
        row = {"mult": m, "risk_usd": risk,
               "share": {f"{c:.2f}": (100.0 * c / risk) for c in costs}}
        row["share_pct"] = row["share"][f"{max(costs):.2f}"]
        row["zone"] = ("red" if row["share_pct"] > 20 else
                       "amber" if row["share_pct"] > COST_MAX_SHARE_PCT else "green")
        out["rows"].append(row)
    return out


# ── placement cards, in plain English ───────────────────────────────────────

def pick_box(boxes, close, atr, max_width_atr=20.0):
    """Choose the box a *stop* can actually be built on.

    The nearest edge is not always the usable one: on this tape the prior-day
    box is routinely 70+ ATR wide, so a stop outside its far edge sits $100+
    away — a swing trade wearing a scalp's clothes. So among boxes narrow enough
    to place a stop on, take the one whose edge price is closest to, and report
    what was skipped so the card can say why rather than silently lying.

    Returns (box, note) where note is None or a plain-English sentence.
    """
    if not boxes:
        return None, "no boxes on this tape yet"
    def edge_atr(b):
        return min(abs(b.get("dist_up_atr") or 0), abs(b.get("dist_down_atr") or 0))

    usable = [b for b in boxes
              if atr and b.get("width_atr") is not None and b["width_atr"] <= max_width_atr]
    skipped = [b for b in boxes if b not in usable]
    pool = usable or sorted(boxes, key=lambda b: b.get("width_atr") or 1e9)[:1]
    chosen = min(pool, key=edge_atr)
    note = None
    # Only explain the refusal when the refused box is the one the eye would
    # have gone to first — i.e. its edge is closer than the chosen box's.
    if skipped and usable:
        nearest_skipped = min(skipped, key=edge_atr)
        if edge_atr(nearest_skipped) < edge_atr(chosen):
            note = (f"{nearest_skipped['name']} is {nearest_skipped['width_atr']:.0f} ATR wide — a stop "
                    f"outside it would be ${nearest_skipped['width']:.0f} away. That is a swing trade, "
                    f"not a scalp, so the card below uses the tighter box instead.")
    return chosen, note


def _side_filter(reasons, side):
    """Drop a blackout reason that names the *other* side.

    pressure.box_watch_cards collects any failing check, including a London
    blackout that blocks BUYs only; printing that on the SELL card would tell a
    manual trader to stand aside from a short for no reason.
    """
    other = "SELL" if side == "BUY" else "BUY"
    return [r for r in reasons if not (f"blocks {other}" in r and f"blocks {side}" not in r)]


def plan_cards(watch_cards, atr=None, cost=COST_USD_MEASURED):
    """Translate pressure.box_watch_cards() into three numbers and a verdict.

    The card exists to answer "where do I put it", so it always prints entry,
    stop and target even when the verdict is *no trade* — a beginner needs to
    see the geometry that failed, not just a red light. `verdict` is
    skip / watch / take-shaped, and `reasons` is never empty when it is `skip`.
    """
    out = []
    for card in watch_cards or []:
        side = card.get("side")
        entry, stop, target = card.get("entry"), card.get("stop"), card.get("target")
        risk = card.get("risk") or 0.0
        reward = card.get("reward") or 0.0
        rr = card.get("net_rr")
        share = (100.0 * cost / risk) if risk else None
        reasons = _side_filter(list(card.get("reasons") or []), side)
        if rr is not None and rr < 1.0:
            reasons.append(f"the target is only {rr:.2f}R away — you would be risking more "
                           f"than you can win")
        if share is not None and share > COST_MAX_SHARE_PCT:
            reasons.append(f"the spread is {share:.0f}% of your risk (over "
                           f"{COST_MAX_SHARE_PCT:.0f}% is not worth it)")
        if card.get("chasing"):
            reasons.append("price is already more than 1 ATR past the edge — this is chasing")
        verdict = "skip" if reasons else ("watch" if not card.get("confirmed") else "ready")
        stop_side = "below" if side == "BUY" else "above"
        out.append({
            "side": side,
            "tone": "buy" if side == "BUY" else "sell",
            "headline": (f"{side} only if price closes {'above' if side == 'BUY' else 'below'} "
                         f"${card.get('threshold', 0):,.2f}"),
            "entry": entry, "stop": stop, "target": target,
            "risk_usd": risk, "reward_usd": reward,
            "rr": rr, "gross_rr": card.get("gross_rr"),
            "cost_pct": share, "cost_usd": cost,
            "box": card.get("box"), "state": card.get("state"),
            "verdict": verdict,
            "verdict_text": {"skip": "SKIP", "watch": "WATCH", "ready": "SETUP — still context only"}[verdict],
            "reasons": reasons,
            "stop_sentence": (f"Put the stop at ${stop:,.2f} — that is {stop_side} the whole box, "
                              f"so an ordinary wick back inside cannot reach it."
                              if stop is not None else ""),
            "target_sentence": (f"Target ${target:,.2f} = one box width from entry. "
                                f"Take it off before the next box." if target is not None else ""),
        })
    return out


# ── one-line plain verdict ──────────────────────────────────────────────────

def plain_verdict(box_status, feed=None):
    """Turn the box checklist into one sentence a beginner can act on.

    Never says buy or sell. It says whether the *conditions* exist, and which
    one is missing — the same discipline as the Boxes tab, in fewer words.
    """
    out = {"ok": False, "headline": "No read yet", "detail": "",
           "tone": "neutral", "missing": []}
    if not box_status or not box_status.get("ok"):
        out["detail"] = (box_status or {}).get("reason") or "the box read is unavailable"
        return out
    checks = box_status.get("checks") or []
    failing = [c for c in checks if c.get("state") != "pass"]
    out["ok"] = True
    out["missing"] = [c.get("label") or c.get("key") for c in failing]
    verdict = box_status.get("verdict") or {}
    tone = verdict.get("tone") or "neutral"
    out["tone"] = {"ok": "ok", "warn": "warn", "block": "block"}.get(tone, "neutral")
    out["headline"] = verdict.get("headline") or "Conditions do not line up"
    if failing:
        named = ", ".join(out["missing"][:3]).lower()
        out["detail"] = (f"{len(failing)} of {len(checks)} conditions are not met "
                         f"({named}). Wait — do not force a trade.")
    else:
        out["detail"] = ("All the conditions line up, but that is context, not a forecast: "
                         "the measured base rate for these is near a coin flip.")
    return out


# ── how to read it (static teaching text, kept next to the code it explains) ─

HOW_TO_READ = (
    ("The candles", "Each bar is 5 minutes of price. Green = closed higher than it opened, "
                    "red = lower. The thin line is the full range; the fat part is where it "
                    "opened and closed."),
    ("The lines", "These are the box edges. Solid = the bot's own 20-bar level (its stop sits "
                  "outside this). Dashed = the last hour and 4 hours. Dotted = yesterday's "
                  "high and low. Boxes tell you WHERE, never WHEN."),
    ("The shaded hours", "Asia / London / New York. Grey blocks are windows where the bot "
                         "stands aside (news and rollover). The London block only blocks buys."),
    ("Entry, stop, target", "Entry is a close beyond the line plus a small buffer. The stop goes "
                            "outside the FAR side of the box, never inside it. The target is one "
                            "box width. If the target is closer than the stop, there is no trade."),
    ("The cost ruler", "The spread is charged on every trade, win or lose. Long stops make it "
                       "small; short stops make it huge. That is the whole reason most tight "
                       "gold scalps lose."),
    ("What is deliberately not here", "No Fibonacci, pivots, round numbers, VWAP, volume profile, "
                                      "trendlines, Ichimoku or MACD. The first three are unmeasured "
                                      "on this tape, VWAP and volume profile need real traded "
                                      "volume (this feed carries tick volume), and the rest are "
                                      "subjective — two people draw different lines. A tool earns "
                                      "a place here only if it is deterministic or measured."),
)
