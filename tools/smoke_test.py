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

  O) Structural-stop GUARD + replay-harness fidelity (2026-10-13) -> strategy_lab's 20-bar level
     MUST equal the engine's own logged Dynamic_Floor on every bar (it was 19 bars: 86% match);
     tools/check_structural_stop.py MUST classify each stop as OLD / NEW / BOTH rule, MUST locate the
     deploy between the last OLD and first NEW trade, and MUST tell a BOUNDARY error (old-rule trades
     before the first new-rule trade: exit 1 'BOUNDARY ERROR') from a REGRESSION (old-rule trade
     after the first new-rule trade) while passing a clean deploy (exit 0). Synthetic data only.

  P) HANDOFF freshness gate (2026-10-13, port of bitcoin-trading-bot's handoff_check) ->
     tools/handoff_check.py MUST treat normal drift (new bars, a few closed trades, a new open trade,
     up to 30 trades / 48 h) as fresh so the autosync digest never cries wolf, and MUST flag STALE:
     >30 trades or >48 h behind, outcomes/money changed with an unchanged trade count (ledger edited),
     a snapshot AHEAD of the data, a different cost assumption, a cutover that disagrees with
     strategy_lab.LIVE_CUTOVER, a missing key, a missing block (exit 2). `--update` rewrites only
     the marked block. Synthetic data only; the verdict is advisory in autosync (never blocks).

  Q) XM quote + contract-spec logger (2026-10-13, port of bitcoin-trading-bot PR #10) ->
     tools/mt5_quotes.py MUST be read-only by construction (AST walk for trading-API names, a fake
     terminal that records any trading call), MUST never write a login/name/server/balance/Windows
     path into the public repo (allow-lists, planted secrets), MUST write 30 s UTC-aligned rows
     with a point sample + 5 s envelope, MUST record a closed market as STALE rows (not NOQUOTE,
     and without tripping its own dead-logger watchdog), MUST NOT let a frozen tick or one glitchy
     tick move the learned server offset, MUST pick up a DST change on 2 agreeing fresh ticks -
     including one that happens while gold is shut - and MUST survive schema drift, a torn line,
     restarts and UTC-midnight rotation. The autosync/unit wiring is checked statically.
     Synthetic data only; fake terminal + fake clock (no sleeping, no Wine).

  R) xm_quote_report + broker_time (2026-10-13) -> MUST separate scheduled closures from feed
     stalls from logger outages, count only usable rows in the spread tables, join ledger trades to
     the quote at entry AND exit (cost = the mean of the two, vs the assumed $0.40), print the
     --spread/--cost flags that re-cost the ledger, and keep the DST verdict UNVERIFIED until a
     transition has been observed (EU vs US vs NEITHER). Also reads the logger's OWN output.

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
      f"entry-floor distance {(p_n - floor_n) / atr_n:.2f} ATR (live median 2.42 ATR)")

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

# --- Scenario O ---
print("\nScenario O: structural-stop guard + replay-harness fidelity "
      "(tools/check_structural_stop.py, tools/strategy_lab.py)")
import contextlib  # noqa: E402
import io  # noqa: E402
import strategy_lab as SL  # noqa: E402
import check_structural_stop as CSS  # noqa: E402

# O1: the lab's 20-bar level is the ENGINE's level (20 PRIOR bars, oldest included). Feed one
# synthetic series to the real engine and to the lab, and compare the engine's own logged
# Dynamic_Floor with the lab's floor on every bar. (The lab used 19 prior bars until 2026-10-13:
# an 86% match on the live log, which tightened every replayed structural stop.)
tmp_o = tempfile.mkdtemp(prefix="gold_smoke_o_")
engine.LOG_FILE_PATH = os.path.join(tmp_o, "forward_test_log.csv")
engine.STATUS_FILE_PATH = os.path.join(tmp_o, "status.json")
engine.TRADES_LOG_PATH = os.path.join(tmp_o, "trades.csv")
trade_filter.TRADES_LOG = engine.TRADES_LOG_PATH
trade_filter.SKIP_LOG = os.path.join(tmp_o, "skipped_trades.csv")
trade_filter.is_in_blackout = lambda now=None, side=None: (False, "")

cand_o, p_o = [], 4400.0
for k in range(70):
    d_o = (0.6, -0.4, 0.5, -0.7, 0.3)[k % 5]
    o_o, c_o = p_o, p_o + d_o
    hi_o = max(o_o, c_o) + 0.3 + 0.05 * (k % 3)
    lo_o = min(o_o, c_o) - 0.3 - 0.05 * (k % 4)
    if k == 0:                       # extreme bar 0: it is the OLDEST bar of bar 20's window
        lo_o -= 6.0
        hi_o += 6.0
    if k == 40:                      # a later extreme that drops out of the window at bar 60
        lo_o -= 3.0
    cand_o.append((round(o_o, 2), round(hi_o, 2), round(lo_o, 2), round(c_o, 2)))
    p_o = c_o
eng_o = engine.GoldEngine()
run_candles(eng_o, cand_o, datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))
with open(engine.LOG_FILE_PATH, newline="") as fh_o:
    rows_o = list(csv.DictReader(fh_o))
bars_o = [(datetime(2026, 6, 1) + timedelta(minutes=k), o_, h_, l_, c_, 30.0)
          for k, (o_, h_, l_, c_) in enumerate(cand_o)]
lab_o = SL.Lab(bars_o)
n_cmp = n_bad = 0
for k in range(SL.LOOKBACK, len(cand_o)):
    logged_o = rows_o[k]["Dynamic_Floor"]
    if logged_o in ("Calculating", ""):
        continue
    n_cmp += 1
    if abs(float(logged_o) - lab_o.floor[k]) > 0.006:
        n_bad += 1
check("O: strategy_lab floor == the engine's logged Dynamic_Floor on every bar",
      n_cmp >= 40 and n_bad == 0, f"{n_cmp} bars compared, {n_bad} differ")
check("O: bar 20's level window still holds bar 0 (the oldest of the 20 prior bars)",
      lab_o.floor[SL.LOOKBACK] == min(l_ for (_o, _h, l_, _c) in cand_o[:20])
      and lab_o.ceil[SL.LOOKBACK] == max(h_ for (_o, h_, _l, _c) in cand_o[:20]),
      f"floor={lab_o.floor[SL.LOOKBACK]} ceil={lab_o.ceil[SL.LOOKBACK]}")
check("O: bar 0 has left the window by bar 21; no level exists before LOOKBACK bars",
      lab_o.floor[SL.LOOKBACK + 1] == min(l_ for (_o, _h, l_, _c) in cand_o[1:21])
      and lab_o.floor[SL.LOOKBACK - 1] is None and lab_o.ceil[SL.LOOKBACK - 1] is None)
shutil.rmtree(tmp_o, ignore_errors=True)

# O2: which rule produced a stop? (pure; atr=2.0 so 2xATR=4.0, SL_CLEAR_ATR*ATR=1.0)
for label, risk_, dist_, want_ in (
        ("risk 2.0 ATR with the level 5 $ away -> OLD", 4.0, 5.0, "OLD"),
        ("risk = level + 0.5 ATR -> NEW", 6.0, 5.0, "NEW"),
        ("level hugging the entry: both rules give 2.0 ATR -> BOTH", 4.0, 0.4, "BOTH"),
        ("a stop between the two rules (join error?) -> ???", 5.0, 5.0, "???")):
    got_ = CSS.geometry_class(risk_, 2.0, dist_)
    check(f"O: geometry_class: {label}", got_ == want_, f"got {got_}")


# O3/O4: locate the deploy from the ledger and diagnose a failure (pure)
def _orow(num, minute, cls_):
    return {"cls": cls_, "tr": {"num": num, "et": datetime(2026, 10, 6, 3, minute), "side": "SELL"},
            "risk": 2.0, "dist": 2.5}


clean_o = [_orow(1, 0, "OLD"), _orow(2, 5, "BOTH"), _orow(3, 10, "OLD"), _orow(4, 20, "NEW"), _orow(5, 25, "BOTH")]
lo_, fn_, late_ = CSS.boundary_evidence(clean_o)
check("O: boundary evidence = (last OLD, first NEW, no late OLD) on a clean deploy",
      lo_["tr"]["num"] == 3 and fn_["tr"]["num"] == 4 and late_ == [])
mixed_o = clean_o + [_orow(6, 30, "OLD")]
lo_, fn_, late_ = CSS.boundary_evidence(mixed_o)
check("O: an OLD trade after the first NEW one is reported as late (mixed geometry)",
      [r["tr"]["num"] for r in late_] == [6])
check("O: no NEW trade yet -> no evidence, no crash",
      CSS.boundary_evidence([_orow(1, 0, "OLD")])[1] is None)
cut_o = datetime(2026, 10, 6, 3, 0)
check("O: diagnosis: old-rule trades before the first new-rule trade = BOUNDARY ERROR",
      "BOUNDARY ERROR" in CSS.diagnose_failure([clean_o[0]], clean_o[2], clean_o[3], [], cut_o))
check("O: diagnosis: an old-rule trade after the first new-rule trade = REGRESSION",
      "REGRESSION" in CSS.diagnose_failure([mixed_o[5]], mixed_o[5], clean_o[3], [mixed_o[5]], cut_o))

# O5: the whole tool, end to end, on a synthetic ledger. Flat 4100 tape (range 2.0 -> ATR 2.0)
# with a 4110 spike at 02:20 and another at 03:20, so the 20-bar ceiling sits ~10 $ above a SELL
# entry for the 20 bars after each spike (the level binds: new risk 11 vs old 4).
def _o_world(trades_spec):
    """trades_spec = [(hh, mm, 'OLD'|'NEW')] SELLs entered at that minute of 2026-10-06."""
    root_ = tempfile.mkdtemp(prefix="gold_smoke_o2_")
    t0_ = datetime(2026, 10, 6, 1, 0)
    bars_ = []
    for k in range(170):
        t_ = t0_ + timedelta(minutes=k)
        hi_ = 4101.0
        if t_ in (datetime(2026, 10, 6, 2, 20), datetime(2026, 10, 6, 3, 20)):
            hi_ = 4110.0
        bars_.append((t_, 4100.0, hi_, 4099.0, 4100.0, 20.0))
    with open(os.path.join(root_, "forward_test_log.csv"), "w", newline="") as fh_:
        w_ = csv.writer(fh_)
        w_.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        for b_ in bars_:
            w_.writerow([b_[0].strftime("%Y-%m-%d %H:%M:%S")] + [f"{x_:.2f}" for x_ in b_[1:5]] + [int(b_[5])])
    lab_ = SL.Lab(bars_)
    with open(os.path.join(root_, "trades.csv"), "w", newline="") as fh_:
        w_ = csv.writer(fh_)
        w_.writerow(["Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss",
                     "Take_Profit", "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
                     "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"])
        for n_, (hh_, mm_, rule_) in enumerate(trades_spec, start=1):
            et_ = datetime(2026, 10, 6, hh_, mm_)
            i_ = [b[0] for b in bars_].index(et_)
            atr_, lvl_ = lab_.atr[i_], lab_.ceil[i_]
            risk_ = 2.0 * atr_ if rule_ == "OLD" else max(2.0 * atr_, abs(4100.0 - lvl_) + 0.5 * atr_)
            sl_, tp_ = round(4100.0 + risk_, 2), round(4100.0 - SL.RR_TARGET * risk_, 2)
            w_.writerow([n_, "SELL", et_.strftime("%Y-%m-%d %H:%M:%S"),
                         (et_ + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S"), "4100.00",
                         f"{sl_:.2f}", f"{tp_:.2f}", f"{sl_:.2f}", "SL", f"{-risk_:.2f}", "490.00", "45.0",
                         f"{atr_:.2f}", "60.0%", "4100.00", "4100.00"])
    return root_


def _o_run(spec):
    root_ = _o_world(spec)
    buf_ = io.StringIO()
    with contextlib.redirect_stdout(buf_):
        rc_ = CSS.main(["--root", root_])
    shutil.rmtree(root_, ignore_errors=True)
    return rc_, buf_.getvalue()


# The synthetic timeline is built around a 03:00 cutover. Pin the constant for these cases so the
# scenario stays valid when LIVE_CUTOVER is legitimately moved for a future deploy (this file is the
# autosync deploy gate: a test coupled to the live constant would roll back a good deploy).
_live_cutover_saved = SL.LIVE_CUTOVER
SL.LIVE_CUTOVER = datetime(2026, 10, 6, 3, 0)
# clean: two old-rule trades before 03:00, two new-rule trades after it
rc_, out_ = _o_run([(2, 30, "OLD"), (2, 40, "OLD"), (3, 25, "NEW"), (3, 35, "NEW")])
check("O: clean deploy (OLD before the cutover, NEW after) -> exit 0, PASS, bracket OK",
      rc_ == 0 and "PASS" in out_ and "is inside the bracket" in out_, f"rc={rc_}")
# boundary error: an OLD-rule trade at 03:25 is 'post-cutover' only because the constant is too early
rc_, out_ = _o_run([(2, 30, "OLD"), (2, 40, "OLD"), (3, 25, "OLD"), (3, 35, "NEW")])
check("O: old-rule trade after LIVE_CUTOVER but before the first new-rule trade -> exit 1, BOUNDARY ERROR",
      rc_ == 1 and "FAIL" in out_ and "BOUNDARY ERROR" in out_ and "too EARLY" in out_, f"rc={rc_}")
# regression: new rule is running, then an old-rule stop shows up again
rc_, out_ = _o_run([(2, 30, "OLD"), (3, 25, "NEW"), (3, 35, "OLD")])
check("O: old-rule trade AFTER the first new-rule trade -> exit 1, REGRESSION",
      rc_ == 1 and "REGRESSION" in out_, f"rc={rc_}")
# a cutover constant that contradicts the ledger evidence is itself a failure, even with 0 'inside'
SL.LIVE_CUTOVER = datetime(2026, 10, 6, 2, 35)       # earlier than the last old-rule trade (02:40)
rc_, out_ = _o_run([(2, 30, "OLD"), (2, 40, "OLD"), (3, 25, "NEW"), (3, 35, "NEW")])
check("O: a cutover constant earlier than the last old-rule trade is flagged EARLY (exit 1)",
      rc_ == 1 and "too EARLY" in out_, f"rc={rc_}")
SL.LIVE_CUTOVER = _live_cutover_saved

# --- Scenario P ---
print("\nScenario P: handoff_check tolerance policy (30 trades / 48 h, no crying wolf)")
import handoff_check as HC  # noqa: E402

P_DOC = {
    "as_of_utc": "2026-10-13 11:59", "data_collection": "226", "closed_trades": "575",
    "outcomes": "110W/248L/215BE/2TIME", "decisive_wr_pct": "30.7", "engine_ledger_usd": "197.46",
    "true_equity_usd": "180.49", "cost_usd_per_side": "0.20", "net_pnl_usd_at_cost": "-549.51",
    "cutover_utc": SL.LIVE_CUTOVER.strftime("%Y-%m-%d %H:%M"), "structstop_era_trades": "78",
    "structstop_era_outcomes": "25W/37L/15BE/1TIME", "log_bars": "38954",
    "log_last_bar_utc": "2026-10-13 11:59", "skip_rows": "1307", "open_trade": "SELL #577 @ 4182.61",
}


def p_stale(doc=None, **live_over):
    """Keys HC.compare() calls STALE when the live data differs by live_over."""
    live = dict(P_DOC)
    live.update(live_over)
    rows = HC.compare(doc or P_DOC, live)
    return sorted(k for k, _d, _l, verdict, _n in rows if verdict == "STALE")


def p_after(n_trades, **kw):
    """Live values n_trades closed trades after P_DOC (a small, plausible P/L move)."""
    base = dict(closed_trades=str(575 + n_trades), structstop_era_trades=str(78 + n_trades),
                outcomes="%dW/%dL/215BE/2TIME" % (110 + n_trades // 3, 248 + n_trades - n_trades // 3),
                decisive_wr_pct="30.9", structstop_era_outcomes="26W/38L/15BE/1TIME",
                engine_ledger_usd="%.2f" % (197.46 - 2.0 * n_trades),
                true_equity_usd="%.2f" % (180.49 - 2.0 * n_trades),
                net_pnl_usd_at_cost="%+.2f" % (-549.51 - 2.4 * n_trades), open_trade="none")
    base.update(kw)
    return base


# normal drift: the box trades and logs while the doc sleeps -> never STALE
check("P: identical snapshot is fresh", p_stale() == [])
check("P: a few new M1 bars are normal drift",
      p_stale(as_of_utc="2026-10-13 12:03", data_collection="227", log_bars="38958",
              log_last_bar_utc="2026-10-13 12:03") == [])
check("P: one closed trade + a new open trade is normal drift",
      p_stale(**p_after(1, open_trade="BUY #578 @ 4190.10")) == [])
check("P: an open-trade change alone is normal drift", p_stale(open_trade="none") == [])
check("P: 47 h of log is still fresh",
      p_stale(log_bars=str(38954 + 47 * 60), log_last_bar_utc="2026-10-15 10:59") == [])
check("P: 30 closed trades behind is still fresh (the documented tolerance, ~2 trading days)",
      p_stale(**p_after(30)) == [])

# genuinely behind or contradictory -> STALE
st31 = p_stale(**p_after(31))
check("P: 31 closed trades behind is STALE (count and outcomes both flagged)",
      "closed_trades" in st31 and "outcomes" in st31, f"stale={st31}")
check("P: 49 h of log is STALE",
      "log_last_bar_utc" in p_stale(log_bars=str(38954 + 49 * 60), log_last_bar_utc="2026-10-15 12:59"))
check("P: changed outcomes with an unchanged trade count are STALE (ledger edited?)",
      p_stale(outcomes="111W/247L/215BE/2TIME", decisive_wr_pct="31.0") == ["decisive_wr_pct", "outcomes"])
check("P: money moved with an unchanged trade count is STALE",
      p_stale(engine_ledger_usd="199.00") == ["engine_ledger_usd"])
check("P: money moved by more than N trades could explain is STALE",
      "engine_ledger_usd" in p_stale(**p_after(2, engine_ledger_usd="150.00")))
check("P: a snapshot NEWER than the log is STALE (lost data / stale checkout)",
      p_stale(log_last_bar_utc="2026-10-13 10:00") == ["log_last_bar_utc"])
check("P: a snapshot AHEAD of the ledger is STALE (lost trades)",
      "closed_trades" in p_stale(closed_trades="570", structstop_era_trades="73"))
check("P: a different cost assumption is STALE (config must match exactly)",
      p_stale(cost_usd_per_side="0.35") == ["cost_usd_per_side"])
check("P: a cutover that disagrees with strategy_lab.LIVE_CUTOVER is STALE",
      p_stale(cutover_utc="2026-10-05 21:00") == ["cutover_utc"])
check("P: a key missing from the doc is STALE",
      p_stale(doc={k: v for k, v in P_DOC.items() if k != "skip_rows"}) == ["skip_rows"])
check("P: tolerances stay tied to the documented 30 trades / 48 h",
      HC.TRADE_TOLERANCE == 30 and HC.MAX_AGE_HOURS == 48 and HC.BAR_TOLERANCE == HC.MAX_AGE_HOURS * 60,
      f"{HC.TRADE_TOLERANCE} trades, {HC.MAX_AGE_HOURS} h, {HC.BAR_TOLERANCE} rows")

# the doc must agree with itself: --cost commands vs the snapshot, and referenced files
tmp_p = tempfile.mkdtemp(prefix="gold_smoke_p_")
os.makedirs(os.path.join(tmp_p, "docs"))
with open(os.path.join(tmp_p, "docs", "REAL.md"), "w") as fh_p:
    fh_p.write("x")
doc_text = ("Run:\n```bash\npython3 tools/strategy_lab.py --cost 0.35\n```\nsee `docs/REAL.md`, `docs/MISSING.md`, "
            "`docs/REVIEW-YYYY-MM-DD.md` and `tools/*.py`\n")
probs = HC.doc_consistency(tmp_p, P_DOC, doc_text)
check("P: a --cost command that disagrees with the snapshot is flagged",
      any("--cost 0.35" in x for x in probs), str(probs))
check("P: a reference to a missing file is flagged; placeholders and globs are not",
      any("docs/MISSING.md" in x for x in probs) and not any("YYYY" in x or "*" in x or "REAL" in x for x in probs),
      str(probs))
shutil.rmtree(tmp_p, ignore_errors=True)

# end to end on a synthetic box: --update fills the block (and only the block), a doc that is
# ahead of the data is STALE, a doc with no block is exit 2 - and none of it needs the wall clock
root_p = _o_world([(2, 30, "OLD"), (3, 25, "NEW")])
with open(os.path.join(root_p, "status.json"), "w") as fh_p:
    json.dump({"equity": 480.12, "trade_active": False, "last_update": "2026-10-06 03:49:00"}, fh_p)
with open(os.path.join(root_p, "skipped_trades.csv"), "w", newline="") as fh_p:
    fh_p.write("Timestamp,Reason,Price,ATR\n2026-10-06 02:00:00,x,4100.00,2.00\n")
os.makedirs(os.path.join(root_p, "docs"), exist_ok=True)
doc_path = os.path.join(root_p, "docs", "HANDOFF.md")
PROSE_BEFORE, PROSE_AFTER = "# prose above stays byte-for-byte\n\n", "\n## 1. prose below too: 999 closed\n"
with open(doc_path, "w") as fh_p:
    fh_p.write(PROSE_BEFORE + "<!-- HANDOFF-SNAPSHOT x -->\n| key | value |\n|---|---|\n| as_of_utc | ? |\n"
               "<!-- /HANDOFF-SNAPSHOT -->\n" + PROSE_AFTER)


def p_main(*argv):
    buf_p = io.StringIO()
    with contextlib.redirect_stdout(buf_p):
        rc_p = HC.main([root_p, *argv])
    return rc_p, buf_p.getvalue()


rc_p, out_p = p_main("--update")
with open(doc_path) as fh_p:
    doc_after = fh_p.read()
check("P: --update fills the block and leaves every prose byte alone",
      rc_p == 0 and doc_after.startswith(PROSE_BEFORE) and doc_after.endswith(PROSE_AFTER)
      and "| closed_trades | 2 |" in doc_after and "| outcomes | 0W/2L/0BE/0TIME |" in doc_after
      and "| log_last_bar_utc | 2026-10-06 03:49 |" in doc_after, f"rc={rc_p}")
rc_p, out_p = p_main("--quiet")
check("P: a freshly updated doc is FRESH (exit 0, one line)",
      rc_p == 0 and out_p.strip().startswith("fresh") and len(out_p.strip().splitlines()) == 1, out_p.strip()[:80])
with open(doc_path, "w") as fh_p:
    fh_p.write(doc_after.replace("| closed_trades | 2 |", "| closed_trades | 40 |"))
rc_p, out_p = p_main("--quiet")
check("P: a doc claiming more trades than the ledger holds is STALE (exit 1)",
      rc_p == 1 and out_p.startswith("STALE"), out_p.strip()[:100])
with open(doc_path, "w") as fh_p:
    fh_p.write("# no snapshot block here\n")
rc_p, out_p = p_main("--quiet")
check("P: a doc with no snapshot block is exit 2, one line, no crash",
      rc_p == 2 and out_p.startswith("not run"), out_p.strip()[:100])
shutil.rmtree(root_p, ignore_errors=True)

# --- Scenario Q ------------------------------------------------------------
print("\nScenario Q: XM GOLD quote + contract-spec logger (tools/mt5_quotes.py, read-only sidecar)")
import ast  # noqa: E402
import collections  # noqa: E402
import contextlib  # noqa: E402,F811
import io  # noqa: E402,F811
import re  # noqa: E402
import mt5_quotes as MQ  # noqa: E402

Q_T0 = 1791892800  # 2026-10-13 12:00:00 UTC (a Tuesday, market open)
Q_DAY = "2026-10-13"
Q_SECRETS = ("123456789", "Jane Doe", "XMGlobal-MT5 17", "99999.5", "jane", "Common")


class QClock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class QMT5(types.ModuleType):
    """A fake terminal. Ticks carry the current SERVER time (UTC + offset). mode='stale' freezes the
    tick (a closed market: its time never moves). Any trading call is recorded - the logger must
    never make one."""
    ORDER_TYPE_BUY = 0

    def __init__(self, clock, offset=10800):
        super().__init__("MetaTrader5")
        self.clock, self.offset = clock, offset
        self.flip_utc = self.offset_after = None
        self.spread, self.bid, self.mode, self.frozen = 0.25, 4500.0, "ok", None
        self.glitch = False                      # next fresh tick carries a bogus +1 h skew, once
        self.stops_level = 30
        self.used, self.trading_calls, self.unknown = collections.Counter(), [], set()
        for name in MQ.FORBIDDEN_API:                       # recorded, never legitimately called
            setattr(self, name, (lambda n: lambda *a, **k: self.trading_calls.append(n))(name))

    def __getattr__(self, name):
        self.unknown.add(name)
        raise AttributeError(name)

    def _off_at(self, utc):
        return self.offset_after if (self.flip_utc is not None and utc >= self.flip_utc) else self.offset

    def symbol_info_tick(self, symbol):
        self.used["symbol_info_tick"] += 1
        T = collections.namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
        if self.mode == "none":
            return None
        if self.mode == "bad":
            return T(int(self.clock.t + self._off_at(self.clock.t)), 0.0, 0.0, 0, 0, 0, 0, 0)
        if self.mode == "crossed":
            return T(int(self.clock.t + self._off_at(self.clock.t) - 0.4), self.bid, self.bid - 0.5, 0, 0, 0, 0, 0)
        if self.mode == "stale":                           # a frozen tick: its time never moves
            if self.frozen is None:
                self.frozen = int(self.clock.t + self._off_at(self.clock.t) - 5)
            return T(self.frozen, self.bid, self.bid + self.spread, 0, 0, 0, 0, 0)
        self.frozen = None
        skew, self.glitch = (3600 if self.glitch else 0), False
        return T(int(self.clock.t + self._off_at(self.clock.t) - 0.4 + skew), self.bid, self.bid + self.spread,
                 0, 0, 0, 0, 0)

    def symbol_info(self, symbol):
        self.used["symbol_info"] += 1
        S = collections.namedtuple("S", "name description path digits point spread spread_float "
                                   "trade_calc_mode trade_mode trade_exemode filling_mode order_mode "
                                   "expiration_mode trade_stops_level trade_freeze_level "
                                   "trade_contract_size volume_min volume_max volume_step swap_mode "
                                   "swap_long swap_short swap_rollover3days session_deals bidhigh")
        return S("GOLD", "Gold vs US Dollar", "Metals\\GOLD", 2, 0.01, 25, True, 2, 4, 2, 3, 127,
                 15, self.stops_level, 0, 100.0, 0.01, 50.0, 0.01, 1, -25.0, 10.0, 3, 7, 4600.0)

    def account_info(self):
        self.used["account_info"] += 1
        A = collections.namedtuple("A", "login name server balance equity profit trade_mode leverage "
                                   "margin_mode currency trade_allowed company margin_free credit")
        return A(123456789, "Jane Doe", "XMGlobal-MT5 17", 99999.5, 99998.0, 1.5, 0, 500, 2, "USD", True,
                 "XM Global Limited", 99990.0, 0.0)

    def terminal_info(self):
        self.used["terminal_info"] += 1
        Tm = collections.namedtuple("Tm", "build connected trade_allowed maxbars company name path "
                                    "data_path commondata_path ping_last")
        return Tm(5000, True, True, 100000, "XM Global Limited", "MetaTrader 5", "C:\\Users\\jane\\MT5",
                  "C:\\Users\\jane\\MT5\\data", "C:\\Users\\jane\\Common", 77000)

    def order_calc_profit(self, action, symbol, volume, price_open, price_close):
        self.used["order_calc_profit"] += 1
        return round((price_close - price_open) * volume * 100.0, 2)          # contract = 100 oz

    def order_calc_margin(self, action, symbol, volume, price):
        self.used["order_calc_margin"] += 1
        return round(price * volume * 100.0 / 500.0, 2)

    def shutdown(self):
        self.used["shutdown"] += 1

    def initialize(self):
        self.used["initialize"] += 1
        return True

    def symbol_select(self, symbol, enable):
        self.used["symbol_select"] += 1
        return True


def q_new(tmp, clk, fm, **kw):
    logs = []
    return MQ.XmLogger(fm, "GOLD", tmp, log=logs.append, sleep=clk.sleep, **kw), logs


def q_run(lg, clk, seconds):
    """Poll on the logger's own 5 s grid for `seconds` of fake time."""
    end = clk.t + seconds
    t = lg.next_poll_time(clk.t)
    while t < end:
        clk.t = t
        lg.step(t)
        t = lg.next_poll_time(t)


def q_quotes(tmp, day=Q_DAY):
    with open(os.path.join(tmp, f"quotes-{day}.csv"), newline="") as f:
        return list(csv.DictReader(f))


def q_flush(lg, clk, tmp, k=None, day=Q_DAY):
    lg.flush_window(clk.t)
    rows = q_quotes(tmp, day)
    return rows if k is None else rows[-k:]


# Q1: read-only by construction (AST, so docstrings that NAME the forbidden calls are fine)
src_tree = ast.parse(open(os.path.join(HERE, "mt5_quotes.py")).read())
used_names = {n.attr for n in ast.walk(src_tree) if isinstance(n, ast.Attribute)} | \
             {n.id for n in ast.walk(src_tree) if isinstance(n, ast.Name)}
hit = sorted(set(MQ.FORBIDDEN_API) & used_names)
check("Q: the logger never references a trading API (order_send/positions/history/login...)",
      not hit, f"found {hit}")
check("Q: it imports without MetaTrader5 (pure functions usable on Linux)", hasattr(MQ, "XmLogger"))
check("Q: no engine import, so it can never touch the order path",
      not any(isinstance(n, (ast.Import, ast.ImportFrom)) and
              any(a.name.split(".")[0] in ("engine", "trade_filter") for a in getattr(n, "names", []))
              for n in ast.walk(src_tree)))
check("Q: no candle code was ported (gold's engine already consumes this broker's feed)",
      "copy_rates" not in used_names and not hasattr(MQ, "merge_candles"))

# Q2: server-offset estimator (MT5 'time' is broker server time, not UTC)
check("Q: a fresh tick on a +3 h server -> offset 10800",
      MQ.estimate_offset(Q_T0 + 10800 - 1, Q_T0) == 10800)
check("Q: a fresh tick on a +2 h server -> offset 7200",
      MQ.estimate_offset(Q_T0 + 7200 - 2, Q_T0) == 7200)
check("Q: a tick 20 min old is NOT used to learn the offset (rounding would be ambiguous)",
      MQ.estimate_offset(Q_T0 + 10800 - 1200, Q_T0) is None)
check("Q: an empty tick time gives no offset", MQ.estimate_offset(0, Q_T0) is None)
check("Q: tick age uses the offset (a 3 h-behind stale tick is 3 h old, not fresh)",
      abs(MQ.tick_age_s(Q_T0 + 10800 - 10800, 10800, Q_T0) - 10800) < 1e-6)

# Q3: a session of polls -> aligned rows, point sample + envelope, no duplicates
tmp = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 7)                       # start mid-window on purpose
    fm = QMT5(clk)
    lg, logs = q_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    check("Q: the server offset is learned from live ticks at start-up", lg.offset == 10800, f"{lg.offset}")
    n_poll = [0]
    real_step = lg.step

    def scripted(now):                           # spreads 0.25 .. 0.30 cycling every poll
        fm.spread = 0.25 + 0.01 * (n_poll[0] % 6)
        n_poll[0] += 1
        return real_step(now)

    lg.step = scripted
    q_run(lg, clk, 190)
    lg.flush_window(clk.t)
    rows = q_quotes(tmp)
    stamps = [r["ts_utc"] for r in rows]
    check("Q: the window grid - a poll at the boundary still belongs to the OLD window, ~1 s later to the new one",
          lg.grid(Q_T0 + 30.0) == Q_T0 and lg.grid(Q_T0 + 31.0) == Q_T0 + 30 and lg.grid(Q_T0 + 59.0) == Q_T0 + 30
          and lg.next_poll_time(Q_T0 + 31.0) == Q_T0 + 36.0)
    check("Q: quote rows land on the 30 s grid (UTC)", all(x[-2:] in ("00", "30") for x in stamps), f"{stamps[:3]}")
    check("Q: no duplicate or out-of-order quote stamps", stamps == sorted(set(stamps)), f"{len(stamps)} rows")
    full = [r for r in rows if r["n_ok"] == "6"]
    check("Q: a full window holds 6 polls (30 s / 5 s)", len(full) >= 4, f"{[r['n_ok'] for r in rows]}")
    check("Q: the point sample is the FIRST valid poll; spread = ask - bid",
          all(abs(float(r["ask"]) - float(r["bid"]) - float(r["spread"])) < 0.005 for r in rows))
    check("Q: spread_min/max bracket the point sample",
          all(float(r["spread_min"]) <= float(r["spread"]) <= float(r["spread_max"]) for r in rows))
    check("Q: the envelope catches spikes between row stamps",
          any(float(r["spread_max"]) > float(r["spread"]) for r in rows))
    check("Q: the half-window start is flagged LATE (the sample was not at the boundary)",
          rows[0]["flags"] == "LATE" and all(r["flags"] == "" for r in rows[1:]), f"{[r['flags'] for r in rows]}")
    check("Q: the row carries the server offset and a small tick age",
          all(r["srv_offset_s"] == "10800" and 0 <= float(r["tick_age_s"]) < 5 for r in rows))
    check("Q: prices are written with the symbol's 2 digits",
          all(len(r["bid"].split(".")[1]) == 2 and len(r["spread"].split(".")[1]) == 2 for r in rows),
          f"{rows[0]['bid']} {rows[0]['spread']}")

    # Q4: restart on the same files -> no duplicates; 25 min downtime -> an honest, visible gap
    stamps_before = len(q_quotes(tmp))
    lg2, logs2 = q_new(tmp, clk, fm)
    lg2.start(clk(), clock=clk)
    check("Q: a restart resumes after the last quote row", lg2.last_stamp is not None)
    q_run(lg2, clk, 70)
    lg2.flush_window(clk.t)
    st2 = [r["ts_utc"] for r in q_quotes(tmp)]
    check("Q: a restart never duplicates a quote row", st2 == sorted(set(st2)) and len(st2) > stamps_before)
    clk.t += 25 * 60                               # the sidecar was down for 25 minutes
    lg3, logs3 = q_new(tmp, clk, fm)
    lg3.start(clk(), clock=clk)
    q_run(lg3, clk, 40)
    lg3.flush_window(clk.t)
    st3 = [MQ.parse_utc(r["ts_utc"]) for r in q_quotes(tmp)]
    check("Q: a downtime is an honest gap in the data (no invented rows), still ascending and unique",
          st3 == sorted(set(st3)) and max(b - a for a, b in zip(st3, st3[1:])) >= 25 * 60)

    # Q5: bad / stale / crossed quotes are recorded explicitly, never silently skipped
    fm.mode = "none"
    q_run(lg3, clk, 65)
    r_none = q_flush(lg3, clk, tmp, 2)
    fm.mode = "bad"
    q_run(lg3, clk, 65)
    r_bad = q_flush(lg3, clk, tmp, 2)
    fm.mode = "crossed"
    q_run(lg3, clk, 65)
    r_crossed = q_flush(lg3, clk, tmp, 2)
    check("Q: no tick -> NOQUOTE rows (outages are explicit)",
          all(r["flags"] == "NOQUOTE" and r["bid"] == "" and r["n_ok"] == "0" for r in r_none), f"{r_none}")
    check("Q: zero-price ticks -> BADQUOTE rows", all(r["flags"] == "BADQUOTE" for r in r_bad), f"{r_bad}")
    check("Q: crossed quotes (ask < bid) are never logged as a negative spread",
          all(r["flags"] == "BADQUOTE" and r["spread"] == "" for r in r_crossed), f"{r_crossed}")

    # the CLOSED MARKET (weekend / daily break): the terminal keeps answering with a frozen tick
    fm.mode = "stale"
    off_before = lg3.offset
    n_changes_before = sum(1 for m in logs3 if "offset changed" in m)
    code_frozen = None
    try:
        q_run(lg3, clk, 7500)   # 2 h 5 min: the frozen tick passes through 'exactly 1 h' and '2 h old'
    except SystemExit as e:
        code_frozen = e.code
    check("Q: two hours of frozen ticks never trip the dead-logger watchdog (a closed market is not a dead logger)",
          code_frozen is None, f"exit {code_frozen}")
    r_stale = q_flush(lg3, clk, tmp, 3)
    check("Q: a closed market (frozen tick) is written as STALE rows - not NOQUOTE, the logger is alive",
          all("STALE" in r["flags"] and "NOQUOTE" not in r["flags"] and r["bid"] != "" for r in r_stale),
          f"{r_stale}")
    check("Q: a feed frozen for hours does NOT move the learned server offset (a tick exactly N hours "
          "old looks like a fresh tick on a server N hours behind) and the rows keep carrying it",
          lg3.offset == off_before == 10800
          and sum(1 for m in logs3 if "offset changed" in m) == n_changes_before
          and all(r["srv_offset_s"] == "10800" for r in r_stale), f"{lg3.offset}")
    fm.mode = "ok"
    q_run(lg3, clk, 70)
    r_back = q_flush(lg3, clk, tmp, 2)
    check("Q: when the market reopens the rows are usable again with the same offset",
          all(r["flags"] == "" and r["srv_offset_s"] == "10800" for r in r_back), f"{r_back}")

    # one glitchy fresh tick (an hour off) must not flip the learned offset: a CHANGE needs 2 agreeing ticks
    fm.glitch = True
    q_run(lg3, clk, 40)
    check("Q: a single glitchy tick (an hour off) does not flip the learned offset (a change needs 2 agreeing ticks)",
          lg3.offset == 10800 and sum(1 for m in logs3 if "offset changed" in m) == n_changes_before,
          f"{lg3.offset}")
    fm.glitch = True
    q_run(lg3, clk, 40)                      # a second glitch, separated from the first by good ticks
    check("Q: two glitches separated by good ticks do not add up to a change (consecutive agreement only)",
          lg3.offset == 10800 and sum(1 for m in logs3 if "offset changed" in m) == n_changes_before,
          f"{lg3.offset}")

    # Q6: server DST fall-back (+3 h -> +2 h) while the market is OPEN
    fm.flip_utc, fm.offset_after = int(clk.t) + 200, 7200
    q_run(lg3, clk, 1500)
    lg3.flush_window(clk.t)
    check("Q: the logger notices the server offset change (needs 2 consistent fresh ticks)",
          lg3.offset == 7200 and any("offset changed" in m for m in logs3), f"offset {lg3.offset}")
    offs = [r["srv_offset_s"] for r in q_quotes(tmp)]
    check("Q: the quote rows switch offset with it (the empirical DST record the converter needs)",
          {"10800", "7200"} <= set(offs) and offs.index("7200") > offs.index("10800"), f"{collections.Counter(offs)}")

    # Q7: contract-spec snapshot - allow-listed, decoded, change-logged, nothing identifying
    spec = json.load(open(os.path.join(tmp, "symbol_spec.json")))
    dec = spec["decoded"]
    check("Q: spec decodes account kind, execution mode and filling flags",
          dec["account_kind"] == "DEMO" and dec["execution_mode"] == "MARKET"
          and dec["filling_allowed_flags"] == ["FOK", "IOC"] and dec["margin_mode"] == "RETAIL_HEDGING", f"{dec}")
    check("Q: spec records stops level, volume step, swap and contract size (100 oz)",
          spec["symbol_info"]["trade_stops_level"] == 30 and spec["symbol_info"]["volume_step"] == 0.01
          and spec["symbol_info"]["swap_long"] == -25.0 and spec["symbol_info"]["trade_contract_size"] == 100.0)
    check("Q: the order_calc probe confirms 0.01 lot x $1 = $1.00 (the engine's P/L unit equals the broker's)",
          spec["probes"]["calc_profit_usd_0.01lot_plus_1usd"] == 1.0, f"{spec['probes']}")
    blob = "".join(open(os.path.join(tmp, f), encoding="utf-8", errors="replace").read()
                   for f in sorted(os.listdir(tmp)))
    leaked = [x for x in Q_SECRETS if x in blob]
    check("Q: PRIVACY - no login, name, server, balance or Windows path in any output file (the repo is public)",
          not leaked, f"leaked {leaked}")
    check("Q: PRIVACY - the allow-lists contain no identifying field",
          not ({"login", "name", "server", "balance", "equity", "profit", "margin_free"} & set(MQ.ACCOUNT_FIELDS))
          and not ({"path", "data_path", "commondata_path"} & set(MQ.TERMINAL_FIELDS)))
    hist = open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()
    h0 = json.loads(hist[0])["hash"]
    lg3.snapshot_spec(clk.t + 7 * 3600)
    check("Q: an unchanged spec is NOT re-appended to the history",
          len(open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()) == len(hist))
    fm.stops_level = 250                          # the broker widens the stops level
    lg3.snapshot_spec(clk.t + 14 * 3600)
    hist2 = open(os.path.join(tmp, "symbol_spec_history.jsonl")).read().splitlines()
    check("Q: a CHANGED spec (stops level) is appended and logged",
          len(hist2) == len(hist) + 1 and json.loads(hist2[-1])["hash"] != h0
          and json.loads(hist2[-1])["symbol_info"]["trade_stops_level"] == 250
          and any("CHANGED" in m for m in logs3))

    # Q8: what the fake terminal saw - read-only, and only the documented calls
    allowed = {"symbol_info_tick", "symbol_info", "account_info", "terminal_info", "order_calc_profit",
               "order_calc_margin", "shutdown", "initialize", "symbol_select"}
    check("Q: read-only - not one trading call reached the terminal", fm.trading_calls == [],
          f"{fm.trading_calls}")
    check("Q: only the documented read calls were used", set(fm.used) <= allowed and not fm.unknown,
          f"used {sorted(fm.used)} unknown {sorted(fm.unknown)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Q6b: a DST change that happens while the market is SHUT (it always does: Sunday 01:00 UTC)
tmp = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 1)
    fm = QMT5(clk)
    lg, logs = q_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    q_run(lg, clk, 90)
    fm.mode = "stale"                               # the weekend close ...
    fm.flip_utc, fm.offset_after = int(clk.t) + 600, 7200    # ... and the server clock falls back during it
    q_run(lg, clk, 3 * 3600)
    r_shut = q_flush(lg, clk, tmp, 3)
    check("Q: while the market is shut the old offset is carried and every row is STALE",
          lg.offset == 10800 and all("STALE" in r["flags"] and r["srv_offset_s"] == "10800" for r in r_shut),
          f"{lg.offset} {[r['flags'] for r in r_shut]}")
    fm.mode = "ok"                                  # ... the Sunday-evening reopen
    q_run(lg, clk, 120)
    r_open = q_flush(lg, clk, tmp, 2)
    check("Q: the new offset is learned from the first two fresh ticks after the reopen",
          lg.offset == 7200 and any("offset changed" in m for m in logs)
          and all(r["srv_offset_s"] == "7200" and r["flags"] == "" for r in r_open), f"{lg.offset} {r_open}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Q9: file hygiene - schema drift, torn line, CRLF, midnight rotation
tmp = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 1)
    fm = QMT5(clk)
    lg, logs = q_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    q_run(lg, clk, 100)
    lg.flush_window(clk.t)
    qpath = os.path.join(tmp, f"quotes-{Q_DAY}.csv")
    txt = open(qpath, newline="").read()
    open(qpath, "w", newline="").write(txt.replace("n_ok,n_bad", "n_ok,n_bad,extra", 1))
    lg2, logs2 = q_new(tmp, clk, fm)
    lg2.start(clk(), clock=clk)
    q_run(lg2, clk, 70)
    lg2.flush_window(clk.t)
    aside = [f for f in os.listdir(tmp) if f.startswith(f"quotes-{Q_DAY}.csv.old-")]
    check("Q: a drifted header moves the file ASIDE instead of appending misaligned rows",
          len(aside) == 1 and open(qpath).readline().strip().split(",") == MQ.QUOTE_FIELDS
          and any("schema drift" in m for m in logs2), f"{aside}")
    TORN = "2026-10-13 12:05:00,4500.00,450"
    with open(qpath, "ab") as f:
        f.write(TORN.encode())                              # killed mid-write: no newline
    lg3, logs3 = q_new(tmp, clk, fm)
    lg3.start(clk(), clock=clk)
    q_run(lg3, clk, 70)
    lg3.flush_window(clk.t)
    lines = open(qpath).read().splitlines()
    bad = [ln for ln in lines[1:] if len(ln.split(",")) != len(MQ.QUOTE_FIELDS)]
    check("Q: a torn last line stays isolated (byte-identical, not glued to the next row) and the next row is intact",
          bad == [TORN] and len(lines[-1].split(",")) == len(MQ.QUOTE_FIELDS)
          and len(lines) > lines.index(TORN) + 1, f"bad {bad}")
    check("Q: no carriage return in any file (the Wine Python would write CRLF in text mode)",
          not any(b"\r" in open(os.path.join(tmp, f), "rb").read() for f in os.listdir(tmp)))
    clk.t = float(Q_T0 + 12 * 3600 - 40)                   # 40 s before 2026-10-14 00:00 UTC
    lg4, logs4 = q_new(tmp, clk, fm)
    lg4.start(clk(), clock=clk)
    q_run(lg4, clk, 100)
    lg4.flush_window(clk.t)
    days = sorted(f for f in os.listdir(tmp) if f.startswith("quotes-") and f.endswith(".csv"))
    d2 = q_quotes(tmp, "2026-10-14")
    check("Q: quote files rotate at UTC midnight", days == ["quotes-2026-10-13.csv", "quotes-2026-10-14.csv"]
          and d2 and d2[0]["ts_utc"] == "2026-10-14 00:00:00", f"{days} {d2[:1]}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Q10/Q11: watchdog and the real loop (injected clock + sleep, no real waiting)
tmp = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 1)
    fm = QMT5(clk)
    lg, logs = q_new(tmp, clk, fm)
    lg.start(clk(), clock=clk)
    q_run(lg, clk, 30)
    fm.mode = "none"
    code = None
    try:
        q_run(lg, clk, 1200)
    except SystemExit as e:
        code = e.code
    check("Q: 15 minutes without a quote exits 2 so systemd restarts a clean process", code == 2, f"{code}")
    check("Q: before exiting it re-initialises the MT5 link (once a minute)",
          fm.used["shutdown"] >= 5 and fm.used["initialize"] >= 5, f"{fm.used['shutdown']}")
    check("Q: the outage is in the data as NOQUOTE rows",
          sum(1 for r in q_quotes(tmp) if r["flags"] == "NOQUOTE") >= 20)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 2.3)
    fm = QMT5(clk)
    fm.mode = "stale"                       # a closed market must NOT trip the watchdog: ticks still answer
    seen = []
    lg, logs = q_new(tmp, clk, fm)
    real = lg.step

    def spy(now):
        seen.append(round(now, 3))
        if len(seen) >= 14:
            raise KeyboardInterrupt
        return real(now)

    lg.step = spy
    lg.run_forever(clock=clk)
    gaps = {round(b - a, 3) for a, b in zip(seen, seen[1:])}
    check("Q: run_forever polls on a steady 5 s grid and ends cleanly on interrupt",
          len(seen) == 14 and gaps == {5.0}, f"{gaps}")
    check("Q: the partial window is flushed on shutdown", len(q_quotes(tmp)) >= 2)
    lg.step = real                           # drop the spy: the next check polls for real
    code = None
    try:
        q_run(lg, clk, 3 * 3600)             # three hours of closed market through the watchdog
    except SystemExit as e:
        code = e.code
    check("Q: a closed market (frozen but answering ticks) never trips the dead-logger watchdog", code is None,
          f"exit {code}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# Q14: the CLI modes the on-box checklist tells the operator to run (docs/XM-LOGGER.md)
def q_cli(argv, env=None):
    clk = QClock(Q_T0 + 1)
    fm = QMT5(clk)
    old = dict(os.environ)
    os.environ.update(env or {})
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = MQ.main(argv, mt5mod=fm, clock=clk, sleep=clk.sleep)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return rc, buf.getvalue(), fm


tmp = tempfile.mkdtemp()
try:
    rc, out, fm = q_cli(["--spec", "--dir", tmp])
    try:
        parsed = json.loads(out)
    except ValueError:
        parsed = None
    check("Q: --spec prints PURE JSON (nothing before or after it) and writes no file",
          rc == 0 and parsed is not None and os.listdir(tmp) == [], f"rc {rc} files {os.listdir(tmp)}")
    check("Q: --spec output carries no login/name/server/balance/path",
          not [x for x in Q_SECRETS if x in out] and parsed["decoded"]["account_kind"] == "DEMO",
          f"{[x for x in Q_SECRETS if x in out]}")
    rc, out, fm = q_cli(["--once", "--dir", tmp], {"MT5_QUOTES_LABEL": "XM Standard demo"})
    names = sorted(os.listdir(tmp))
    i_spec, i_off = out.find("contract spec recorded"), out.find("server offset +3h")
    check("Q: --once learns the offset, records the spec and writes a quote row, in that order",
          rc == 0 and 0 <= i_spec < i_off and "quote row" in out
          and names == [f"quotes-{Q_DAY}.csv", "symbol_spec.json", "symbol_spec_history.jsonl"],
          f"rc {rc} {names}\n{out[:300]}")
    check("Q: --once is read-only too, and the operator's label is published (MT5 does not expose the tier)",
          fm.trading_calls == [] and not fm.unknown
          and json.load(open(os.path.join(tmp, "symbol_spec.json")))["label"] == "XM Standard demo")
    if MQ.mt5 is None:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                MQ.main(["--spec"])
            code = None
        except SystemExit as e:
            code = e.code
        check("Q: without MetaTrader5 the CLI refuses with a clear message and exit 1 (Linux python)",
              code == 1 and "install it in the WINE python" in buf.getvalue(), f"{code}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Q12: the deploy wiring that gets the logger's data to main (static: autosync is bash with side
# effects, so it is exercised by the sandbox harness in docs/XM-LOGGER.md, but these lines must never regress)
auto = open(os.path.join(HERE, "autosync.sh")).read()
data_line = next((ln for ln in auto.splitlines() if ln.startswith("DATA_FILES=")), "")
check("Q: autosync commits xm_data/ with the other live data (else the logger's output never reaches main)",
      "xm_data" in data_line, data_line)
check("Q: an autosync merge conflict in xm_data/ resolves server-wins like the other data files",
      "|xm_data/*)" in auto and "git checkout --ours" in auto.split("|xm_data/*)")[1][:80])
check("Q: autosync actually RUNS the report and puts its line in the digest (advisory)",
      re.search(r"python3 tools/xm_quote_report\.py --quiet\s*>", auto) is not None and "\U0001F4E1 $XM_MSG" in auto)
alert_block = auto.split('"xm logger: STALE"*)')[1].split(";;")[0] if '"xm logger: STALE"*)' in auto else "$"
check("Q: the STALE alert names the unit and carries no changing numbers",
      "$XM_MSG" not in alert_block and "mt5quotes-gold" in alert_block, alert_block.strip()[:90])
before_4d, after_4d = auto.split("phase 4d")[0], auto.split("phase 4d")[1].split('log "done.')[0]
check("Q: the logger phase runs AFTER the deploy decision and never assigns a deploy variable (advisory only)",
      "XM_MSG" not in before_4d and not any(v in after_4d for v in ("SMOKE=", "DEPLOY_MSG=", "git reset", "MERGE_RC=")))
unit_txt = open(os.path.join(ROOT, "deploy", "mt5quotes.service")).read()
check("Q: the unit file installs as mt5quotes-gold (never BTC's mt5quotes-btc) and never carries a login or password",
      "mt5quotes-gold" in unit_txt and "mt5quotes-btc" not in unit_txt
      and "MT5_QUOTES_DIR=Z:/opt/gold/xm_data" in unit_txt
      and not any(w in unit_txt.lower().replace("never put a login", "").replace("or password", "")
                  for w in ("password=", "login=", "mt5_login", "mt5_password")))
check("Q: the logger's default data dir is the one autosync commits (xm_data under /opt/gold)",
      MQ.DEFAULT_DIR == "Z:/opt/gold/xm_data")
check("Q: an incompatible interval/poll falls back to 30/5 instead of mis-aligning rows",
      (lambda lg: (lg.interval, lg.poll))(MQ.XmLogger(QMT5(QClock(Q_T0)), "GOLD", "/nonexistent-never-written",
                                                    interval=30, poll=7, log=lambda m: None)) == (30, 5))

# --- Scenario R ------------------------------------------------------------
print("\nScenario R: xm_quote_report + broker_time (measured cost vs the assumed $0.40, "
      "closed market vs stall, DST evidence)")
import re  # noqa: E402
import xm_quote_report as XR  # noqa: E402
import broker_time as BT  # noqa: E402

R_START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)      # a Monday
R_END = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)        # 16 whole days
R_STEP = 300                                  # this fixture's logger interval (the report reads it from the data)
R_FIELDS = MQ.QUOTE_FIELDS


def r_closed(dt):
    """Synthetic schedule: daily break 21:55-23:05 UTC, weekend Fri 21:55 -> Sun 23:05."""
    m, wd = dt.hour * 60 + dt.minute, dt.weekday()
    if 21 * 60 + 55 <= m < 23 * 60 + 5:
        return True
    return (wd == 4 and m >= 21 * 60 + 55) or wd == 5 or (wd == 6 and m < 23 * 60 + 5)


def r_spread(dt):
    m, h = dt.hour * 60 + dt.minute, dt.hour
    if 21 * 60 + 45 <= m <= 22 * 60 + 30:
        return 0.60                                     # the engine's rollover blackout
    if h >= 23 or h < 7:
        return 0.30                                     # ASIA
    return 0.20 if h < 12 else 0.22                     # LONDON / NY


def r_stall(dt):                                        # market open but the tick is frozen: Wed 10:00-10:40
    return dt.date().isoformat() == "2026-10-14" and 10 * 60 <= dt.hour * 60 + dt.minute < 10 * 60 + 40


def r_outage(dt):                                       # the LOGGER is down: Thu 14:00-14:30 (no rows)
    return dt.date().isoformat() == "2026-10-15" and 14 * 60 <= dt.hour * 60 + dt.minute < 14 * 60 + 30


def r_write_quotes(qdir, start=R_START, end=R_END, offset=10800):
    os.makedirs(qdir, exist_ok=True)
    by_day = {}
    t = start
    while t < end:
        if not r_outage(t):
            sp = r_spread(t)
            frozen = r_closed(t) or r_stall(t)
            row = {"ts_utc": t.strftime("%Y-%m-%d %H:%M:%S"), "bid": "4500.00", "ask": "%.2f" % (4500 + sp),
                   "spread": "%.2f" % sp, "spread_min": "%.2f" % sp, "spread_max": "%.2f" % (sp + 0.05),
                   "n_ok": 6, "n_bad": 0, "tick_age_s": "900.0" if frozen else "0.6",
                   "srv_offset_s": offset, "flags": "STALE" if frozen else ""}
            by_day.setdefault(t.strftime("%Y-%m-%d"), []).append(row)
        t += timedelta(seconds=R_STEP)
    for day, rows in by_day.items():
        with open(os.path.join(qdir, f"quotes-{day}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=R_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


LEDGER_HEAD = ["Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
               "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry", "ATR_At_Entry",
               "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry"]


def r_write_ledger(root, spec_rows):
    """spec_rows: (entry, exit, pnl). Entry 4500.00, stop 4497.00, TP 4504.50 -> 1R = $3.00 for every trade."""
    with open(os.path.join(root, "trades.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(LEDGER_HEAD)
        for i, (et, xt, pnl) in enumerate(spec_rows, 1):
            w.writerow([i, "BUY", et, xt, "4500.00", "4497.00", "4504.50", "%.2f" % (4500 + pnl),
                        "TP" if pnl > 0 else "SL", "%.2f" % pnl, "500.00", "50.0", "1.50", "50.0%", "4499.00", "4490.00"])


def r_main(root, *argv, now=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = XR.main(["--root", root, *argv] + (["--now", str(now)] if now is not None else []))
    return rc, buf.getvalue()


R_LAST_ROW = R_END.timestamp() - R_STEP
R_NOW = R_LAST_ROW + 600                      # 10 min after the newest row
NY_PNL = [3.0, -2.0, 3.0, -2.0, 0.0, 3.0, -2.0, -2.0, 3.0, 0.0, -2.0, 3.0]        # sum +5.00
trade_rows = [("2026-10-04 12:00:02", "2026-10-04 12:05:01", 3.0)]                 # before the logger: no quote
for day in ("2026-10-07", "2026-10-08", "2026-10-09"):                             # 12 NY trades (spread 0.22)
    for hh in (13, 14, 15, 16):
        trade_rows.append((f"{day} {hh}:00:02", f"{day} {hh}:05:01", NY_PNL[len(trade_rows) - 1]))
for day in ("2026-10-12", "2026-10-13", "2026-10-14"):                             # 3 trades that ENTER at 0.22 and
    trade_rows.append((f"{day} 21:40:01", f"{day} 21:50:01", -2.0))                # EXIT in the 0.60 rollover spike
trade_rows.append(("2026-10-14 10:10:01", "2026-10-14 10:20:01", 3.0))             # inside the feed stall: stale quotes
trade_rows.append(("2026-10-15 13:55:01", "2026-10-15 14:10:01", -2.0))            # exit inside the logger outage

root_r = tempfile.mkdtemp()
try:
    r_write_quotes(os.path.join(root_r, "xm_data"))
    r_write_ledger(root_r, trade_rows)
    clk_r = QClock(Q_T0)
    spec_r = MQ.build_spec(QMT5(clk_r), "GOLD", "XM Standard demo", Q_T0)
    with open(os.path.join(root_r, "xm_data", "symbol_spec.json"), "w") as fh_r:
        json.dump(spec_r, fh_r)
    with open(os.path.join(root_r, "xm_data", "symbol_spec_history.jsonl"), "w") as fh_r:
        fh_r.write(json.dumps(spec_r) + "\n")

    rc, out = r_main(root_r, now=R_NOW)
    check("R: the full report runs and has all five sections",
          rc == 0 and all(h in out for h in ("== 1. LOGGER", "== 2. SPREAD", "== 3. COST", "== 4. SERVER TIME",
                                            "== 5. SPEC")), out[:200])
    check("R: 16 complete days and 2 complete weekends meet the sample target (a closed day still has its rows)",
          "complete UTC days (>= 80% of rows): 16 / 14" in out and "complete weekends (Sat+Sun): 2 / 2" in out
          and "sample target: MET" in out)
    check("R: a logger outage is reported as an outage with its length (35 min between rows)",
          "1 gaps > 5 min" in out and "longest gaps: 2026-10-15 13:55:00 UTC for 35 min" in out,
          out[out.find("rows "):][:300])
    check("R: scheduled closures (4 daily breaks + 1 weekend per week) are NOT outages: 12 scheduled runs",
          "12 scheduled runs (daily break / weekend)" in out, [ln for ln in out.splitlines() if "scheduled runs" in ln])
    check("R: a frozen feed while the market should be open IS reported as a stall, with its time and length",
          "FEED STALLS while the market should be open" in out and "2026-10-14 10:00:00 UTC (Wed) 40 min" in out
          and "1, 0.7 h in total" in out, [ln for ln in out.splitlines() if "STALL" in ln])
    check("R: the newest row is fresh and the market is shown as open",
          "newest row 10 min ago (market OPEN - fresh tick)" in out)

    def row_of(label):
        return next((ln for ln in out.splitlines() if ln.strip().startswith(label)), "")

    check("R: spread by session reproduces the synthetic schedule (LONDON 0.20, NY 0.22, ASIA 0.30)",
          re.search(r"LONDON 07-12\s+\d+\s+\$\s+0\.20", row_of("LONDON 07-12"))
          and re.search(r"NY 12-21\s+\d+\s+\$\s+0\.22", row_of("NY 12-21"))
          and re.search(r"ASIA 23-07\s+\d+\s+\$\s+0\.30", row_of("ASIA 23-07")),
          [row_of("LONDON 07-12"), row_of("NY 12-21"), row_of("ASIA 23-07")])
    check("R: the engine's own blackout windows are tabulated, and the rollover window shows its spread spike",
          re.search(r"21:45-22:30 Daily Market R\s+\d+\s+\$\s+0\.60", out) is not None
          and re.search(r"13:25-15:15 NY Open & US H\s+\d+\s+\$\s+0\.22", out) is not None
          and "outside every blackout" in out)
    check("R: the weekly re-open (Sunday evening -> Monday 01:00) has its own row",
          "WEEKLY OPEN (Sun-Mon 01h)" in out)
    usable_n = rows_n = 0
    t_r = R_START
    while t_r < R_END:
        if not r_outage(t_r):
            rows_n += 1
            usable_n += not (r_closed(t_r) or r_stall(t_r))
        t_r += timedelta(seconds=R_STEP)
    check("R: exactly the usable rows enter the spread tables (%d of %d rows; closed-market and stalled rows are "
          "excluded)" % (usable_n, rows_n),
          f"usable {usable_n} of {rows_n} rows" in out, out.split("== 2. SPREAD")[1].split("\n")[0])
    check("R: the assumed $0.40 is compared with 1R ($3.00 here) and with the measured median",
          "the assumed $0.40 is 13.3% of 1R" in out and re.search(r"median spread = \d+\.\d% of 1R", out) is not None,
          [ln for ln in out.splitlines() if "of 1R" in ln])
    check("R: cost section joins the ledger to the quotes: 15 trades have a usable quote at entry and exit "
          "(not the pre-logger, stalled or outage ones)",
          "15 trades with a usable quote at entry and exit" in out, [ln for ln in out.splitlines() if "usable quote at entry" in ln])
    check("R: measured round trip = the MEAN of the entry and exit spread (3 trades: (0.22+0.60)/2 = 0.41) "
          "-> mean 0.26, median 0.22, vs the assumed 0.40",
          "measured round trip: mean $0.26  median $0.22" in out and "(assumed $0.40)" in out,
          [ln for ln in out.splitlines() if "measured round trip" in ln])
    check("R: same trades: gross -1.00 | net at 0.40 flat -7.00 | net at the MEASURED cost -4.87",
          "gross -1.00 | net at $0.40 flat -7.00 | net at the MEASURED cost -4.87" in out,
          [ln for ln in out.splitlines() if "same trades" in ln])
    check("R: it tells the operator the exact flags that re-cost the ledger at the measured median",
          "win_rate_report.py --spread 0.22" in out and "strategy_lab.py --cost 0.11" in out)
    check("R: the sample is flagged as a plumbing check below n=30", "far too small to conclude anything" in out)
    check("R: one offset in the data -> the DST rule is reported UNVERIFIED with both next-change dates",
          "verdict [UNVERIFIED]" in out and "2026-10-25 01:00" in out and "2026-11-01 06:00" in out, out[out.find("verdict"):][:200])
    check("R: spec section: 0.01 lot x $1 = $1.00 and 100 oz contract are confirmed, DEMO account noted",
          "0.01 lot x $1 move = $1.00 (order_calc_profit) OK" in out and "contract size 100 oz (0.01 lot = 1 oz) OK" in out
          and "DEMO" in out and "XM Standard demo" in out)

    # --quiet: the autosync digest line
    rc, q_ok = r_main(root_r, "--quiet", now=R_NOW)
    check("R: --quiet is ONE line starting 'xm logger: OK'",
          rc == 0 and q_ok.startswith("xm logger: OK |") and len(q_ok.strip().splitlines()) == 1
          and "16/14 complete days, 2/2 weekends" in q_ok and "spread median $0.22" in q_ok, q_ok.strip())
    rc, q_stale = r_main(root_r, "--quiet", now=R_LAST_ROW + 3 * 3600)
    check("R: a logger whose newest row is hours old reads STALE (so autosync raises its warning)",
          q_stale.startswith("xm logger: STALE (newest row 3.0 h old - is mt5quotes-gold running?)"), q_stale.strip())
    rc, q_none = r_main(tempfile.mkdtemp(), "--quiet", now=R_NOW)
    check("R: no data yet -> 'not collecting yet' (never an error, never STALE)",
          q_none.startswith("xm logger: not collecting yet") and rc == 0, q_none.strip())
    rc, q_dir = r_main(root_r, "--quiet", "--dir", "no_such_dir", now=R_NOW)
    check("R: --quiet never fails, even on a missing directory", rc == 0 and q_dir.startswith("xm logger:"), q_dir.strip())

    # --days: only the newest N UTC days
    rc, out2 = r_main(root_r, "--days", "2", now=R_NOW)
    nrows = int(re.search(r"(\d+) quote files, (\d+) rows", out2).group(2))
    check("R: --days 2 reads only the newest two days (about 2 x 288 rows)", rc == 0 and 570 <= nrows <= 580, f"{nrows}")

    # a torn line and a foreign header are skipped and counted, never fatal
    qd = os.path.join(root_r, "xm_data")
    with open(os.path.join(qd, "quotes-2026-10-20.csv"), "ab") as fh_r:
        fh_r.write(b"2026-10-20 23:59:00,4500.0")
    with open(os.path.join(qd, "quotes-2026-10-19.csv"), "w") as fh_r:
        fh_r.write("some,other,header\n1,2,3\n")
    rc, out3 = r_main(root_r, now=R_NOW)
    check("R: malformed lines and files are skipped and counted, the report still runs",
          rc == 0 and "malformed lines skipped" in out3, out3.splitlines()[0])
finally:
    shutil.rmtree(root_r, ignore_errors=True)

# R2: the market is CLOSED right now -> --quiet says so, and still reads OK (the logger is alive)
root_r = tempfile.mkdtemp()
try:
    r_write_quotes(os.path.join(root_r, "xm_data"), end=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc))   # Sat noon
    rc, q_closed = r_main(root_r, "--quiet", now=datetime(2026, 10, 10, 12, 4, tzinfo=timezone.utc).timestamp())
    check("R: on a Saturday the report reads OK with 'market closed or feed frozen' (a closed market is not a dead logger)",
          q_closed.startswith("xm logger: OK") and "market closed or feed frozen" in q_closed, q_closed.strip())
    rc, out4 = r_main(root_r, now=datetime(2026, 10, 10, 12, 4, tzinfo=timezone.utc).timestamp())
    check("R: ... and the full report shows 'market CLOSED or feed frozen' and no stall",
          "market CLOSED or feed frozen" in out4 and "FEED STALLS" not in out4
          and "feed stalls outside the scheduled closures: none" in out4, out4[out4.find("newest row"):][:160])
    rc, out5 = r_main(root_r, now=datetime(2026, 10, 10, 12, 4, tzinfo=timezone.utc).timestamp())
    check("R: with only 5 days of data the sample target is NOT met and says how much is missing",
          "sample target: NOT YET" in out5)
finally:
    shutil.rmtree(root_r, ignore_errors=True)

# R3: scheduled-closure classification and the session helpers (UTC)
def r_t(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


check("R: closed windows - Fri evening, all Saturday, Sunday until 23:10 and the daily break are scheduled",
      all(XR.in_closed_window(r_t(s)) for s in ("2026-10-09 21:00", "2026-10-09 23:30", "2026-10-10 12:00",
                                                "2026-10-11 22:00", "2026-10-12 21:30", "2026-10-13 22:30")))
check("R: ... and ordinary trading hours are not (Mon 10:00, Wed 13:00, Sun 23:11, Fri 20:00)",
      not any(XR.in_closed_window(r_t(s)) for s in ("2026-10-12 10:00", "2026-10-14 13:00", "2026-10-11 23:11",
                                                    "2026-10-09 20:00")))
runs_r = [(r_t("2026-10-09 21:55"), 49 * 3600 + 10 * 60),        # the weekend: scheduled
          (r_t("2026-10-13 21:55"), 70 * 60),                   # a daily break: scheduled
          (r_t("2026-10-12 21:55"), 5 * 3600),                  # a 'break' that does not end by 23:10: a stall
          (r_t("2026-10-14 10:00"), 40 * 60),                   # mid-session: a stall
          (r_t("2026-10-14 11:00"), 5 * 60)]                    # a 5 min blip: below the stall threshold
sched_r, stall_r = XR.classify_runs(runs_r)
check("R: classify_runs separates scheduled closures from stalls (and ignores blips under 10 min)",
      len(sched_r) == 2 and [t for t, _ in stall_r] == [r_t("2026-10-12 21:55"), r_t("2026-10-14 10:00")],
      f"{len(sched_r)} {stall_r}")
check("R: session buckets are exhaustive and ordered (ASIA 23-07, LONDON 07-12, NY 12-21, ROLLOVER 21-23)",
      [XR.session_of(r_t(f"2026-10-14 {h:02d}:30")) for h in (0, 6, 7, 11, 12, 20, 21, 22, 23)] ==
      ["ASIA", "ASIA", "LONDON", "LONDON", "NY", "NY", "ROLLOVER", "ROLLOVER", "ASIA"])
check("R: the weekly open is Sunday plus Monday before 01:00 (and nothing else)",
      XR.week_open_of(r_t("2026-10-11 23:30")) and XR.week_open_of(r_t("2026-10-12 00:30"))
      and not XR.week_open_of(r_t("2026-10-12 01:00")) and not XR.week_open_of(r_t("2026-10-10 23:30")))
check("R: the assumed cost mirrors strategy_lab's --cost default ($0.20 per side) and 1R uses the 1:1.5 geometry",
      XR.ASSUMED_SIDE_USD == 0.20 and 'default=0.20' in open(os.path.join(HERE, "strategy_lab.py")).read()
      and XR.RR == 1.5 and XR.ASSUMED_USD_PER_TRADE == 0.40)

# R4: the DST verdict (what the converter's rule choice rests on) - synthetic offsets around the 2026 changes
def r_samples(rule=None, fixed=None, start="2026-10-24 00:00", end="2026-11-02 12:00", step=600, stale=False):
    out, t, end_t = [], r_t(start), r_t(end)
    while t < end_t:
        off = fixed if fixed is not None else BT.server_offset_s(datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None), rule)
        out.append(XR.Sample(t, 0.25, 0.25, 0.30, frozenset({"STALE"}) if stale else frozenset(), 0.5, 6, 0, off))
        t += step
    return out


check("R: offsets that follow the EU rule through the change -> verdict EU",
      XR.server_time_verdict(r_samples("eu"))[0] == "EU", XR.server_time_verdict(r_samples("eu"))[1])
check("R: offsets that follow the US rule -> verdict US (the window 10-25..11-01 tells them apart)",
      XR.server_time_verdict(r_samples("us"))[0] == "US", XR.server_time_verdict(r_samples("us"))[1])
check("R: a +4 h server that neither rule explains -> NEITHER, with the advice to use --offset-hours",
      XR.server_time_verdict(r_samples(fixed=14400))[0] == "NEITHER"
      and "--offset-hours" in XR.server_time_verdict(r_samples(fixed=14400))[1])
check("R: offsets seen only on STALE rows are not evidence -> NONE",
      XR.server_time_verdict(r_samples("eu", stale=True))[0] == "NONE")
one = r_samples(fixed=10800, start="2026-10-13 00:00", end="2026-10-20 00:00")
check("R: a single offset -> UNVERIFIED and it names the next EU and US change",
      XR.server_time_verdict(one)[0] == "UNVERIFIED" and "2026-10-25 01:00" in XR.server_time_verdict(one)[1])

# R5: broker_time (the one place the DST rule lives)
check("R: EU summer time 2026 = 2026-03-29 01:00 .. 2026-10-25 01:00 UTC; US = 03-08 07:00 .. 11-01 06:00",
      BT.eu_transitions(2026) == (datetime(2026, 3, 29, 1), datetime(2026, 10, 25, 1))
      and BT.us_transitions(2026) == (datetime(2026, 3, 8, 7), datetime(2026, 11, 1, 6)))
check("R: server offset is +3 h in summer and +2 h in winter, switching at 01:00 UTC",
      BT.server_offset_s(datetime(2026, 7, 1, 12)) == 10800 and BT.server_offset_s(datetime(2026, 12, 1, 12)) == 7200
      and BT.server_offset_s(datetime(2026, 10, 25, 0, 59)) == 10800 and BT.server_offset_s(datetime(2026, 10, 25, 1, 0)) == 7200)
rt_bad, t_bt = 0, datetime(2025, 1, 1)
REPEATED = (datetime(2025, 10, 26, 1), datetime(2026, 10, 25, 1))        # 01:00-01:59 UTC: server 03:xx happens twice
while t_bt < datetime(2027, 1, 1):
    sv = t_bt + timedelta(seconds=BT.server_offset_s(t_bt))
    if not any(h <= t_bt < h + timedelta(hours=1) for h in REPEATED) and BT.server_to_utc(sv) != t_bt:
        rt_bad += 1
    t_bt += timedelta(minutes=30)
check("R: server_to_utc inverts server_offset_s for every half hour of 2025-2026 (except the one repeated fall-back hour)",
      rt_bad == 0, f"{rt_bad} mismatches")
check("R: a fixed offset and a bad rule name behave", BT.server_offset_s(datetime(2026, 7, 1), "fixed:3") == 10800
      and BT.server_to_utc(datetime(2026, 1, 1, 12), "fixed:2") == datetime(2026, 1, 1, 10))
try:
    BT.server_offset_s(datetime(2026, 1, 1), "zz")
    bad_rule_ok = False
except ValueError:
    bad_rule_ok = True
check("R: an unknown DST rule raises instead of silently guessing", bad_rule_ok)


# R6: the report reads the LOGGER'S OWN output (not a hand-written fixture): open -> frozen -> open
root_r = tempfile.mkdtemp()
try:
    clk = QClock(Q_T0 + 1)
    fm = QMT5(clk)
    lg = MQ.XmLogger(fm, "GOLD", os.path.join(root_r, "xm_data"), log=lambda m: None, sleep=clk.sleep)
    lg.start(clk(), clock=clk)
    q_run(lg, clk, 20 * 60)
    fm.mode = "stale"                                   # the feed freezes mid-session (Tue 12:20 UTC, not a scheduled break)
    q_run(lg, clk, 20 * 60)
    fm.mode = "ok"
    q_run(lg, clk, 20 * 60)
    lg.flush_window(clk.t)
    got, bad_n, nf = XR.load_quotes(os.path.join(root_r, "xm_data"))
    runs_l = XR.unusable_runs(got, 30)
    sched_l, stalls_l = XR.classify_runs(runs_l)
    check("R: the report parses every row the logger wrote (no malformed line, 30 s cadence)",
          len(got) >= 115 and bad_n == 0 and XR.coverage(got)["interval"] == 30, f"{len(got)} rows, {bad_n} bad")
    check("R: a mid-session freeze in the logger's real output is ONE feed stall of about 18 minutes "
          "(the first ~2 min of a frozen tick are not yet old enough to be flagged)",
          len(stalls_l) == 1 and len(sched_l) == 0 and 15 * 60 <= stalls_l[0][1] <= 20 * 60,
          f"stalls {stalls_l} sched {sched_l}")
    check("R: the logger's rows around the freeze are usable again afterwards, with the learned offset",
          XR.usable(got[-1]) and got[-1].off == 10800 and all(XR.usable(x) for x in got[-10:]))
    rc, out6 = r_main(root_r, now=clk.t + 60)
    check("R: the full report runs on the logger's own files (spec snapshot included) and sees the stall",
          rc == 0 and "FEED STALLS while the market should be open" in out6
          and "0.01 lot x $1 move = $1.00 (order_calc_profit) OK" in out6 and "DEMO" in out6
          and "verdict [UNVERIFIED]" in out6, out6[:160])
    rc, q6 = r_main(root_r, "--quiet", now=clk.t + 60)
    check("R: --quiet on the logger's own files is OK and one line", q6.startswith("xm logger: OK") and len(q6.splitlines()) == 1,
          q6.strip())
finally:
    shutil.rmtree(root_r, ignore_errors=True)

# --- Scenario S ------------------------------------------------------------
print("\nScenario S: history_to_log (broker server time -> UTC, proven against the MT5-era log; DST observed, not assumed)")
import random as _rnd  # noqa: E402
import history_to_log as H2L  # noqa: E402

S_TS = "%Y-%m-%d %H:%M:%S"


def syn_series(start, n, seed=9, sigma=0.9, wick=0.5, p0=4300.0, drift_amp=0.05):
    """Deterministic synthetic M1 tape on gold's weekly schedule (closed Fri 20:57 -> Sun 22:00 UTC): a random walk with
    alternating 3 h trend legs. -> [(close_utc, o, h, l, c, vol)], 2-digit prices. Hermetic: no live data, no wall clock."""
    rnd, t, p, out, k = _rnd.Random(seed), start, p0, [], 0
    while len(out) < n:
        wd, m = t.weekday(), t.hour * 60 + t.minute
        if (wd == 4 and m >= 20 * 60 + 57) or wd == 5 or (wd == 6 and m < 22 * 60):
            t += timedelta(minutes=1)
            continue
        k += 1
        o = p
        c = o + drift_amp * (1 if (k // 180) % 2 == 0 else -1) + rnd.gauss(0, sigma)
        h = max(o, c) + abs(rnd.gauss(0, wick))
        l = min(o, c) - abs(rnd.gauss(0, wick))
        out.append((t + timedelta(minutes=1), round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                    float(20 + int(abs(rnd.gauss(0, 15))))))
        p, t = c, t + timedelta(minutes=1)
    return out


def s_px(x):                                           # mimic mt5_history_dump's price text (5 decimals, zeros stripped)
    return f"{x:.5f}".rstrip("0").rstrip(".")


def s_write_log(path, series, jitter=4):
    """The live log's shape: stamped a few seconds AFTER the bar closes, CRLF like the real file."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        for t, o, h, l, c, v in series:
            w.writerow([(t + timedelta(seconds=jitter)).strftime(S_TS), f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}", int(v)])


def s_write_raw(path, bars, off_fn, forming=True, corrupt=0):
    """mt5_history_dump's shape: stamped at bar OPEN, in SERVER time (open_utc + off_fn(open_utc) seconds). `bars` may be
    several series (already ascending). The last row is a still-forming bar with partial OHLC, as the real dump has."""
    rows = []
    for t, o, h, l, c, v in bars:
        u = t - timedelta(minutes=1)
        rows.append([(u + timedelta(seconds=off_fn(u))).strftime(S_TS), o, h, l, c, int(v), 25])
    if corrupt:
        for i, r in enumerate(rows):
            if i % 10 < corrupt:
                r[1:5] = [x + 0.5 for x in r[1:5]]      # a valid bar, but not the live feed's bar
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Timestamp", "Open", "High", "Low", "Close", "TickVolume", "Spread"])
        for r in rows:
            w.writerow([r[0]] + [s_px(x) for x in r[1:5]] + r[5:])
        if forming:
            last = datetime.strptime(rows[-1][0], S_TS) + timedelta(minutes=1)
            w.writerow([last.strftime(S_TS), "1.0", "1.5", "0.5", "1.2", 3, 25])


def s_run(argv):
    buf = io.StringIO()
    rc = H2L.main(argv, out=lambda m: buf.write(m + "\n"))
    return rc, buf.getvalue()


def s_read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def s_equal(out_path, series):
    """True when the converted file holds EXACTLY the series: same UTC close stamps, same OHLC."""
    rows = s_read(out_path)
    if len(rows) != len(series):
        return False
    for r, (t, o, h, l, c, v) in zip(rows, series):
        if r["Timestamp"] != t.strftime(S_TS) or int(r["Volume"]) != int(v):
            return False
        if any(abs(float(r[k]) - x) > 0.006 for k, x in zip(("Open", "High", "Low", "Close"), (o, h, l, c))):
            return False
    return True


def eu_off(u):
    return BT.server_offset_s(u, "eu")


def us_off(u):
    return BT.server_offset_s(u, "us")


tmp_s = tempfile.mkdtemp()
try:
    P = lambda name: os.path.join(tmp_s, name)          # noqa: E731
    ser = syn_series(datetime(2026, 9, 14, 0, 0), 3000)  # Mon-Wed, all inside one regime under both rules
    s_write_log(P("log.csv"), ser)
    s_write_raw(P("raw.csv"), ser, lambda u: 10800)

    # S1: a summer pull (+3 h): proven, converted, last (forming) bar dropped
    rc, out = s_run([P("raw.csv"), "--out", P("utc.csv"), "--log", P("log.csv")])
    check("S: a +3 h summer history is accepted, with 100% exact OHLC match as the proof",
          rc == 0 and "offset  +3h : 100.0% exact OHLC match" in out and s_equal(P("utc.csv"), ser), out[-400:])
    check("S: output is UTC and stamped at bar CLOSE (open + 60 s), in the log's column order, never the server time",
          open(P("utc.csv")).readline().strip() == "Timestamp,Open,High,Low,Close,Volume"
          and s_read(P("utc.csv"))[0]["Timestamp"] == ser[0][0].strftime(S_TS))
    check("S: the dump's last row (the still-forming bar) is dropped and says so",
          "dropped the last bar" in out and len(s_read(P("utc.csv"))) == len(ser))
    check("S: a span inside one regime under BOTH rules is reported as rule-independent",
          "does not depend on which rule is right" in out)
    check("S: the default scan covers -12h..+14h and every wrong offset scores 0% (the proof is sharp)",
          len(H2L.CANDIDATES_H) == 27 and "offset -12h" in out + "offset -12h"   # printed only if among the top 3
          and re.search(r"offset\s+[-+]\d+h : +0\.0% exact", out) is not None, out[-300:])
    ALL_CANDIDATES = H2L.CANDIDATES_H
    H2L.CANDIDATES_H = range(1, 5)          # keep the smoke fast: the full scan just ran; the rest need only +2/+3/+4 h
    rc, out = s_run([P("raw.csv"), "--out", P("utc_keep.csv"), "--log", P("log.csv"), "--keep-last"])
    check("S: --keep-last keeps the forming bar (and the proof still passes)",
          rc == 0 and len(s_read(P("utc_keep.csv"))) == len(ser) + 1)
    check("S: the atomic write leaves no .tmp behind", not [f for f in os.listdir(tmp_s) if f.endswith(".tmp")])
    before_files = set(os.listdir(tmp_s))
    rc, out = s_run([P("raw.csv"), "--check-only", "--log", P("log.csv")])
    check("S: --check-only validates and writes nothing", rc == 0 and "nothing written" in out
          and set(os.listdir(tmp_s)) == before_files)

    # S2: a server that is NOT on the documented offset (+2 h in summer) is refused, not silently converted
    s_write_raw(P("raw2.csv"), ser, lambda u: 7200)
    rc, out = s_run([P("raw2.csv"), "--out", P("u2.csv"), "--log", P("log.csv")])
    check("S: +2 h data in summer is REFUSED under the default rule (the EU rule predicts +3 h there)",
          rc == 1 and "REFUSED" in out and "use --dst none" in out and not os.path.exists(P("u2.csv")), out[-300:])
    rc, out = s_run([P("raw2.csv"), "--out", P("u2.csv"), "--log", P("log.csv"), "--dst", "none"])
    check("S: ... and --dst none converts it with the fixed offset the overlap proved", rc == 0 and s_equal(P("u2.csv"), ser))
    rc, out = s_run([P("raw2.csv"), "--out", P("u2b.csv"), "--log", P("log.csv"), "--dst", "eu"])
    check("S: an explicit --dst eu that the data contradicts is refused", rc == 1 and "WRONG offset" in out, out[-200:])

    # S3: an asserted offset is still validated
    rc, out = s_run([P("raw.csv"), "--out", P("u3.csv"), "--log", P("log.csv"), "--offset-hours", "3"])
    check("S: --offset-hours 3 passes validation", rc == 0 and "validated" in out and s_equal(P("u3.csv"), ser))
    rc, out = s_run([P("raw.csv"), "--out", P("u3b.csv"), "--log", P("log.csv"), "--offset-hours", "2"])
    check("S: --offset-hours 2 on +3 h data is REFUSED (a wrong assertion cannot ride through)",
          rc == 1 and "explain only" in out and not os.path.exists(P("u3b.csv")), out[-200:])
    rc, out = s_run([P("raw.csv"), "--out", P("u3c.csv"), "--log", P("log.csv"), "--offset-hours", "3", "--dst", "eu"])
    check("S: --offset-hours together with --dst eu is a usage error (exit 2)", rc == 2)

    # S9: a history whose bars differ from the live feed
    s_write_raw(P("raw9.csv"), ser, lambda u: 10800, corrupt=3)
    rc, out = s_run([P("raw9.csv"), "--out", P("u9.csv"), "--log", P("log.csv")])
    check("S: bars that only 70% match the live feed are REFUSED at the 90% default", rc == 1 and "explain only" in out, out[-200:])
    rc, out = s_run([P("raw9.csv"), "--out", P("u9.csv"), "--log", P("log.csv"), "--min-match", "0.6"])
    check("S: ... and accepted when the operator lowers --min-match consciously", rc == 0 and os.path.exists(P("u9.csv")))

    # S8: no overlap to prove anything against
    rc, out = s_run([P("raw.csv"), "--out", P("u8.csv"), "--log", P("missing.csv")])
    check("S: no log to prove against -> REFUSED with the way out", rc == 1 and "no MT5-era rows" in out
          and "--no-validate" in out and not os.path.exists(P("u8.csv")), out[-200:])
    rc, out = s_run([P("raw.csv"), "--out", P("u8.csv"), "--log", P("missing.csv"), "--no-validate"])
    check("S: --no-validate alone is not enough (an assertion is required)", rc == 1)
    rc, out = s_run([P("raw.csv"), "--out", P("u8.csv"), "--log", P("missing.csv"), "--no-validate", "--offset-hours", "3"])
    check("S: --no-validate --offset-hours 3 converts but labels the result UNVALIDATED",
          rc == 0 and "UNVALIDATED" in out and s_equal(P("u8.csv"), ser))
    march = syn_series(datetime(2026, 3, 27, 12, 0), 1137, seed=4)     # Fri 12:00 -> Mon 08:00, across the EU spring change
    s_write_raw(P("rawm.csv"), march, eu_off)
    rc, out = s_run([P("rawm.csv"), "--out", P("um.csv"), "--log", P("log.csv")])
    check("S: a pull that does not reach the log's period shares no minute -> REFUSED", rc == 1 and "share NO minute" in out, out[-200:])
    s_write_log(P("old_log.csv"), syn_series(datetime(2026, 9, 1, 0, 0), 1500))
    rc, out = s_run([P("raw.csv"), "--out", P("u8.csv"), "--log", P("old_log.csv")])
    check("S: log rows before the MT5 feed started (Twelve Data era) are never used as proof",
          rc == 1 and "no MT5-era rows" in out, out[-200:])

    # S10/S11/S12: guards
    rc, out = s_run([P("utc.csv"), "--out", P("u10.csv"), "--log", P("log.csv")])
    check("S: an already-converted (log-format) file is refused - converting twice would shift it again",
          rc == 1 and "already looks like a converted" in out, out[-200:])
    open(P("junk.csv"), "w").write("a,b,c\n1,2,3\n")
    rc, out = s_run([P("junk.csv"), "--out", P("u10.csv"), "--log", P("log.csv")])
    check("S: a file that is not mt5_history_dump output is refused", rc == 1 and "not mt5_history_dump output" in out)
    rc, out = s_run([P("nope.csv"), "--out", P("u10.csv"), "--log", P("log.csv")])
    check("S: a missing input is a refusal, not a traceback", rc == 1 and "cannot read" in out)
    rc, out = s_run([P("raw.csv"), "--out", P("log.csv"), "--log", P("log.csv")])
    check("S: it refuses to write over the live log", rc == 1 and "refusing to write over" in out
          and open(P("log.csv"), newline="").read().startswith("Timestamp,Open,High,Low,Close,Volume\r\n"))
    rc, out = s_run([P("raw.csv"), "--log", P("log.csv")])
    check("S: --out is required unless --check-only (usage error 2)", rc == 2)
    with open(P("raw.csv")) as f:
        txt = f.read().splitlines()
    dirty = txt[:50] + ["garbage,row", "2026-09-14 03:00:00,100,90,95,98,5,5", txt[10]] + txt[50:]     # junk, a corrupt bar, a duplicate minute
    open(P("rawd.csv"), "w").write("\n".join(dirty) + "\n")
    rc, out = s_run([P("rawd.csv"), "--out", P("ud.csv"), "--log", P("log.csv")])
    check("S: malformed rows, corrupt bars (high < low) and duplicate minutes are skipped and counted, not fatal",
          rc == 0 and "2 malformed rows skipped" in out and s_equal(P("ud.csv"), ser), out[:200])

    # S13: a flat tape matches at EVERY offset, so it proves nothing - refuse instead of picking one
    flat = [(t, 4300.0, 4300.0, 4300.0, 4300.0, 10.0) for (t, *_rest) in ser]
    s_write_log(P("log_flat.csv"), flat)
    s_write_raw(P("raw_flat.csv"), flat, lambda u: 10800)
    rc, out = s_run([P("raw_flat.csv"), "--out", P("u_flat.csv"), "--log", P("log_flat.csv")])
    check("S: a flat tape (every offset matches equally) proves nothing -> REFUSED, not guessed",
          rc == 1 and "no UTC day in the overlap has a clear winner" in out and not os.path.exists(P("u_flat.csv")), out[-250:])

    # S4: a DST change INSIDE the overlap (EU rule): observed from the OHLC match, then the rule is chosen by the data
    # Fri 2026-10-23 12:00 -> Mon 10-26 08:00 UTC (537 + 120 + 480 bars): one voting day each side of the EU change
    dst = syn_series(datetime(2026, 10, 23, 12, 0), 1137, seed=5)
    s_write_log(P("log_dst.csv"), dst)
    s_write_raw(P("raw_eu.csv"), dst, eu_off)
    rc, out = s_run([P("raw_eu.csv"), "--out", P("u_eu.csv"), "--log", P("log_dst.csv")])
    check("S: a transition INSIDE the overlap is observed day by day (+3 h, then +2 h) and the EU rule is chosen by the data",
          rc == 0 and "+3h 2026-10-23..2026-10-23 (1d), +2h 2026-10-26..2026-10-26 (1d)" in out
          and "EU rule - the overlap OBSERVED a transition" in out, out[-700:])
    check("S: ... every bar on both sides of the change converts exactly (no hour lost or duplicated)",
          s_equal(P("u_eu.csv"), dst))
    check("S: ... and the report calls the change OBSERVED, not assumed",
          "the span crosses a DST change (+3h -> +2h)" in out and "OBSERVED in the overlap" in out)
    rc, out = s_run([P("raw_eu.csv"), "--out", P("u_x.csv"), "--log", P("log_dst.csv"), "--dst", "us"])
    check("S: forcing the US rule on EU-shaped data is refused", rc == 1 and "US DST rule predicts the WRONG offset" in out, out[-200:])
    rc, out = s_run([P("raw_eu.csv"), "--out", P("u_x.csv"), "--log", P("log_dst.csv"), "--dst", "none"])
    check("S: a fixed offset over an overlap that changes is refused", rc == 1 and "server clock changed" in out, out[-200:])

    # S5: a server that follows NEW YORK time
    usd = syn_series(datetime(2026, 10, 30, 12, 0), 1137, seed=6)      # Fri 10-30 -> Mon 11-02: across the US change
    s_write_log(P("log_us.csv"), usd)
    s_write_raw(P("raw_us.csv"), usd, us_off)
    rc, out = s_run([P("raw_us.csv"), "--out", P("u_us.csv"), "--log", P("log_us.csv")])
    check("S: US-rule data is recognised from the overlap and converts exactly",
          rc == 0 and "US rule - the overlap OBSERVED a transition" in out and s_equal(P("u_us.csv"), usd), out[-500:])
    rc, out = s_run([P("raw_us.csv"), "--out", P("u_x.csv"), "--log", P("log_us.csv"), "--dst", "eu"])
    check("S: ... and the EU rule is refused on it", rc == 1 and "EU DST rule predicts the WRONG offset" in out, out[-200:])

    # S6: a change that neither rule explains is never guessed at
    def odd_off(u):
        return 10800 if u < datetime(2026, 10, 25, 1) else 14400
    s_write_raw(P("raw_odd.csv"), dst, odd_off)
    rc, out = s_run([P("raw_odd.csv"), "--out", P("u_x.csv"), "--log", P("log_dst.csv")])
    check("S: an offset change that neither DST rule explains is REFUSED (never guessed)",
          rc == 1 and "neither" in out and not os.path.exists(P("u_x.csv")), out[-300:])

    # S7: history that reaches BEFORE the overlap across a transition the overlap cannot confirm
    s_write_raw(P("raw_long.csv"), march + ser, eu_off)
    rc, out = s_run([P("raw_long.csv"), "--out", P("u_long.csv"), "--log", P("log.csv")])
    check("S: bars before the overlap are converted by the rule and the crossing is flagged RULE ONLY / unconfirmed",
          rc == 0 and "from the RULE ONLY" in out and "+2h 2026-03-27 .. 2026-03-27" in out
          and "+3h 2026-03-30 .. 2026-09-16" in out, out[-600:])
    check("S: ... both sides of the spring change convert to the right UTC (+2 h before it, +3 h after)",
          s_equal(P("u_long.csv"), march + ser))
finally:
    H2L.CANDIDATES_H = ALL_CANDIDATES
    shutil.rmtree(tmp_s, ignore_errors=True)

# --- Scenario T ------------------------------------------------------------
print("\nScenario T: strategy_lab --bars (large-N replay of today's rules over UTC broker history; default paths untouched)")
import strategy_lab as SL  # noqa: E402,F811


def t_run(argv, cwd):
    """Run strategy_lab.main(argv) in-process inside `cwd` (its default paths are relative). -> (exit, stdout)."""
    old, buf, code = os.getcwd(), io.StringIO(), None
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(buf):
            try:
                SL.main(argv)
            except SystemExit as e:
                code = e.code
    finally:
        os.chdir(old)
    return code, buf.getvalue()


tmp_t = tempfile.mkdtemp()
try:
    hist = syn_series(datetime(2026, 8, 31, 0, 0), 9000)         # Aug 31 -> Sep 8: straddles the 2026-09-04 tuning start
    hist_path = os.path.join(tmp_t, "history_utc.csv")
    s_write_log(hist_path, hist, jitter=0)                        # a history file is stamped exactly at bar close
    empty = tempfile.mkdtemp()                                   # NO trades.csv, NO forward_test_log.csv here

    code, out = t_run(["--bars", hist_path], empty)
    out_main = out
    check("T: --bars replays history with NO ledger and NO log in the working directory (it reads neither)",
          code is None and "strategy_lab HISTORY" in out and "--bars implies no ledger" in out, out[:200])
    check("T: banner states the cost model and the ratchet (constant 0.75R by default)",
          "cost $0.20/side = $0.40/round trip" in out and "BE ratchet: constant 0.75R" in out)
    check("T: out-of-sample and in-sample windows are separated at the first live trade (2026-09-04)",
          "OOS (< 09-04)" in out and "IN-SAMPLE (>= 09-04)" in out and "lie BEFORE 2026-09-04" in out)
    check("T: months are independent windows and partial months are marked",
          "2026-08  (partial)" in out and "2026-09  (partial)" in out)
    rows_all = {m.group(1): int(m.group(2)) for m in re.finditer(r"ALL\s+(baseline|structstop)\s+n=\s*(\d+)", out)}
    check("T: the synthetic tape produces enough trades to read (>= 20 per variant)",
          rows_all.get("baseline", 0) >= 20 and rows_all.get("structstop", 0) >= 20, f"{rows_all}")
    check("T: the baseline - structstop delta line and the cost table are printed",
          "structstop - baseline:" in out and all(f"${c:8.2f} " in out for c in (0.0, 0.15, 0.20, 0.35)))
    costs_r = re.findall(r"\$\s+(\d\.\d\d)\s+n=\s*\d+\s+([+-]\d+\.\d+)R.*?n=\s*\d+\s+([+-]\d+\.\d+)R", out)
    seq_b = [float(b) for _, b, _ in costs_r]
    seq_s = [float(s_) for _, _, s_ in costs_r]
    check("T: ... for both variants", len(costs_r) == 4 and seq_b == sorted(seq_b, reverse=True)
          and seq_s == sorted(seq_s, reverse=True) and seq_b[0] > seq_b[-1], f"{costs_r}")
    check("T: the honesty caveats are printed (broker history, hypothesis only, flat cost, intra-bar bias)",
          all(x in out for x in ("READ THIS BEFORE QUOTING", "PRE-REGISTER", "Intra-bar ordering is unknowable",
                                 "the live ledger and forward test stay the authority")))
    code2, out2 = t_run(["--bars", hist_path], empty)
    check("T: the replay is deterministic (same file, same bytes - no wall clock, no randomness)", out2 == out)

    code, out_off = t_run(["--bars", hist_path, "--ratchet", "off"], empty)
    code, out_era = t_run(["--bars", hist_path, "--ratchet", "era"], empty)
    be_const = re.search(r"ALL\s+baseline\s+n=\s*\d+\s+\d+W/\s*\d+L/\s*(\d+)BE", out)
    be_off = re.search(r"ALL\s+baseline\s+n=\s*\d+\s+\d+W/\s*\d+L/\s*(\d+)BE", out_off)
    be_era = re.search(r"ALL\s+baseline\s+n=\s*\d+\s+\d+W/\s*\d+L/\s*(\d+)BE", out_era)
    check("T: --ratchet const arms scratches, off arms none, and era (none before 2026-09-10 12:34) arms none on this "
          "pre-09-10 tape", be_const and be_off and be_era and int(be_const.group(1)) > 0 and int(be_off.group(1)) == 0
          and int(be_era.group(1)) == 0 and "live-era schedule" in out_era and "BE ratchet: OFF" in out_off,
          f"const {be_const and be_const.group(1)} off {be_off and be_off.group(1)} era {be_era and be_era.group(1)}")
    code, out_one = t_run(["--bars", hist_path, "--only", "baseline", "--cost", "0.35"], empty)
    check("T: --only and --cost apply (one variant, $0.35/side in the banner, no delta line)",
          code is None and "structstop" not in out_one.split("== H4")[0].split("== H2")[1] and "$0.35/side" in out_one
          and "structstop - baseline" not in out_one)

    # refusals
    raw_path = os.path.join(tmp_t, "mt5_history.csv")
    s_write_raw(raw_path, hist[:2000], lambda u: 10800)
    code, out = t_run(["--bars", raw_path], empty)
    check("T: RAW mt5_history_dump output is refused with the converter command (server time labelled UTC would silently "
          "shift every blackout and session)", isinstance(code, str) and "history_to_log.py" in code and "BROKER SERVER time" in code,
          str(code)[:120])
    short_path = os.path.join(tmp_t, "short.csv")
    s_write_log(short_path, hist[:600])
    code, out = t_run(["--bars", short_path], empty)
    check("T: a file too short to warm up is refused", isinstance(code, str) and "usable bars" in code, str(code)[:100])
    code, out = t_run(["--bars", os.path.join(tmp_t, "nope.csv")], empty)
    check("T: a missing file is a clean message", isinstance(code, str) and "cannot read" in code)
    open(os.path.join(tmp_t, "bad.csv"), "w").write("Timestamp,Price\n1,2\n")
    code, out = t_run(["--bars", os.path.join(tmp_t, "bad.csv")], empty)
    check("T: a file without OHLC columns is a clean message", isinstance(code, str) and "needs the columns" in code)
    code, out = t_run(["--bars", hist_path, "--only", "nonsense"], empty)
    check("T: an unknown variant is a clean message", isinstance(code, str) and "unknown variant" in code)
    code, out = t_run(["--bars", hist_path, "--table"], empty)
    check("T: --table does not combine with --bars", isinstance(code, str) and "does not combine" in code)
    code, out = t_run(["--ratchet", "off"], empty)
    check("T: --ratchet without --bars is refused (the live-era replay always uses the era schedule)",
          isinstance(code, str) and "only applies with --bars" in code)

    # the converter's output feeds the lab end to end (the real chain: dump -> convert -> replay)
    s_write_log(os.path.join(tmp_t, "log_chain.csv"), hist[3000:])
    s_write_raw(os.path.join(tmp_t, "raw_chain.csv"), hist, lambda u: 10800)
    rc, cout = s_run([os.path.join(tmp_t, "raw_chain.csv"), "--out", os.path.join(tmp_t, "history_utc2.csv"),
                      "--log", os.path.join(tmp_t, "log_chain.csv"), "--overlap-from", "2026-08-31"])
    code, out_chain = t_run(["--bars", os.path.join(tmp_t, "history_utc2.csv")], empty)
    same = [ln for ln in out_chain.splitlines() if not ln.startswith("file:")]
    base = [ln for ln in out_main.splitlines() if not ln.startswith("file:")]
    check("T: dump -> history_to_log -> strategy_lab --bars works end to end and reports exactly what replaying the "
          "source tape reports (the converter lost and shifted nothing)",
          rc == 0 and code is None and same == base and len(same) > 20, cout[-200:])

    # default path untouched: calibration still runs from the cwd's ledger and log
    cwd_def = tempfile.mkdtemp()
    s_write_log(os.path.join(cwd_def, "forward_test_log.csv"), hist)
    r_write_ledger(cwd_def, [("2026-09-02 10:00:02", "2026-09-02 10:05:01", 3.0),
                             ("2026-09-02 11:00:02", "2026-09-02 11:05:01", -2.0)])
    code, out_def = t_run(["--calib-only"], cwd_def)
    check("T: WITHOUT --bars the default path still reads the cwd's log + ledger and prints the calibration (unchanged)",
          code is None and "== 1. CALIBRATION" in out_def and "HISTORY" not in out_def and "ledger: 2 closed trades" in out_def,
          out_def[:160])
    shutil.rmtree(cwd_def, ignore_errors=True)
    shutil.rmtree(empty, ignore_errors=True)
finally:
    shutil.rmtree(tmp_t, ignore_errors=True)


print()
if FAILURES:
    print(f"SMOKE TEST FAILED: {FAILURES}")
    sys.exit(1)
print("SMOKE TEST PASSED")
