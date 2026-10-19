#!/usr/bin/env python3
"""pressure.py — read-only tape pressure + setup/state reads for dashboard.py.

WHAT THIS IS
    A display layer. It answers three questions a human asks before a session:

      1. "Which way is the tape being pushed?"      -> pressure()
      2. "Would the engine take this bar, and if not, what is missing?"
                                                    -> setup_read()
      3. "Is the book / this experiment in a state where that matters?"
                                                    -> portfolio_read(), book_read(), feed_read()
      4. "Given a very strong signal, where did price actually head?"
                                                    -> signal_outlook() / outlook_now()
         (historical frequencies over the bot's own taken signals — a cone
         and base rates, never a forecast; see the 5b banner below)

WHAT THIS IS NOT
    It is NOT a strategy input. Nothing in here is imported by engine.py or
    trade_filter.py, nothing writes a file, and no dashboard number is allowed to
    become an entry condition without a pre-registered bar (docs/HANDOFF.md §11).
    The composite in pressure() is a *description* of the tape: because the engine's
    trend gate keys side on EMA50 vs EMA200, high buy-pressure entries are BUYs and
    low ones are SELLs almost by construction, so a pooled read of it is a side read
    in disguise (§8 "never read a momentum claim without a side split"). The same
    source is why `tools/pressure_report.py` exists: it measures, per side and per
    era, whether the buckets separate outcomes at all — and writes the answer down
    instead of asserting one (calibration(); ANALYSIS-2026-10-16-dashboard-pressure.md).

MIRRORED CONSTANTS
    The gate thresholds below belong to engine.py / trade_filter.py. They are
    duplicated here on purpose (the dashboard must not import the engine: it would
    drag in requests/dotenv and would keep stale constants across an engine-only
    deploy), and `tools/smoke_test.py` Scenario U fails the deploy if they ever
    drift from the real ones. Change them here only in the same commit that changes
    the source of truth.

Era/geometry conventions are the repo's own (docs/HANDOFF.md §8):
  * ratcheted rows are reconstructed from the REWARD leg: risk = |TP - Entry| / 1.5,
    never from ATR_At_Entry;
  * the 20-bar floor/ceiling excludes the bar being evaluated (engine.evaluate_candle);
  * R = Profit / risk, on decisive trades only.

Usage (library):  import pressure ; pressure.build(read_tail=True)
Usage (CLI read): python3 tools/pressure_report.py
"""
from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Mirrored constants — source of truth is engine.py / trade_filter.py.
# Scenario U asserts every one of them against the live modules.
# ─────────────────────────────────────────────────────────────────────────────

# strategy funnel (engine.py)
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.38
FLOOR_BUFFER_PCT = 0.0020
EMA_SLOPE_LOOKBACK = 30
MAX_BELOW_EMA_ATR = 0.30
RSI_MIN = 30.0
RSI_MAX = 68.0
SELL_RSI_MIN = 100.0 - RSI_MAX       # 32.0 — engine's symmetric short bounds
SELL_RSI_MAX = 100.0 - RSI_MIN       # 70.0
MIN_ATR = 1.10                       # engine's atr_ok uses a strict >
REQUIRE_VOLUME_CONFIRM = False       # funnel stage is OFF, shown as n/a

# stop/exit geometry (engine.py)
ATR_SL_MULT = 2.0
SL_CLEAR_ATR = 0.5
RR_TARGET = 1.5
BE_TRIGGER_R = 0.75
MAX_HOLD_MINUTES = 240

# portfolio gates (trade_filter.py)
MIN_ATR_TO_TRADE = 1.10
MAX_ATR_TO_TRADE = 4.50
MAX_DAILY_LOSSES = 10
SL_COOLDOWN_BASE_MINUTES = 30
SL_COOLDOWN_ESCALATED_MINUTES = 60
MOMENTUM_LOOKBACK_MINUTES = 60
BLACKOUT_WINDOWS = [
    (7, 55, 9, 0, "London Open & Early Session Kill-Zone", ("BUY",)),
    (12, 25, 12, 45, "NY Early Pre-Market", ("BUY", "SELL")),
    (13, 25, 15, 15, "NY Open & US High-Impact Macro Releases", ("BUY", "SELL")),
    (21, 45, 22, 30, "Daily Market Rollover & Spread Spike", ("BUY", "SELL")),
]

# era boundary — must equal strategy_lab.LIVE_CUTOVER (see HANDOFF "Snapshot")
STRUCT_STOP_CUTOVER = datetime(2026, 10, 6, 3, 0)

# pre-registered struct-stop bar — thresholds copied from
# docs/ANALYSIS-2026-10-05-stop-loss-geometry.md §7 (the contract, not a summary of it)
BAR_SL_PER_DAY = 6.5              # B1: SL events / calendar day <= 6.5 (baseline 8.2)
BAR_SL_SHARE_PCT = 47.0           # B2: SL share of closed trades <= 47% (baseline 45.4%)
BAR_SCRATCH_PCT = 35.0            # B3: BE (scratch) share <= 35% (baseline 32.8%)
BAR_WR_PCT = 36.0                 # C SCREEN: decisive WR >= 36
BAR_R_PER_TRADE = -0.10           # C SCREEN: R/trade >= -0.10R (cost-0 ledger scale)
BAR_PASS_N = 150                  # PASS: n >= 150 AND Wilson LB > 32.1%
BREAKEVEN_WR_PCT = 32.1           # uncosted 1:1.5 breakeven decisive WR
BAR_LEVEL_BOUND = (70.0, 90.0)    # A4: level-bound share window (replay 80.2%)
BAR_MEDIAN_RISK_ATR = (2.7, 3.5)  # A5: median risk in ATR (replay 3.07)
PRE_CHANGE_AVG_SL_USD = 3.91      # R6 baseline quoted by §7
REVERT_R_PER_TRADE = -0.20
REVERT_SL_MULTIPLE = 2.2          # avg SL loss vs PRE_CHANGE_AVG_SL_USD
REVERT_DD_USD = 250.0
REVIEW_DUE = datetime(2026, 10, 19, 21, 0)   # scheduled judgement (or n=150)

# ── display-only volatility guard (human advice, never a trade gate) ──
# Thresholds are deliberately conservative and match the dashboard's language.
# They DO NOT change engine.py / trade_filter.py behaviour. Scenario U does NOT
# pin them — they are free to evolve without a deploy gate.
VOLATILITY_ATR_ELEVATED = 2.5     # ATR above this = choppy / elevated
VOLATILITY_ATR_HIGH = 3.5         # ATR above this = volatile
VOLATILITY_ATR_SPIKE_RATIO = 1.5  # ATR vs its 60-bar median
VOLATILITY_SPREAD_WARN = 0.45     # $ spread — caution
VOLATILITY_SPREAD_BLOCK = 0.60    # $ spread — bot blocks (>60 pts)
VOLATILITY_MOMENTUM_WARN_ATR = 2.0
VOLATILITY_MOMENTUM_HIGH_ATR = 3.0
VOLATILITY_RANGE_WARN_ATR = 25.0
VOLATILITY_RANGE_HIGH_ATR = 35.0

# tape-pressure window (bars) and the composite weights
PRESSURE_WINDOW = 60
PRESSURE_WEIGHTS = {
    "flow": 0.30,        # volume-weighted signed body over the window
    "momentum": 0.20,    # close now vs close PRESSURE_WINDOW bars ago, in ATR
    "trend": 0.20,       # EMA50 - EMA200, in ATR
    "slope": 0.15,       # EMA50 now vs EMA_SLOPE_LOOKBACK bars ago, in ATR
    "rsi": 0.15,         # RSI posture around 50
}

DATA_DIR = os.getenv("GOLD_DATA_DIR", "/opt/gold")
LOG_FILE_PATH = os.getenv("GOLD_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
TRADES_FILE_PATH = os.getenv("GOLD_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))
SKIP_FILE_PATH = os.getenv("GOLD_SKIP_FILE", os.path.join(DATA_DIR, "skipped_trades.csv"))
STATUS_FILE_PATH = os.getenv("GOLD_STATUS_FILE", os.path.join(DATA_DIR, "status.json"))


# ─────────────────────────────────────────────────────────────────────────────
# small parsing helpers (all tolerant: the live CSVs have "Calculating" cells,
# torn tails, and historical rows with resets — check_data.py is the gate, this
# layer must never raise on them)
# ─────────────────────────────────────────────────────────────────────────────

def parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_pct(value):
    """'69.9%' -> 69.9 ; 0.699 -> 69.9 ; None -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("%"):
        return parse_float(text[:-1])
    num = parse_float(text)
    if num is None:
        return None
    return num * 100.0 if num <= 1.0 else num


def parse_ts(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def read_rows(path):
    """Full CSV read as dicts. [] on any problem (missing/short/locked file)."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def tail_rows(path, n=400, window_bytes=128 * 1024):
    """Last n rows (oldest→newest) without reading the whole file.

    The 1-min log is multi-MB and grows forever; the dashboard refreshes every
    15 s, so it must not re-read it end to end. `window_bytes` widens the tail
    for callers that need more than the default ~1100 rows (the box panel needs
    a prior trading day, which can sit ~3000 bars back on a Monday).
    """
    if not path or not os.path.isfile(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as raw:
            header_line = raw.readline()
            if not header_line:
                return []
            header = header_line.decode("utf-8", errors="replace").strip().split(",")
            chunk = max(128 * 1024, int(window_bytes))
            if size > chunk:
                raw.seek(max(len(header_line), size - chunk))
                data = raw.read().decode("utf-8", errors="replace")
                nl = data.find("\n")
                if nl >= 0:
                    data = data[nl + 1:]
            else:
                raw.seek(len(header_line))
                data = raw.read().decode("utf-8", errors="replace")
        rows = list(csv.DictReader(data.splitlines(), fieldnames=header))
        return rows[-n:]
    except Exception:
        return []


def _series(rows):
    """Column arrays for the bar maths (None where 'Calculating'/blank)."""
    def col(name):
        return [parse_float(r.get(name)) for r in rows]
    return {
        "ts": [parse_ts(r.get("Timestamp")) for r in rows],
        "open": col("Open"),
        "high": col("High"),
        "low": col("Low"),
        "close": col("Close"),
        "volume": [parse_float(r.get("Volume")) or 0.0 for r in rows],
        "ema_fast": col("EMA_50"),
        "ema_slow": col("EMA_200"),
        "rsi": col("RSI"),
        "atr": col("ATR"),
        "floor_logged": col("Dynamic_Floor"),
    }


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def _clip01(x):
    return max(0.0, min(1.0, x))


# ─────────────────────────────────────────────────────────────────────────────
# 1. TAPE PRESSURE — "which side is pushing the tape right now"
# ─────────────────────────────────────────────────────────────────────────────

def pressure(rows, window=PRESSURE_WINDOW):
    """Buy/sell pressure composite over the last `window` closed bars.

    Returns None when there is not enough history. Each component is reported as
    a 0..1 buy-share plus its raw value, so the number can be audited rather than
    trusted: the dashboard shows both, and the calibration shows what (if
    anything) the composite separated in the live book.
    """
    need = max(window, EMA_SLOPE_LOOKBACK + 1) + 1
    if len(rows) < need:
        return None
    s = _series(rows)
    i = len(rows) - 1
    atr = s["atr"][i]
    close = s["close"][i]
    if not atr or close is None:
        return None

    # flow: Σ (close-open)/range × volume, i.e. who did the moving, size-weighted
    num = den = 0.0
    for j in range(i - window + 1, i + 1):
        o, c, h, l = s["open"][j], s["close"][j], s["high"][j], s["low"][j]
        if None in (o, c, h, l):
            continue
        rng = h - l
        if rng <= 0:
            continue
        num += ((c - o) / rng) * s["volume"][j]
        den += s["volume"][j]
    if den <= 0:
        return None
    flow = num / den
    j0 = i - window + 1
    if s["close"][j0] is None:
        return None
    momentum = (close - s["close"][j0]) / atr
    trend = ((s["ema_fast"][i] - s["ema_slow"][i]) / atr
             if (s["ema_fast"][i] is not None and s["ema_slow"][i] is not None) else 0.0)
    k = i - EMA_SLOPE_LOOKBACK
    slope = ((s["ema_fast"][i] - s["ema_fast"][k]) / atr
             if (k >= 0 and s["ema_fast"][i] is not None and s["ema_fast"][k] is not None) else 0.0)
    rsi = s["rsi"][i] if s["rsi"][i] is not None else 50.0

    shares = {
        "flow": (flow + 1.0) / 2.0,
        "momentum": _sigmoid(momentum / 1.5),
        "trend": _sigmoid(trend / 0.5),
        "slope": _sigmoid(slope / 0.5),
        "rsi": _clip01((_clip01((rsi - 50.0) / 20.0 + 1.0) / 2.0)),
    }
    buy_pct = 100.0 * sum(shares[k_] * w for k_, w in PRESSURE_WEIGHTS.items())
    components = [
        {"key": "flow", "label": "Volume-weighted flow",
         "raw": f"{flow:+.2f}", "unit": "±1 signed body × volume",
         "buy_share": shares["flow"], "weight": PRESSURE_WEIGHTS["flow"]},
        {"key": "momentum", "label": f"{window}-bar momentum",
         "raw": f"{momentum:+.2f}", "unit": "ATR",
         "buy_share": shares["momentum"], "weight": PRESSURE_WEIGHTS["momentum"]},
        {"key": "trend", "label": "EMA50 vs EMA200",
         "raw": f"{trend:+.2f}", "unit": "ATR",
         "buy_share": shares["trend"], "weight": PRESSURE_WEIGHTS["trend"]},
        {"key": "slope", "label": f"EMA50 {EMA_SLOPE_LOOKBACK}-bar slope",
         "raw": f"{slope:+.2f}", "unit": "ATR",
         "buy_share": shares["slope"], "weight": PRESSURE_WEIGHTS["slope"]},
        {"key": "rsi", "label": "RSI posture",
         "raw": f"{rsi:.1f}", "unit": "50 = neutral",
         "buy_share": shares["rsi"], "weight": PRESSURE_WEIGHTS["rsi"]},
    ]

    # label is descriptive only; the shades exist so the panel can colour the bar
    if buy_pct >= 70:
        label, tone = "Tape pushed UP hard", "up-strong"
    elif buy_pct >= 58:
        label, tone = "Tape leaning UP", "up"
    elif buy_pct > 42:
        label, tone = "Tape balanced", "flat"
    elif buy_pct > 30:
        label, tone = "Tape leaning DOWN", "down"
    else:
        label, tone = "Tape pushed DOWN hard", "down-strong"

    return {
        "window": window,
        "buy_pct": buy_pct,
        "sell_pct": 100.0 - buy_pct,
        "label": label,
        "tone": tone,
        "components": components,
        "as_of": rows[-1].get("Timestamp"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. LOCATION + SETUP READ — the engine's own gates, evaluated on the last bar
# ─────────────────────────────────────────────────────────────────────────────

def levels(rows, lookback=LOOKBACK_PERIOD):
    """(floor, ceiling) exactly as engine.evaluate_candle builds them.

    The engine computes the floor/ceiling from the bars BEFORE the one it is
    evaluating (min low / max high of the previous `lookback` bars), so the level
    is taken from rows[:-1] here too. The BUY-side value is cross-checked against
    the engine's own logged Dynamic_Floor when present; a mismatch is reported by
    the dashboard rather than silently trusted (it would mean the column layout
    or the window moved).
    """
    if len(rows) < lookback + 1:
        return None, None, None
    prior = rows[:-1][-lookback:]
    lows = [parse_float(r.get("Low")) for r in prior]
    highs = [parse_float(r.get("High")) for r in prior]
    lows = [v for v in lows if v is not None]
    highs = [v for v in highs if v is not None]
    if not lows or not highs:
        return None, None, None
    floor, ceiling = min(lows), max(highs)
    logged = parse_float(rows[-1].get("Dynamic_Floor"))
    return floor, ceiling, logged


def structural_risk(entry, atr, level):
    """engine.GoldEngine.structural_risk — stop distance in $ (1 oz: $1 move = $1)."""
    risk = atr * ATR_SL_MULT
    if level and atr and atr > 0:
        beyond = abs(entry - level) + SL_CLEAR_ATR * atr
        if beyond > risk:
            risk = beyond
    return risk


def _wick_ratios(row):
    o, h, l, c = (parse_float(row.get(k)) for k in ("Open", "High", "Low", "Close"))
    if None in (o, h, l, c):
        return None, None
    rng = h - l
    if rng <= 0:
        return 0.0, 0.0
    lower = (min(o, c) - l) / rng
    upper = (h - max(o, c)) / rng
    return lower * 100.0, upper * 100.0


def _gate(name, side, value, threshold, ok, note="", inactive=False):
    return {"name": name, "side": side, "value": value, "threshold": threshold,
            "ok": bool(ok), "note": note, "inactive": inactive}


def setup_read(rows):
    """Evaluate the engine's entry gates on the LAST logged bar, both sides.

    BUY-side rows use the engine's own logged flags where they exist
    (Tested_Floor / Valid_Rejection / Held_Floor / Trend_Confirmed); everything the
    log does not carry (the ceiling side, the EMA slope, the EMA proximity buffer)
    is recomputed from the same columns with the same rules. That keeps the panel
    honest: it shows the engine's verdict, not a lookalike.
    """
    out = {"ok": False, "reason": "", "as_of": None, "nearest_miss": {"BUY": None, "SELL": None}}
    if not rows:
        out["reason"] = "no log rows"
        return out
    last = rows[-1]
    close = parse_float(last.get("Close"))
    atr = parse_float(last.get("ATR"))
    rsi = parse_float(last.get("RSI"))
    ema_f = parse_float(last.get("EMA_50"))
    ema_s = parse_float(last.get("EMA_200"))
    if None in (close, atr, rsi, ema_f, ema_s) or not atr:
        out["reason"] = "last bar still warming up (indicator columns not numeric)"
        return out
    floor, ceiling, floor_logged = levels(rows)
    if floor is None or ceiling is None:
        out["reason"] = f"needs {LOOKBACK_PERIOD + 1} logged bars for the 20-bar level"
        return out

    lower_wick, upper_wick = _wick_ratios(last)
    slope_ok = {"BUY": False, "SELL": False}
    if len(rows) >= EMA_SLOPE_LOOKBACK + 1:
        prev = parse_float(rows[-1 - EMA_SLOPE_LOOKBACK].get("EMA_50"))
        if prev is not None:
            slope_ok = {"BUY": ema_f > prev, "SELL": ema_f < prev}

    # the engine's own logged BUY-side flags (fall back to recomputation)
    logged = {
        "tested": str(last.get("Tested_Floor")).strip().lower() == "true",
        "rej": str(last.get("Valid_Rejection")).strip().lower() == "true",
        "held": str(last.get("Held_Floor")).strip().lower() == "true",
        "trend_buy": str(last.get("Trend_Confirmed")).strip().lower() == "true",
    }
    has_logged = last.get("Tested_Floor") not in (None, "")

    tested = {
        "BUY": logged["tested"] if has_logged else parse_float(last.get("Low")) <= floor * (1 + FLOOR_BUFFER_PCT),
        "SELL": parse_float(last.get("High")) >= ceiling * (1 - FLOOR_BUFFER_PCT),
    }
    held = {
        "BUY": logged["held"] if has_logged else close > floor,
        "SELL": close < ceiling,
    }
    trend = {
        "BUY": logged["trend_buy"] if has_logged else ema_f > ema_s,
        "SELL": (not logged["trend_buy"]) if has_logged else ema_f < ema_s,
    }
    rej = {
        "BUY": logged["rej"] if has_logged else (lower_wick is not None and lower_wick >= WICK_RATIO_TARGET * 100),
        "SELL": upper_wick is not None and upper_wick >= WICK_RATIO_TARGET * 100,
    }
    near_ema = {
        "BUY": close >= ema_f - atr * MAX_BELOW_EMA_ATR,
        "SELL": close <= ema_f + atr * MAX_BELOW_EMA_ATR,
    }
    rsi_ok = {
        "BUY": RSI_MIN < rsi < RSI_MAX,
        "SELL": SELL_RSI_MIN < rsi < SELL_RSI_MAX,
    }
    atr_ok = MIN_ATR < atr <= MAX_ATR_TO_TRADE

    gates = {"BUY": [], "SELL": []}
    for side in ("BUY", "SELL"):
        lev = floor if side == "BUY" else ceiling
        dist_atr = abs(close - lev) / atr if lev else None
        wick = lower_wick if side == "BUY" else upper_wick
        gates[side] = [
            _gate("Level tested", side, (f"${parse_float(last.get('Low') if side == 'BUY' else last.get('High')):.2f}"),
                  f"{'floor' if side == 'BUY' else 'ceiling'} ${lev:.2f} ±{FLOOR_BUFFER_PCT:.2%}",
                  tested[side], f"price is {dist_atr:.2f} ATR from the level" if dist_atr is not None else ""),
            _gate("Rejection wick", side, f"{wick:.0f}%" if wick is not None else "—",
                  f"≥ {WICK_RATIO_TARGET:.0%}", rej[side],
                  "lower wick" if side == "BUY" else "upper wick"),
            _gate("Held the level", side, f"${close:.2f}",
                  f"{'>' if side == 'BUY' else '<'} ${lev:.2f}", held[side], ""),
            _gate("Trend (EMA50 vs EMA200)", side, f"{ema_f:.2f} {'>' if ema_f > ema_s else '<'} {ema_s:.2f}",
                  f"EMA50 {'>' if side == 'BUY' else '<'} EMA200", trend[side],
                  f"spread {abs(ema_f - ema_s) / atr:.2f} ATR"),
            _gate(f"EMA50 slope ({EMA_SLOPE_LOOKBACK}b)", side,
                  f"{ema_f - (parse_float(rows[-1 - EMA_SLOPE_LOOKBACK].get('EMA_50')) or ema_f):+.2f}",
                  f"{'>' if side == 'BUY' else '<'} 0", slope_ok[side], ""),
            _gate("Near EMA50", side, f"${close:.2f}",
                  f"{'≥' if side == 'BUY' else '≤'} ${ema_f - atr * MAX_BELOW_EMA_ATR:.2f}"
                  if side == "BUY" else f"≤ ${ema_f + atr * MAX_BELOW_EMA_ATR:.2f}",
                  near_ema[side], f"buffer {MAX_BELOW_EMA_ATR} ATR"),
            _gate("RSI window", side, f"{rsi:.1f}",
                  f"{RSI_MIN:.0f}–{RSI_MAX:.0f}" if side == "BUY" else f"{SELL_RSI_MIN:.0f}–{SELL_RSI_MAX:.0f}",
                  rsi_ok[side], ""),
            _gate("ATR bounds", side, f"{atr:.2f}",
                  f"{MIN_ATR_TO_TRADE:.2f}–{MAX_ATR_TO_TRADE:.2f}", atr_ok, "portfolio gate"),
            _gate("Volume spike", side, "off", "disabled in engine", True,
                  "REQUIRE_VOLUME_CONFIRM = False", inactive=True),
        ]

    for side in ("BUY", "SELL"):
        active = [g for g in gates[side] if not g["inactive"]]
        out[side] = {
            "gates": gates[side],
            "passed": sum(1 for g in active if g["ok"]),
            "total": len(active),
            "ready": all(g["ok"] for g in active),
            "level": floor if side == "BUY" else ceiling,
            "level_dist_atr": abs(close - (floor if side == "BUY" else ceiling)) / atr,
        }

    # what would have to flip first (the failing gate with the smallest gap) —
    # this is the "what am I waiting for" line.
    misses = []
    for side in ("BUY", "SELL"):
        for g in gates[side]:
            if g["inactive"] or g["ok"]:
                continue
            misses.append((side, g))
    if misses:
        side, g = misses[0]
        out["nearest_miss"][side] = f"{g['name']}: {g['value']} vs {g['threshold']}"

    out.update({
        "ok": True,
        "as_of": last.get("Timestamp"),
        "close": close, "atr": atr, "rsi": rsi,
        "ema_fast": ema_f, "ema_slow": ema_s,
        "floor": floor, "ceiling": ceiling, "floor_logged": floor_logged,
        "floor_mismatch": (floor_logged is not None and abs(floor_logged - floor) > 0.01),
        "lower_wick": lower_wick, "upper_wick": upper_wick,
        "last_bar_low": parse_float(last.get("Low")),
        "last_bar_high": parse_float(last.get("High")),
    })
    return out


def location_read(setup):
    """Where price sits in the 20-bar range, in $ and ATR, for both sides."""
    if not setup.get("ok"):
        return None
    floor, ceiling, close, atr = setup["floor"], setup["ceiling"], setup["close"], setup["atr"]
    span = ceiling - floor
    def _desc(level, name, above_is_inside):
        """'floor 7.62 ATR below price' vs 'price is 1.42 ATR above the ceiling'."""
        d = (close - level) / atr
        if above_is_inside:          # the level is BELOW price (floor / ceiling)
            return (f"{name} {d:.2f} ATR below price" if d >= 0
                    else f"price {abs(d):.2f} ATR below the {name}")
        return (f"{name} {abs(d):.2f} ATR above price" if d <= 0
                else f"price {d:.2f} ATR above the {name}")

    return {
        "floor": floor, "ceiling": ceiling, "close": close, "span": span,
        "range_pos_pct": 100.0 * (close - floor) / span if span > 0 else None,
        "up_to_ceiling_atr": (ceiling - close) / atr,
        "down_to_floor_atr": (close - floor) / atr,
        "floor_desc": _desc(floor, "floor", True),
        "ceiling_desc": _desc(ceiling, "ceiling", False),
        "buy": {"level": floor, "risk": structural_risk(close, atr, floor),
                "level_bound": structural_risk(close, atr, floor) > atr * ATR_SL_MULT + 1e-9},
        "sell": {"level": ceiling, "risk": structural_risk(close, atr, ceiling),
                 "level_bound": structural_risk(close, atr, ceiling) > atr * ATR_SL_MULT + 1e-9},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. PORTFOLIO READ — the state gates (blackout / cooldown / breaker / skips)
# ─────────────────────────────────────────────────────────────────────────────

def _blackout_state(now, side=None):
    t = now.time()
    for sh, sm, eh, em, label, sides in BLACKOUT_WINDOWS:
        start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = t.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start <= t <= end and (side is None or side in sides):
            return True, label, sides
    return False, "", ()


def next_blackout(now):
    """(label, sides, start_dt) of the next window opening today/tomorrow."""
    best = None
    for day in (0, 1):
        base = (now + timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        for sh, sm, eh, em, label, sides in BLACKOUT_WINDOWS:
            start = base.replace(hour=sh, minute=sm)
            if start > now and (best is None or start < best[2]):
                best = (label, sides, start)
    return best


def portfolio_read(trades, now=None, log_rows=None):
    """Live-state mirror of trade_filter.should_take_trade's gate order."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    out = {"now": now, "sides_blocked": {"BUY": None, "SELL": None}}
    for side in ("BUY", "SELL"):
        blocked, label, _sides = _blackout_state(now, side)
        out["sides_blocked"][side] = label if blocked else None
    out["blackout_any"] = bool(out["sides_blocked"]["BUY"] or out["sides_blocked"]["SELL"])
    out["next_window"] = next_blackout(now)

    # daily breaker
    today = now.strftime("%Y-%m-%d")
    daily_sls = 0
    for t in trades:
        if (t.get("Exit_Time") or "").startswith(today) and \
                (t.get("Exit_Reason") or "").strip().upper() == "SL":
            daily_sls += 1
    out["daily_sls"] = daily_sls
    out["breaker_on"] = daily_sls >= MAX_DAILY_LOSSES
    out["momentum_side"] = momentum_side(log_rows, now) if log_rows else None
    if out["breaker_on"]:
        mom = out["momentum_side"]
        if mom is None:
            out["sides_blocked"]["BUY"] = out["sides_blocked"]["SELL"] = \
                f"daily breaker: {daily_sls}/{MAX_DAILY_LOSSES} SLs, momentum unavailable → both sides halted"
        else:
            other = "SELL" if mom == "BUY" else "BUY"
            if out["sides_blocked"][other] is None:
                out["sides_blocked"][other] = \
                    f"daily breaker: {daily_sls}/{MAX_DAILY_LOSSES} SLs → trend-side-only (momentum {mom})"

    # escalating SL cooldown (last trade only, exactly like trade_filter)
    out["cooldown_minutes_left"] = 0
    out["cooldown_note"] = ""
    if trades:
        last = trades[-1]
        if (last.get("Exit_Reason") or "").strip().upper() == "SL":
            streak = 0
            for t in reversed(trades):
                reason = (t.get("Exit_Reason") or "").strip().upper()
                if reason == "SL":
                    streak += 1
                elif reason == "TP":
                    break
            mins = SL_COOLDOWN_ESCALATED_MINUTES if streak >= 2 else SL_COOLDOWN_BASE_MINUTES
            exit_ts = parse_ts(last.get("Exit_Time"))
            if exit_ts:
                left = (exit_ts + timedelta(minutes=mins) - now).total_seconds() / 60.0
                if left > 0:
                    out["cooldown_minutes_left"] = int(left) + 1
                    out["cooldown_note"] = f"{streak} consecutive SLs → {mins} min window"
    return out


def momentum_side(log_rows, now=None, minutes=MOMENTUM_LOOKBACK_MINUTES):
    """trade_filter.get_momentum_side on already-loaded rows (display mirror)."""
    if not log_rows:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=minutes)
    close_now = close_then = None
    last_ts = None
    for row in log_rows:
        ts = parse_ts(row.get("Timestamp"))
        c = parse_float(row.get("Close"))
        if ts is None or c is None:
            continue
        if ts <= cutoff:
            close_then = c
        last_ts, close_now = ts, c
    if close_now is None or close_then is None or last_ts is None:
        return None
    if (now - last_ts) > timedelta(minutes=15):
        return None
    if close_now > close_then:
        return "BUY"
    if close_now < close_then:
        return "SELL"
    return None


def skip_summary(skip_rows, now=None, hours=24):
    """Blocked setups in the last `hours` — the leak the funnel cannot show.

    Bucketed by the reason's leading classifier so the counts stay readable
    ('SL Cooldown: 12 min remaining' and the streak variant land together).
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=hours)
    buckets = {}
    total = 0
    for row in skip_rows:
        ts = parse_ts(row.get("Timestamp"))
        if ts is None or ts < cutoff:
            continue
        total += 1
        reason = (row.get("Reason") or "").strip()
        low = reason.lower()
        if low.startswith("blackout"):
            key = "Blackout"
        elif low.startswith("sl cooldown"):
            key = "SL cooldown"
        elif low.startswith("daily loss limit"):
            key = "Daily breaker"
        elif low.startswith("atr too low"):
            key = "ATR too low"
        elif low.startswith("atr too high"):
            key = "ATR too high"
        else:
            key = reason.split(":")[0][:28] or "Other"
        buckets[key] = buckets.get(key, 0) + 1
    ordered = sorted(buckets.items(), key=lambda kv: -kv[1])
    return {"hours": hours, "total": total, "buckets": ordered,
            "last": skip_rows[-1].get("Timestamp") if skip_rows else None}


# ─────────────────────────────────────────────────────────────────────────────
# 4. BOOK / EXPERIMENT READ — era stats against the pre-registered bars
# ─────────────────────────────────────────────────────────────────────────────

def wilson_interval(successes, n, z=1.96):
    """95% Wilson score interval in percent — the repo's CI convention."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100.0 * max(0.0, centre - half), 100.0 * min(1.0, centre + half))


def trade_risk(row):
    """Actual risk in $ from the REWARD leg (HANDOFF §8) — never ATR_At_Entry."""
    entry = parse_float(row.get("Entry_Price"))
    tp = parse_float(row.get("Take_Profit"))
    if entry is None or tp is None or tp == entry:
        return None
    return abs(tp - entry) / RR_TARGET


def era_stats(trades, cutover=STRUCT_STOP_CUTOVER, label="struct-stop era"):
    """Outcome/P&L/R summary for entries >= cutover, checked against §7's bar.

    Every threshold and its baseline text comes from
    docs/ANALYSIS-2026-10-05-stop-loss-geometry.md §7; the panel shows the same
    verdicts, so a session reading the dashboard sees exactly the contract the
    review will be judged on — never a friendlier restatement of it.
    """
    era = [t for t in trades if (parse_ts(t.get("Entry_Time")) or datetime.min) >= cutover]
    if not era:
        return None
    counts = {"TP": 0, "SL": 0, "BE": 0, "TIME": 0}
    gross = 0.0
    r_sum = 0.0          # decisive-only mean R, per-trade risk (secondary read)
    r_n = 0
    one_r = []           # win_rate_report's 1R: |Entry − Stop_Loss| per trade
    sl_loss = 0.0
    sl_n = 0
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    sessions = set()
    risks_atr = []
    level_bound = 0
    for t in era:
        reason = (t.get("Exit_Reason") or "").strip().upper()
        if reason in counts:
            counts[reason] += 1
        profit = parse_float(t.get("Profit")) or 0.0
        gross += profit
        running += profit
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
        risk = trade_risk(t)
        # 1R must be the ORIGINAL risk: on a ratcheted row Stop_Loss == Entry_Price, so
        # |entry − sl| collapses to 0 and would understate the book's 1R (the same trap
        # win_rate_report.py avoids by rebuilding the stop from the reward leg).
        entry_px, stop_px = parse_float(t.get("Entry_Price")), parse_float(t.get("Stop_Loss"))
        if risk:
            one_r.append(risk)
        elif entry_px is not None and stop_px is not None:
            one_r.append(abs(entry_px - stop_px))
        atr = parse_float(t.get("ATR_At_Entry"))
        if risk and atr:
            risks_atr.append(risk / atr)
            if risk > ATR_SL_MULT * atr + 0.01:
                level_bound += 1
        if risk and reason in ("TP", "SL"):
            r_sum += profit / risk
            r_n += 1
        if reason == "SL":
            sl_loss += abs(profit)
            sl_n += 1
        entry = parse_ts(t.get("Entry_Time"))
        if entry:
            sessions.add(entry.date())
    n = len(era)
    decisive = counts["TP"] + counts["SL"]
    wr = 100.0 * counts["TP"] / decisive if decisive else 0.0
    lb, ub = wilson_interval(counts["TP"], decisive)
    # §7/B1 counts SL events per calendar day; strategy_lab's per-day columns use
    # distinct session dates, which is what the 10-15 report quoted (5.2/day).
    days = max(1, len(sessions))
    sl_per_day = counts["SL"] / days
    sl_share = 100.0 * counts["SL"] / n
    scratch_pct = 100.0 * counts["BE"] / n
    avg_sl = (sl_loss / sl_n) if sl_n else None
    # The §7 bar's R/trade is quoted from win_rate_report.py --spread's cost view:
    # (gross $ per trade) / (mean 1R in $), on ALL trades incl. BE/TIME. Aligning to
    # the tool's own convention is what lets the panel's verdict be the tool's verdict;
    # the decisive-only mean (per-trade risk) is kept alongside as a secondary read.
    one_r_usd = _median(one_r) if one_r else None
    mean_1r = (sum(one_r) / len(one_r)) if one_r else None
    r_per_trade = ((gross / n) / mean_1r) if mean_1r else None
    r_per_trade_decisive = (r_sum / r_n) if r_n else None
    level_bound_pct = 100.0 * level_bound / len(risks_atr) if risks_atr else None
    median_risk_atr = _median(risks_atr)

    checks = {
        "B1": {"name": "SL events / day", "value": sl_per_day, "bar": BAR_SL_PER_DAY,
               "cmp": "≤", "unit": "/day", "ok": sl_per_day <= BAR_SL_PER_DAY, "baseline": "8.2/day"},
        "B2": {"name": "SL share of closed", "value": sl_share, "bar": BAR_SL_SHARE_PCT,
               "cmp": "≤", "unit": "%", "ok": sl_share <= BAR_SL_SHARE_PCT, "baseline": "45.4%"},
        "B3": {"name": "Scratch (BE) share", "value": scratch_pct, "bar": BAR_SCRATCH_PCT,
               "cmp": "≤", "unit": "%", "ok": scratch_pct <= BAR_SCRATCH_PCT, "baseline": "32.8%"},
        "C1": {"name": "R/trade (gross)", "value": r_per_trade, "bar": BAR_R_PER_TRADE,
               "cmp": "≥", "unit": "R", "ok": (r_per_trade is not None and r_per_trade >= BAR_R_PER_TRADE),
               "baseline": "$/trade ÷ mean 1R (win_rate_report scale)"},
        "C2": {"name": "Decisive WR", "value": wr, "bar": BAR_WR_PCT,
               "cmp": "≥", "unit": "%", "ok": wr >= BAR_WR_PCT, "baseline": "36%"},
    }
    reverts = {
        "R4": {"name": "R/trade ≤ −0.20R", "fired": (r_per_trade is not None and r_per_trade <= REVERT_R_PER_TRADE),
               "value": r_per_trade},
        "R5": {"name": f"avg SL loss > {REVERT_SL_MULTIPLE:.1f}× pre-change (${PRE_CHANGE_AVG_SL_USD:.2f})",
               "fired": (avg_sl is not None and avg_sl > REVERT_SL_MULTIPLE * PRE_CHANGE_AVG_SL_USD),
               "value": avg_sl},
        "R7": {"name": f"era drawdown > ${REVERT_DD_USD:.0f}", "fired": max_dd > REVERT_DD_USD,
               "value": max_dd},
    }
    geometry = {
        "A4": {"name": "Level-bound share", "value": level_bound_pct, "unit": "%", "lo": BAR_LEVEL_BOUND[0],
               "hi": BAR_LEVEL_BOUND[1],
               "ok": (level_bound_pct is not None and BAR_LEVEL_BOUND[0] <= level_bound_pct <= BAR_LEVEL_BOUND[1]),
               "baseline": "replay 80.2%"},
        "A5": {"name": "Median risk (ATR)", "value": median_risk_atr, "unit": " ATR", "lo": BAR_MEDIAN_RISK_ATR[0],
               "hi": BAR_MEDIAN_RISK_ATR[1],
               "ok": (median_risk_atr is not None and BAR_MEDIAN_RISK_ATR[0] <= median_risk_atr <= BAR_MEDIAN_RISK_ATR[1]),
               "baseline": "replay 3.07"},
    }
    screen_ok = all(c["ok"] for c in checks.values())
    pass_ok = screen_ok and n >= BAR_PASS_N and lb > BREAKEVEN_WR_PCT
    status = ("SCREEN MET" if screen_ok else "SCREEN NOT MET")
    if pass_ok:
        status = "PASS (n≥150 & Wilson LB > 32.1%)"
    elif screen_ok and n < BAR_PASS_N:
        status = f"SCREEN MET — {BAR_PASS_N - n} trades short of PASS"
    if any(r["fired"] for r in reverts.values()):
        status = "REVERT TRIGGER FIRED"
    return {
        "label": label, "n": n, "cutover": cutover, "sessions": days,
        "counts": counts, "gross": gross, "gross_per_trade": gross / n,
        "wr": wr, "wr_ci": (lb, ub), "r_per_trade": r_per_trade,
        "r_per_trade_decisive": r_per_trade_decisive, "mean_1r_usd": mean_1r,
        "sl_per_day": sl_per_day, "sl_share_pct": sl_share, "scratch_pct": scratch_pct,
        "avg_sl_usd": avg_sl, "max_dd": max_dd,
        "level_bound_pct": level_bound_pct, "median_risk_atr": median_risk_atr,
        "median_risk_usd": _median([trade_risk(t) for t in era]),
        "checks": checks, "reverts": reverts, "geometry": geometry,
        "screen_ok": screen_ok, "pass_ok": pass_ok,
        "revert_fired": any(r["fired"] for r in reverts.values()),
        "status": status,
        "trades_to_pass": max(0, BAR_PASS_N - n),
        "last_entry": max((parse_ts(t.get("Entry_Time")) for t in era if parse_ts(t.get("Entry_Time"))),
                          default=None),
    }


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def open_trade_read(status, price):
    """Unrealized progress of the open trade in $ and R, from the last logged close.

    Risk is recovered from the REWARD leg (|TP − Entry| ÷ 1.5, HANDOFF §8) so a
    ratcheted stop does not shrink the denominator mid-trade; `to_tp` / `to_sl`
    are the $ still left to each geometry. The page has no ticker of its own, so
    `price` is the newest logged close — labelled as such on screen.
    """
    if not status.get("trade_active"):
        return None
    entry, tp, sl = (parse_float(status.get(k))
                     for k in ("entry_price", "take_profit", "stop_loss"))
    if entry is None or tp is None or price is None or tp == entry:
        return None
    risk = abs(tp - entry) / RR_TARGET
    direction = 1.0 if (status.get("trade_type") or "BUY") == "BUY" else -1.0
    return {
        "price": price, "risk": risk,
        "pnl": (price - entry) * direction,
        "r_now": (price - entry) * direction / risk,
        "be_price": entry + direction * BE_TRIGGER_R * risk, "be_trigger_r": BE_TRIGGER_R,
        "to_tp": abs(tp - price), "to_sl": abs(sl - price) if sl is not None else 0.0,
    }


def book_read(trades, now=None):
    """Today's activity + the running streak picture (no wall-clock inside)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.strftime("%Y-%m-%d")
    todays = [t for t in trades if (t.get("Exit_Time") or "").startswith(today)]
    counts = {"TP": 0, "SL": 0, "BE": 0, "TIME": 0}
    pnl = 0.0
    for t in todays:
        reason = (t.get("Exit_Reason") or "").strip().upper()
        if reason in counts:
            counts[reason] += 1
        pnl += parse_float(t.get("Profit")) or 0.0
    last = trades[-1] if trades else None
    return {
        "today": today, "n": len(todays), "counts": counts, "pnl": pnl,
        "last": last,
        "last_20": "".join({"TP": "W", "SL": "L", "BE": "·", "TIME": "T"}.get(
            (t.get("Exit_Reason") or "").strip().upper(), "?") for t in trades[-20:]),
    }


def market_quiet(dt):
    """Mirror of engine.is_market_quiet: weekend, or the broker daily break.

    Gold spot ticks ~02:00–21:00 UTC Mon–Fri (the broker break observed in this
    log runs ~21:15–01:41). A silent log there is normal; anywhere else it is the
    2026-09-29 signature and must be shown, not smoothed over.
    """
    if dt.weekday() >= 5:
        return True
    return dt.hour >= 21 or dt.hour < 2


def feed_read(log_rows, now=None, tail_minutes=60):
    """Last-bar age, bar take in the last `tail_minutes`, and OPEN-MARKET gaps."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if not log_rows:
        return {"ok": False, "reason": "no log rows"}
    ts = [parse_ts(r.get("Timestamp")) for r in log_rows]
    known = [t for t in ts if t is not None]
    if not known:
        return {"ok": False, "reason": "no parseable timestamps"}
    last = known[-1]
    hour_bars = sum(1 for t in known if t > last - timedelta(minutes=tail_minutes))
    # A gap is suspicious only if the market was expected open at BOTH ends: the
    # weekly close (Fri 20:57 -> Sun 22:00 in this log) and the daily break would
    # otherwise be reported as a 49-hour/hour-long "outage". The lost time is
    # counted in OPEN-MARKET minutes, the unit the 2026-09-29 review used
    # (a 583-min wall gap = ~283 open-market minutes).
    gaps, micro = [], 0
    for a, b in zip(known, known[1:]):
        minutes = (b - a).total_seconds() / 60.0
        if minutes <= 2.0 or market_quiet(a) or market_quiet(b):
            continue
        open_minutes = 0.0
        step = a
        while step < b:
            if not market_quiet(step):
                open_minutes += 1.0
            step += timedelta(minutes=1)
        if open_minutes >= 5.0:
            gaps.append({"start": a, "end": b, "wall_minutes": minutes,
                         "open_minutes": open_minutes})
        else:
            micro += 1
    return {
        "ok": True, "last_bar": last, "age_seconds": int((now - last).total_seconds()),
        f"bars_{tail_minutes}m": hour_bars,
        "gaps": len(gaps), "micro_gaps": micro,
        "largest_gap_minutes": max((g["open_minutes"] for g in gaps), default=0.0),
        "gap_detail": sorted(gaps, key=lambda g: -g["open_minutes"])[:3],
        "first_bar": known[0], "rows": len(log_rows), "quiet_now": market_quiet(last),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. CALIBRATION — does the composite separate outcomes? Measure, don't assert.
# ─────────────────────────────────────────────────────────────────────────────

def _feature_at_entry(trade, s, ts_list):
    """Pressure features of the last bar STRICTLY BEFORE the entry minute.

    HANDOFF §8: the log lags the ledger by ~1 min, so the entry bar itself must
    never be part of a pre-entry feature.
    """
    entry = parse_ts(trade.get("Entry_Time"))
    if entry is None:
        return None
    # bisect without importing it: the arrays are small and monotonic
    import bisect
    k = bisect.bisect_left(ts_list, entry) - 1
    if k < PRESSURE_WINDOW:
        return None
    atr = s["atr"][k]
    if not atr:
        return None
    num = den = 0.0
    for j in range(k - PRESSURE_WINDOW + 1, k + 1):
        o, c, h, l = s["open"][j], s["close"][j], s["high"][j], s["low"][j]
        if None in (o, c, h, l):
            continue
        rng = h - l
        if rng <= 0:
            continue
        num += ((c - o) / rng) * s["volume"][j]
        den += s["volume"][j]
    if den <= 0 or s["close"][k - PRESSURE_WINDOW + 1] is None:
        return None
    flow = num / den
    momentum = (s["close"][k] - s["close"][k - PRESSURE_WINDOW + 1]) / atr
    trend = ((s["ema_fast"][k] - s["ema_slow"][k]) / atr
             if (s["ema_fast"][k] is not None and s["ema_slow"][k] is not None) else 0.0)
    kk = k - EMA_SLOPE_LOOKBACK
    slope = ((s["ema_fast"][k] - s["ema_fast"][kk]) / atr
             if (kk >= 0 and s["ema_fast"][k] is not None and s["ema_fast"][kk] is not None) else 0.0)
    rsi = s["rsi"][k] if s["rsi"][k] is not None else 50.0
    shares = {
        "flow": (flow + 1.0) / 2.0,
        "momentum": _sigmoid(momentum / 1.5),
        "trend": _sigmoid(trend / 0.5),
        "slope": _sigmoid(slope / 0.5),
        "rsi": _clip01((_clip01((rsi - 50.0) / 20.0 + 1.0) / 2.0)),
    }
    buy_pct = 100.0 * sum(shares[k_] * w for k_, w in PRESSURE_WEIGHTS.items())
    risk = trade_risk(trade)
    profit = parse_float(trade.get("Profit"))
    return {
        "buy_pct": buy_pct, "side": (trade.get("Trade_Type") or "").strip().upper(),
        "reason": (trade.get("Exit_Reason") or "").strip().upper(),
        "profit": profit, "risk": risk,
        "r": (profit / risk) if (risk and profit is not None) else None,
    }


def calibration(log_rows, trades, cutover=STRUCT_STOP_CUTOVER):
    """Per-side pressure buckets in the current era, with an honest verdict.

    The split is fixed in advance (and mirrored in tools/pressure_report.py):
    for each side, "aligned" = the tape pushes that side's way (BUY: buy_pct ≥ 58,
    SELL: buy_pct ≤ 42), "mixed" = the middle band, "against" = the tape pushes the
    other way. One split, three buckets, no slicing to fit. `verdict` refuses to
    call a difference a signal when the decisive sample is too small or the gap is
    inside the noise it reports.
    """
    if not log_rows or not trades:
        return {"ok": False, "reason": "needs the log and the ledger"}
    s = _series(log_rows)
    ts_list = [t if t is not None else datetime.min for t in s["ts"]]
    era = []
    for t in trades:
        f = _feature_at_entry(t, s, ts_list)
        if not f:
            continue
        et = parse_ts(t.get("Entry_Time"))
        if et is None or et < cutover:
            continue
        era.append(f)

    if not era:
        return {"ok": False, "reason": f"no joinable trades in the era (cutover {cutover:%Y-%m-%d %H:%M})"}

    def bucket_of(side, buy_pct):
        if side == "BUY":
            if buy_pct >= 58:
                return "aligned"
            return "mixed" if buy_pct >= 42 else "against"
        if buy_pct <= 42:
            return "aligned"
        return "mixed" if buy_pct <= 58 else "against"

    table = {}
    within = {}
    for side in ("BUY", "SELL"):
        rows = [f for f in era if f["side"] == side]
        per = {}
        for name in ("aligned", "mixed", "against"):
            sub = [f for f in rows if bucket_of(side, f["buy_pct"]) == name]
            tp = sum(1 for f in sub if f["reason"] == "TP")
            sl = sum(1 for f in sub if f["reason"] == "SL")
            dec = tp + sl
            rs = [f["r"] for f in sub if f["r"] is not None and f["reason"] in ("TP", "SL")]
            per[name] = {
                "n": len(sub), "tp": tp, "sl": sl, "dec": dec,
                "wr": (100.0 * tp / dec) if dec else None,
                "r_per_trade": (sum(rs) / len(rs)) if rs else None,
            }
        table[side] = per
        vals = sorted(f["buy_pct"] for f in rows)
        within[side] = {
            "n": len(vals),
            "min": vals[0] if vals else None,
            "median": _median(vals),
            "max": vals[-1] if vals else None,
        }

    # verdict on the one pre-specified contrast: aligned vs the rest
    gaps = {}
    for side in ("BUY", "SELL"):
        al = table[side]["aligned"]
        rest_rows = [f for f in era if f["side"] == side and bucket_of(side, f["buy_pct"]) != "aligned"]
        tp = sum(1 for f in rest_rows if f["reason"] == "TP")
        sl = sum(1 for f in rest_rows if f["reason"] == "SL")
        dec = tp + sl
        rest_wr = (100.0 * tp / dec) if dec else None
        rs = [f["r"] for f in rest_rows if f["r"] is not None and f["reason"] in ("TP", "SL")]
        gaps[side] = {
            "aligned_wr": al["wr"], "aligned_n": al["n"], "aligned_dec": al["dec"],
            "rest_wr": rest_wr, "rest_n": len(rest_rows), "rest_dec": dec,
            "wr_gap": (al["wr"] - rest_wr) if (al["wr"] is not None and rest_wr is not None) else None,
            "r_gap": ((al["r_per_trade"] or 0) - (sum(rs) / len(rs) if rs else 0))
            if (al["r_per_trade"] is not None) else None,
        }

    # Why this matters: the engine's trend gate keys side on EMA50 vs EMA200, so a
    # BUY almost cannot print with low buy-pressure. Degeneracy is the EXPECTED
    # result here, not a bug — and it is the honest reason to show the composite as
    # context rather than as a signal (HANDOFF §8, same trap as pooled momentum).
    degenerate = all(
        (table[s]["aligned"]["n"] / max(1, within[s]["n"] or 1)) >= 0.85 or
        (table[s]["against"]["n"] + table[s]["mixed"]["n"]) < 10
        for s in ("BUY", "SELL"))
    small = any(min(g["aligned_dec"], g["rest_dec"]) < 20 for g in gaps.values())
    noisy = all((g["wr_gap"] is None or abs(g["wr_gap"]) < 10.0) for g in gaps.values())
    if degenerate:
        verdict, reliable, reason = (
            "collinear with side — not separable within-side",
            False,
            "the trend gate means BUYs print with high buy-pressure and SELLs with low; "
            "the aligned bucket is ~all of each side, so there is nothing to contrast inside it")
    elif small:
        verdict, reliable, reason = ("no measurable separation", False, "decisive sample too small")
    elif noisy:
        verdict, reliable, reason = ("no measurable separation", False,
                                     "aligned-vs-rest gap inside ±10 pp noise")
    else:
        verdict, reliable, reason = (
            "separation worth re-testing (still not a gate)", False,
            "gap larger than the noise floor at this n — pre-register a bar before using it")
    return {
        "ok": True, "cutover": cutover, "n": len(era), "table": table, "gaps": gaps,
        "within_side": within, "degenerate": degenerate,
        "verdict": verdict, "reliable": reliable, "reason": reason,
        "era_label": f"entries ≥ {cutover:%Y-%m-%d %H:%M} UTC",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5b. SIGNAL OUTLOOK — "given a very strong signal, where did price head?"
# Historical frequencies over this bot's own taken signals. Not a forecast.
# ─────────────────────────────────────────────────────────────────────────────

# analysis choices (NOT engine mirrors — nothing here feeds a gate):
OUTLOOK_HORIZONS = (15, 30, 60, 240)     # minutes ahead; 240 = MAX_HOLD lifetime
OUTLOOK_PRIMARY_HORIZON = 30             # struct-era median hold ~25 min (whole book ~9)
OUTLOOK_MAX_GAP_MIN = 5.0                # a bigger log hole censors the window
OUTLOOK_TAIL_SLACK_MIN = 2.0             # last bar must reach the horizon (− slack)
OUTLOOK_MIN_COVERAGE = 0.7               # need >= 70% of the horizon's 1-min bars
OUTLOOK_COST_USD = 0.40                  # assumed round trip (registered, not measured)


def _quantile(values, p):
    """Linear-interpolated quantile of the non-None values (None when empty)."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    f = int(k)
    return vals[f] + (vals[f + 1] - vals[f]) * (k - f) if f + 1 < len(vals) else vals[f]


def _outlook_bars(rows):
    """Parsed, time-sorted OHLC bars for the forward walks (tolerant, like the rest)."""
    bars = []
    for r in rows:
        ts = parse_ts(r.get("Timestamp"))
        o, h, l, c = (parse_float(r.get(k)) for k in ("Open", "High", "Low", "Close"))
        if ts is None or None in (o, h, l, c):
            continue
        bars.append({"ts": ts, "o": o, "h": h, "l": l, "c": c,
                     "ema_fast": parse_float(r.get("EMA_50")),
                     "ema_slow": parse_float(r.get("EMA_200")),
                     "atr": parse_float(r.get("ATR"))})
    bars.sort(key=lambda b: b["ts"])
    return bars


def _forward_window(bars, ts_list, start, horizon_min):
    """Bars in (start, start+horizon], or None when the window is censored.

    Censored (never guessed across): a log gap > OUTLOOK_MAX_GAP_MIN inside the
    window, the tail falling short of the horizon (market closure / end of log),
    or < OUTLOOK_MIN_COVERAGE of the expected 1-min bars present.
    """
    import bisect
    end = start + timedelta(minutes=horizon_min)
    w = bars[bisect.bisect_right(ts_list, start):bisect.bisect_right(ts_list, end)]
    if not w:
        return None
    prev = start
    for b in w:
        if (b["ts"] - prev).total_seconds() / 60.0 > OUTLOOK_MAX_GAP_MIN:
            return None
        prev = b["ts"]
    if (end - w[-1]["ts"]).total_seconds() / 60.0 > OUTLOOK_TAIL_SLACK_MIN:
        return None
    if len(w) < OUTLOOK_MIN_COVERAGE * horizon_min:
        return None
    return w


def _forward_path(window, side, entry, risk, atr, cost):
    """Signed forward facts for one signal. + always means 'the trade's way'.

    Drift/MFE/MAE describe the raw price path over the full window (exits and
    the BE ever-hit flags count touches anywhere in the window, while `race`
    is the first of the +1.5R / −1R barriers to print ("AMB" when one 1-min
    bar spans both — intrabar order is unknowable from this log). A SELL's
    favourable extreme is the bar LOW (HANDOFF §8).
    """
    d = 1.0 if side == "BUY" else -1.0
    drift = d * (window[-1]["c"] - entry)
    if side == "BUY":
        mfe = max(b["h"] for b in window) - entry
        mae = entry - min(b["l"] for b in window)
    else:
        mfe = entry - min(b["l"] for b in window)
        mae = max(b["h"] for b in window) - entry
    tp_lvl = entry + d * RR_TARGET * risk
    sl_lvl = entry - d * risk
    be_lvl = entry + d * BE_TRIGGER_R * risk
    ever = {"tp": False, "sl": False, "be": False}
    race = None
    for b in window:
        if side == "BUY":
            hit_tp, hit_sl, hit_be = b["h"] >= tp_lvl, b["l"] <= sl_lvl, b["h"] >= be_lvl
        else:
            hit_tp, hit_sl, hit_be = b["l"] <= tp_lvl, b["h"] >= sl_lvl, b["l"] <= be_lvl
        ever["tp"] |= hit_tp
        ever["sl"] |= hit_sl
        ever["be"] |= hit_be
        if race is None and (hit_tp or hit_sl):
            race = "AMB" if (hit_tp and hit_sl) else ("TP" if hit_tp else "SL")
    return {
        "drift_usd": drift, "drift_r": drift / risk,
        "drift_atr": (drift / atr) if atr else None,
        "fav": drift > 0, "fav_cost": drift > cost,
        "mfe_r": mfe / risk, "mae_r": mae / risk,
        "ever_tp": ever["tp"], "ever_sl": ever["sl"], "ever_be": ever["be"],
        "race": race,
    }


def _summarise_paths(paths):
    """One horizon cell: how often, how far, which barrier first (Wilson CIs)."""
    n = len(paths)
    if not n:
        return {"n": 0}
    fav = sum(1 for p in paths if p["fav"])
    fav_cost = sum(1 for p in paths if p["fav_cost"])
    race_tp = sum(1 for p in paths if p["race"] == "TP")
    race_sl = sum(1 for p in paths if p["race"] == "SL")
    decisive = race_tp + race_sl
    dr = [p["drift_r"] for p in paths]
    return {
        "n": n,
        "fav_n": fav, "fav_pct": 100.0 * fav / n, "fav_ci": wilson_interval(fav, n),
        "fav_cost_n": fav_cost, "fav_cost_pct": 100.0 * fav_cost / n,
        "fav_cost_ci": wilson_interval(fav_cost, n),
        "drift_r_median": _quantile(dr, 0.5), "drift_r_mean": sum(dr) / n,
        "drift_r_q25": _quantile(dr, 0.25), "drift_r_q75": _quantile(dr, 0.75),
        "drift_atr_median": _quantile([p["drift_atr"] for p in paths], 0.5),
        "drift_usd_median": _quantile([p["drift_usd"] for p in paths], 0.5),
        "mfe_r_median": _quantile([p["mfe_r"] for p in paths], 0.5),
        "mae_r_median": _quantile([p["mae_r"] for p in paths], 0.5),
        "ever_be_pct": 100.0 * sum(1 for p in paths if p["ever_be"]) / n,
        "ever_tp_pct": 100.0 * sum(1 for p in paths if p["ever_tp"]) / n,
        "ever_sl_pct": 100.0 * sum(1 for p in paths if p["ever_sl"]) / n,
        "race_tp": race_tp, "race_sl": race_sl,
        "race_amb": sum(1 for p in paths if p["race"] == "AMB"),
        "race_none": sum(1 for p in paths if p["race"] is None),
        "race_decisive": decisive,
        "tp_first_pct": (100.0 * race_tp / decisive) if decisive else None,
        "tp_first_ci": wilson_interval(race_tp, decisive) if decisive else (None, None),
    }


def signal_outlook(log_rows, trades, cutover=STRUCT_STOP_CUTOVER,
                   horizons=OUTLOOK_HORIZONS, cost=OUTLOOK_COST_USD):
    """Where price actually went after this bot's full (all-gates) signals.

    The sample is the ledger itself: every closed trade IS a "very strong
    signal" by the engine's own definition (all funnel gates + the risk layer
    passed). Skipped signals are excluded on purpose — `skipped_trades.csv`
    does not log a side, and reconstructing one would need a second funnel
    implementation that can drift. The one-position rule also censors
    overlapping signals; this measures the signals the bot acted on.

    Risk is the reward leg (HANDOFF §8), so ratcheted rows keep their original
    geometry. The path starts at the first bar stamped strictly after
    Entry_Time (the signal bar's own range is never counted). Baseline =
    non-overlapping every-Hth-bar drift in the EMA-trend direction over the
    same era — "just follow the trend anywhere" — so the signal rows have
    something honest to beat. Display-only: no number here is an entry
    condition, a sizing input or a forecast (docs/HANDOFF.md §11).
    """
    if not log_rows or not trades:
        return {"ok": False, "reason": "needs the log and the ledger"}
    bars = _outlook_bars(log_rows)
    if not bars:
        return {"ok": False, "reason": "no parsable log bars"}
    ts_list = [b["ts"] for b in bars]

    sample, excluded = [], 0
    for t in trades:
        et = parse_ts(t.get("Entry_Time"))
        side = (t.get("Trade_Type") or "").strip().upper()
        entry = parse_float(t.get("Entry_Price"))
        atr = parse_float(t.get("ATR_At_Entry"))
        risk = trade_risk(t)
        if et is None or et < cutover:
            continue
        if side not in ("BUY", "SELL") or entry is None or not risk or not atr:
            excluded += 1
            continue
        xt = parse_ts(t.get("Exit_Time"))
        sample.append({"side": side, "entry_t": et, "entry": entry, "risk": risk,
                       "atr": atr, "reason": (t.get("Exit_Reason") or "").strip().upper(),
                       "hold_min": ((xt - et).total_seconds() / 60.0) if xt else None})
    if not sample:
        return {"ok": False, "reason": f"no usable trades in the era (cutover {cutover:%Y-%m-%d %H:%M})"}

    def group(rows):
        counts = {"TP": 0, "SL": 0, "BE": 0, "TIME": 0, "other": 0}
        for r in rows:
            counts[r["reason"] if r["reason"] in counts else "other"] += 1
        cells = {}
        for h in horizons:
            paths = []
            for r in rows:
                w = _forward_window(bars, ts_list, r["entry_t"], h)
                if w is not None:
                    paths.append(_forward_path(w, r["side"], r["entry"], r["risk"], r["atr"], cost))
            cell = _summarise_paths(paths)
            cell["censored"] = len(rows) - cell["n"]
            cells[h] = cell
        return {"n": len(rows), "outcomes": counts, "horizons": cells}

    baseline = {}
    for h in horizons:
        drifts, i = [], 0
        while i < len(bars):
            b = bars[i]
            i += h
            if b["ts"] < cutover or None in (b["ema_fast"], b["ema_slow"]) or not b["atr"]:
                continue
            if b["ema_fast"] == b["ema_slow"]:
                continue
            w = _forward_window(bars, ts_list, b["ts"], h)
            if w is None:
                continue
            d = 1.0 if b["ema_fast"] > b["ema_slow"] else -1.0
            drifts.append(d * (w[-1]["c"] - b["c"]) / b["atr"])
        fav = sum(1 for v in drifts if v > 0)
        baseline[h] = {"n": len(drifts),
                       "fav_pct": (100.0 * fav / len(drifts)) if drifts else None,
                       "fav_ci": wilson_interval(fav, len(drifts)) if drifts else (None, None),
                       "drift_atr_median": _quantile(drifts, 0.5)}

    holds = [r["hold_min"] for r in sample if r["hold_min"] is not None]
    return {
        "ok": True, "cutover": cutover, "cost": cost, "horizons": tuple(horizons),
        "era_label": f"entries ≥ {cutover:%Y-%m-%d %H:%M} UTC",
        "n": len(sample), "excluded": excluded,
        "hold_median_min": _quantile(holds, 0.5), "hold_p90_min": _quantile(holds, 0.9),
        # driftless first-hit probability for +1.5R vs −1R (no ratchet/costs):
        "barrier_reference_pct": 100.0 / (1.0 + RR_TARGET),
        "pooled": group(sample),
        "sides": {s: group([r for r in sample if r["side"] == s]) for s in ("BUY", "SELL")},
        "baseline": baseline,
    }


def outlook_now(setup, outlook, horizon=OUTLOOK_PRIMARY_HORIZON):
    """Apply the era base rates to the last bar IF a side is fully ready (8/8).

    The cone transfers historical drift in R onto today's structural risk
    (cone = entry ± drift-R quantile × today's risk) — an explicit assumption,
    printed wherever the numbers are shown. Returns ready_side=None (with the
    gate counts) when no side passed every gate: there is no "almost" read.
    """
    if not setup.get("ok"):
        return {"ok": False, "reason": setup.get("reason", "setup unavailable")}
    if not outlook.get("ok"):
        return {"ok": False, "reason": outlook.get("reason", "outlook unavailable")}
    out = {"ok": True, "horizon": horizon, "as_of": setup.get("as_of"),
           "close": setup["close"], "ready_side": None,
           "passed": {s: setup[s]["passed"] for s in ("BUY", "SELL")},
           "total": {s: setup[s]["total"] for s in ("BUY", "SELL")}}
    for side in ("BUY", "SELL"):
        if not setup[side].get("ready"):
            continue
        level = setup[side]["level"]
        risk = structural_risk(setup["close"], setup["atr"], level)
        d = 1.0 if side == "BUY" else -1.0
        cell = outlook["sides"][side]["horizons"].get(horizon, {})
        pooled = outlook["pooled"]["horizons"].get(horizon, {})

        def cone(c):
            if not c.get("n") or c.get("drift_r_median") is None:
                return None
            return {"q25": setup["close"] + d * c["drift_r_q25"] * risk,
                    "median": setup["close"] + d * c["drift_r_median"] * risk,
                    "q75": setup["close"] + d * c["drift_r_q75"] * risk}

        applied = []
        for h in outlook["horizons"]:
            c = outlook["sides"][side]["horizons"].get(h, {})
            cn = cone(c)
            if not cn:
                continue
            lo, hi = sorted((cn["q25"], cn["q75"]))
            applied.append({"horizon": h, "n": c["n"], "fav_pct": c["fav_pct"],
                            "fav_ci": c["fav_ci"], "tp_first_pct": c["tp_first_pct"],
                            "tp_first_ci": c["tp_first_ci"],
                            "drift_r_median": c["drift_r_median"],
                            "cone_lo": lo, "cone_median": cn["median"], "cone_hi": hi})
        out.update({"ready_side": side, "entry": setup["close"], "risk": risk,
                    "level": level,
                    "stop": setup["close"] - d * risk,
                    "target": setup["close"] + d * RR_TARGET * risk,
                    "cell": cell, "pooled_cell": pooled, "cone": cone(cell),
                    "applied": applied,
                    "side_n": outlook["sides"][side]["n"]})
        break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 5c. BOX READ — where the boxes are, and whether a box trade's conditions line up
# Display-only. Measured on this log on 2026-10-20: not one breakout or fade
# geometry cleared its driftless reference (8 cells, 2 box sizes, 4 sessions),
# and 74-75% of closes outside a box are back inside within 15 minutes.
# So a box is a place to PUT A STOP, not a place to READ A PREDICTION
# (docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md). Nothing here is an
# entry rule, a sizing rule or a reason to hold past a stop.
# ─────────────────────────────────────────────────────────────────────────────

BOX_SPREAD_USD = 0.55        # round trip, $/oz — the quote logger's measured median
BOX_EDGE_ATR = 0.50          # "at an edge" = the close is within this many ATR
BOX_BREAK_ATR = 0.10         # a close this far beyond an edge = confirmed break
BOX_REJECT_ATR = 0.15        # wick through the edge + a close this far back inside = rejection
BOX_CLEAR_ATR = 0.50         # stop clearance beyond the far edge
BOX_COST_SHARE_OK = 10.0     # cost as % of R — below this, geometry is not the problem
BOX_COST_SHARE_MAX = 20.0    # above this, the spread IS most of the trade
BOX_GAP_MINUTES = 3.0        # a bar-to-bar gap this long splits the tape
BOX_FRESH_BARS = 3           # a break only counts if price was inside that box recently
BOX_SIZES = ((20, "20-bar level (engine's own)"),
             (60, "last 1h (60 bars)"),
             (240, "last 4h (240 bars)"))
BOX_PRIOR_DAY_MIN_BARS = 600  # a Sunday evening is not a day to draw a box on
BOX_FEED_STALE_SECONDS = 300

# The measured verdict, copied from the 2026-10-20 analysis — printed wherever
# the panel could otherwise be mistaken for a signal. Scenario U pins these.
BOX_MEASURED = {
    "source": "docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md",
    "cells": 8, "cleared": 0,
    "false_break_pct_20": 74.0, "false_break_pct_60": 75.0,
    "best": "stop outside the whole box + a 1-box target (near break-even, not an edge)",
}


def _box_bars(rows):
    """(ts, high, low, close, atr) tuples, oldest first. Bad rows are dropped."""
    bars = []
    for r in rows:
        ts = parse_ts(r.get("Timestamp"))
        h = parse_float(r.get("High"))
        l = parse_float(r.get("Low"))
        c = parse_float(r.get("Close"))
        if ts is None or h is None or l is None or c is None:
            continue
        bars.append((ts, h, l, c, parse_float(r.get("ATR"))))
    bars.sort(key=lambda b: b[0])
    return bars


def _box_run_offsets(bars, gap_minutes=BOX_GAP_MINUTES):
    """Index of the first bar of the contiguous run each bar belongs to."""
    start = [0] * len(bars)
    for i in range(1, len(bars)):
        if (bars[i][0] - bars[i - 1][0]).total_seconds() / 60.0 > gap_minutes:
            start[i] = i
        else:
            start[i] = start[i - 1]
    return start


def _box_bounds(bars, i, n, start):
    """(high, low) of the n bars STRICTLY before i, like the engine's floor."""
    if i - start[i] < n:
        return None
    prior = bars[i - n:i]
    hi = max(b[1] for b in prior)
    lo = min(b[2] for b in prior)
    return (hi, lo) if hi > lo else None


def _box_side_read(close, atr, box_hi, box_lo, edge, far, side, spread):
    """Structural and far-edge numbers for one side of one box."""
    engine_risk = structural_risk(close, atr, edge) if atr else None
    far_risk = abs(close - far) + BOX_CLEAR_ATR * atr if atr else None
    width = box_hi - box_lo
    return {
        "side": side, "edge": edge, "far": far,
        "engine_risk": engine_risk, "engine_tp": (RR_TARGET * engine_risk) if engine_risk else None,
        "far_risk": far_risk, "far_tp": (width if far_risk else None),   # measured move, 1 box
        "far_rr": (width / far_risk) if far_risk else None,
        "cost_share_pct": (100.0 * spread / far_risk) if far_risk else None,
        "cost_share_engine_pct": (100.0 * spread / engine_risk) if engine_risk else None,
        "cost_usd": spread,
    }


def box_geometry(rows, spread=BOX_SPREAD_USD):
    """Every box the operator would draw, the nearest edge, and the trigger.

    Pure geometry over the rows it is given (no clock, no portfolio) so the
    dashboard can cache it and the CLI can reuse it.
    """
    bars = _box_bars(rows)
    if len(bars) < 25:
        return {"ok": False, "reason": "not enough bars for a box read"}
    start = _box_run_offsets(bars)
    i = len(bars) - 1
    ts, _h, _l, close, atr = bars[i]
    out = {"ok": True, "as_of": ts, "close": close, "atr": atr, "bars": len(bars), "boxes": []}
    if not atr or atr <= 0:
        return {"ok": False, "reason": "ATR unavailable on the last bar"}

    specs = []
    for n, name in BOX_SIZES:
        bounds = _box_bounds(bars, i, n, start)
        if bounds:
            specs.append((name, bounds[0], bounds[1]))

    # prior trading day: the most recent complete UTC date with enough bars
    today = ts.date()
    by_day = {}
    for b in bars:
        if b[0].date() < today:
            by_day.setdefault(b[0].date(), []).append(b)
    for d in sorted(by_day, reverse=True):
        day_bars = by_day[d]
        if len(day_bars) >= BOX_PRIOR_DAY_MIN_BARS:
            specs.append((f"prior day {d} (UTC)",
                          max(b[1] for b in day_bars), min(b[2] for b in day_bars)))
            break

    for name, hi, lo in specs:
        width = hi - lo
        box = {"name": name, "high": hi, "low": lo, "width": width,
               "width_atr": width / atr,
               "pos_pct": 100.0 * (close - lo) / width if width > 0 else None,
               "dist_up_usd": hi - close, "dist_down_usd": close - lo,
               "dist_up_atr": (hi - close) / atr, "dist_down_atr": (close - lo) / atr}
        box["buy"] = _box_side_read(close, atr, hi, lo, hi, lo, "BUY", spread)
        box["sell"] = _box_side_read(close, atr, hi, lo, lo, hi, "SELL", spread)
        out["boxes"].append(box)

    if not out["boxes"]:
        return {"ok": False, "reason": "no box could be built (short or gappy tape)"}

    # nearest edge, whichever box it belongs to
    nearest = None
    for box in out["boxes"]:
        for side, edge, dist in (("BUY", box["high"], box["dist_up_atr"]),
                                 ("SELL", box["low"], box["dist_down_atr"])):
            d = abs(dist)
            if nearest is None or d < nearest["distance_atr"]:
                nearest = {"box": box["name"], "side": side, "edge": edge,
                           "distance_usd": abs(edge - close), "distance_atr": d,
                           "width": box["width"]}
    out["nearest"] = nearest

    # trigger on the last closed bar: a FRESH break or a rejection at an edge.
    # "Fresh" matters: a box price left days ago is a fact about history, not a
    # setup. A break only counts if a close inside that box happened within the
    # last BOX_FRESH_BARS bars, so the crossing is the current event.
    trigger = {"state": "none", "side": None, "box": None, "detail": "no edge tested on the last bar"}
    best = None
    for box in out["boxes"]:
        hi, lo = box["high"], box["low"]
        was_inside_hi = any(bars[i - k][3] <= hi for k in range(1, BOX_FRESH_BARS + 1))
        was_inside_lo = any(bars[i - k][3] >= lo for k in range(1, BOX_FRESH_BARS + 1))
        # (distance, state, side, tested edge, opposite edge, edge name)
        candidates = []
        if close >= hi + BOX_BREAK_ATR * atr and was_inside_hi:   # fresh close beyond the top
            candidates.append(((close - hi) / atr, "break", "BUY", hi, lo, "high"))
        if close <= lo - BOX_BREAK_ATR * atr and was_inside_lo:   # fresh close beyond the bottom
            candidates.append(((lo - close) / atr, "break", "SELL", lo, hi, "low"))
        if _h >= hi and close <= hi - BOX_REJECT_ATR * atr:       # wick through the top, close back in
            candidates.append(((hi - close) / atr, "reject", "SELL", hi, lo, "high"))
        if _l <= lo and close >= lo + BOX_REJECT_ATR * atr:       # wick through the bottom, close back in
            candidates.append(((close - lo) / atr, "reject", "BUY", lo, hi, "low"))
        for dist, state, side, edge, far, edge_name in candidates:
            # the nearest edge wins: that is the box price is actually trading at
            if best is None or dist < best[0]:
                best = (dist, state, side, edge, far, edge_name, box)
    if best:
        dist, state, side, edge, far, edge_name, box = best
        trigger = {"state": state, "side": side, "box": box["name"], "edge": edge, "far": far,
                   "edge_name": edge_name, "strength_atr": dist,
                   "detail": (f"{'closed beyond' if state == 'break' else 'rejected'} the "
                              f"{box['name']} {edge_name} ({dist:.2f} ATR)")}
        entry = close
        if state == "break":
            stop = far - BOX_CLEAR_ATR * atr if side == "BUY" else far + BOX_CLEAR_ATR * atr
        else:                                  # fade back into the box
            stop = edge + BOX_CLEAR_ATR * atr if side == "SELL" else edge - BOX_CLEAR_ATR * atr
        risk = abs(entry - stop)
        target = (entry + box["width"]) if side == "BUY" else (entry - box["width"])
        reward = abs(target - entry)
        engine_risk = structural_risk(entry, atr, edge)
        trigger["setup"] = {
            "side": side, "entry": entry, "stop": stop, "target": target,
            "risk_usd": risk, "reward_usd": reward,
            "rr": (reward / risk) if risk else None,
            "cost_usd": spread, "cost_share_pct": (100.0 * spread / risk) if risk else None,
            "box": box["name"], "edge": edge, "far": far, "state": state,
            "edge_name": edge_name,
            # the engine's own rule on the same edge, for comparison
            "engine_risk": engine_risk,
            "engine_tp": RR_TARGET * engine_risk,
            "engine_cost_share_pct": (100.0 * spread / engine_risk) if engine_risk else None,
        }
    out["trigger"] = trigger
    return out


def box_status(geom, portfolio=None, feed=None, now=None, spread=BOX_SPREAD_USD):
    """The condition checklist and the one-line verdict, over a cached geometry.

    Every item is a measurement, not an instruction: the panel may say the
    conditions line up, and it must still print that the measured base rate has
    no edge. Nothing here can block or place a trade.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if not geom.get("ok"):
        return {"ok": False, "reason": geom.get("reason", "no geometry"), "geometry": geom,
                "checks": [], "verdict": {"code": "unavailable", "tone": "idle",
                                          "headline": "Box read unavailable",
                                          "detail": geom.get("reason", "")}}

    nearest = geom["nearest"]
    trig = geom["trigger"]
    setup = trig.get("setup")
    atr = geom["atr"]
    checks = []

    def add(key, label, state, detail):
        checks.append({"key": key, "label": label, "state": state, "detail": detail})

    # 1. location — is there anything to look at? A live trigger at an edge
    # counts as being at the edge even when the nearest-line distance is larger.
    loc_state = "pass" if (trig["state"] != "none" or nearest["distance_atr"] <= BOX_EDGE_ATR) else (
        "warn" if nearest["distance_atr"] <= 1.0 else "fail")
    add("location", "Location",
        loc_state,
        f"{abs(nearest['distance_atr']):.2f} ATR from the {nearest['box']} "
        f"{'high' if nearest['side'] == 'BUY' else 'low'} (${nearest['edge']:.2f})"
        + (" — at the edge" if loc_state == "pass" else
           " — mid-box, nothing to do" if loc_state == "fail" else " — approaching"))

    # 2. trigger — a closed bar beyond, or a rejection of, that edge
    if trig["state"] == "none":
        add("trigger", "Trigger", "fail", trig["detail"])
    else:
        add("trigger", "Trigger", "pass",
            f"{trig['detail']} → {trig['side']} {trig['state']} candidate")

    # 3. feed — a stale tape invalidates every number above. While the market is
    # closed a stale bar is EXPECTED (the 2026-09-29 lesson: a weekend silence is
    # not an outage), so the session check carries that verdict, not this one.
    if feed and feed.get("ok"):
        age = feed.get("age_seconds", 0)
        if market_quiet(now):
            add("feed", "Feed", "na",
                f"market closed — the last bar {age // 60} min ago is expected")
        else:
            add("feed", "Feed", "pass" if age <= 120 else (
                "warn" if age <= BOX_FEED_STALE_SECONDS else "fail"),
                f"last bar {age // 60} min ago" if age >= 60 else f"last bar {age} s ago")
    else:
        add("feed", "Feed", "na", "feed health unavailable")

    # 4. session — weekend / daily break / the engine's own blackouts
    side = setup["side"] if setup else None
    if market_quiet(now):
        add("session", "Session", "fail",
            f"market quiet at {now.strftime('%H:%M')} UTC (weekend or the daily break)")
    else:
        blocked = None
        for s in ([side] if side else ["BUY", "SELL"]):
            hit, label, _sides = _blackout_state(now, s)
            if hit:
                blocked = f"{label} blocks {s}"
                break
        add("session", "Session", "fail" if blocked else "pass",
            blocked or f"{now.strftime('%H:%M')} UTC — outside every blackout window")

    # 5. risk state — the engine's own portfolio gates
    if portfolio:
        cd = portfolio.get("cooldown_minutes_left") or 0
        if portfolio.get("breaker_on"):
            add("risk_state", "Risk state", "fail",
                f"daily breaker on ({portfolio.get('daily_sls')} SLs today)")
        elif cd:
            add("risk_state", "Risk state", "fail",
                f"SL cooldown, {cd} min left ({portfolio.get('cooldown_note') or 'after a stop'})")
        else:
            add("risk_state", "Risk state", "pass", "no cooldown, no daily breaker")
    else:
        add("risk_state", "Risk state", "na", "portfolio state unavailable")

    # 6. volatility — the engine's ATR band, and a spike check against its median
    if atr < MIN_ATR_TO_TRADE:
        add("volatility", "Volatility", "fail",
            f"ATR ${atr:.2f} < the engine's ${MIN_ATR_TO_TRADE:.2f} floor — it would not trade this")
    elif atr > MAX_ATR_TO_TRADE:
        add("volatility", "Volatility", "fail",
            f"ATR ${atr:.2f} > the engine's ${MAX_ATR_TO_TRADE:.2f} ceiling")
    else:
        add("volatility", "Volatility", "pass",
            f"ATR ${atr:.2f} inside the engine's ${MIN_ATR_TO_TRADE:.2f}-${MAX_ATR_TO_TRADE:.2f} band")

    # 7. geometry — the one the 2026-10-20 measurement says actually matters
    if setup:
        share = setup["cost_share_pct"]
        state = "pass" if share <= BOX_COST_SHARE_OK else (
            "warn" if share <= BOX_COST_SHARE_MAX else "fail")
        add("geometry", "Geometry", state,
            f"stop ${setup['stop']:.2f} ({setup['risk_usd']:.2f} risk), target "
            f"${setup['target']:.2f} ({setup['rr']:.1f}:1) — the ${spread:.2f} spread is "
            f"{share:.0f}% of R")
    else:
        add("geometry", "Geometry", "na", "no setup to size")

    by_key = {c["key"]: c for c in checks}
    if by_key["location"]["state"] == "fail":
        verdict = {"code": "no_setup", "tone": "idle", "headline": "No box setup — mid-box",
                   "detail": "nothing to do until price reaches an edge; the checklist below is context"}
    elif by_key["trigger"]["state"] == "fail":
        verdict = {"code": "wait", "tone": "warn", "headline": "Waiting — at the edge, no trigger",
                   "detail": "a box only answers WHERE. Wait for a close beyond the edge, or a rejection of it"}
    elif by_key["feed"]["state"] == "fail":
        verdict = {"code": "blocked", "tone": "block", "headline": "Blocked — the feed is stale",
                   "detail": by_key["feed"]["detail"] + " while the market is open"}
    elif by_key["session"]["state"] == "fail" or by_key["risk_state"]["state"] == "fail":
        first = by_key["session"] if by_key["session"]["state"] == "fail" else by_key["risk_state"]
        verdict = {"code": "blocked", "tone": "block", "headline": f"Blocked — {first['label'].lower()}",
                   "detail": first["detail"]}
    elif by_key["volatility"]["state"] == "fail":
        verdict = {"code": "blocked", "tone": "block", "headline": "Blocked — volatility",
                   "detail": by_key["volatility"]["detail"]}
    elif by_key["geometry"]["state"] == "fail":
        verdict = {"code": "wait", "tone": "warn", "headline": "Waiting — the stop is too tight for the spread",
                   "detail": by_key["geometry"]["detail"] + " — measured: tight stops lose to cost"}
    elif by_key["geometry"]["state"] == "warn":
        verdict = {"code": "candidate_weak", "tone": "warn",
                   "headline": "Candidate, weak geometry",
                   "detail": by_key["geometry"]["detail"] + " — the spread is a large share of R"}
    else:
        verdict = {"code": "candidate", "tone": "ok",
                   "headline": f"Candidate — {setup['side']} at the {setup['box']}" if setup else "Candidate",
                   "detail": "conditions line up. Base rate still shows no edge: this is context, not a signal"}

    return {"ok": True, "now": now, "geometry": geom, "checks": checks, "verdict": verdict,
            "setup": setup, "nearest": nearest, "trigger": trig, "measured": BOX_MEASURED,
            "spread_usd": spread}


def box_read(rows, now=None, portfolio=None, feed=None, spread=BOX_SPREAD_USD):
    """box_geometry + box_status in one call (library/CLI convenience)."""
    geom = box_geometry(rows, spread=spread)
    out = box_status(geom, portfolio=portfolio, feed=feed, now=now, spread=spread)
    out["geometry"] = geom
    return out


def evidence_read(trades, cost=0.40):
    """All valid closed era exits, costed equally including scratches; exit-order DD."""
    groups = []
    era = [t for t in trades if (parse_ts(t.get('Entry_Time')) or datetime.min) >= STRUCT_STOP_CUTOVER]
    for side in ('ALL', 'BUY', 'SELL'):
        sample = [t for t in era if side == 'ALL' or t.get('Trade_Type') == side]
        values, rs, excluded = [], [], 0
        for t in sorted(sample, key=lambda t: parse_ts(t.get('Exit_Time')) or datetime.max):
            p, risk = parse_float(t.get('Profit')), trade_risk(t)
            if p is None or not math.isfinite(p) or not risk or not math.isfinite(risk) or not parse_ts(t.get('Exit_Time')):
                excluded += 1
                continue
            values.append(p - cost)
            rs.append((p - cost) / risk)
        running = peak = dd = 0.0
        for v in values:
            running += v
            peak = max(peak, running)
            dd = max(dd, peak - running)
        gains, losses = sum(max(v, 0) for v in values), -sum(min(v, 0) for v in values)
        groups.append(dict(side=side, n=len(values), excluded=excluded, net=sum(values),
                           expectancy=sum(rs)/len(rs) if rs else None,
                           pf=gains/losses if losses else None, dd=dd))
    return groups


def market_map(rows):
    """Completed UTC buckets only. Require every M1 minute (no gap interpolation)."""
    bars = {}
    for r in rows:
        ts = parse_ts(r.get('Timestamp'))
        vals = [parse_float(r.get(k)) for k in ('High', 'Low', 'Close', 'ATR')]
        if ts and all(v is not None and math.isfinite(v) for v in vals[:3]):
            bars[ts.replace(second=0, microsecond=0)] = vals
    if not bars:
        return None
    last = max(bars)
    price, atr = bars[last][2:]
    result = dict(as_of=str(last), trends=[], levels=[])
    for minutes in (15, 60):
        buckets = {}
        for ts in sorted(bars):
            start = ts.replace(minute=(ts.minute // minutes)*minutes)
            buckets.setdefault(start, []).append(ts)
        complete = [(start, times) for start, times in sorted(buckets.items())
                    if len(times) == minutes and start + timedelta(minutes=minutes) <= last]
        # Four consecutive completed buckets; refuse outage-spanning momentum.
        recent = complete[-4:]
        valid = len(recent) == 4 and recent[-1][0] - recent[0][0] == timedelta(minutes=3*minutes)
        valid = valid and recent[-1][0] + timedelta(minutes=2*minutes) > last
        delta = bars[recent[-1][1][-1]][2] - bars[recent[0][1][-1]][2] if valid else None
        result['trends'].append(dict(tf=f'M{minutes}' if minutes == 15 else 'H1', delta=delta))
    prior = [ts.date() for ts in bars if ts.date() < last.date()]
    if prior:
        day = max(prior)
        # Only publish a prior-day range if the read window includes its start.
        if min(bars).date() < day:
            values = [v for ts, v in bars.items() if ts.date() == day]
            for label, level in ((f'{day} high', max(v[0] for v in values)),
                                 (f'{day} low', min(v[1] for v in values))):
                result['levels'].append(dict(label=label, price=level,
                    distance=(price-level)/atr if atr and math.isfinite(atr) and atr > 0 else None))
    return result


def risk_read(status, quote_rows, now):
    """Indicative closure warning, NOT a broker schedule or a trading gate."""
    close = now.replace(hour=21, minute=0, second=0, microsecond=0)
    while close <= now or close.weekday() >= 5:
        close += timedelta(days=1)
    entry = parse_ts(status.get('entry_time')) if status.get('trade_active') else None
    remaining = max(0, MAX_HOLD_MINUTES - (now-entry).total_seconds()/60) if entry else None
    quotes = []
    for q in quote_rows:
        ts, spread = parse_ts(q.get('ts_utc')), parse_float(q.get('spread'))
        if ts and ts <= now and spread is not None and math.isfinite(spread) and spread >= 0 and (parse_float(q.get('n_ok')) or 0) > 0 and not q.get('flags'):
            quotes.append((ts, spread))
    quotes.sort()
    quote = None
    if quotes:
        ts, spread = quotes[-1]
        quote = dict(as_of=str(ts), spread=spread, age=int((now-ts).total_seconds()), stale=(now-ts).total_seconds()>120)
    minutes = (close-now).total_seconds()/60
    return dict(close=str(close), minutes=int(minutes), remaining=remaining,
                spans=remaining is not None and remaining >= minutes,
                quiet=market_quiet(now), quote=quote)


def build(read_tail=True, now=None, log_rows=None, trades=None, skip_rows=None):
    """Everything the dashboard needs, in one call (all reads are read-only)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    log_rows = log_rows if log_rows is not None else (
        tail_rows(LOG_FILE_PATH, 400) if read_tail else read_rows(LOG_FILE_PATH))
    trades = trades if trades is not None else read_rows(TRADES_FILE_PATH)
    skip_rows = skip_rows if skip_rows is not None else read_rows(SKIP_FILE_PATH)
    setup = setup_read(log_rows)
    return {
        "now": now,
        "evidence": evidence_read(trades),
        "map": market_map(tail_rows(LOG_FILE_PATH, 6000) if read_tail else log_rows),
        "pressure": pressure(log_rows),
        "setup": setup,
        "location": location_read(setup),
        "portfolio": portfolio_read(trades, now, log_rows),
        "skips": skip_summary(skip_rows, now),
        "era": era_stats(trades),
        "book": book_read(trades, now),
        "feed": feed_read(log_rows, now),
    }

# ─────────────────────────────────────────────────────────────────────────────
# 6. SIMPLE SUMMARY + VOLATILITY GUARD — human-friendly tab, never a gate
# Display-only. Every threshold here is advisory and explicitly NOT enforced by
# engine.py / trade_filter.py. The engine already blocks ATR/spread extremes on
# its own; this layer translates those blocks (and softer warnings) into plain
# English so the operator knows whether to leave the bot alone, stay cautious,
# or sit out. See docs/ANALYSIS-2026-10-16-dashboard-pressure.md section 1.
# ─────────────────────────────────────────────────────────────────────────────

def _atr_median(log_rows, window=60):
    """Median ATR over the last window bars, or None when warming up."""
    vals = []
    for r in log_rows[-window:]:
        atr = parse_float(r.get("ATR"))
        if atr is not None and math.isfinite(atr) and atr > 0:
            vals.append(atr)
    return _median(vals) if vals else None


def _factor(name, label, detail, level, value_text="", advice=""):
    """One volatility / risk factor row: level 0 ok, 1 watch, 2 block/high."""
    icons = {0: "🟢", 1: "🟡", 2: "🔴"}
    colors = {0: "emerald", 1: "amber", 2: "rose"}
    level_names = {0: "OK", 1: "Caution", 2: "High / Blocked"}
    return {
        "key": name, "name": label, "detail": detail, "level": level,
        "level_name": level_names.get(level, "—"),
        "icon": icons.get(level, "⚪"), "color": colors.get(level, "slate"),
        "value": value_text, "advice": advice,
    }


def volatility_guard(log_rows=None, portfolio=None, feed=None, risk=None, mkt=None, setup=None, now=None):
    """Plain-English volatility / risk checklist (display-only).

    Each factor is evaluated independently against display thresholds (VOLATILITY_*).
    The overall verdict is the worst factor, softened so a single transient caution
    does not paint everything red — counts matter. This function never raises: missing
    inputs degrade to unknown rows, never to an exception.
    """
    try:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        factors = []

        # ATR (engine already blocks outside 1.10-4.50)
        atr = None
        atr_median = None
        if setup and setup.get("ok"):
            atr = setup.get("atr")
        if log_rows:
            atr_median = _atr_median(log_rows, 60)
        if atr is None:
            factors.append(_factor("atr", "Market Volatility (ATR)",
                                   "Unknown — last bar still warming up", 0,
                                   "—", "Not enough data yet."))
        else:
            if atr < MIN_ATR_TO_TRADE:
                factors.append(_factor("atr", "Market Volatility (ATR)",
                                       f"Very quiet — ATR ${atr:.2f} is below the ${MIN_ATR_TO_TRADE:.2f} trading floor",
                                       1, f"${atr:.2f}",
                                       "Bot will skip new entries until volatility picks up. Nothing is broken — just a calm patch."))
            elif atr > MAX_ATR_TO_TRADE:
                factors.append(_factor("atr", "Market Volatility (ATR)",
                                       f"Extreme — ATR ${atr:.2f} exceeds the ${MAX_ATR_TO_TRADE:.2f} news filter",
                                       2, f"${atr:.2f}",
                                       "Auto-blocked: the bot will not enter. Sit out — spreads and slippage are worst here."))
            elif atr >= VOLATILITY_ATR_HIGH:
                factors.append(_factor("atr", "Market Volatility (ATR)",
                                       f"High — ATR ${atr:.2f} — large bars, fast moves, elevated risk",
                                       2, f"${atr:.2f}",
                                       "Consider skipping new entries. If you do trade, expect bigger swings."))
            elif atr >= VOLATILITY_ATR_ELEVATED:
                factors.append(_factor("atr", "Market Volatility (ATR)",
                                       f"Elevated — ATR ${atr:.2f} — choppy day, wider swings than normal",
                                       1, f"${atr:.2f}",
                                       "Trade with extra caution, or wait for calmer conditions."))
            else:
                spike = (atr / atr_median) if (atr_median and atr_median > 0) else None
                if spike and spike >= 2.0:
                    factors.append(_factor("atr", "Market Volatility (ATR)",
                                           f"Spiking — ATR ${atr:.2f} is {spike:.1f}x its 60-bar median (${atr_median:.2f})",
                                           1, f"${atr:.2f}",
                                           "Volatility is accelerating. Let it settle before trusting new levels."))
                elif spike and spike >= VOLATILITY_ATR_SPIKE_RATIO:
                    factors.append(_factor("atr", "Market Volatility (ATR)",
                                           f"Slightly spiking — ATR ${atr:.2f} is {spike:.1f}x its recent median",
                                           0, f"${atr:.2f}",
                                           "Worth watching, but still within normal bounds."))
                else:
                    factors.append(_factor("atr", "Market Volatility (ATR)",
                                           f"Normal — ATR ${atr:.2f} is in the sweet spot for this strategy",
                                           0, f"${atr:.2f}",
                                           "Conditions are calm enough for normal operation."))

        # Spread
        spread = None
        spread_stale = False
        spread_age = None
        if risk and risk.get("quote"):
            spread = risk["quote"].get("spread")
            spread_stale = bool(risk["quote"].get("stale"))
            spread_age = risk["quote"].get("age")
        if spread is None:
            factors.append(_factor("spread", "Spread (cost to enter)",
                                   "Unknown — no recent quote from the broker feed",
                                   0, "—",
                                   "Bot assumes $0.40 round-trip until the logger has 14 days. No block today."))
        else:
            ago = f"{spread_age}s ago" if spread_age is not None else ""
            if spread >= VOLATILITY_SPREAD_BLOCK:
                factors.append(_factor("spread", "Spread (cost to enter)",
                                       f"Wide — spread ${spread:.2f} ({ago}) — costs eat the edge",
                                       2, f"${spread:.2f}",
                                       "Bot blocks entries above $0.60. Let the spike pass."))
            elif spread >= VOLATILITY_SPREAD_WARN:
                factors.append(_factor("spread", "Spread (cost to enter)",
                                       f"Elevated — spread ${spread:.2f} ({ago}) — trading is more expensive right now",
                                       1, f"${spread:.2f}",
                                       "Be cautious with new entries; the cost headwind is higher than normal."))
            else:
                stale_note = " · quote is stale" if spread_stale else ""
                factors.append(_factor("spread", "Spread (cost to enter)",
                                       f"Normal — spread ${spread:.2f}{stale_note}",
                                       0, f"${spread:.2f}",
                                       "Cost headwind is normal for this market."))

        # Blackout / session windows
        if portfolio:
            if portfolio.get("blackout_any"):
                blocked = []
                for sd, msg in portfolio.get("sides_blocked", {}).items():
                    if msg:
                        blocked.append(f"{sd}: {msg}")
                blocked_txt = "; ".join(blocked) or "both sides blocked"
                factors.append(_factor("blackout", "News / Session Window",
                                       f"In blackout now — {blocked_txt}",
                                       2, "BLOCKED",
                                       "Auto-blocked: the bot will skip. These windows are where whipsaws cluster."))
            else:
                nxt = portfolio.get("next_window")
                if nxt:
                    label, sides, start = nxt
                    mins = (start - now).total_seconds() / 60.0
                    side_str = ", ".join(sides)
                    if mins <= 15:
                        factors.append(_factor("blackout", "News / Session Window",
                                               f"Next blackout in {mins:.0f} min — {label} blocks {side_str}",
                                               1, f"{mins:.0f} min",
                                               "A new position opened now could be caught in the window. Wait until it passes if you can."))
                    elif mins <= 60:
                        factors.append(_factor("blackout", "News / Session Window",
                                               f"Next blackout in {mins:.0f} min — {label}",
                                               0, f"{mins:.0f} min",
                                               "Normal — still time before the next risky window."))
                    else:
                        factors.append(_factor("blackout", "News / Session Window",
                                               "No blackout for at least an hour", 0, "clear",
                                               "Session risk is low right now."))
                else:
                    factors.append(_factor("blackout", "News / Session Window", "No upcoming blackout found", 0, "—", ""))
        else:
            factors.append(_factor("blackout", "News / Session Window", "Unknown — no portfolio state", 0, "—", ""))

        # Cooldown
        if portfolio and portfolio.get("cooldown_minutes_left"):
            mins = portfolio["cooldown_minutes_left"]
            note = portfolio.get("cooldown_note") or ""
            extra = f" ({note})" if note else ""
            factors.append(_factor("cooldown", "Cooldown After Loss",
                                   f"Cooling down — {mins} min left{extra}",
                                   1, f"{mins} min",
                                   "The bot auto-pauses after stop-losses to avoid revenge entries. This is protection, not a fault."))
        else:
            factors.append(_factor("cooldown", "Cooldown After Loss",
                                   "No cooldown — ready for next valid setup", 0, "clear",
                                   "The bot will not re-enter the same losing pattern immediately."))

        # Daily breaker
        if portfolio is not None:
            dls = portfolio.get("daily_sls", 0)
            breaker = bool(portfolio.get("breaker_on"))
            if breaker:
                mom = portfolio.get("momentum_side") or "unknown trend"
                factors.append(_factor("breaker", "Daily Loss Limit",
                                       f"Limit hit — {dls}/{MAX_DAILY_LOSSES} stop-losses today -> trend-side-only ({mom})",
                                       2, f"{dls}/{MAX_DAILY_LOSSES}",
                                       "The bot now takes only trend-aligned setups. Expect fewer trades today."))
            elif dls >= 7:
                factors.append(_factor("breaker", "Daily Loss Limit",
                                       f"Getting close — {dls}/{MAX_DAILY_LOSSES} stop-losses today",
                                       1, f"{dls}/{MAX_DAILY_LOSSES}",
                                       "If a few more losses hit, the bot will tighten to trend-only. Consider smaller or no manual adds."))
            else:
                factors.append(_factor("breaker", "Daily Loss Limit",
                                       f"Healthy — {dls}/{MAX_DAILY_LOSSES} stop-losses today", 0,
                                       f"{dls}/{MAX_DAILY_LOSSES}",
                                       "Plenty of headroom today."))
        else:
            factors.append(_factor("breaker", "Daily Loss Limit", "Unknown", 0, "—", ""))

        # Market closure
        if risk:
            mins = risk.get("minutes")
            remaining = risk.get("remaining")
            spans = bool(risk.get("spans"))
            if mins is not None:
                hrs = mins / 60.0
                if remaining is not None and spans:
                    factors.append(_factor("closure", "Market Closure Risk",
                                           f"Heads up — market closes in {mins:.0f} min and your current max-hold ({remaining:.0f} min left) would span the close",
                                           2, f"{mins:.0f} min to close",
                                           "A position held through the daily break is not protected — gap risk. No auto-exit is set."))
                elif mins <= 30:
                    factors.append(_factor("closure", "Market Closure Risk",
                                           f"Market closes in {mins:.0f} min — a fresh position would ride the daily break",
                                           1, f"{mins:.0f} min",
                                           "Avoid opening new positions right before the 21:00 UTC close."))
                elif mins <= 90:
                    factors.append(_factor("closure", "Market Closure Risk",
                                           f"Market closes in {hrs:.1f}h — normal, but watch the clock for new entries",
                                           0, f"{hrs:.1f}h",
                                           "Still enough time for a 4-hour max-hold, but a late entry will span the break."))
                else:
                    factors.append(_factor("closure", "Market Closure Risk",
                                           f"Market closes in {hrs:.1f}h — plenty of time", 0, f"{hrs:.1f}h",
                                           "No close risk for at least the next hour."))
            else:
                factors.append(_factor("closure", "Market Closure Risk", "Unknown — no closure estimate", 0, "—", ""))
        else:
            factors.append(_factor("closure", "Market Closure Risk", "Unknown — no quote/closure feed", 0, "—", ""))

        # Trend speed
        if mkt and mkt.get("trends"):
            atr_val = (setup.get("atr") if setup and setup.get("atr") else None)
            deltas = [t.get("delta") for t in mkt.get("trends", []) if t.get("delta") is not None]
            if deltas and atr_val:
                largest = max(deltas, key=abs)
                atrs = abs(largest) / atr_val if atr_val else 0
                if atrs >= VOLATILITY_MOMENTUM_HIGH_ATR:
                    factors.append(_factor("trend", "Trend Speed",
                                           f"Very fast move — price swung ${abs(largest):.2f} ({atrs:.1f}x ATR) on the last hour",
                                           1, f"{atrs:.1f}x ATR",
                                           "Fast trends often snap back. The bot levels may be stale — let the move settle."))
                elif atrs >= VOLATILITY_MOMENTUM_WARN_ATR:
                    factors.append(_factor("trend", "Trend Speed",
                                           f"Elevated — price moved ${abs(largest):.2f} ({atrs:.1f}x ATR) recently",
                                           1, f"{atrs:.1f}x ATR",
                                           "Market is energetic. Setups near fresh levels are higher risk."))
                else:
                    dir_word = "up" if largest > 0 else "down" if largest < 0 else "flat"
                    factors.append(_factor("trend", "Trend Speed",
                                           f"Calm — trending {dir_word} ${abs(largest):.2f} on the hour ({atrs:.1f}x ATR)",
                                           0, f"{atrs:.1f}x ATR",
                                           "Trend speed is normal."))
            else:
                factors.append(_factor("trend", "Trend Speed",
                                       "Unknown — not enough complete hourly buckets yet", 0, "—",
                                       "Needs four full 15-min buckets. Try again in a few minutes."))
        else:
            factors.append(_factor("trend", "Trend Speed", "Unknown — no market map", 0, "—", ""))

        # Gaps / feed health
        if feed and feed.get("ok"):
            gaps = feed.get("gaps", 0)
            largest = feed.get("largest_gap_minutes", 0) or 0
            if gaps > 0:
                lvl = 2 if largest >= 30 else 1
                factors.append(_factor("gaps", "Recent Gaps / Feed Health",
                                       f"{gaps} open-market gap(s) recently — largest {largest:.0f} open-min lost",
                                       lvl, f"{gaps} gap(s)",
                                       "The feed had a stall. Price history may have holes — verify the engine log before trusting signals."))
            else:
                age_m = (feed.get("age_seconds") or 0) / 60.0
                if age_m > 5:
                    factors.append(_factor("gaps", "Recent Gaps / Feed Health",
                                           f"No gaps, but last bar is {age_m:.0f} min old — possible stall building",
                                           1, f"{age_m:.0f} min old",
                                           "The feed may be lagging. Check engine heartbeat."))
                else:
                    factors.append(_factor("gaps", "Recent Gaps / Feed Health",
                                           "Healthy — no open-market gaps in the last hour", 0, "0 gaps",
                                           "Data feed is current."))
        else:
            reason = (feed.get("reason") if feed else "no feed") or "no feed"
            factors.append(_factor("gaps", "Recent Gaps / Feed Health",
                                   f"Unknown — {reason}", 0, "—",
                                   "Feed health could not be checked."))

        # Day range
        if mkt and mkt.get("levels"):
            try:
                levels = mkt.get("levels") or []
                if len(levels) >= 2 and setup and setup.get("atr"):
                    hi = max(l.get("price") for l in levels if l.get("price") is not None)
                    lo = min(l.get("price") for l in levels if l.get("price") is not None)
                    rng = hi - lo
                    atr_val = setup.get("atr")
                    ratio = rng / atr_val if atr_val else 0
                    if ratio >= VOLATILITY_RANGE_HIGH_ATR:
                        factors.append(_factor("range", "Day Range",
                                               f"Very wide day — prior range ${rng:.2f} ({ratio:.0f}x ATR)",
                                               1, f"{ratio:.0f}x ATR",
                                               "Big-range days often mean news-driven, choppy conditions."))
                    elif ratio >= VOLATILITY_RANGE_WARN_ATR:
                        factors.append(_factor("range", "Day Range",
                                               f"Wide — prior range ${rng:.2f} ({ratio:.0f}x ATR)",
                                               0, f"{ratio:.0f}x ATR",
                                               "Above average but not extreme."))
                    else:
                        factors.append(_factor("range", "Day Range",
                                               f"Normal — prior range ${rng:.2f} ({ratio:.0f}x ATR)",
                                               0, f"{ratio:.0f}x ATR",
                                               "Day range is typical."))
                else:
                    factors.append(_factor("range", "Day Range", "Unknown — not enough history for prior-day levels", 0, "—", ""))
            except Exception:
                factors.append(_factor("range", "Day Range", "Unknown — could not compute range", 0, "—", ""))
        else:
            factors.append(_factor("range", "Day Range", "Unknown — no market map", 0, "—", ""))

        # overall verdict
        reds = sum(1 for f in factors if f["level"] == 2)
        ambers = sum(1 for f in factors if f["level"] == 1)
        vol_red_keys = {"atr", "spread", "trend", "gaps", "closure"}
        vol_reds = sum(1 for f in factors if f["level"] == 2 and f["key"] in vol_red_keys)
        if reds >= 2 or vol_reds >= 1:
            verdict = "red"
            label = "Pause — conditions are risky right now"
            icon = "🛑"
            headline = "Market looks volatile or blocked — sitting out is the safe choice"
            sub = "One or more risk flags are high. The bot will auto-skip extreme entries; you should too. Wait for a clearer window."
            action = "Avoid new entries. Let the bots cooldown/blackout pass, and re-check after the next update."
        elif reds == 1 or ambers >= 2:
            verdict = "amber"
            label = "Caution — choppy, trade carefully"
            icon = "⚠️"
            headline = "Conditions are a bit choppy — extra caution warranted"
            sub = "No hard block right now, but a few warning lights are on. Smaller size or fewer trades makes sense."
            action = "Trade cautiously if you must, or wait an hour for a cleaner tape. Follow the bots auto-skips."
        else:
            verdict = "green"
            label = "Calm — normal operation"
            icon = "✅"
            headline = "Conditions look calm — normal rules apply"
            sub = "No major volatility or session risk right now. The bot may take the next valid setup."
            action = "Let the bot run normally. It will still auto-skip any bad setup."

        return {
            "verdict": verdict, "label": label, "icon": icon,
            "headline": headline, "sub": sub, "action": action,
            "factors": factors, "counts": {"red": reds, "amber": ambers, "green": len(factors) - reds - ambers},
            "volatile": (verdict != "green"),
            "should_avoid": (verdict == "red"),
            "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        return {
            "verdict": "unknown", "label": "Check unavailable", "icon": "❓",
            "headline": "Could not assess volatility right now",
            "sub": str(exc), "action": "Refresh in a minute.",
            "factors": [], "counts": {"red": 0, "amber": 0, "green": 0},
            "volatile": False, "should_avoid": False,
            "as_of": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            "error": str(exc),
        }


def simple_summary(status, ctx, volatility=None, now=None):
    """High-level, human-friendly summary for the Simple tab (display-only).

    status is the engines status.json dict, ctx is the output of build(),
    volatility is the output of volatility_guard(). All are optional — missing
    pieces degrade to friendly unknown lines rather than errors.
    """
    try:
        now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        equity = None
        try:
            equity = float(status.get("equity"))
        except Exception:
            pass
        delta = (equity - 500.0) if equity is not None else None
        trade_active = bool(status.get("trade_active"))
        book = ctx.get("book") if ctx else None
        era = ctx.get("era") if ctx else None
        setup = ctx.get("setup") if ctx else None
        mkt = ctx.get("map") if ctx else None
        feed = ctx.get("feed") if ctx else None

        market_sentences = []
        if setup and setup.get("ok"):
            atr_txt = f"ATR ${setup['atr']:.2f}" if setup.get("atr") else "ATR unknown"
            if setup["atr"] and setup["atr"] < MIN_ATR_TO_TRADE:
                market_sentences.append(f"Market is quiet right now ({atr_txt}). Bars are small, so the bot is waiting for more movement before it will enter.")
            elif setup["atr"] and setup["atr"] > MAX_ATR_TO_TRADE:
                market_sentences.append(f"Market is very volatile ({atr_txt}). The bots safety filter is blocking new entries until things settle.")
            elif setup["atr"] and setup["atr"] >= VOLATILITY_ATR_HIGH:
                market_sentences.append(f"Market is volatile ({atr_txt}). Expect bigger swings — new positions carry extra risk.")
            elif setup["atr"] and setup["atr"] >= VOLATILITY_ATR_ELEVATED:
                market_sentences.append(f"Market is a bit choppy ({atr_txt}). Not extreme, but wider than average.")
            else:
                market_sentences.append(f"Market volatility looks normal ({atr_txt}). Price action is within the usual range.")
            if mkt and mkt.get("levels"):
                try:
                    hi = max(l["price"] for l in mkt["levels"] if l.get("price") is not None)
                    lo = min(l["price"] for l in mkt["levels"] if l.get("price") is not None)
                    market_sentences.append(f"Prior session ran ${lo:.2f} -> ${hi:.2f}. Price is ${setup['close']:.2f} inside that context.")
                except Exception:
                    pass
            if mkt and mkt.get("trends"):
                for tr in mkt["trends"]:
                    d = tr.get("delta")
                    if d is None:
                        market_sentences.append(f"{tr['tf']} trend: not enough clean data to tell — a gap or incomplete hour.")
                    elif abs(d) < 1.0:
                        market_sentences.append(f"{tr['tf']} trend: basically flat (${d:+.2f}). No strong push either way.")
                    else:
                        dir_word = "up" if d > 0 else "down"
                        market_sentences.append(f"{tr['tf']} trend: drifting {dir_word} (${d:+.2f} on the last hour).")
            else:
                market_sentences.append("Trend info is still building — check back after four full hourly buckets.")
        else:
            market_sentences.append("Market data is still warming up — a few more minutes needed before a read is available.")

        bot_next = "Bot is idle between setups."
        if setup and setup.get("ok"):
            ready_sides = [s for s in ("BUY", "SELL") if setup.get(s, {}).get("ready")]
            if ready_sides:
                joined = " / ".join(ready_sides)
                bot_next = f"Bot sees a clean {joined} setup on the last bar — if the risk gates allow it, it will enter on the next candle."
            else:
                misses = []
                for side in ("BUY", "SELL"):
                    miss = setup.get("nearest_miss", {}).get(side)
                    if miss:
                        misses.append(f"{side}: waiting for {miss}")
                if misses:
                    bot_next = "Bot is waiting: " + "; ".join(misses[:2]) + "."
                else:
                    bot_next = "No side is fully ready — the 20-bar level, wick or trend condition is still missing."
            pf = ctx.get("portfolio") if ctx else None
            if pf:
                if pf.get("blackout_any"):
                    bot_next += " However, a session blackout is active right now, so the bot will skip even a perfect setup."
                elif pf.get("cooldown_minutes_left"):
                    bot_next += f" Note: cooldown for {pf['cooldown_minutes_left']} min after the last stop — the bot is deliberately pausing."
                elif pf.get("breaker_on"):
                    bot_next += " Daily loss limit is active — only trend-side setups will be taken today."
        if trade_active:
            entry = status.get("entry_price")
            tp = status.get("take_profit")
            sl = status.get("stop_loss")
            typ = status.get("trade_type") or "position"
            bot_next = f"Bot is IN a {typ} trade from ${entry} -> TP ${tp} / SL ${sl}. It will manage the exit (BE ratchet + time stop) automatically."

        human_tip = "Let the bot follow its rules. No manual override needed while conditions are calm."
        if volatility:
            if volatility.get("verdict") == "red":
                human_tip = "Manual tip: sit out new entries until this clears. Volatility, spread or session risk is high — even the bots auto-skips cannot protect you from a gap."
            elif volatility.get("verdict") == "amber":
                human_tip = "Manual tip: if you trade by hand, use smaller size or wait 30-60 min for a cleaner window. Do not chase moves."

        today_line = "No trades yet today."
        if book:
            n = book.get("n", 0)
            if n:
                c = book.get("counts", {})
                pnl = book.get("pnl", 0)
                today_line = f"Today: {n} closed — {c.get('TP',0)} wins / {c.get('SL',0)} losses / {c.get('BE',0)} scratches — P&L ${pnl:+.2f} (paper)."
                streak = book.get("last_20") or ""
                if streak:
                    today_line += f" Last 20 exits (old->new): {streak}"

        stale_note = None
        if feed and feed.get("ok"):
            age = feed.get("age_seconds") or 0
            if age > 300:
                stale_note = f"Data is {age//60} min old — the feed may be stalled. Treat signals as stale."

        return {
            "mode": "paper",
            "equity": equity, "equity_delta": delta,
            "trade_active": trade_active,
            "trade_type": status.get("trade_type"),
            "book": book, "era": era, "setup": setup,
            "market_sentences": market_sentences,
            "bot_next": bot_next,
            "today_line": today_line,
            "human_tip": human_tip,
            "stale_note": stale_note,
            "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        return {
            "mode": "paper", "equity": None, "market_sentences": [f"Summary unavailable: {exc}"],
            "bot_next": "Check again in a minute.", "today_line": "—", "human_tip": "—",
            "stale_note": None, "as_of": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"), "error": str(exc),
        }



if __name__ == "__main__":  # pragma: no cover - convenience only
    data = build()
    p = data["pressure"]
    print("tape:", "—" if not p else f"{p['label']} (buy {p['buy_pct']:.1f}% / sell {p['sell_pct']:.1f}%)")
    s = data["setup"]
    if s.get("ok"):
        for side in ("BUY", "SELL"):
            print(f"{side}: {s[side]['passed']}/{s[side]['total']} gates"
                  f"{' — SETUP READY' if s[side]['ready'] else ''}")
    else:
        print("setup:", s.get("reason"))
