#!/usr/bin/env python3
"""pressure.py — read-only tape pressure + setup/state reads for dashboard.py.

WHAT THIS IS
    A display layer. It answers three questions a human asks before a session:

      1. "Which way is the tape being pushed?"      -> pressure()
      2. "Would the engine take this bar, and if not, what is missing?"
                                                    -> setup_read()
      3. "Is the book / this experiment in a state where that matters?"
                                                    -> portfolio_read(), book_read(), feed_read()

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


def tail_rows(path, n=400):
    """Last n rows (oldest→newest) without reading the whole file.

    The 1-min log is multi-MB and grows forever; the dashboard refreshes every
    15 s, so it must not re-read it end to end.
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
            chunk = 128 * 1024
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
