#!/usr/bin/env python3
"""
Smoke test for the engine's regime gates, bidirectional (Buy/Sell) execution,
daily loss circuit breaker, and trades.csv schema migration.

Runs GoldEngine.evaluate_candle() over synthetic 1-minute candles in temp
directories (no /opt/gold, no network, no Telegram, no real API keys needed).

Scenarios:
  A) Uptrend + rejection dip at 20-bar floor       -> BUY trade MUST trigger & close with TP
  B) Established decline + floor rejection dip     -> BUY trade MUST be blocked
  C) Downtrend + ceiling rejection dip             -> SELL trade MUST trigger & close with TP
  D) Daily loss circuit breaker                    -> MUST halt after MAX_DAILY_LOSSES SLs
  E) Restart from log                             -> EMA50 history seeds properly
  F) trades.csv schema drift (2026-09-10 incident) -> engine MUST auto-migrate and
     restore correct risk-gate counting for SELL trades
  G) stale-feed guard (2026-09-10 silent WebSocket stall) -> MUST detect a quiet
     feed, classify market-quiet hours, and rate-limit Telegram alerts
  H) MT5 sidecar feed file (DATA_SOURCE=MT5) -> engine MUST read the sidecar's
     JSON file, evaluate each closed M1 candle exactly once (no re-log after
     restart), and default to TWELVEDATA
  I) Breakeven ratchet (BE_TRIGGER_R) -> MUST arm at +BE_TRIGGER_R (0.75R since
     2026-09-15; it must NOT arm below the trigger), exit at entry with
     reason "BE" (scratch: counted separately from SL/TP, survives restart)
  J) Direction-aware risk gates -> London blackout blocks BUY but allows SELL;
     daily-loss breaker degrades to trend-side-only (momentum from price log),
     legacy no-side calls keep the old hard halt
  K) Max-hold time stop (MAX_HOLD_MINUTES, 2026-09-21) -> MUST close at market
     with reason "TIME" once older than the window (tick path + MT5 candle
     path, P&L-signed, own time_exits counter, survives restart); price exits
     take priority over TIME; a fresh trade must stay open
  L) MT5 feed health (2026-09-29 frozen-file stall) -> MUST report a missing (clock pinned)
     file, a stale sidecar heartbeat (frozen mt5_last_candle.json, even when no
     candle was ever accepted after a restart), and an unparseable payload;
     MUST stay quiet on a closed market with a live heartbeat; recovery fires
     once, on a newly accepted candle
  M) Restart boundary candle (2026-09-29) -> the mt5_last_candle_ts watermark
     MUST survive a restart. __init__ runs save_status() before run_mt5_test()
     reads it, so a None start clobbered it to null, dropped the dedup floor to
     0 and re-played the boundary candle (re-logged + re-tradeable). MUST also
     survive a flat candle (h==l) and an evaluate_candle() error, MUST still
     accept the next candle, and MUST degrade to a fresh start on a corrupt
     status.json

  N) Structural stop (2026-10-05) -> the stop must clear the 20-bar level the entry was
     anchored to (risk = max(2xATR, |entry-level| + SL_CLEAR_ATR x ATR)) and TP must keep
     1:1.5 against that ACTUAL risk; a retest of the level must NOT stop the trade out;
     the BE ratchet must arm at BE_TRIGGER_R x the NEW risk; entries that hug the level
     (and level=None) must keep the pre-change geometry byte-for-byte.

Usage: python3 tools/smoke_test.py
"""
import os
import sys
import json
import csv
import shutil
import tempfile
import time
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

# Scenarios A-C monkey-patch this away; J needs the real implementation.
REAL_IS_IN_BLACKOUT = trade_filter.is_in_blackout

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
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

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
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

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
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

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
print("\nScenario D: daily loss circuit breaker -> halts trading after MAX_DAILY_LOSSES SLs")
# Build exactly MAX_DAILY_LOSSES SL exits so the scenario stays valid
# however the constant is tuned (3 -> 10 on 2026-09-10).
trades_sim = [
    {"Trade_Num": str(i + 1), "Trade_Type": "SELL" if i == 2 else "BUY",
     "Entry_Time": f"2026-09-10 {1 + i:02d}:00:00", "Exit_Time": f"2026-09-10 {1 + i:02d}:10:00",
     "Exit_Reason": "SL", "Profit": "-3.00"}
    for i in range(trade_filter.MAX_DAILY_LOSSES)
]
sl_count = trade_filter.get_daily_sl_count(trades_sim, datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc))
halted, halt_reason = trade_filter.check_daily_loss_limit(trades_sim, datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc))
check("D: daily SL count equals MAX_DAILY_LOSSES", sl_count == trade_filter.MAX_DAILY_LOSSES, f"count={sl_count}")
check("D: circuit breaker triggered", halted and "Daily Loss Limit Reached" in halt_reason, f"reason={halt_reason}")


# --- Scenario E ---
print("\nScenario E: restart state persistence")
eng_e = engine.GoldEngine()
check("E: EMA50 history seeded from CSV", len(eng_e.ema50_history) >= engine.EMA_SLOPE_LOOKBACK, f"{len(eng_e.ema50_history)} loaded")
check("E: trade stats loaded from trades.csv", eng_e.wins == 1 and eng_e.losses == 0)

shutil.rmtree(tmp_c, ignore_errors=True)


# --- Scenario F ---
print("\nScenario F: trades.csv schema drift (pre-SELL header + SELL row) -> auto-migrate")
OLD_HEADER = ["Trade_Num", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
              "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
              "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"]
tmp_f = tempfile.mkdtemp(prefix="gold_smoke_f_")
engine.LOG_FILE_PATH = os.path.join(tmp_f, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_f, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_f, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_f, "skipped_trades.csv")

with open(engine.TRADES_LOG_PATH, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(OLD_HEADER)
    # two old-schema BUY rows (15 fields)
    w.writerow(["1", "2026-09-09 01:00:00", "2026-09-09 01:05:00", "4400.00", "4397.00", "4404.50",
                "4404.50", "TP", "4.50", "504.50", "55.0", "1.50", "50.0%", "4395.00", "4390.00"])
    w.writerow(["2", "2026-09-09 02:00:00", "2026-09-09 02:05:00", "4402.00", "4399.00", "4406.50",
                "4398.90", "SL", "-3.10", "501.40", "50.0", "1.55", "45.0%", "4396.00", "4391.00"])
    # the incident: 16-field SELL row appended under the 15-field header
    w.writerow(["3", "SELL", "2026-09-10 00:09:00", "2026-09-10 00:11:04", "4391.74", "4393.95",
                "4388.44", "4394.06", "SL", "-2.32", "450.40", "36.4", "1.10", "55.6%", "4395.23", "4399.46"])

# 1) demonstrate the incident: with drift, the SELL SL is invisible to the risk gates
drifted = trade_filter.load_recent_trades()
cnt_before = trade_filter.get_daily_sl_count(drifted, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc))
check("F: drifted file misses the SELL SL (bug reproduced)", cnt_before == 0, f"daily_sls={cnt_before}")

# 2) engine start must auto-migrate and resync stats
eng_f = engine.GoldEngine()
with open(engine.TRADES_LOG_PATH, newline="") as f:
    rdr = csv.DictReader(f)
    rows_f = list(rdr)
    hdr_f = rdr.fieldnames
check("F: header migrated to 16-field schema", hdr_f == engine.TRADES_FIELDNAMES, f"{hdr_f}")
check("F: old rows backfilled as BUY", all(r["Trade_Type"] == "BUY" for r in rows_f[:2]))
check("F: SELL row aligned (Exit_Reason=SL, Profit=-2.32)",
      rows_f[2]["Trade_Type"] == "SELL" and rows_f[2]["Exit_Reason"] == "SL"
      and rows_f[2]["Profit"] == "-2.32" and rows_f[2]["Balance_After"] == "450.40")
check("F: engine stats resynced (1W/2L, next=#4)",
      eng_f.wins == 1 and eng_f.losses == 2 and eng_f.next_trade_num == 4 and abs(eng_f.balance - 450.40) < 0.01,
      f"{eng_f.wins}W/{eng_f.losses}L next=#{eng_f.next_trade_num} bal={eng_f.balance}")

# 3) risk gates see the SELL SL now
migrated = trade_filter.load_recent_trades()
cnt_after = trade_filter.get_daily_sl_count(migrated, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc))
check("F: daily SL count sees the SELL SL after migration", cnt_after == 1, f"daily_sls={cnt_after}")

# 4) migration is idempotent and keeps a backup
check("F: re-migration is a no-op", engine.migrate_trades_csv(engine.TRADES_LOG_PATH) is False)
check("F: backup kept", os.path.exists(engine.TRADES_LOG_PATH + ".bak-pre-migration"))
shutil.rmtree(tmp_f, ignore_errors=True)


# --- Scenario G ---
print("\nScenario G: stale-feed guard (silent WebSocket stall)")
tmp_g = tempfile.mkdtemp(prefix="gold_smoke_g_")
engine.LOG_FILE_PATH = os.path.join(tmp_g, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_g, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_g, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_g, "skipped_trades.csv")

eng_g = engine.GoldEngine()

# fresh feed -> not stale
eng_g._last_price_mono = time.monotonic()
check("G: fresh feed not stale", eng_g.feed_stale_seconds() < 1.0, f"{eng_g.feed_stale_seconds():.2f}s")

# 11 min without ticks -> stale
eng_g._last_price_mono = time.monotonic() - (engine.STALE_FEED_SECONDS + 60)
stale = eng_g.feed_stale_seconds()
check("G: 11-min gap detected as stale", stale > engine.STALE_FEED_SECONDS, f"{stale:.0f}s")

# quiet-hours classification (no weekend/break alert spam)
check("G: Saturday 12:00 UTC is quiet", engine.is_market_quiet(datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)))
check("G: Friday 23:00 UTC is quiet (daily break)", engine.is_market_quiet(datetime(2026, 9, 11, 23, 0, tzinfo=timezone.utc)))
check("G: Thursday 01:30 UTC is quiet (daily break)", engine.is_market_quiet(datetime(2026, 9, 10, 1, 30, tzinfo=timezone.utc)))
check("G: Thursday 12:00 UTC is NOT quiet", not engine.is_market_quiet(datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)))

# alert rate-limit: first alert fires, immediate second is suppressed
first = eng_g.maybe_alert_stale_feed(stale)
second = eng_g.maybe_alert_stale_feed(stale)
check("G: stale alert fires once, then rate-limited", first is True and second is False)
shutil.rmtree(tmp_g, ignore_errors=True)


# --- Scenario H ---
print("\nScenario H: MT5 sidecar feed file (DATA_SOURCE=MT5)")
tmp_h = tempfile.mkdtemp(prefix="gold_smoke_h_")
engine.LOG_FILE_PATH = os.path.join(tmp_h, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_h, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_h, "trades.csv")
engine.MT5_FEED_FILE = os.path.join(tmp_h, "mt5_last_candle.json")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_h, "skipped_trades.csv")

check("H: default data source stays TWELVEDATA", engine.DATA_SOURCE == "TWELVEDATA",
      f"DATA_SOURCE={engine.DATA_SOURCE}")

eng_h = engine.GoldEngine()
check("H: missing feed file -> None", eng_h.read_mt5_feed() is None)

# sidecar publishes the latest closed candle; engine reads + normalizes it
feed1 = {"ts": 2000, "open": 4400.0, "high": 4401.0, "low": 4399.0,
         "close": 4400.5, "tick_volume": 12, "updated_at": "2026-09-10 05:01:03"}
with open(engine.MT5_FEED_FILE, "w") as f:
    json.dump(feed1, f)
r1 = eng_h.read_mt5_feed()
check("H: feed file normalized to rate shape",
      r1 is not None and r1[0]["time"] == 2000 and r1[0]["open"] == 4400.0 and r1[0]["tick_volume"] == 12)
check("H: first closed candle accepted",
      (lambda c: c is not None and c[0] == 2000 and c[1] == 4400.0 and c[5] == 12)(eng_h.mt5_next_candle(r1, 0)))
check("H: same candle NOT re-evaluated (restart dedup)", eng_h.mt5_next_candle(r1, 2000) is None)

with open(engine.MT5_FEED_FILE, "w") as f:
    json.dump({"ts": 2060, "open": 4400.5, "high": 4402.0, "low": 4400.0,
               "close": 4401.5, "tick_volume": 34, "updated_at": "2026-09-10 05:02:03"}, f)
c2 = eng_h.mt5_next_candle(eng_h.read_mt5_feed(), 2000)
check("H: next minute's candle accepted", c2 is not None and c2[0] == 2060 and c2[5] == 34)

with open(engine.MT5_FEED_FILE, "w") as f:
    f.write("corrupted")
check("H: corrupt feed file -> None (no crash)", eng_h.read_mt5_feed() is None)
check("H: no rates -> None", engine.latest_closed_candle_ts(None) is None)
check("H: empty rates -> None", engine.latest_closed_candle_ts([]) is None)
shutil.rmtree(tmp_h, ignore_errors=True)

# --- Scenario I ---
print(f"\nScenario I: breakeven ratchet -> +{engine.BE_TRIGGER_R:.2f}R arms, "
      "dip back to entry exits at ~0 (reason BE)")
tmp_i = tempfile.mkdtemp(prefix="gold_smoke_i_")
engine.LOG_FILE_PATH = os.path.join(tmp_i, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_i, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_i, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_i, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

eng_i = engine.GoldEngine()
run_candles(eng_i, candles_uptrend(240), datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc))
dip_i = rejection_dip_buy(eng_i)
run_candles(eng_i, [dip_i], datetime(2026, 5, 1, 4, 0, tzinfo=timezone.utc))
check("I: BUY trade triggered", eng_i.trade_active and eng_i.trade_type == "BUY",
      f"trade_active={eng_i.trade_active}")

entry_i = eng_i.entry_price
risk_i = entry_i - eng_i.stop_loss
check("I: risk sane", risk_i > 0, f"entry={entry_i} sl={eng_i.stop_loss}")

# 2026-09-15: trigger raised 0.30R -> 0.75R because +0.30R was one noisy minute of
# noise and scratched 78% of trades. Guard the NEW semantics too: an excursion that
# stays below the trigger must leave the stop where it was.
if engine.BE_TRIGGER_R > 0.4:
    sl_before_i = eng_i.stop_loss
    mid_i = entry_i + 0.4 * risk_i
    run_candles(eng_i, [(entry_i + 0.05, mid_i + 0.05, entry_i + 0.01, mid_i)],
                datetime(2026, 5, 1, 4, 1, tzinfo=timezone.utc))
    check(f"I: +0.40R does NOT arm the ratchet (trigger +{engine.BE_TRIGGER_R:.2f}R)",
          not eng_i.be_armed and eng_i.trade_active and eng_i.stop_loss == sl_before_i,
          f"armed={eng_i.be_armed} sl={eng_i.stop_loss} sl_before={sl_before_i} "
          f"active={eng_i.trade_active}")

# push price to just past the BE trigger, then collapse back below entry
be_level = entry_i + engine.BE_TRIGGER_R * risk_i
up_i = [(entry_i + 0.05, be_level + 0.07, entry_i + 0.01, be_level + 0.02)]
run_candles(eng_i, up_i, datetime(2026, 5, 1, 4, 2, tzinfo=timezone.utc))
check(f"I: BE ratchet armed at +{engine.BE_TRIGGER_R:.2f}R",
      eng_i.be_armed and eng_i.stop_loss == round(entry_i, 2),
      f"armed={eng_i.be_armed} sl={eng_i.stop_loss} entry={entry_i}")

bal_before = eng_i.balance
down_i = [(entry_i - 0.05, entry_i + 0.02, entry_i - 0.5, entry_i - 0.4)]
run_candles(eng_i, down_i, datetime(2026, 5, 1, 4, 3, tzinfo=timezone.utc))
check("I: trade closed as scratch (not a loss)",
      not eng_i.trade_active and eng_i.losses == 0 and eng_i.be_exits == 1,
      f"losses={eng_i.losses} be_exits={eng_i.be_exits} wins={eng_i.wins}")
check("I: balance ~unchanged after BE exit",
      abs(eng_i.balance - bal_before) <= max(1.0, risk_i) and eng_i.balance >= bal_before - risk_i - 0.01,
      f"balance={eng_i.balance} before={bal_before}")

with open(engine.TRADES_LOG_PATH, newline="") as f:
    rows_i = list(csv.DictReader(f))
check("I: trades.csv row logged with Exit_Reason=BE",
      len(rows_i) == 1 and rows_i[0]["Exit_Reason"] == "BE",
      f"rows={len(rows_i)} reason={rows_i[0]['Exit_Reason'] if rows_i else 'n/a'}")

# restart must restore BE-aware stats without crashing on the 'BE' reason
eng_i2 = engine.GoldEngine()
check("I: stats restore counts BE separately",
      eng_i2.be_exits == 1 and eng_i2.losses == 0 and eng_i2.wins == 0,
      f"wins={eng_i2.wins} losses={eng_i2.losses} be_exits={eng_i2.be_exits}")
shutil.rmtree(tmp_i, ignore_errors=True)


# --- Scenario J ---
print("\nScenario J: direction-aware gates (London BUY blackout / SELL allowed, trend-side breaker)")
trade_filter.is_in_blackout = REAL_IS_IN_BLACKOUT  # undo the A/B/C stub
bo_buy, _ = trade_filter.is_in_blackout(datetime(2026, 9, 10, 8, 30, tzinfo=timezone.utc), side="BUY")
bo_sell, _ = trade_filter.is_in_blackout(datetime(2026, 9, 10, 8, 30, tzinfo=timezone.utc), side="SELL")
check("J: London window blocks BUY", bo_buy)
check("J: London window allows SELL (phantom edge)", not bo_sell)
bo_ny_buy, _ = trade_filter.is_in_blackout(datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc), side="BUY")
bo_ny_sell, _ = trade_filter.is_in_blackout(datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc), side="SELL")
check("J: NY window still blocks both sides", bo_ny_buy and bo_ny_sell)

# trend-side daily-loss breaker: momentum file says DOWN -> SELL passes, BUY blocked
tmp_j = tempfile.mkdtemp(prefix="gold_smoke_j_")
now_j = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
pl_j = os.path.join(tmp_j, "forward_test_log.csv")
with open(pl_j, "w") as f:
    f.write("Timestamp,Open,High,Low,Close\n")
    f.write("2026-09-10 18:59:00,4400.0,4400.5,4399.5,4400.0\n")   # ~60 min before now
    f.write("2026-09-10 19:59:30,4379.0,4379.5,4378.5,4379.0\n")  # latest: clearly down
trade_filter.PRICE_LOG = pl_j
trades_j = [
    {"Trade_Num": str(i + 1), "Trade_Type": "BUY",
     "Entry_Time": f"2026-09-10 {1 + i:02d}:00:00", "Exit_Time": f"2026-09-10 {1 + i:02d}:10:00",
     "Exit_Reason": "SL", "Profit": "-3.00"}
    for i in range(trade_filter.MAX_DAILY_LOSSES)
]
blocked_buy, r_buy = trade_filter.check_daily_loss_limit(trades_j, now_j, side="BUY")
blocked_sell, r_sell = trade_filter.check_daily_loss_limit(trades_j, now_j, side="SELL")
check("J: momentum reads SELL from log", trade_filter.get_momentum_side(now_j) == "SELL")
check("J: after limit, counter-momentum BUY blocked with Daily Loss reason",
      blocked_buy and r_buy.startswith("Daily Loss Limit"), f"reason={r_buy}")
check("J: after limit, trend-side SELL still allowed", not blocked_sell, f"reason={r_sell}")
blocked_legacy, r_legacy = trade_filter.check_daily_loss_limit(trades_j, now_j)  # no side -> hard halt
check("J: legacy no-side call keeps hard halt",
      blocked_legacy and "Trading Halted" in r_legacy, f"reason={r_legacy}")
trade_filter.PRICE_LOG = "/opt/gold/forward_test_log.csv"
shutil.rmtree(tmp_j, ignore_errors=True)



# --- Scenario K ---
print(f"\nScenario K: max-hold time stop -> TIME exit after {engine.MAX_HOLD_MINUTES} min")
tmp_k = tempfile.mkdtemp(prefix="gold_smoke_k_")
engine.LOG_FILE_PATH = os.path.join(tmp_k, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_k, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_k, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_k, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

eng_k = engine.GoldEngine()
run_candles(eng_k, candles_uptrend(240), datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))
run_candles(eng_k, [rejection_dip_buy(eng_k)], datetime(2026, 6, 1, 4, 0, tzinfo=timezone.utc))
check("K: BUY trade triggered", eng_k.trade_active and eng_k.trade_type == "BUY")

entry_k = eng_k.entry_price
risk_k = entry_k - eng_k.stop_loss
drift_px = entry_k + 0.1 * risk_k  # mid-range: arms nothing, touches nothing

# fresh trade must NOT time-stop
eng_k.check_position(drift_px)
check("K: fresh trade stays open (no TIME, no arm)",
      eng_k.trade_active and eng_k.time_exits == 0 and not eng_k.be_armed,
      f"active={eng_k.trade_active} time_exits={eng_k.time_exits} armed={eng_k.be_armed}")

# expired trade closes at market with reason TIME (tick path)
past_k = (datetime.now(timezone.utc) - timedelta(minutes=engine.MAX_HOLD_MINUTES + 1))
past_k = past_k.strftime("%Y-%m-%d %H:%M:%S")
eng_k.entry_time = past_k
bal_k = eng_k.balance
eng_k.check_position(drift_px)
check("K: expired trade TIME-exits on tick path (neutral bucket)",
      not eng_k.trade_active and eng_k.time_exits == 1
      and eng_k.wins == 0 and eng_k.losses == 0 and eng_k.be_exits == 0,
      f"wins={eng_k.wins} losses={eng_k.losses} be={eng_k.be_exits} time={eng_k.time_exits}")
check("K: TIME books signed P&L (+0.1R here)",
      abs(eng_k.balance - (bal_k + 0.1 * risk_k)) < 0.01,
      f"balance={eng_k.balance:.2f} expected~{bal_k + 0.1 * risk_k:.2f}")

# price exits take priority over TIME
run_candles(eng_k, [rejection_dip_buy(eng_k)], datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc))
check("K: second BUY triggered (TIME exit caused no cooldown)", eng_k.trade_active)
eng_k.entry_time = past_k  # expired, but price gets there first
eng_k.check_position(eng_k.take_profit + 0.05)
check("K: simultaneous TP beats TIME", not eng_k.trade_active and eng_k.wins == 1
      and eng_k.time_exits == 1, f"wins={eng_k.wins} time={eng_k.time_exits}")

# MT5 candle path: inside-range candle on an expired trade -> TIME at close
run_candles(eng_k, [rejection_dip_buy(eng_k)], datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc))
check("K: third BUY triggered", eng_k.trade_active)
eng_k.entry_time = past_k
rk3 = eng_k.entry_price - eng_k.stop_loss
c3 = eng_k.entry_price + 0.1 * rk3
eng_k.resolve_open_trade_on_candle(o=c3 - 0.05, h=c3 + 0.05, l=c3 - 0.05, c=c3)
check("K: candle path TIME-exits at close",
      not eng_k.trade_active and eng_k.time_exits == 2,
      f"time_exits={eng_k.time_exits}")

# SELL sign check via direct state (profit = entry - price)
eng_k.trade_active = True
eng_k.trade_type = "SELL"
eng_k.current_trade_num = eng_k.next_trade_num
eng_k.next_trade_num += 1
eng_k.entry_price = 4400.0
eng_k.stop_loss = 4404.0
eng_k.take_profit = 4394.0
eng_k.be_armed = False
eng_k.entry_time = past_k
bal_s = eng_k.balance
eng_k.check_position(4398.0)
check("K: SELL TIME books entry-minus-price (+$2.00)",
      not eng_k.trade_active and eng_k.time_exits == 3
      and abs(eng_k.balance - (bal_s + 2.0)) < 0.01,
      f"balance={eng_k.balance:.2f} time={eng_k.time_exits}")

# BE-armed but timed-out: reason stays TIME (the stop never triggered)
eng_k.trade_active = True
eng_k.trade_type = "BUY"
eng_k.current_trade_num = eng_k.next_trade_num
eng_k.next_trade_num += 1
eng_k.entry_price = 4400.0
eng_k.stop_loss = 4400.0
eng_k.take_profit = 4405.0
eng_k.be_armed = True
eng_k.entry_time = past_k
eng_k.check_position(4400.5)  # above the ratcheted stop, below TP: no price level touched
with open(engine.TRADES_LOG_PATH, newline="") as f:
    rows_k = list(csv.DictReader(f))
check("K: armed-but-expired exits as TIME (not BE)",
      rows_k[-1]["Exit_Reason"] == "TIME" and abs(float(rows_k[-1]["Profit"]) - 0.5) < 0.01
      and eng_k.time_exits == 4 and eng_k.be_exits == 0,
      f"reason={rows_k[-1]['Exit_Reason']} profit={rows_k[-1]['Profit']} time={eng_k.time_exits}")

# restart restores TIME-aware stats + status.json carries the new counter
eng_k2 = engine.GoldEngine()
with open(engine.STATUS_FILE_PATH) as f:
    st_k = json.load(f)
check("K: stats restore counts TIME separately",
      eng_k2.time_exits == 4 and eng_k2.wins == 1 and eng_k2.losses == 0 and eng_k2.be_exits == 0,
      f"{eng_k2.wins}W/{eng_k2.losses}L/{eng_k2.be_exits}BE/{eng_k2.time_exits}TIME")
check("K: status.json total includes TIME exits",
      st_k.get("time_exits") == 4 and st_k.get("total_trades") == 5,
      f"time_exits={st_k.get('time_exits')} total={st_k.get('total_trades')}")
shutil.rmtree(tmp_k, ignore_errors=True)


# --- Scenario L ---
print("\nScenario L: MT5 feed health (2026-09-29 frozen-file stall)")
tmp_l = tempfile.mkdtemp(prefix="gold_smoke_l_")
engine.LOG_FILE_PATH = os.path.join(tmp_l, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_l, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_l, "trades.csv")
engine.MT5_FEED_FILE = os.path.join(tmp_l, "mt5_last_candle.json")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_l, "skipped_trades.csv")

eng_l = engine.GoldEngine()

# Pin the clock's "quiet hours" verdict for this scenario: mt5_feed_problem() calls
# is_market_quiet() with NO argument, so the stall checks below read the REAL wall
# clock and the scenario went red on a clean checkout at 00:09 UTC on 2026-10-05
# (quiet hours are 21:00-01:59 UTC + weekends). A smoke test must be a fact about the
# code, not about the time of day it happens to run.
REAL_IS_QUIET = engine.is_market_quiet
engine.is_market_quiet = lambda now=None: False     # active market hours

# 1) file missing -> reported, and never silently looped over
check("L: missing feed file reported", (eng_l.mt5_feed_problem() or "").startswith("feed file"),
      eng_l.mt5_feed_problem() or "None")

# sidecar publishes normally
CANDLE = {"ts": 1790681280, "open": 4141.39, "high": 4141.53, "low": 4140.06,
          "close": 4140.61, "tick_volume": 17, "updated_at": "2026-09-29 08:29:19"}


def publish(payload, mtime_age=0.0):
    with open(engine.MT5_FEED_FILE, "w") as f:
        json.dump(payload, f)
    t = time.time() - mtime_age
    os.utime(engine.MT5_FEED_FILE, (t, t))


publish(CANDLE)
check("L: fresh feed -> no problem", eng_l.mt5_feed_problem() is None,
      f"publisher_age={eng_l.feed_publisher_age_seconds():.1f}s")

# 2) the incident: file frozen (sidecar/terminal dead). No candle is ever
#    accepted, so _last_price_mono is still None after the 08:29 restart and the
#    old price-event guard was structurally blind - the heartbeat must catch it.
eng_l._last_price_mono = None
publish(CANDLE, mtime_age=engine.MT5_FEED_PUBLISHER_STALE_SECONDS + 600)
problem_l = eng_l.mt5_feed_problem()
check("L: frozen file detected with NO price event (post-restart case)",
      problem_l is not None and "stopped publishing" in problem_l, problem_l or "None")
check("L: price-event clock stays 0.0 here (why the old guard was blind)",
      eng_l.feed_stale_seconds() == 0.0)

# 3) a closed market is NOT a problem: the sidecar keeps republishing its last
#    closed bar (heartbeat fresh), so the heartbeat check stays quiet and the
#    price-event check is suppressed during quiet hours.
publish(CANDLE)  # heartbeat fresh again
eng_l._last_price_mono = time.monotonic() - (engine.STALE_FEED_SECONDS + 3600)
real_quiet = engine.is_market_quiet
engine.is_market_quiet = lambda now=None: True            # e.g. Saturday
check("L: quiet market with fresh heartbeat -> no problem",
      eng_l.mt5_feed_problem() is None, eng_l.mt5_feed_problem() or "None")
engine.is_market_quiet = real_quiet

# 4) publisher alive (market hours) but candles stalled -> still a problem
check("L: stalled candles with live publisher detected",
      "stalled" in (eng_l.mt5_feed_problem() or ""), eng_l.mt5_feed_problem() or "None")

# 5) corrupt payload with a live publisher -> a problem (not a silent loop)
with open(engine.MT5_FEED_FILE, "w") as f:
    f.write("corrupted")
eng_l.read_mt5_feed()  # the loop always reads before it checks
check("L: corrupt feed file reported",
      "cannot parse" in (eng_l.mt5_feed_problem() or ""), eng_l.mt5_feed_problem() or "None")

# 6) alert policy: rate-limited Telegram, journal print cooldown, recovery line
print("   (expect one 'MT5 feed problem' line and one 'recovered' line below)")
eng_l2 = engine.GoldEngine()
eng_l2.send_telegram = lambda text: setattr(eng_l2, "_sent", text)  # capture, don't send
eng_l2._sent = None
publish(CANDLE, mtime_age=engine.MT5_FEED_PUBLISHER_STALE_SECONDS + 600)
p0 = eng_l2.mt5_feed_problem()
first_l = eng_l2.report_mt5_feed_problem(p0)
second_l = eng_l2.report_mt5_feed_problem(p0)
check("L: alert fires once then rate-limited (30-min cooldown)",
      first_l is True and second_l is False, f"first={first_l} second={second_l}")
check("L: alert carries the MT5 wording, not the Twelve Data one",
      eng_l2._sent is not None and "MT5 feed dead" in eng_l2._sent, (eng_l2._sent or "None")[:60])
check("L: journal print is cooldown-limited too",
      eng_l2._last_feed_problem_log_mono is not None)

# ...but a recovery is only ever declared on a NEWLY accepted candle: the
# dedup (same ts) returns None, so the loop `continue`s before that call.
publish(CANDLE)
check("L: frozen file never reaches the recovery call (dedup gates it)",
      eng_l2.mt5_next_candle(eng_l2.read_mt5_feed(), CANDLE["ts"]) is None
      and eng_l2._mt5_feed_problem_active is True)
check("L: recovery line fires exactly once",
      eng_l2.report_mt5_feed_recovered(CANDLE["ts"] + 60) is True
      and eng_l2.report_mt5_feed_recovered(CANDLE["ts"] + 120) is False
      and eng_l2._mt5_feed_problem_active is False)
eng_l2._mt5_feed_problem_active = True  # leave it consistent for the next check

# 7) recovery actually resumes the forward test (new candle accepted once)
publish({"ts": CANDLE["ts"] + 60, "open": 4140.61, "high": 4142.0, "low": 4140.0,
         "close": 4141.5, "tick_volume": 22, "updated_at": "2026-09-29 14:40:00"})
c_l = eng_l2.mt5_next_candle(eng_l2.read_mt5_feed(), CANDLE["ts"])
check("L: new candle accepted after recovery (exactly once)",
      c_l is not None and c_l[0] == CANDLE["ts"] + 60
      and eng_l2.mt5_next_candle(eng_l2.read_mt5_feed(), CANDLE["ts"] + 60) is None)
engine.is_market_quiet = REAL_IS_QUIET
shutil.rmtree(tmp_l, ignore_errors=True)


# --- Scenario M ---
print("\nScenario M: restart boundary candle (watermark must survive a restart)")
tmp_m = tempfile.mkdtemp(prefix="gold_smoke_m_")
engine.LOG_FILE_PATH = os.path.join(tmp_m, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_m, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_m, "trades.csv")
engine.MT5_FEED_FILE = os.path.join(tmp_m, "mt5_last_candle.json")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_m, "skipped_trades.csv")

BOUNDARY_TS = 1790681280


def publish_m(ts, o=4141.0, h=4142.0, l=4140.0, c=4141.5, v=17):
    with open(engine.MT5_FEED_FILE, "w") as f:
        json.dump({"ts": ts, "open": o, "high": h, "low": l, "close": c,
                   "tick_volume": v, "updated_at": "2026-09-29 08:29:19"}, f)
    t = time.time()
    os.utime(engine.MT5_FEED_FILE, (t, t))


def persisted_ts():
    try:
        with open(engine.STATUS_FILE_PATH) as f:
            return json.load(f).get("mt5_last_candle_ts")
    except Exception:
        return "<unreadable>"


def count_log_rows(ts=None):
    """Rows in forward_test_log.csv, optionally only those matching an OHLC."""
    if not os.path.isfile(engine.LOG_FILE_PATH):
        return 0
    with open(engine.LOG_FILE_PATH) as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows[1:] if r]
    if ts is None:
        return len(rows)
    return sum(1 for r in rows if r[1:5] == ["4141.0", "4142.0", "4140.0", "4141.5"])


# Session 1: accept the boundary candle and persist the watermark.
eng_m1 = engine.GoldEngine()
publish_m(BOUNDARY_TS)
c_m1 = eng_m1.mt5_next_candle(eng_m1.read_mt5_feed(), eng_m1._mt5_last_candle_ts or 0)
check("M: session 1 accepts the boundary candle",
      c_m1 is not None and c_m1[0] == BOUNDARY_TS, str(c_m1))
eng_m1._mt5_last_candle_ts = BOUNDARY_TS
eng_m1.save_status()
check("M: watermark persisted to status.json", persisted_ts() == BOUNDARY_TS, str(persisted_ts()))

# Session 2: restart. __init__ runs save_status() *before* run_mt5_test() reads
# the watermark, so starting _mt5_last_candle_ts at None used to null it out and
# drop the dedup floor to 0 -> the boundary candle got re-played.
eng_m2 = engine.GoldEngine()
check("M: restart restores the watermark in memory",
      eng_m2._mt5_last_candle_ts == BOUNDARY_TS, str(eng_m2._mt5_last_candle_ts))
check("M: __init__'s own save_status() does NOT null the watermark",
      persisted_ts() == BOUNDARY_TS, str(persisted_ts()))
publish_m(BOUNDARY_TS)
check("M: boundary candle NOT re-accepted after restart (no re-log, no re-trade)",
      eng_m2.mt5_next_candle(eng_m2.read_mt5_feed(), eng_m2._mt5_last_candle_ts or 0) is None)
publish_m(BOUNDARY_TS + 60)
check("M: the NEXT candle is still accepted (fix must not stall the feed)",
      (lambda c: c is not None and c[0] == BOUNDARY_TS + 60)(
          eng_m2.mt5_next_candle(eng_m2.read_mt5_feed(), eng_m2._mt5_last_candle_ts or 0)))

# The watermark must also survive candles whose evaluate_candle() bails before
# its save_status(): a flat candle (h == l) and the loop's exception handler.
eng_m3 = engine.GoldEngine()
eng_m3._mt5_last_candle_ts = BOUNDARY_TS
eng_m3.save_status()
eng_m3.evaluate_candle(4141.0, 4141.0, 4141.0, 4141.0, 5)   # flat: early return
check("M: flat candle (h==l) still persists the watermark",
      persisted_ts() == BOUNDARY_TS, str(persisted_ts()))
FLAT_TS = BOUNDARY_TS + 120
eng_m3._mt5_last_candle_ts = FLAT_TS
eng_m3.evaluate_candle(4141.0, 4141.0, 4141.0, 4141.0, 5)   # flat, new ts
check("M: a flat candle is consumed (no replay of it after a restart)",
      persisted_ts() == FLAT_TS, str(persisted_ts()))
check("M: a flat candle is not logged as a price row",
      count_log_rows() == 0, f"{count_log_rows()} rows")

# ...and when evaluate_candle() raises: run_mt5_test's handler has to persist,
# because that candle was already consumed from the feed. Drive one real loop
# iteration in a thread; mt5_feed_problem() is patched to end the loop on the
# next pass (KeyboardInterrupt is only delivered to the main thread, so it has
# to be raised from inside the worker).
import threading  # noqa: E402

eng_m4 = engine.GoldEngine()
eng_m4._mt5_last_candle_ts = BOUNDARY_TS
eng_m4.save_status()
RAISE_TS = BOUNDARY_TS + 180
publish_m(RAISE_TS, o=4200.0, h=4201.0, l=4199.0, c=4200.5)

_real_eval = engine.GoldEngine.evaluate_candle
_real_problem = engine.GoldEngine.mt5_feed_problem
_calls = {"n": 0}


def _raiser(self, *a, **k):
    _calls["n"] += 1
    raise RuntimeError("synthetic evaluate_candle failure")


def _stopper(self, *a, **k):
    if _calls["n"]:
        raise KeyboardInterrupt        # ends the loop after the erroring pass
    return _real_problem(self)


engine.GoldEngine.evaluate_candle = _raiser
engine.GoldEngine.mt5_feed_problem = _stopper
th = threading.Thread(target=eng_m4.run_mt5_test, daemon=True)
th.start()
th.join(timeout=30)
engine.GoldEngine.evaluate_candle = _real_eval
engine.GoldEngine.mt5_feed_problem = _real_problem
check("M: erroring candle was attempted", _calls["n"] >= 1, f"calls={_calls['n']}")
check("M: evaluate_candle error still persists the watermark (no replay)",
      persisted_ts() == RAISE_TS, f"persisted={persisted_ts()} expected={RAISE_TS}")
check("M: loop thread exited", not th.is_alive())

# Corrupt status.json must degrade to a fresh start, never crash the boot.
with open(engine.STATUS_FILE_PATH, "w") as f:
    f.write("{not json")
eng_m5 = engine.GoldEngine()
check("M: corrupt status.json -> no crash, watermark None",
      eng_m5._mt5_last_candle_ts is None, str(eng_m5._mt5_last_candle_ts))
shutil.rmtree(tmp_m, ignore_errors=True)

# --- Scenario N ---
print("\nScenario N: structural stop -> the stop must clear the 20-bar level the entry was built on")
tmp_n = tempfile.mkdtemp(prefix="gold_smoke_n_")
engine.LOG_FILE_PATH = os.path.join(tmp_n, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_n, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_n, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_n, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

eng_n = engine.GoldEngine()
run_candles(eng_n, candles_uptrend(240), datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))
floor_n = min(list(eng_n.lows)[-engine.LOOKBACK_PERIOD:])
atr_n = eng_n.atr
p_n = list(eng_n.closes)[-1]
check("N: setup is a *chased* entry (close well clear of the floor)",
      (p_n - floor_n) / atr_n > 1.5,
      f"entry-floor distance {(p_n - floor_n) / atr_n:.2f} ATR (live median 2.53 ATR)")

# Rejection bar: sweeps below the 20-bar floor, closes above it, 90% lower wick.
dip_n = (p_n, p_n + 0.3, floor_n - 0.1, p_n - 1.2)
run_candles(eng_n, [dip_n], datetime(2026, 6, 1, 4, 0, tzinfo=timezone.utc))
check("N: BUY trade triggered", eng_n.trade_active and eng_n.trade_type == "BUY",
      f"active={eng_n.trade_active} type={eng_n.trade_type}")

entry_n = eng_n.entry_price
risk_n = entry_n - eng_n.stop_loss
atr_entry_n = eng_n.atr            # unchanged until the NEXT bar is evaluated
expected_n = (entry_n - floor_n) + engine.SL_CLEAR_ATR * atr_entry_n
check("N: stop is level-bound, not ATR-bound",
      eng_n.structural_stop_bound and risk_n > engine.ATR_SL_MULT * atr_entry_n + 1e-9,
      f"risk={risk_n:.3f} ATR-floor={engine.ATR_SL_MULT * atr_entry_n:.3f}")
check("N: risk == distance-to-level + clearance",
      abs(risk_n - expected_n) < 1e-6, f"risk={risk_n:.3f} expected={expected_n:.3f}")
check("N: stop sits beyond the floor by >= SL_CLEAR_ATR (the premise of the trade)",
      floor_n - eng_n.stop_loss >= engine.SL_CLEAR_ATR * atr_entry_n - 1e-6,
      f"sl={eng_n.stop_loss:.3f} floor={floor_n:.3f} clearance={floor_n - eng_n.stop_loss:.3f} "
      f"(needs {engine.SL_CLEAR_ATR * atr_entry_n:.3f})")
check("N: TP keeps the 1:1.5 ratio against the ACTUAL risk",
      abs((eng_n.take_profit - entry_n) - engine.RR_TARGET * risk_n) < 1e-6,
      f"tp dist={eng_n.take_profit - entry_n:.3f} vs {engine.RR_TARGET:.2f}x risk")

# The old 2xATR stop was INSIDE the range, so a mere retest of the level printed an
# SL (median SL lifetime 7.2 min on the 0.75R master book). Now it must survive one.
legacy_stop = entry_n - engine.ATR_SL_MULT * atr_entry_n
retest_low = floor_n - 0.2
check("N: the retest WOULD have hit the old 2xATR stop",
      retest_low < legacy_stop, f"retest_low={retest_low:.2f} old stop={legacy_stop:.2f}")
sl_before_n = eng_n.stop_loss
run_candles(eng_n, [(entry_n - 0.5, entry_n + 0.2, retest_low, entry_n - 0.8)],
            datetime(2026, 6, 1, 4, 1, tzinfo=timezone.utc))
check("N: level retest no longer stops the trade out",
      eng_n.trade_active and eng_n.losses == 0 and eng_n.stop_loss == sl_before_n,
      f"active={eng_n.trade_active} losses={eng_n.losses} sl={eng_n.stop_loss} was={sl_before_n}")

# A restart mid-trade must keep the WIDER stop: restore_open_trade_from_status() reads
# entry/SL/TP from status.json, and its "if be_armed: SL = entry" branch must not
# re-derive the geometry from ATR (that would move the stop back inside the level).
with open(engine.STATUS_FILE_PATH) as f:
    st_n = json.load(f)
eng_n3 = engine.GoldEngine()
check("N: status.json + restart keep the structural stop/TP",
      eng_n3.trade_active and abs(eng_n3.stop_loss - eng_n.stop_loss) < 0.011
      and abs(eng_n3.take_profit - eng_n.take_profit) < 0.011
      and abs(st_n["stop_loss"] - eng_n.stop_loss) < 0.011,
      f"sl={eng_n3.stop_loss:.3f} want={eng_n.stop_loss:.3f} tp={eng_n3.take_profit:.3f} "
      f"want={eng_n.take_profit:.3f}")

# +0.40R must NOT arm the ratchet, +0.75R must - and 0.75R is measured against the
# WIDER risk (that is the point: the scratch rate was 33% because 0.75 x 2ATR was noise).
if engine.BE_TRIGGER_R > 0.4:
    sl_before_n = eng_n.stop_loss
    mid_n = entry_n + 0.40 * risk_n
    run_candles(eng_n, [(entry_n - 0.6, mid_n + 0.2, entry_n - 0.8, mid_n)],
                datetime(2026, 6, 1, 4, 2, tzinfo=timezone.utc))
    check("N: +0.40R of the NEW risk does not arm", not eng_n.be_armed and eng_n.stop_loss == sl_before_n,
          f"armed={eng_n.be_armed}")
be_level_n = entry_n + engine.BE_TRIGGER_R * risk_n
run_candles(eng_n, [(mid_n, be_level_n + 0.1, mid_n - 0.1, be_level_n)],
            datetime(2026, 6, 1, 4, 3, tzinfo=timezone.utc))
check(f"N: ratchet arms at +{engine.BE_TRIGGER_R:.2f}R of the structural risk",
      eng_n.be_armed and eng_n.stop_loss == round(entry_n, 2),
      f"armed={eng_n.be_armed} sl={eng_n.stop_loss} entry={entry_n}")

# Backward compatibility, checked on the pure function because the funnel's own
# MAX_BELOW_EMA_ATR guard makes a *hugging* entry nearly impossible in a trending
# synthetic series (median |EMA50 - level| is 0.93 ATR, so a floor-close entry has to
# be far below the EMA): whenever the ATR floor already clears the level, or there is
# no level at all (short history, restart restore), geometry must be EXACTLY the
# pre-2026-10-05 one - risk = 2 x ATR, TP = 3 x ATR.
a = 1.5
for label, lvl in (("no level (history too short)", None), ("level 0.1 ATR away", 4400.0 - 0.15),
                   ("level 1.5 ATR away", 4400.0 - 2.25)):
    got = eng_n.structural_risk("BUY", 4400.0, a, lvl)
    check(f"N: {label} -> risk = ATR_SL_MULT x ATR ({engine.ATR_SL_MULT * a:.2f})",
          abs(got - engine.ATR_SL_MULT * a) < 1e-12, f"got={got}")
check("N: a level 3.9 ATR away pushes risk to level + clearance",
      abs(eng_n.structural_risk("BUY", 4400.0, a, 4400.0 - 3.9 * a) - (3.9 * a + engine.SL_CLEAR_ATR * a)) < 1e-9,
      f"got={eng_n.structural_risk('BUY', 4400.0, a, 4400.0 - 3.9 * a):.4f} "
      f"want={3.9 * a + engine.SL_CLEAR_ATR * a:.4f}")
check("N: a SELL stop is mirrored (above the ceiling, same distance)",
      abs(eng_n.structural_risk("SELL", 4400.0, a, 4400.0 + 3.9 * a) - (3.9 * a + engine.SL_CLEAR_ATR * a)) < 1e-9)

shutil.rmtree(tmp_n, ignore_errors=True)


print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
