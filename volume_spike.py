#!/usr/bin/env python3
"""volume_spike.py — does a 5m volume spike point at a *price level*? (read-only)

THE QUESTION THIS ANSWERS
    Owner ask (2026-11-28): "Step down from the 5-minute chart to the 1-minute
    chart to find the exact price level where volume surges. Check whether the
    spike sits near a recent intraday swing high or low (which is supposed to be
    ~80% of such spikes), and whether a channel-high/lo penetration triggered
    algorithmic order flow."

    Each of those three claims is testable on this repo's own tape, and none of
    them had been tested. This module tests them in that order:

      1. DETECT      -> a 5m bucket spikes when its tick volume beats the volume
                        that slot *normally* prints, not a trailing mean (see
                        MEASUREMENT TRAP below).
      2. STEP DOWN   -> inside the spiking 5m bucket, which of the five M1 bars
                        carries the surge, and does it hold the bar's extreme?
      3. LOCATE      -> is the spike near a confirmed past swing (pivot) high/low,
                        and how does that compare with an ordinary bucket?
      4. PENETRATE   -> did the spike bar newly break the 20-bar 5m channel, and
                        is volume actually elevated *on* penetration bars?

WHAT THIS IS NOT
    Not a signal, not a gate, not an entry condition, not a sizing input.
    Nothing here is imported by engine.py or trade_filter.py, nothing writes a
    file, and no number here may become a gate without a dated pre-registration
    (docs/HANDOFF.md §11). The measured verdict travels with every reading, and
    on this tape the verdict is *negative* — see VERDICT below and
    docs/ANALYSIS-2026-11-28-volume-spike-localisation.md.

MEASUREMENT TRAP (why the repo's own lab number is inflated)
    engine.py's `Vol_MA` is a plain 20-bar trailing mean. Gold's tick volume runs
    ~79/min in the late-session lull and ~367/min in the NY overlap — a 4.6x
    session swing. Measured on this log, an entry whose 5m volume is >=1.3x
    `Vol_MA` wins 41.1% vs 37.1% for normal volume (Δ+4.0pp, Fisher p=0.66,
    n=411 decisive): indistinguishable. The "spike >1.3x is the only p<0.05 in
    the lab" line (docs/INDICATOR-AUDIT-2026-10-23.md §2) is therefore most
    likely a session proxy, not a participation edge. `session_profile()` below
    is the honest baseline: each bucket is compared with the same weekday-class
    + hour + minute across the previous `BASELINE_LOOKBACK_DAYS` days, and both
    sides are divided by that day's median first, so a slow day is not called
    quiet everywhere.

VERDICT (measured 2026-11-28, log through 2026-11-27 19:39 UTC, 14,963
        complete 5m buckets over 69 days, 158 spikes at >=2.0x)
    1. The feed cannot localise a spike to one minute, let alone one price. The
       largest of the five M1 bars carries a median 23% of its bucket's volume
       (p90 27%) and never reaches 50% in any of the 158 spikes: the surge is
       spread across the whole five minutes.
    2. "~80% of spikes are near a swing" is a BASE RATE, not a signature. At the
       0.50-ATR tolerance 84.2% of spikes sit near a confirmed swing — but so do
       88.7% of ALL buckets. The lift is NEGATIVE at every tolerance tested
       (-0.1 / -4.5 / -5.0 / -5.0pp at 0.25/0.50/0.75/1.00 ATR) and under both
       distance definitions; spikes are marginally *less* swing-anchored than
       random bars, which is what you expect if the surge often CREATES the next
       pivot.
    3. Channel penetration is the only claim with real lift: 20.3% of spikes
       newly break the 20-bar 5m channel vs 8.4% of all buckets (+11.9pp). But
       the causal story does not hold — only 16.7% of penetration bars reach the
       p90 volume percentile vs 10.0% of ordinary bars (+6.7pp, n=1,255 vs
       13,708), and a 30-minute follow-through cannot separate
       penetration-with-spike from penetration-without (64.7% vs 61.7% close
       back inside, n=17 vs 776).

    Also measured, and the reason this module exists at all: the audit's naive
    basis (5m volume vs Vol_MA*5) puts the entry-time participation gap at
    41.1% vs 37.1% decisive WR on the era (Delta+4.0pp, Fisher p=0.66), and the
    whole effect is BUY/NY (BUY p=0.020, SELL p=0.743). The significance the
    audit reported came from pooling eras against a trailing mean that crosses a
    4.6x session swing.

Stdlib only, pure functions of the rows they are given, so they are cacheable
and testable without a clock or a live CSV.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds. Every one is pinned by tools/test_volume_spike.py and named in
# the analysis doc; none is a trading parameter.
# ─────────────────────────────────────────────────────────────────────────────
VOLUME_ERA_START = datetime(2026, 9, 10)
#: Before this instant forward_test_log.csv came from Twelve Data, whose
#: tick-count pipeline logged a near-constant ~29 ticks/min (docs/
#: history_to_log.py: the MT5 sidecar starts 2026-09-10). Mixing the two
#: vendors makes every ratio meaningless, so the era cut is mandatory.

M5_MINUTES = 5
BASELINE_LOOKBACK_DAYS = 14
BASELINE_MIN_OBS = 5
SPIKE_RATIO = 2.0

PIVOT_K = 2                  # a swing needs K higher-highs/lower-lows each side
SWING_WINDOW_BARS = 48       # 4 h of 5m bars = "recent intraday"
CHANNEL_LOOKBACK = 20        # mirrors engine.LOOKBACK_PERIOD
NEAR_SWING_ATR = 0.50
PENETRATION_MIN_ATR = 0.10   # a break smaller than this is not a penetration
HOLD_MINUTES = 30            # forward window for the follow-through test
POISSON_MIN_LAMBDA = 50      # below this the normal approximation is poor


# ── small helpers ───────────────────────────────────────────────────────────

def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ts(value):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except (TypeError, ValueError):
            continue
    return None


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def wilson(k, n, z=1.96):
    """95% Wilson interval on a proportion, as percentages. (None, None) on n=0."""
    if not n:
        return None, None
    p = k / n
    d = 1.0 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100.0 * max(0.0, mid - half), 100.0 * min(1.0, mid + half)


# ── rows -> M1 -> 5m ────────────────────────────────────────────────────────

def load_rows(path):
    """Forward-test log rows as dicts. [] on any problem (never raises).

    Deliberately duplicates pressure.read_rows' contract rather than importing
    it: this module is display-only and must stay importable on its own.
    """
    import csv
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def m1_bars(rows):
    """Rows -> closed M1 bars, sorted, de-duplicated by minute."""
    out = {}
    for row in rows or []:
        ts = _ts(row.get("Timestamp"))
        o, h, l, c = (_f(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        v = _f(row.get("Volume"))
        if None in (ts, o, h, l, c, v):
            continue
        ts = ts.replace(second=0, microsecond=0)
        # Vol_MA travels with the bar so the audit's naive basis can be
        # reproduced beside the seasonal one (see naive_ratio / the docstring).
        out[ts] = {"ts": ts, "o": o, "h": h, "l": l, "c": c, "v": v,
                   "volma": _f(row.get("Vol_MA"))}
    return [out[k] for k in sorted(out)]


def m5_buckets(bars, era_start=VOLUME_ERA_START):
    """M1 bars -> 5m buckets. A bucket is `complete` only when all 5 minutes are
    present, because a partial bucket's volume is not comparable with a full
    one and would fake a "thin" reading at every feed gap."""
    buckets = {}
    for b in bars:
        ts = b["ts"]
        if ts < era_start:
            continue
        start = ts.replace(minute=(ts.minute // M5_MINUTES) * M5_MINUTES,
                           second=0, microsecond=0)
        cur = buckets.get(start)
        if cur is None:
            buckets[start] = {"ts": start, "o": b["o"], "h": b["h"], "l": b["l"],
                              "c": b["c"], "v": b["v"], "m1": [b]}
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
            cur["v"] += b["v"]
            cur["m1"].append(b)
    out = []
    for key in sorted(buckets):
        bucket = buckets[key]
        bucket["minutes"] = len({b["ts"].minute for b in bucket["m1"]})
        bucket["complete"] = bucket["minutes"] == M5_MINUTES
        out.append(bucket)
    return out


# ── indicators on the 5m series ─────────────────────────────────────────────

def add_atr(series, n=CHANNEL_LOOKBACK):
    """Simple-mean ATR (`n`) over the 5m series — the same convention as the
    engine (simple, not Wilder). None until `n` true ranges exist."""
    trs = [None]
    for prev, cur in zip(series, series[1:]):
        trs.append(max(cur["h"] - cur["l"], abs(cur["h"] - prev["c"]),
                       abs(cur["l"] - prev["c"])))
    for i, bar in enumerate(series):
        window = [t for t in trs[max(0, i - n + 1):i + 1] if t is not None]
        bar["atr"] = statistics.mean(window) if len(window) >= n else None
    return series


def add_pivots(series, k=PIVOT_K):
    """Fractal swing flags. A flag is only *usable* once `k` later bars exist —
    `confirmed_end(i)` is the last index whose flags may be read at bar `i`,
    which is what keeps every "near a swing" test free of look-ahead."""
    for bar in series:
        bar["sh"] = bar["sl"] = False
    for i in range(k, len(series) - k):
        highs = [series[j]["h"] for j in range(i - k, i + k + 1)]
        lows = [series[j]["l"] for j in range(i - k, i + k + 1)]
        if series[i]["h"] == max(highs) and highs.count(series[i]["h"]) == 1:
            series[i]["sh"] = True
        if series[i]["l"] == min(lows) and lows.count(series[i]["l"]) == 1:
            series[i]["sl"] = True
    return series


def confirmed_end(i, k=PIVOT_K):
    """Last index whose pivot flag is knowable at bar `i`."""
    return i - k


def add_channel(series, lookback=CHANNEL_LOOKBACK):
    """The channel as it stood *before* bar i: the prior `lookback` bars define
    the level, so a break is measured against a level the market could see."""
    for i, bar in enumerate(series):
        if i < lookback + 1:
            bar["ch"] = bar["cl"] = bar["pch"] = bar["pcl"] = None
            continue
        bar["ch"] = max(b["h"] for b in series[i - lookback:i])
        bar["cl"] = min(b["l"] for b in series[i - lookback:i])
        bar["pch"] = max(b["h"] for b in series[i - lookback - 1:i - 1])
        bar["pcl"] = min(b["l"] for b in series[i - lookback - 1:i - 1])
    return series


# ── the baseline: what does THIS slot normally print? ───────────────────────

def _slot(ts):
    """Weekday-class + hour + minute. Weekends trade differently on gold, so the
    two classes are pooled separately rather than smeared together."""
    return "wk" if ts.weekday() < 5 else "we", ts.hour, ts.minute


def session_profile(series, lookback_days=BASELINE_LOOKBACK_DAYS,
                    min_obs=BASELINE_MIN_OBS):
    """Attach `expected` and `ratio` to every complete bucket.

    Both the observation and the historical samples are divided by their own
    day's median volume before being compared, so a genuinely slow day (thin
    liquidity, a holiday) is not reported as "quiet" in all 288 of its slots.
    History is strictly past-only: a bucket is never compared with itself or a
    later day.
    """
    by_slot = {}
    by_day = {}
    for bar in series:
        if not bar["complete"]:
            continue
        by_slot.setdefault(_slot(bar["ts"]), {})[bar["ts"].date()] = bar["v"]
        by_day.setdefault(bar["ts"].date(), []).append(bar["v"])
    day_median = {d: statistics.median(v) for d, v in by_day.items()}

    for bar in series:
        bar["expected"] = bar["ratio"] = bar["day_median"] = None
        if not bar["complete"]:
            continue
        today = bar["ts"].date()
        dm = day_median.get(today)
        if not dm:
            continue
        bar["day_median"] = dm
        past = {d: v for d, v in by_slot.get(_slot(bar["ts"]), {}).items()
                if 0 < (today - d).days <= lookback_days}
        if len(past) < min_obs:
            continue
        expected_norm = statistics.median(v / day_median[d] for d, v in past.items())
        if expected_norm <= 0:
            continue
        bar["expected"] = expected_norm * dm
        bar["ratio"] = (bar["v"] / dm) / expected_norm
    return series


def naive_ratio(bar):
    """The audit's own basis: bucket volume / (Vol_MA x 5). Kept so the two
    baselines can be compared in one table — see the module docstring."""
    volma = _f(bar["m1"][-1].get("volma")) if bar["m1"] else None
    if not volma:
        return None
    return bar["v"] / (volma * M5_MINUTES)


def hourly_profile(series, days=30):
    """Per-hour median tick volume and median seasonally-adjusted ratio.

    This is the table that explains the trap: if the ratio drifts with the hour,
    the raw volume reading is a clock, not a participant count.
    """
    cutoff = None
    if series:
        cutoff = series[-1]["ts"] - timedelta(days=days)
    rows = {}
    for bar in series:
        if not bar["complete"] or cutoff is None or bar["ts"] < cutoff:
            continue
        cell = rows.setdefault(bar["ts"].hour, {"vol": [], "ratio": []})
        cell["vol"].append(bar["v"])
        if bar["ratio"] is not None:
            cell["ratio"].append(bar["ratio"])
    return [{"hour": h, "n": len(rows.get(h, {}).get("vol", [])),
             "median_volume": _median(rows.get(h, {}).get("vol", [])),
             "median_ratio": _median(rows.get(h, {}).get("ratio", []))}
            for h in range(24)]


# ── the noise floor: what can a 1-minute step-down even resolve? ────────────

def noise_floor(series, min_lambda=POISSON_MIN_LAMBDA):
    """Observed vs Poisson within-bucket dispersion of the five M1 volumes.

    If within-window variation behaved like a constant arrival rate plus noise,
    observed sd ~= sqrt(lambda). Anything well above 1.0 means real sub-5m
    structure exists; the *share* held by the biggest minute then says whether
    that structure is localised (a burst) or diffuse (a busy five minutes).
    """
    observed, poisson, shares = [], [], []
    for bar in series:
        if not bar["complete"]:
            continue
        vols = [b["v"] for b in bar["m1"]]
        if len(vols) != M5_MINUTES:
            continue
        lam = sum(vols) / M5_MINUTES
        if lam < min_lambda:
            continue
        observed.append(statistics.pstdev(vols))
        poisson.append(math.sqrt(lam))
        shares.append(max(vols) / bar["v"])
    if not observed:
        return {"n": 0}
    ratio = statistics.mean(observed) / statistics.mean(poisson)
    shares.sort()
    return {
        "n": len(observed),
        "observed_sd": statistics.mean(observed),
        "poisson_sd": statistics.mean(poisson),
        "dispersion_ratio": ratio,
        "top_minute_share_median": shares[len(shares) // 2],
        "top_minute_share_p90": shares[min(len(shares) - 1, int(0.9 * len(shares)))],
        "top_minute_share_max": shares[-1],
        "localised": ratio > 1.2 and shares[len(shares) // 2] >= 0.50,
    }


# ── swings, channels, penetration ──────────────────────────────────────────

def swings_before(series, i, kind="sh", window=SWING_WINDOW_BARS, k=PIVOT_K):
    """Confirmed pivot prices in the `window` bars before `i`. Past-only: the
    last readable index is `confirmed_end(i)`."""
    end = confirmed_end(i, k)
    start = max(0, i - window)
    key = "h" if kind == "sh" else "l"
    return [series[j][key] for j in range(start, end + 1) if series[j][kind]]


def nearest_swing(series, i, window=SWING_WINDOW_BARS, k=PIVOT_K):
    """(distance, price, kind) to the closest confirmed swing, or None.

    Distance is measured from the swing PRICE to the bar's RANGE — zero if the
    bar traded through the level. That is the honest way to ask "did this surge
    print at the swing?": matching a swing high to the bar's low would call a
    bar "near" a high it never touched, and would inflate both the spike and the
    control rate without telling anyone anything.
    """
    bar = series[i]
    best = None
    for kind in ("sh", "sl"):
        for price in swings_before(series, i, kind, window, k):
            if bar["l"] <= price <= bar["h"]:
                dist = 0.0
            else:
                dist = min(abs(bar["h"] - price), abs(bar["l"] - price))
            if best is None or dist < best[0]:
                best = (dist, price, kind)
    return best


def penetration(series, i, min_atr=PENETRATION_MIN_ATR):
    """Did bar `i` *newly* break the channel it could already see?

    "Newly" matters: a bar that sits above a channel it broke ten bars ago is
    not a trigger, it is a trend. Returns None or a dict with the side, the
    level, and the depth in ATR.
    """
    if i < 2:
        return None
    bar, prev = series[i], series[i - 1]
    if bar["pch"] is None or bar["atr"] in (None, 0):
        return None
    floor = min_atr * bar["atr"]
    if bar["h"] > bar["pch"] and prev["h"] <= bar["pch"]:
        depth = bar["h"] - bar["pch"]
        if depth >= floor:
            return {"side": "UP", "level": bar["pch"], "depth": depth,
                    "depth_atr": depth / bar["atr"]}
    if bar["l"] < bar["pcl"] and prev["l"] >= bar["pcl"]:
        depth = bar["pcl"] - bar["l"]
        if depth >= floor:
            return {"side": "DOWN", "level": bar["pcl"], "depth": depth,
                    "depth_atr": depth / bar["atr"]}
    return None


def volume_on_penetration(series, min_atr=PENETRATION_MIN_ATR):
    """Volume percentile of penetration bars vs ordinary bars.

    This is the causality test, stated as cheaply as possible: if algorithmic
    flow is *triggered* by the break, the break bar should be the loud one. The
    ratio is the bar's volume over its trailing 100-bar median (no session
    correction needed here — it is a same-window comparison).
    """
    medians = []
    for i in range(len(series)):
        window = [b["v"] for b in series[max(0, i - 100):i + 1]]
        medians.append(statistics.median(window) if window else None)
    pen, normal = [], []
    for i, bar in enumerate(series):
        if not bar["complete"] or medians[i] in (None, 0):
            continue
        vr = bar["v"] / medians[i]
        (pen if penetration(series, i, min_atr) else normal).append((i, vr))
    pen_vr = sorted(v for _, v in pen)
    out = {"n_penetration": len(pen), "n_normal": len(normal),
           "median_penetration": _median(pen_vr),
           "median_normal": _median([v for _, v in normal])}
    for name, q in (("p90", 0.90), ("p95", 0.95)):
        if not normal:
            continue
        ordered = sorted(v for _, v in normal)
        threshold = ordered[min(len(ordered) - 1, int(q * len(ordered)))]
        hit = sum(1 for _, v in pen if v >= threshold)
        base = sum(1 for _, v in normal if v >= threshold)
        out[f"{name}_threshold"] = threshold
        out[f"{name}_pen_pct"] = 100.0 * hit / len(pen) if pen else 0.0
        out[f"{name}_normal_pct"] = 100.0 * base / len(normal) if normal else 0.0
        out[f"{name}_lift_pp"] = out[f"{name}_pen_pct"] - out[f"{name}_normal_pct"]
    return out


# ── the spike record ───────────────────────────────────────────────────────

def stepdown(series, i):
    """The 1-minute detail inside bucket `i`: which minute carried the volume,
    and did that minute print the bucket's extreme?"""
    bar = series[i]
    if not bar["m1"]:
        return {}
    top = max(bar["m1"], key=lambda b: b["v"])
    vols = [b["v"] for b in bar["m1"]]
    return {
        "top_minute": top["ts"],
        "top_minute_volume": top["v"],
        "top_minute_share": top["v"] / bar["v"] if bar["v"] else None,
        "top_minute_holds_high": top["h"] >= bar["h"] - 1e-9,
        "top_minute_holds_low": top["l"] <= bar["l"] + 1e-9,
        "minutes": [{"ts": b["ts"], "v": b["v"], "h": b["h"], "l": b["l"]}
                    for b in bar["m1"]],
        "sd": statistics.pstdev(vols) if len(vols) > 1 else 0.0,
    }


def forward(series, i, minutes=HOLD_MINUTES):
    """What the next `minutes` of 5m bars did, in ATR units, and whether price
    closed back inside the channel it broke (the fade test).

    `back_inside` is None when the bar did not break anything at all — not
    False. Coercing "no break" into "did not fade" would quietly pad the
    denominator of the fade rate with bars that had nothing to fade.
    """
    bar = series[i]
    if bar["atr"] in (None, 0):
        return None
    horizon = max(1, minutes // M5_MINUTES)
    future = series[i + 1:i + 1 + horizon]
    if len(future) < horizon:            # not enough tape to judge
        return None
    up = (max(b["h"] for b in future) - bar["c"]) / bar["atr"]
    down = (bar["c"] - min(b["l"] for b in future)) / bar["atr"]
    closes = [b["c"] for b in future]
    back_inside = None
    if bar.get("ch") is not None and bar["c"] > bar["ch"]:
        back_inside = any(c <= bar["ch"] for c in closes)
    elif bar.get("cl") is not None and bar["c"] < bar["cl"]:
        back_inside = any(c >= bar["cl"] for c in closes)
    return {"mfe_atr": max(up, down), "mae_atr": min(up, down),
            "up_atr": up, "down_atr": down, "back_inside": back_inside}


def classify(series, i, tolerance=NEAR_SWING_ATR, window=SWING_WINDOW_BARS):
    """Everything this module knows about one bucket, in one dict."""
    bar = series[i]
    atr = bar["atr"]
    swing = nearest_swing(series, i, window)
    record = {
        "ts": bar["ts"],
        "volume": bar["v"],
        "expected": bar["expected"],
        "ratio": bar["ratio"],
        "naive_ratio": naive_ratio(bar),
        "atr": atr,
        "range_atr": (bar["h"] - bar["l"]) / atr if atr else None,
        "swing": None,
        "penetration": penetration(series, i),
        "stepdown": stepdown(series, i),
        "forward": forward(series, i),
    }
    if swing is not None and atr:
        record["swing"] = {
            "distance": swing[0],
            "distance_atr": swing[0] / atr,
            "price": swing[1],
            "kind": swing[2],
            "near": (swing[0] / atr) <= tolerance,
        }
    return record


def find_spikes(series, threshold=SPIKE_RATIO):
    """Indices of complete buckets whose seasonally-adjusted volume >= threshold."""
    return [i for i, bar in enumerate(series)
            if bar["complete"] and bar["ratio"] is not None
            and bar["ratio"] >= threshold]


def base_rates(series, tolerance=NEAR_SWING_ATR, window=SWING_WINDOW_BARS):
    """The control the spike set must be compared against.

    Without this row the "~80% of spikes are near a swing" claim looks true: a
    swing every ~8 bars means most *ordinary* bars are near one too. The claim
    only means something as a lift over this base rate.
    """
    every = [classify(series, i, tolerance, window)
             for i in range(len(series)) if series[i]["complete"]]
    judged = [r for r in every if r["swing"] is not None]
    near = sum(1 for r in judged if r["swing"]["near"])
    pen = sum(1 for r in every if r["penetration"])
    return {
        "n": len(judged),
        "near_swing_pct": 100.0 * near / len(judged) if judged else None,
        "penetration_pct": 100.0 * pen / len(every) if every else None,
        "median_swing_distance_atr": _median([r["swing"]["distance_atr"]
                                              for r in judged]),
        "records": every,
    }


# ── the report ─────────────────────────────────────────────────────────────

def report(rows, threshold=SPIKE_RATIO, tolerance=NEAR_SWING_ATR,
           window=SWING_WINDOW_BARS, era_start=VOLUME_ERA_START):
    """The whole read. Pure: rows in, dict out, no clock, no writes."""
    bars = m1_bars(rows)
    series = m5_buckets(bars, era_start)
    add_atr(series)
    add_pivots(series)
    add_channel(series)
    session_profile(series)

    base = base_rates(series, tolerance, window)
    spike_idx = find_spikes(series, threshold)
    spikes = [classify(series, i, tolerance, window) for i in spike_idx]

    judged = [s for s in spikes if s["swing"] is not None]
    near = [s for s in judged if s["swing"]["near"]]
    pen = [s for s in spikes if s["penetration"]]
    with_fwd = [s for s in spikes if s["forward"] is not None]

    top_shares = [s["stepdown"].get("top_minute_share") for s in spikes
                  if s["stepdown"].get("top_minute_share") is not None]
    extreme_hits = 0
    extreme_total = 0
    for spike in pen:
        top = spike["stepdown"].get("top_minute_holds_high")
        low = spike["stepdown"].get("top_minute_holds_low")
        extreme_total += 1
        if spike["penetration"]["side"] == "UP":
            extreme_hits += 1 if top else 0
        else:
            extreme_hits += 1 if low else 0

    days = len({b["ts"].date() for b in series}) or 1
    summary = {
        "n_buckets": sum(1 for b in series if b["complete"]),
        "n_judged": len(base["records"]),
        "days": days,
        "threshold": threshold,
        "tolerance_atr": tolerance,
        "n_spikes": len(spikes),
        "spikes_per_day": len(spikes) / days,
        "spike_share_pct": (100.0 * len(spikes) / len(base["records"])
                            if base["records"] else None),
        "near_swing_pct": (100.0 * len(near) / len(judged)) if judged else None,
        "near_swing_base_pct": base["near_swing_pct"],
        "near_swing_lift_pp": (
            (100.0 * len(near) / len(judged)) - base["near_swing_pct"]
            if judged and base["near_swing_pct"] is not None else None),
        "median_swing_distance_atr": _median(
            [s["swing"]["distance_atr"] for s in judged]),
        "base_median_swing_distance_atr": base["median_swing_distance_atr"],
        "penetration_pct": (100.0 * len(pen) / len(spikes)) if spikes else None,
        "penetration_base_pct": base["penetration_pct"],
        "penetration_lift_pp": (
            (100.0 * len(pen) / len(spikes)) - base["penetration_pct"]
            if spikes and base["penetration_pct"] is not None else None),
        "penetration_up": sum(1 for s in pen if s["penetration"]["side"] == "UP"),
        "penetration_down": sum(1 for s in pen if s["penetration"]["side"] == "DOWN"),
        "penetration_median_depth_atr": _median(
            [s["penetration"]["depth_atr"] for s in pen]),
        "top_minute_share_median": _median(top_shares),
        "one_minute_over_50_pct": (100.0 * sum(1 for s in top_shares if s >= 0.5)
                                   / len(top_shares)) if top_shares else None,
        "extreme_in_top_minute_pct": (100.0 * extreme_hits / extreme_total
                                      if extreme_total else None),
        "penetration_extreme_n": extreme_total,
        "near_swing_wilson": wilson(len(near), len(judged)) if judged else (None, None),
        "n_with_forward": len(with_fwd),
    }

    # Follow-through, split by whether the penetration carried a spike. This is
    # the closest the module gets to the "did the break get algorithmic flow"
    # question, and the honest answer is that it cannot tell them apart.
    # Both sides use the same gate: the bar must have actually broken a channel
    # and have a full forward window, or it is not counted at all.
    follow = {}
    def _broke(s):
        f = s.get("forward")
        return bool(f) and f["back_inside"] is not None

    for label, pool in (
            ("penetration_with_spike", [s for s in pen if _broke(s)]),
            ("penetration_all", [s for s in classify_bucket_set(series, "penetration")
                                 if _broke(s)])):
        if not pool:
            follow[label] = {"n": 0}
            continue
        follow[label] = {
            "n": len(pool),
            "back_inside_pct": 100.0 * sum(1 for s in pool if s["forward"]["back_inside"]) / len(pool),
            "median_mfe_atr": _median([s["forward"]["mfe_atr"] for s in pool]),
            "median_mae_atr": _median([s["forward"]["mae_atr"] for s in pool]),
        }

    noise = noise_floor(series)
    vop = volume_on_penetration(series)
    out = {
        "meta": {
            "bars": len(bars),
            "buckets": len(series),
            "first_ts": bars[0]["ts"] if bars else None,
            "last_ts": bars[-1]["ts"] if bars else None,
            "era_start": era_start,
            "threshold": threshold,
            "tolerance_atr": tolerance,
            "window_bars": window,
        },
        "baseline_check": noise,
        "profile": hourly_profile(series),
        "summary": summary,
        "follow": follow,
        "volume_on_penetration": vop,
        "spikes": sorted(spikes, key=lambda s: -(s["ratio"] or 0)),
    }
    out["verdict"] = verdict(summary, follow, noise, vop)
    return out


def classify_bucket_set(series, kind):
    """Every bucket of one kind, classified. Used to build the full penetration
    set so the spike-penetration subset has a same-shape control."""
    out = []
    for i in range(len(series)):
        if not series[i]["complete"]:
            continue
        if kind == "penetration" and penetration(series, i):
            out.append(classify(series, i))
    return out


def verdict(summary, follow, noise, volume_on_penetration_=None):
    """The honest read, as sentences the CLI and the dashboard can both print.

    Written once, here, so a panel cannot quietly restate a number more
    favourably than the doc does.
    """
    lines = []
    if noise.get("n"):
        lines.append(
            f"Feed resolution: inside a 5m bucket the largest 1-minute bar carries a "
            f"median {100 * noise['top_minute_share_median']:.0f}% of the volume "
            f"(p90 {100 * noise['top_minute_share_p90']:.0f}%), and within-bucket "
            f"dispersion is {noise['dispersion_ratio']:.2f}x Poisson. "
            + ("A spike is a busy five minutes, not a one-minute burst — this tape "
               "cannot pin it to a single price print."
               if not noise["localised"] else
               "The surge is localised enough to support a 1-minute read."))

    lift = summary.get("near_swing_lift_pp")
    if lift is not None:
        lines.append(
            f"Swing proximity: {summary['near_swing_pct']:.1f}% of spikes are within "
            f"{summary['tolerance_atr']:.2f} ATR of a confirmed swing, but so are "
            f"{summary['near_swing_base_pct']:.1f}% of ALL buckets "
            f"(lift {lift:+.1f}pp). The headline '~80% near a swing' is the base "
            f"rate of standing near a swing, not a property of spikes.")

    pen_lift = summary.get("penetration_lift_pp")
    if pen_lift is not None and summary.get("n_spikes"):
        lines.append(
            f"Channel penetration: {summary['penetration_pct']:.1f}% of spikes newly "
            f"break the {CHANNEL_LOOKBACK}-bar channel vs "
            f"{summary['penetration_base_pct']:.1f}% of all buckets "
            f"(lift {pen_lift:+.1f}pp)."
            + (" That is the one real association found — but see causality below."
               if pen_lift >= 5 else
               " Not an association worth acting on at this sample."))

    vop = volume_on_penetration_ or {}
    if vop.get("n_penetration") and vop.get("p90_threshold") is not None:
        lift = vop["p90_lift_pp"]
        lines.append(
            f"Causality: a penetration bar reaches the 90th volume percentile "
            f"{vop['p90_pen_pct']:.1f}% of the time vs {vop['p90_normal_pct']:.1f}% "
            f"for an ordinary bar (lift {lift:+.1f}pp, n={vop['n_penetration']} vs "
            f"{vop['n_normal']}). "
            + ("The break and the surge travel together but neither leads, so "
               "'the break triggered algorithmic order flow' is not shown."
               if lift < 20 else
               "A break bar is clearly the loud one — worth a pre-registered test."))
    else:
        lines.append(
            "Causality: no penetration bars in this window, so the "
            "algorithmic-flow trigger claim is untested here (it needs the full "
            "live log — see docs/ANALYSIS-2026-11-28-volume-spike-localisation.md).")

    with_f = follow.get("penetration_with_spike", {})
    all_f = follow.get("penetration_all", {})
    if with_f.get("n") and all_f.get("n"):
        delta = with_f["back_inside_pct"] - all_f["back_inside_pct"]
        lines.append(
            f"Follow-through: {with_f['back_inside_pct']:.1f}% of spike-penetrations "
            f"closed back inside within {HOLD_MINUTES} min vs "
            f"{all_f['back_inside_pct']:.1f}% of all penetrations "
            f"(n={with_f['n']} vs {all_f['n']}, {delta:+.1f}pp). "
            + ("A volume spike does not change what the break does next."
               if abs(delta) < 10 else
               "The gap is large enough to be worth a registered test on a bigger sample."))

    # The closing verdict is DERIVED, never asserted: an edit that improves the
    # numbers must change the sentence the tool prints.
    edge = bool(
        (summary.get("near_swing_lift_pp") or 0) >= 10
        and (summary.get("n_spikes") or 0) >= 30
        and (noise.get("localised") or (vop.get("p90_lift_pp") or 0) >= 20)
    )
    if edge:
        lines.append(
            "Verdict: this tape shows a level-localisation association worth "
            "pre-registering — but still display-only until a dated bar and a "
            "large-N MT5 history dump (A9/E1) exist.")
    else:
        lines.append(
            "Verdict: no level-localisation edge on this feed. Keep volume as "
            "context (docs/INDICATOR-AUDIT-2026-10-23.md §4 Tier 1), display-only. "
            "Any gate would need a dated pre-registration and a large-N MT5 "
            "history dump (A9/E1).")
    return lines


def main(argv=None):
    """Thin CLI so the module is runnable without the tools/ wrapper."""
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--threshold", type=float, default=SPIKE_RATIO)
    ap.add_argument("--tolerance", type=float, default=NEAR_SWING_ATR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = load_rows(os.path.join(args.root, "forward_test_log.csv"))
    if not rows:
        print("volume_spike: no forward_test_log.csv under", args.root)
        return 2
    rep = report(rows, threshold=args.threshold, tolerance=args.tolerance)
    if args.json:
        print(json.dumps(rep, default=str, indent=2))
        return 0
    for line in rep["verdict"]:
        print("•", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
