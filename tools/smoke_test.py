#!/usr/bin/env python3
"""
Smoke test for the engine's regime gates, bidirectional (Buy/Sell) execution,
and daily loss circuit breaker.

Runs GoldEngine.evaluate_candle() over synthetic 1-minute candles in temp
directories (no /opt/gold, no network, no Telegram, no real API keys needed).

Scenarios:
  A) Uptrend + rejection dip at 20-bar floor       -> BUY trade MUST trigger & close with TP
  B) Established decline + floor rejection dip     -> BUY trade MUST be blocked
  C) Downtrend + ceiling rejection dip             -> SELL trade MUST trigger & close with TP
  D) Daily loss circuit breaker                    -> MUST halt after MAX_DAILY_LOSSES (3)
  E) Restart from log                             -> EMA50 history seeds properly

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

# Stub external dependencies
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


def candles_decline(n, start=4800.0):
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
        eng.check_position(c)
        ts += timedelta(minutes=1)


def rejection_dip_buy(eng):
    """Under-cuts 20-bar floor, closes above it, long lower wick."""
    floor = min(list(eng.lows)[-engine.LOOKBACK_PERIOD:])
    p = list(eng.closes)[-1]
    o = p
    c = p - 0.4
    low = floor - 0.6
    high = p + 0.3
    return (o, high, low, c)


def rejection_dip_sell(eng):
    """Tests 20-bar ceiling, closes below it, long upper wick."""
    ceil = max(list(eng.highs)[-engine.LOOKBACK_PERIOD:])
    p = list(eng.closes)[-1]
    o = p
    c = p - 0.2
    high = ceil + 0.6
    low = p - 0.5
    return (o, high, low, c)


# --- Scenario A ---
print("Scenario A: uptrend + floor rejection -> expect BUY trade")
tmp_a = tempfile.mkdtemp(prefix="gold_smoke_a_")
engine.LOG_FILE_PATH = os.path.join(tmp_a, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_a, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_a, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_a, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_a = engine.GoldEngine()
run_candles(eng_a, candles_uptrend(240), datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
dip_a = rejection_dip_buy(eng_a)
run_candles(eng_a, [dip_a], datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
check("A: BUY trade triggered", eng_a.trade_active and eng_a.trade_type == "BUY",
      f"trade_active={eng_a.trade_active} type={eng_a.trade_type} num={eng_a.current_trade_num}")

# Drive to TP
p_now = list(eng_a.closes)[-1]
up = [(p_now + i, p_now + i + 0.5, p_now + i - 0.2, p_now + i + 0.8) for i in range(1, 10)]
run_candles(eng_a, up, datetime(2026, 1, 1, 4, 1, tzinfo=timezone.utc))
check("A: BUY trade closed with TP", not eng_a.trade_active and eng_a.wins == 1, f"wins={eng_a.wins} losses={eng_a.losses}")
shutil.rmtree(tmp_a, ignore_errors=True)


# --- Scenario B ---
print("\nScenario B: decline + floor rejection dip -> expect NO buy trade")
tmp_b = tempfile.mkdtemp(prefix="gold_smoke_b_")
engine.LOG_FILE_PATH = os.path.join(tmp_b, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_b, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_b, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_b, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_b = engine.GoldEngine()
run_candles(eng_b, candles_decline(240), datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc))
dip_b = rejection_dip_buy(eng_b)
run_candles(eng_b, [dip_b], datetime(2026, 2, 1, 4, 0, tzinfo=timezone.utc))
check("B: no BUY trade in decline", not eng_b.trade_active,
      f"trend_gate=ema50>{'ema200' if eng_b.ema_fast > eng_b.ema_slow else 'CROSSED'}")
shutil.rmtree(tmp_b, ignore_errors=True)


# --- Scenario C ---
print("\nScenario C: downtrend + ceiling rejection -> expect SELL trade")
tmp_c = tempfile.mkdtemp(prefix="gold_smoke_c_")
engine.LOG_FILE_PATH = os.path.join(tmp_c, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_c, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_c, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_c, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None: (False, "")

eng_c = engine.GoldEngine()
run_candles(eng_c, candles_decline(240, 4800.0), datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))
dip_c = rejection_dip_sell(eng_c)
run_candles(eng_c, [dip_c], datetime(2026, 3, 1, 4, 0, tzinfo=timezone.utc))
check("C: SELL trade triggered", eng_c.trade_active and eng_c.trade_type == "SELL",
      f"trade_active={eng_c.trade_active} type={eng_c.trade_type}")

# Drive to SELL TP (downward price)
p_now = list(eng_c.closes)[-1]
down = [(p_now - i, p_now - i + 0.2, p_now - i - 0.8, p_now - i - 0.5) for i in range(1, 10)]
run_candles(eng_c, down, datetime(2026, 3, 1, 4, 1, tzinfo=timezone.utc))
check("C: SELL trade closed with TP", not eng_c.trade_active and eng_c.wins == 1, f"wins={eng_c.wins}")


# --- Scenario D ---
print("\nScenario D: daily loss circuit breaker -> halts trading after 3 SLs")
trades_sim = [
    {"Trade_Num": "1", "Trade_Type": "BUY", "Entry_Time": "2026-09-10 01:00:00", "Exit_Time": "2026-09-10 01:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
    {"Trade_Num": "2", "Trade_Type": "BUY", "Entry_Time": "2026-09-10 02:00:00", "Exit_Time": "2026-09-10 02:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
    {"Trade_Num": "3", "Trade_Type": "SELL", "Entry_Time": "2026-09-10 03:00:00", "Exit_Time": "2026-09-10 03:10:00", "Exit_Reason": "SL", "Profit": "-3.00"},
]
sl_count = trade_filter.get_daily_sl_count(trades_sim, datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc))
halted, halt_reason = trade_filter.check_daily_loss_limit(trades_sim, datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc))
check("D: daily SL count equals 3", sl_count == 3, f"count={sl_count}")
check("D: circuit breaker triggered", halted and "Daily Loss Limit Reached" in halt_reason, f"reason={halt_reason}")


# --- Scenario E ---
print("\nScenario E: restart state persistence")
eng_e = engine.GoldEngine()
check("E: EMA50 history seeded from CSV", len(eng_e.ema50_history) >= engine.EMA_SLOPE_LOOKBACK, f"{len(eng_e.ema50_history)} loaded")
check("E: trade stats loaded from trades.csv", eng_e.wins == 1 and eng_e.losses == 0)

shutil.rmtree(tmp_c, ignore_errors=True)

print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
