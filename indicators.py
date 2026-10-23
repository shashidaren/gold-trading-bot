#!/usr/bin/env python3
"""indicators.py — candidate indicators the engine does NOT use, computed honestly.

WHY THIS FILE EXISTS
    Owner ask (2026-10-23): "need help with the indicators — if there's any more
    that we can add to further improve". This repo's rule is that an indicator is
    not added because it is popular; it is added because its *measured* verdict
    travelled with it (docs/PROPOSAL-2026-10-23-manual-chart-tab.md). So this
    module ships the arithmetic only, with no opinion attached:

      * deterministic, stdlib-only, causal (value at bar i uses bars <= i);
      * every series is the textbook definition, named in DESCRIPTIONS;
      * what it is worth is decided by `journal.indicator_board()` on the bot's
        own entries, and by `tools/indicator_lab.py` on the whole tape.

    The engine's live indicators (EMA50/200, RSI 30-68/32-70, ATR 1.10-4.50,
    wick rejection, the 20-bar level) are deliberately NOT reimplemented here:
    their logged columns are the source of truth. This file only adds the
    candidates that would be *new* information:

      ADX / DMI          trend STRENGTH (the engine only knows EMA direction)
      MACD               momentum, EMA-difference histogram
      Bollinger %B/BW    extension inside 2-sigma bands, squeeze
      Stochastic %K/%D   short-cycle position
      Keltner position   close vs EMA20 in ATR units (a second band, ATR-scaled)
      Donchian position  where close sits in the 20-bar range (the box, as a number)
      Efficiency ratio   how much of the travel was net progress (chop read)
      ATR percentile     volatility regime vs its own recent history
      RVOL               volume vs its 20-bar mean — MT5 *tick* volume, caveat below
      RSI slope          is the logged RSI rising or falling
      body / close-loc   one-bar candle anatomy
      gap                open vs prior close, in ATR

    NOT included, on purpose:
      * VWAP / volume profile — the feed carries MT5 tick volume, not traded
        volume; those formulas would be a guess with a decimal point.
      * Fibonacci, pivots, round numbers — unmeasured levels; see the proposal.
      * RSI divergence / trendlines / waves — the swing definition is subjective;
        two people get two answers, so it cannot be pre-registered.
      * Ichimoku / Supertrend / Hull — more moving averages on the same closes;
        they would be tested as MACD-like momentum, not as new information.

CAUSALITY
    `build()` returns lists aligned to the input rows. Nothing at index i looks
    at i+1..; `at()` is the only accessor the journal uses, and it reads one
    index. The test suite appends future bars and asserts the past snapshot is
    byte-identical.

Stdlib only. Pure functions, no file I/O, no clock, no imports from engine.py.
"""
from __future__ import annotations

import math
from collections import deque

# ─────────────────────────────────────────────────────────────────────────────
# descriptions — one source of truth for the CLI, the dashboard and the docs
# ─────────────────────────────────────────────────────────────────────────────

DESCRIPTIONS = {
    "adx": {
        "label": "ADX (14) trend strength",
        "unit": "",
        "what": "Wilder's ADX with +DI/-DI. High = the tape is trending, low = chop.",
        "why": "The engine gates direction with EMA50/200 but has no strength read: "
               "it cannot tell a strong trend from two flat EMAs crossing.",
    },
    "plus_di": {
        "label": "+DI (14) up-pressure",
        "unit": "",
        "what": "Wilder's positive directional indicator, 0-100.",
        "why": "The raw strength of upward directional movement, before it is "
               "turned into ADX's directionless number.",
    },
    "minus_di": {
        "label": "-DI (14) down-pressure",
        "unit": "",
        "what": "Wilder's negative directional indicator, 0-100.",
        "why": "The mirror read; +DI vs -DI is what gives ADX a side.",
    },
    "di_side": {
        "label": "+DI vs -DI",
        "unit": "",
        "what": "Which directional index is larger when ADX is meaningful.",
        "why": "Turns ADX into a side, so its strength can be tested as a filter.",
    },
    "macd_hist": {
        "label": "MACD histogram (12/26/9)",
        "unit": "",
        "what": "MACD line minus its signal line, in $/oz.",
        "why": "A second, slower momentum view than the 20-bar level and RSI.",
    },
    "bb_pct_b": {
        "label": "Bollinger %B (20, 2σ)",
        "unit": "",
        "what": "Where close sits between the lower (0) and upper (1) band.",
        "why": "The engine has no volatility band; %B says whether a rejection "
               "happened at an extreme or in the middle of the range.",
    },
    "bb_bandwidth": {
        "label": "Bollinger bandwidth",
        "unit": "%",
        "what": "(upper - lower) / middle, as a % of price. A squeeze read.",
        "why": "Volatility compression/expansion is invisible to the fixed ATR bounds.",
    },
    "stoch_k": {
        "label": "Stochastic %K (14)",
        "unit": "",
        "what": "Close's position in the 14-bar high-low range, 0-100.",
        "why": "A shorter-cycle overbought/oversold read than RSI(14).",
    },
    "stoch_d": {
        "label": "Stochastic %D (3)",
        "unit": "",
        "what": "3-bar SMA of %K (the signal line).",
        "why": "%K vs %D is the cross a stochastic trader actually reads.",
    },
    "keltner_pos": {
        "label": "Keltner position (EMA20 ± 2 ATR)",
        "unit": "ATR",
        "what": "(close - EMA20) / ATR(14). 0 = at the mid-band.",
        "why": "An ATR-scaled band, unlike Bollinger's price-scaled one. On gold "
               "the two disagree exactly when volatility is changing.",
    },
    "donchian_pos": {
        "label": "20-bar range position",
        "unit": "",
        "what": "0 at the 20-bar low, 1 at the 20-bar high (the engine's own box).",
        "why": "The box as one number. Mostly collinear with the level gate — "
               "kept to measure that, not to assume it.",
    },
    "er30": {
        "label": "Efficiency ratio (30)",
        "unit": "",
        "what": "|net move| / sum(|bar-to-bar moves|) over 30 bars. 1 = straight line, 0 = chop.",
        "why": "A deterministic chop read. The 2026-10-21 work found chop is normal, "
               "but never turned it into a number the engine could see.",
    },
    "atr_pct": {
        "label": "ATR percentile (200)",
        "unit": "%",
        "what": "Percentile of the current ATR in its last 200 bars.",
        "why": "ATR 1.10-4.50 are fixed dollar bounds; a percentile is regime-relative.",
    },
    "rvol": {
        "label": "RVOL (20)",
        "unit": "×",
        "what": "Bar volume / mean volume of the last 20 bars.",
        "why": "The engine's volume gate is off. This measures whether tick "
               "activity adds anything — CAVEAT: MT5 'Volume' here is tick count, "
               "not traded contracts, so it is participation, not size.",
    },
    "rsi_slope": {
        "label": "RSI slope (5 bars)",
        "unit": "",
        "what": "Logged RSI now minus RSI 5 bars ago.",
        "why": "The engine gates the RSI level but not its direction.",
    },
    "body_atr": {
        "label": "Candle body",
        "unit": "ATR",
        "what": "(close - open) / ATR.",
        "why": "One-bar conviction. The engine reads wicks, not bodies.",
    },
    "close_loc": {
        "label": "Close location in bar",
        "unit": "",
        "what": "(close - low) / (high - low), 0..1.",
        "why": "Whether buyers or sellers owned the last bar, independent of its size.",
    },
    "gap_atr": {
        "label": "Gap from prior close",
        "unit": "ATR",
        "what": "(open - prior close) / ATR.",
        "why": "A discontinuity the 20-bar level and EMA cannot express.",
    },
}

# split rules used by the measurement layer. Every one is fixed in advance:
# a median split is computed once from the sample, the rest are the textbook
# lines (0 for a sign, 0.5 for a band midpoint, 20 for \"trending\" ADX, ...).
# `None` means "Median of this sample". This is what keeps the lab from tuning
# a threshold after seeing the outcomes.
SPLITS = {
    "adx": 20.0,
    "di_side": None,          # categorical: BUY vs SELL
    "macd_hist": 0.0,
    "bb_pct_b": 0.5,
    "bb_bandwidth": None,
    "stoch_k": 50.0,
    "stoch_d": 50.0,
    "keltner_pos": 0.0,
    "donchian_pos": 0.5,
    "er30": 0.3,
    "atr_pct": 50.0,
    "rvol": 1.0,
    "rsi_slope": 0.0,
    "body_atr": 0.0,
    "close_loc": 0.5,
    "gap_atr": 0.0,
}

# The eight that can be read as a *direction* for the standalone walk-forward
# test, plus the exact rule. None of them is an entry rule here.
DIRECTIONAL_RULES = {
    "trend_baseline": ("EMA50 vs EMA200", "BUY when EMA50 > EMA200", "already in the engine"),
    "macd": ("MACD histogram sign", "BUY when hist > 0", "candidate"),
    "adx_di": ("ADX >= 20 with +DI/-DI", "BUY when ADX>=20 and +DI > -DI", "candidate"),
    "stoch": ("Stochastic %K vs %D", "BUY when %K > %D", "candidate"),
    "bb_momentum": ("Bollinger %B", "BUY when %B > 0.5", "candidate"),
    "donchian": ("20-bar range position", "BUY when pos > 0.5", "candidate"),
    "er_direction": ("Efficiency ratio >= 0.3", "BUY when the 30-bar net move is up", "candidate"),
    "rsi_slope": ("RSI slope", "BUY when RSI rose over 5 bars", "candidate"),
    "body": ("Last bar body", "BUY when close > open", "candidate"),
}

# Fields written into the journal's per-trade context. Keys match build().
CONTEXT_FIELDS = (
    "adx", "plus_di", "minus_di", "di_side", "macd_hist", "bb_pct_b", "bb_bandwidth",
    "stoch_k", "stoch_d", "keltner_pos", "donchian_pos", "er30", "atr_pct",
    "rvol", "rsi_slope", "body_atr", "close_loc", "gap_atr",
)


# ─────────────────────────────────────────────────────────────────────────────
# small robust primitives — None means "not enough history", never a guess
# ─────────────────────────────────────────────────────────────────────────────

def _f(value):
    """Float or None; rejects blanks, NaN, inf and 'Calculating'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _mean(values):
    vals = [v for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def sma(values, period):
    """Simple moving average; None until `period` consecutive values exist."""
    out = [None] * len(values)
    if period <= 0:
        return out
    window = deque(maxlen=period)
    total = 0.0
    bad = 0
    for i, v in enumerate(values):
        if len(window) == period:
            old = window[0]
            if old is None:
                bad -= 1
            else:
                total -= old
        window.append(v)
        if v is None:
            bad += 1
        else:
            total += v
        if len(window) == period and bad == 0:
            out[i] = total / period
    return out


def ema(values, period):
    """Standard EMA, seeded with the SMA of the first `period` valid values.

    None until the seed exists, and None again after a missing value resets the
    recursion (the live log only has missing values during warm-up).
    """
    n = len(values)
    out = [None] * n
    if period <= 0:
        return out
    seed = None
    start = None
    for i in range(period - 1, n):
        window = values[i - period + 1:i + 1]
        if any(v is None for v in window):
            continue
        seed = sum(window) / period
        start = i
        out[i] = seed
        break
    if start is None:
        return out
    k = 2.0 / (period + 1.0)
    for i in range(start + 1, n):
        v = values[i]
        out[i] = None if (v is None or out[i - 1] is None) else (v - out[i - 1]) * k + out[i - 1]
    return out


def _wilder_sums(values, period, seed_from=1):
    """Wilder running sums: seed = sum of the first `period` values, then S - S/n + x."""
    n = len(values)
    out = [None] * n
    first_end = seed_from + period - 1
    if n <= first_end:
        return out
    window = values[seed_from:first_end + 1]
    if any(v is None for v in window):
        return out
    out[first_end] = sum(window)
    for i in range(first_end + 1, n):
        prev = out[i - 1]
        v = values[i]
        out[i] = None if (prev is None or v is None) else prev - prev / period + v
    return out


def _rolling_extreme(values, period, fn):
    """Rolling max/min over the trailing `period` bars INCLUDING the current one.

    Monotonic deque: O(n), and it never looks at i+1.
    """
    n = len(values)
    out = [None] * n
    dq = deque()
    for i, v in enumerate(values):
        if v is None:
            dq.clear()
            continue
        while dq and fn(values[dq[-1]], v) >= 0:
            dq.pop()
        dq.append(i)
        while dq and dq[0] <= i - period:
            dq.popleft()
        if i >= period - 1 and period_available(values, i, period) == period:
            out[i] = values[dq[0]]
    return out


def period_available(values, i, period):
    """How many of the trailing `period` values are usable at i (None-safe)."""
    lo = max(0, i - period + 1)
    return sum(1 for j in range(lo, i + 1) if values[j] is not None)


def _rolling_min(values, period):
    # keep the deque increasing from the front: pop anything larger at the back
    return _rolling_extreme(values, period, lambda a, b: 1 if a > b else (-1 if a < b else 0))


def _rolling_max(values, period):
    # keep the deque decreasing from the front: pop anything smaller at the back
    return _rolling_extreme(values, period, lambda a, b: 1 if a < b else (-1 if a > b else 0))


# ─────────────────────────────────────────────────────────────────────────────
# the indicators
# ─────────────────────────────────────────────────────────────────────────────

def true_range(highs, lows, closes):
    """TR with the previous close; the first bar has no TR (no prior close)."""
    n = len(closes)
    out = [None] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        if None in (h, l, pc):
            continue
        out[i] = max(h - l, abs(h - pc), abs(l - pc))
    return out


def atr_sma(highs, lows, closes, period=14):
    """Engine-style ATR: simple mean of the last `period` true ranges.

    This is the engine's own definition (`calculate_atr`), kept so the journal
    can prove its tape parses identically to the log. Candidate indicators use
    Wilder's `atr_wilder`, the textbook definition.
    """
    return sma(true_range(highs, lows, closes), period)


def atr_wilder(highs, lows, closes, period=14):
    """Wilder's ATR (the classic one)."""
    tr = true_range(highs, lows, closes)
    return _wilder_mean(tr, period)


def _wilder_mean(values, period):
    n = len(values)
    out = [None] * n
    first_end = period
    if n <= first_end:
        return out
    window = values[1:first_end + 1]
    if any(v is None for v in window):
        return out
    out[first_end] = sum(window) / period
    for i in range(first_end + 1, n):
        v = values[i]
        out[i] = None if (out[i - 1] is None or v is None) else (out[i - 1] * (period - 1) + v) / period
    return out


def rsi_wilder(closes, period=14):
    """Wilder's RSI — the textbook one (the engine uses a simple mean; see above)."""
    n = len(closes)
    gains = [None] * n
    losses = [None] * n
    for i in range(1, n):
        c, pc = closes[i], closes[i - 1]
        if c is None or pc is None:
            continue
        ch = c - pc
        gains[i] = max(ch, 0.0)
        losses[i] = max(-ch, 0.0)
    ag = _wilder_mean(gains, period)
    al = _wilder_mean(losses, period)
    out = [None] * n
    for i in range(n):
        if ag[i] is None or al[i] is None:
            continue
        out[i] = 100.0 if al[i] == 0 else 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return out


def adx(highs, lows, closes, period=14):
    """Wilder ADX with +DI and -DI. Needs ~2*period bars before ADX exists."""
    n = len(closes)
    plus_dm = [None] * n
    minus_dm = [None] * n
    tr = true_range(highs, lows, closes)
    for i in range(1, n):
        h, l, ph, pl = highs[i], lows[i], highs[i - 1], lows[i - 1]
        if None in (h, l, ph, pl):
            continue
        up = h - ph
        dn = pl - l
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0

    tr_s = _wilder_sums(tr, period)
    pdm_s = _wilder_sums(plus_dm, period)
    mdm_s = _wilder_sums(minus_dm, period)
    plus_di = [None] * n
    minus_di = [None] * n
    dx = [None] * n
    for i in range(n):
        if tr_s[i] and tr_s[i] > 0 and pdm_s[i] is not None and mdm_s[i] is not None:
            plus_di[i] = 100.0 * pdm_s[i] / tr_s[i]
            minus_di[i] = 100.0 * mdm_s[i] / tr_s[i]
            denom = plus_di[i] + minus_di[i]
            dx[i] = (100.0 * abs(plus_di[i] - minus_di[i]) / denom) if denom else 0.0

    adx_out = [None] * n
    first = 2 * period
    if n > first:
        window = dx[period + 1:first + 1]
        if not any(v is None for v in window):
            adx_out[first] = sum(window) / period
            for i in range(first + 1, n):
                if dx[i] is None or adx_out[i - 1] is None:
                    continue
                adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[i]) / period
    return {"adx": adx_out, "plus_di": plus_di, "minus_di": minus_di, "dx": dx}


def macd(closes, fast=12, slow=26, signal=9):
    """MACD line, signal line and histogram, aligned to the input bars."""
    n = len(closes)
    ef = ema(closes, fast)
    es = ema(closes, slow)
    line = [None] * n
    for i in range(n):
        if ef[i] is not None and es[i] is not None:
            line[i] = ef[i] - es[i]

    # EMA of a sparse series: find the first run of `signal` valid values.
    sig = [None] * n
    start = None
    run = 0
    for i in range(n):
        if line[i] is None:
            run = 0
            continue
        run += 1
        if run == signal:
            start = i
            break
    if start is not None:
        sig[start] = sum(line[start - signal + 1:start + 1]) / signal
        k = 2.0 / (signal + 1.0)
        for i in range(start + 1, n):
            if line[i] is None or sig[i - 1] is None:
                continue
            sig[i] = (line[i] - sig[i - 1]) * k + sig[i - 1]
    hist = [None if (line[i] is None or sig[i] is None) else line[i] - sig[i] for i in range(n)]
    return {"macd": line, "signal": sig, "hist": hist}


def bollinger(closes, period=20, k=2.0):
    """Bollinger bands, %B and bandwidth (population σ, as the classic uses)."""
    n = len(closes)
    mid = sma(closes, period)
    upper = [None] * n
    lower = [None] * n
    pct_b = [None] * n
    bandwidth = [None] * n
    for i in range(n):
        if mid[i] is None:
            continue
        window = closes[i - period + 1:i + 1]
        if any(v is None for v in window):
            continue
        var = sum((v - mid[i]) ** 2 for v in window) / period
        sd = math.sqrt(var)
        upper[i] = mid[i] + k * sd
        lower[i] = mid[i] - k * sd
        width = upper[i] - lower[i]
        if width > 0 and closes[i] is not None:
            pct_b[i] = (closes[i] - lower[i]) / width
        if mid[i]:
            bandwidth[i] = 100.0 * width / mid[i]
    return {"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b, "bandwidth": bandwidth}


def stochastic(highs, lows, closes, k_period=14, d_period=3):
    """Fast %K and its 3-bar SMA (%D), 0-100."""
    n = len(closes)
    hh = _rolling_max(highs, k_period)
    ll = _rolling_min(lows, k_period)
    k_line = [None] * n
    for i in range(n):
        if hh[i] is None or ll[i] is None or closes[i] is None:
            continue
        span = hh[i] - ll[i]
        if span > 0:
            k_line[i] = 100.0 * (closes[i] - ll[i]) / span
    return {"k": k_line, "d": sma(k_line, d_period)}


def keltner(highs, lows, closes, period=20, mult=2.0):
    """Keltner mid (EMA20) and position of close in ATR units from it."""
    n = len(closes)
    mid = ema(closes, period)
    atr = atr_wilder(highs, lows, closes, 14)
    pos = [None] * n
    for i in range(n):
        if mid[i] is None or atr[i] is None or closes[i] is None or atr[i] <= 0:
            continue
        pos[i] = (closes[i] - mid[i]) / atr[i]
    return {"mid": mid, "pos": pos, "mult": mult, "atr": atr}


def donchian(highs, lows, closes, period=20):
    """20-bar high/low INCLUDING the current bar, and close's 0..1 position."""
    hh = _rolling_max(highs, period)
    ll = _rolling_min(lows, period)
    pos = [None] * len(closes)
    for i, c in enumerate(closes):
        if hh[i] is None or ll[i] is None or c is None:
            continue
        span = hh[i] - ll[i]
        if span > 0:
            pos[i] = (c - ll[i]) / span
    return {"upper": hh, "lower": ll, "pos": pos}


def efficiency_ratio(closes, period=30):
    """Kaufman's efficiency ratio: net travel / total travel, 0..1."""
    n = len(closes)
    out = [None] * n
    for i in range(period, n):
        c0, c1 = closes[i - period], closes[i]
        if c0 is None or c1 is None:
            continue
        path = 0.0
        ok = True
        for j in range(i - period + 1, i + 1):
            if closes[j] is None or closes[j - 1] is None:
                ok = False
                break
            path += abs(closes[j] - closes[j - 1])
        if ok and path > 0:
            out[i] = abs(c1 - c0) / path
    return out


def atr_percentile(highs, lows, closes, atr_period=14, window=200):
    """Percentile (0-100) of today's Wilder ATR within its last `window` values."""
    import bisect as _bisect
    atr = atr_wilder(highs, lows, closes, atr_period)
    n = len(atr)
    out = [None] * n
    order = deque()
    sorted_vals = []
    for i in range(n):
        v = atr[i]
        if v is None:
            continue
        _bisect.insort(sorted_vals, v)
        order.append(v)
        if len(order) > window:
            old = order.popleft()
            k = _bisect.bisect_left(sorted_vals, old)
            sorted_vals.pop(k)
        if len(sorted_vals) >= 30:
            less = _bisect.bisect_left(sorted_vals, v)
            out[i] = 100.0 * less / (len(sorted_vals) - 1) if len(sorted_vals) > 1 else None
    return out


def rvol(volumes, period=20):
    """Volume / its trailing mean. CAVEAT: this feed's volume is MT5 tick count."""
    avg = sma(volumes, period)
    return [None if (avg[i] is None or not avg[i] or volumes[i] is None)
            else volumes[i] / avg[i] for i in range(len(volumes))]


def _pct_change(a, b):
    if a is None or b is None or b == 0:
        return None
    return 100.0 * (a - b) / b


# ─────────────────────────────────────────────────────────────────────────────
# the series builder + snapshot accessor
# ─────────────────────────────────────────────────────────────────────────────

def bars_from_rows(rows):
    """Parsed bars from log rows (dicts), sorted oldest-first, bad rows dropped.

    Keeps the engine's own logged columns (ATR / RSI / EMA) alongside OHLC so a
    snapshot can carry both the engine's view and the candidates' view.
    Returns a list of dicts with keys ts,o,h,l,c,v,atr,rsi,e50,e200,logged.
    """
    from datetime import datetime
    out = []
    for r in rows:
        ts = _parse_ts(r.get("Timestamp"))
        o, h, l, c = (_f(r.get(k)) for k in ("Open", "High", "Low", "Close"))
        if ts is None or None in (o, h, l, c):
            continue
        out.append({
            "ts": ts, "o": o, "h": h, "l": l, "c": c,
            "v": _f(r.get("Volume")) or 0.0,
            "atr": _f(r.get("ATR")), "rsi": _f(r.get("RSI")),
            "e50": _f(r.get("EMA_50")), "e200": _f(r.get("EMA_200")),
            "logged": r,
        })
    out.sort(key=lambda b: b["ts"])
    return out


def _parse_ts(value):
    from datetime import datetime
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def build(bars):
    """Compute every candidate series once. `bars` = bars_from_rows() output."""
    n = len(bars)
    opens = [b["o"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]

    adx_out = adx(highs, lows, closes)
    macd_out = macd(closes)
    bb_out = bollinger(closes)
    stoch_out = stochastic(highs, lows, closes)
    kelt = keltner(highs, lows, closes)
    donch = donchian(highs, lows, closes)
    atr_w = atr_wilder(highs, lows, closes)

    # engine-style series (recomputed, only used to prove the tape parses and
    # to fill gaps where a logged column is missing)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    log_e50 = [b["e50"] if b["e50"] is not None else e50[i] for i, b in enumerate(bars)]
    log_e200 = [b["e200"] if b["e200"] is not None else e200[i] for i, b in enumerate(bars)]
    log_atr = [b["atr"] if b["atr"] is not None else atr_w[i] for i, b in enumerate(bars)]

    rsi_ref = [b["rsi"] for b in bars]
    rsi_calc = rsi_wilder(closes)
    rsi_slope = [None] * n
    for i in range(5, n):
        a = rsi_ref[i] if rsi_ref[i] is not None else rsi_calc[i]
        b = rsi_ref[i - 5] if rsi_ref[i - 5] is not None else rsi_calc[i - 5]
        if a is not None and b is not None:
            rsi_slope[i] = a - b

    body_atr = [None] * n
    close_loc = [None] * n
    gap_atr = [None] * n
    for i in range(n):
        atr = log_atr[i]
        rng = highs[i] - lows[i]
        if atr and atr > 0:
            body_atr[i] = (closes[i] - opens[i]) / atr
            if i > 0 and closes[i - 1] is not None:
                gap_atr[i] = (opens[i] - closes[i - 1]) / atr
        if rng > 0:
            close_loc[i] = (closes[i] - lows[i]) / rng

    return {
        "n": n, "bars": bars,
        "ts": [b["ts"] for b in bars],
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes,
        "ema50": log_e50, "ema200": log_e200, "atr_logged": log_atr,
        "ema50_calc": e50, "ema200_calc": e200, "atr_wilder": atr_w,
        "rsi_logged": rsi_ref, "rsi_calc": rsi_calc,
        "adx": adx_out["adx"], "plus_di": adx_out["plus_di"], "minus_di": adx_out["minus_di"],
        "macd": macd_out["macd"], "macd_signal": macd_out["signal"],
        "macd_hist": macd_out["hist"],
        "bb_mid": bb_out["mid"], "bb_upper": bb_out["upper"], "bb_lower": bb_out["lower"],
        "bb_pct_b": bb_out["pct_b"], "bb_bandwidth": bb_out["bandwidth"],
        "stoch_k": stoch_out["k"], "stoch_d": stoch_out["d"],
        "keltner_mid": kelt["mid"], "keltner_pos": kelt["pos"],
        "donchian_upper": donch["upper"], "donchian_lower": donch["lower"],
        "donchian_pos": donch["pos"],
        "er30": efficiency_ratio(closes),
        "atr_pct": atr_percentile(highs, lows, closes),
        "rvol": rvol(volumes),
        "rsi_slope": rsi_slope, "body_atr": body_atr, "close_loc": close_loc,
        "gap_atr": gap_atr,
    }


def at(series, i):
    """The causal snapshot at bar i (never reads i+1..)."""
    if series is None or i is None or i < 0 or i >= series["n"]:
        return None
    def g(key):
        v = series.get(key)
        return v[i] if v is not None else None
    snap = {
        "i": i, "ts": series["ts"][i],
        "open": g("open"), "high": g("high"), "low": g("low"), "close": g("close"),
        "atr": g("atr_logged"), "rsi": g("rsi_logged"),
        "ema50": g("ema50"), "ema200": g("ema200"),
        "adx": g("adx"), "plus_di": g("plus_di"), "minus_di": g("minus_di"),
        "macd": g("macd"), "macd_signal": g("macd_signal"), "macd_hist": g("macd_hist"),
        "bb_pct_b": g("bb_pct_b"), "bb_bandwidth": g("bb_bandwidth"),
        "stoch_k": g("stoch_k"), "stoch_d": g("stoch_d"),
        "keltner_pos": g("keltner_pos"), "donchian_pos": g("donchian_pos"),
        "er30": g("er30"), "atr_pct": g("atr_pct"), "rvol": g("rvol"),
        "rsi_slope": g("rsi_slope"), "body_atr": g("body_atr"),
        "close_loc": g("close_loc"), "gap_atr": g("gap_atr"),
    }
    if snap["plus_di"] is not None and snap["minus_di"] is not None:
        snap["di_side"] = ("BUY" if snap["plus_di"] > snap["minus_di"]
                           else "SELL" if snap["minus_di"] > snap["plus_di"] else None)
    else:
        snap["di_side"] = None
    if snap["ema50"] is not None and snap["ema200"] is not None:
        snap["ema_spread_atr"] = ((snap["ema50"] - snap["ema200"]) / snap["atr"]
                                  if snap["atr"] else None)
    else:
        snap["ema_spread_atr"] = None
    return snap


def engine_parity(series, step=250):
    """How well this module's tape maths reproduces the engine's logged columns.

    The engine's ATR/RSI are SIMPLE means (see `atr_sma` / `rsi_sma`), its EMAs
    are seeded with an SMA. A large difference means the log is not what this
    parser thinks it is (a data problem, not an indicator problem), so the lab
    prints it instead of trusting its own columns.
    """
    bars = series["bars"]
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    calc_atr = atr_sma(highs, lows, closes, 14)
    calc_rsi = rsi_sma(closes, 14)
    calc_e50 = ema(closes, 50)
    calc_e200 = ema(closes, 200)
    samples = {"atr": [], "rsi": [], "ema50": [], "ema200": []}
    # log_candle() runs BEFORE update_indicators(), so the indicator columns on
    # row i describe the state through bar i-1. Compare against i-1, not i.
    for i in range(1, series["n"], max(1, step)):
        pairs = (
            ("atr", series["atr_logged"][i], calc_atr[i - 1]),
            ("rsi", series["rsi_logged"][i], calc_rsi[i - 1]),
            ("ema50", series["ema50"][i], calc_e50[i - 1]),
            ("ema200", series["ema200"][i], calc_e200[i - 1]),
        )
        for key, logged, recomputed in pairs:
            if logged is not None and recomputed is not None:
                samples[key].append(abs(logged - recomputed))
    out = {}
    for key, diffs in samples.items():
        if diffs:
            diffs = sorted(diffs)
            out[key] = {"n": len(diffs), "median_abs_diff": diffs[len(diffs) // 2],
                        "max_abs_diff": diffs[-1]}
        else:
            out[key] = {"n": 0, "median_abs_diff": None, "max_abs_diff": None}
    return out


def rsi_sma(closes, period=14):
    """The engine's RSI: simple mean of the last N gains/losses (not Wilder)."""
    n = len(closes)
    gains = [None] * n
    losses = [None] * n
    for i in range(1, n):
        c, pc = closes[i], closes[i - 1]
        if c is None or pc is None:
            continue
        ch = c - pc
        gains[i] = max(ch, 0.0)
        losses[i] = max(-ch, 0.0)
    ag = sma(gains, period)
    al = sma(losses, period)
    out = [None] * n
    for i in range(n):
        if ag[i] is None or al[i] is None:
            continue
        out[i] = 100.0 if al[i] == 0 else 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return out


def describe(key):
    """A copy of the description for one field, or a safe fallback."""
    return dict(DESCRIPTIONS.get(key, {"label": key, "unit": "", "what": "", "why": ""}))


def split_value(key, values):
    """The pre-declared split for a feature; median when SPLITS says None.

    Computed from the sample it is given (that is the only fitted number), and
    returned with a label so every table says which side is which.
    """
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    rule = SPLITS.get(key, None)
    if rule is None:
        mid = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
        return mid
    return rule
