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
  I) Breakeven ratchet (BE_TRIGGER_R) -> MUST arm at +0.30R, exit at entry with
     reason "BE" (scratch: counted separately from SL/TP, survives restart)
  J) Direction-aware risk gates -> London blackout blocks BUY but allows SELL;
     daily-loss breaker degrades to trend-side-only (momentum from price log),
     legacy no-side calls keep the old hard halt

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
print("\nScenario I: breakeven ratchet -> +0.30R arms, dip back to entry exits at ~0 (reason BE)")
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

# push price to just past the BE trigger (+0.30R), then collapse back below entry
be_level = entry_i + engine.BE_TRIGGER_R * risk_i
up_i = [(entry_i + 0.05, be_level + 0.07, entry_i + 0.01, be_level + 0.02)]
run_candles(eng_i, up_i, datetime(2026, 5, 1, 4, 1, tzinfo=timezone.utc))
check("I: BE ratchet armed at +0.30R", eng_i.be_armed and eng_i.stop_loss == round(entry_i, 2),
      f"armed={eng_i.be_armed} sl={eng_i.stop_loss} entry={entry_i}")

bal_before = eng_i.balance
down_i = [(entry_i - 0.05, entry_i + 0.02, entry_i - 0.5, entry_i - 0.4)]
run_candles(eng_i, down_i, datetime(2026, 5, 1, 4, 2, tzinfo=timezone.utc))
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


print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
