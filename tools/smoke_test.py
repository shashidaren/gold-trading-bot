#!/usr/bin/env python3
"""
Smoke test for the engine's regime gates (2026-09-09 review).

Runs GoldEngine.evaluate_candle() over synthetic 1-minute candles in a temp
directory (no /opt/gold, no network, no Telegram, no real API keys needed).

Scenarios:
  A) Uptrend + rejection dip at the 20-bar floor  -> trade MUST trigger
  B) Established decline + rejection dip          -> trade MUST be blocked
  C) Restart from the written log                 -> EMA50 slope history must
     re-seed from the EMA_50 column so the slope gate works immediately

Usage: python3 tools/smoke_test.py
"""
import os
import sys
import json
import csv
import shutil
import tempfile
import types
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# ---- stub the modules the sandbox does not have ----
for name in ("requests", "dotenv", "twelvedata"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "requests":
            mod.post = lambda *a, **k: None
        if name == "dotenv":
            mod.load_dotenv = lambda *a, **k: None
        if name == "twelvedata":
            mod.TDClient = object
        sys.modules[name] = mod

import engine  # noqa: E402
import trade_filter  # noqa: E402

TMP = tempfile.mkdtemp(prefix="gold_smoke_")
engine.LOG_FILE_PATH = os.path.join(TMP, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(TMP, "status.json")
engine.TRADES_LOG_PATH = os.path.join(TMP, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(TMP, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")  # deterministic

FAILURES = []


def check(label, cond, extra=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"  ({extra})" if extra else ""))
    if not cond:
        FAILURES.append(label)


def candles_uptrend(n, start=4400.0):
    """Oscillating uptrend: RSI ~60, ATR ~1.5, EMA50 rising."""
    out, p = [], start
    for i in range(n):
        d = (1.0, 1.0, -0.9, 1.0, -0.9)[i % 5]
        o = p
        c = p + d
        out.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
        p = c
    return out


def candles_decline(n, start):
    """Oscillating decline: RSI ~40, EMA50 falling."""
    out, p = [], start
    for i in range(n):
        d = (-1.0, -1.0, 0.9, -1.0, 0.9)[i % 5]
        o = p
        c = p + d
        out.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
        p = c
    return out


def run_candles(eng, candles, ts_start):
    ts = ts_start
    for (o, h, l, c) in candles:
        eng.evaluate_candle(o, h, l, c, tick_count=30)
        eng.check_position(c)  # drive SL/TP like the tick loop would
        ts += timedelta(minutes=1)


def rejection_dip(eng):
    """One candle: undercuts the 20-bar floor, closes back above it, long wick."""
    floor = min(list(eng.lows)[-engine.LOOKBACK_PERIOD:])
    p = list(eng.closes)[-1]
    o = p
    c = p - 0.4
    low = floor - 0.6
    high = p + 0.3
    return (o, high, low, c)


print("Scenario A: uptrend + floor rejection -> expect a trade")
eng = engine.GoldEngine()
run_candles(eng, candles_uptrend(240), datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
dip = rejection_dip(eng)
run_candles(eng, [dip], datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
check("A: trade triggered", eng.trade_active or eng.current_trade_num is not None,
      f"trade_active={eng.trade_active} num={eng.current_trade_num}")
check("A: EMA50 slope was confirmed at entry", eng.hit_slope_confirmed > 0)
check("A: price-near-EMA counted", eng.hit_price_near_ema > 0)

# let the trade hit TP
p_now = list(eng.closes)[-1]
up = []
p = p_now
for _ in range(10):
    o = p
    c = p + 1.0
    up.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
    p = c
run_candles(eng, up, datetime(2026, 1, 1, 4, 1, tzinfo=timezone.utc))
check("A: trade closed", not eng.trade_active, f"wins={eng.wins} losses={eng.losses}")
with open(engine.TRADES_LOG_PATH, newline="") as f:
    rows = list(csv.DictReader(f))
    expected_cols = {"Trade_Num", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss",
                     "Take_Profit", "Exit_Price", "Exit_Reason", "Profit", "Balance_After"}
check("A: trades.csv schema unchanged", rows and expected_cols.issubset(rows[0].keys()),
      f"{len(rows)} row(s)")
with open(engine.STATUS_FILE_PATH) as f:
    st = json.load(f)
check("A: status.json has new funnel keys",
      "slope_confirmed" in st["funnel"] and "price_near_ema" in st["funnel"])

print("Scenario B: established decline + rejection dip -> expect NO trade")
eng_b = engine.GoldEngine()
run_candles(eng_b, candles_uptrend(240) + candles_decline(60, list(eng_b.closes)[-1] if eng_b.closes else 4467),
            datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc))
dip_b = rejection_dip(eng_b)
eng_b.evaluate_candle(*dip_b, tick_count=30)
check("B: no trade in decline", not eng_b.trade_active and eng_b.current_trade_num is None,
      f"trend_gate=ema50>{'ema200' if eng_b.ema_fast > eng_b.ema_slow else 'CROSSED'}")
slope_now = eng_b.ema_fast > eng_b.ema50_history[-engine.EMA_SLOPE_LOOKBACK] if len(eng_b.ema50_history) >= engine.EMA_SLOPE_LOOKBACK else False
check("B: EMA50 slope negative at the dip", not slope_now)

print("Scenario C: restart -> EMA50 history re-seeds from log")
eng_c = engine.GoldEngine()
check("C: ema50_history seeded from CSV",
      len(eng_c.ema50_history) >= engine.EMA_SLOPE_LOOKBACK,
      f"{len(eng_c.ema50_history)} values loaded")
if len(eng_c.ema50_history) >= engine.EMA_SLOPE_LOOKBACK:
    rising = eng_c.ema_fast > eng_c.ema50_history[-engine.EMA_SLOPE_LOOKBACK]
    check("C: slope computable immediately after restart", isinstance(rising, bool))
check("C: trade stats restored from trades.csv",
      eng_c.wins + eng_c.losses >= 1, f"{eng_c.wins}W/{eng_c.losses}L balance=${eng_c.balance:.2f}")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
