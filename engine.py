#!/usr/bin/env python3
import os
import csv
import json
import time
import sys
import shutil
import math
import requests
from collections import deque
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from trade_filter import should_take_trade, get_daily_sl_count, MAX_DAILY_LOSSES, load_recent_trades

# ==========================================
# CONFIGURATION SWITCH
# Set to "FORWARD_TEST" to use Twelve Data and simulated balance
# Set to "LIVE" to use MetaTrader 5 and real execution
# ==========================================
TRADING_MODE = "FORWARD_TEST"

load_dotenv(dotenv_path="/opt/gold/.env")

# Data source for FORWARD_TEST mode: "TWELVEDATA" (WebSocket, default) or
# "MT5" (local Wine MT5 terminal - broker feed, no API plan limits).
# Set DATA_SOURCE=MT5 in /opt/gold/.env to switch (the MT5 terminal must be
# running and logged in; see archive/wine_mt5_setup.md). Trading stays
# simulated either way.
DATA_SOURCE = (os.getenv("DATA_SOURCE") or "TWELVEDATA").strip().upper()

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.38
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
# SCALE WARNING (2026-10-05): this tolerance is a PRICE-%, so on gold at ~$4,150 it is
# ~$8.30 = 4.5x the median ATR (1.83) while every other threshold in the funnel is
# ATR-scaled. Measured consequence: "price tested the 20-bar floor" is TRUE on 86.9% of
# logged bars (89.1% recomputed for the 0.75R era), i.e. the level test selects for
# almost nothing. Re-scaling it to ATR (0.15-0.25
# ATR) lifts the pooled replay a lot (all-eras cascade at $0.30 round trip: bleed
# -12.4 -> -2.1 $/day, n 563 -> 137) and the current max-hold era (+0.010R vs -0.245R),
# but it is WORSE in 2 of the 4 parameter eras
# (0.30R slice: 0 winners of 21 decisive; 0.75R pre-max-hold: -0.273R vs -0.154R), so it
# is a REGISTERED CANDIDATE only - do not flip it on replay evidence alone.
# Reproduce: tools/strategy_lab.py --grid level
FLOOR_BUFFER_PCT = 0.0020

ATR_SL_MULT = 2.0
ATR_TP_MULT = 3.0

# ── STRUCTURAL STOP (2026-10-05, docs/ANALYSIS-2026-10-05-stop-loss-geometry.md) ──
# 2xATR is a FLOOR on the stop distance, not the right answer. The entry fills at the
# CLOSE of the rejection bar, a median 2.42 ATR away from the 20-bar level it claims to
# bounce off, so the stop sits INSIDE that range - median 0.42 ATR short of it - on
# 203/318 = 63.8% of the 0.75R master book, and 95/149 = 63.8% of its SL exits were that
# class. Price then only has to come BACK to the level to stop us out; no structural break
# is required (median SL lifetime 7.2 min, 46% <= 7 min, out of a 240-min hold budget).
# The stop must clear the level the trade's own premise was built on.
# Verify any era with: python3 tools/check_structural_stop.py   (post-cutover it must print 0)
SL_CLEAR_ATR = 0.5           # min distance the stop sits beyond the tested level
# Reward stays a multiple of the ACTUAL risk so 1:1.5 does not silently degrade as the
# stop widens: TP = RR_TARGET * risk == ATR_TP_MULT * ATR whenever the level does not
# bind, i.e. the pre-2026-10-05 geometry is reproduced exactly in that case.
RR_TARGET = ATR_TP_MULT / ATR_SL_MULT

# ── DAILY-CLOSURE ENTRY GUARD (gap guard) ─────────────────────────────────────
# REGISTERED 2026-10-25: docs/PREREG-2026-10-25-gap-guard-daily-closure.md
# Why: the §7 closure-gap REVERT trigger FIRED at 3/2 post-cutover rides
# (#595/#610/#687), all of them across the broker's DAILY break (20:58 -> 22:00 UTC
# under the current +3h offset). The structural stop cannot be enforced while the
# market is shut, so a position opened just before the close rides the gap.
# Scope (owner-approved 2026-10-25): suppress NEW ENTRIES only, for
# GUARD_CUTOFF_MIN before the derived daily close through the derived reopen.
# Open positions are NOT flattened (that would be a separate registration), and no
# stop/TP/risk parameter changes.
# Schedule source: DERIVED from the observed price-log gaps (never a guessed clock).
# Fail-open: if the daily break signature cannot be derived (fresh install, no
# history), the guard does not block — it cannot invent a schedule. A stale feed
# needs no special case: entries only happen when a NEW candle is evaluated, and a
# stale feed publishes none.
GUARD_CUTOFF_MIN = 30        # owner-approved 2026-10-25 (block from close-30min)
GUARD_LOOKBACK_DAYS = 30     # price-log window used to derive the break signature
GUARD_MIN_BREAK_MIN = 30.0   # a daily break is 30-180 min (check_gap_rides uses the same)
GUARD_MAX_BREAK_MIN = 180.0
GUARD_MIN_SAMPLES = 3        # fewer observed breaks than this -> no signature -> fail-open
GUARD_RECENT_SAMPLES = 5     # modal window over recent breaks so schedule changes converge fast
GUARD_WEEKEND_MIN = 24 * 60.0  # weekly close (>= 24 h); Sunday reopen shares daily reopen tod
GUARD_DST_TOL_MIN = 2        # minute jitter allowed around an exact +-60 min DST shift

# Breakeven stop ratchet (adopted 2026-09-10, docs/ANALYSIS-2026-09-10-losing-trades.md):
# once a trade is +BE_TRIGGER_R in profit, SL moves to entry. Sequence-aware replay of all
# 45 sample trades: -82.51 actual -> ~-63 with the ratchet (12-14 losers scratch).
# RAISED 0.30 -> 0.75 on 2026-09-15 (docs/REVIEW-2026-09-15.md). At +0.30R the trigger
# was 0.60*ATR ~= $1.2 on a $4300 market - one 1-min bar of noise. 92 of 119 new-regime
# trades armed it and scratched (median scratch lifetime 1.5 min), which is what pinned
# the decisive win rate at 22%. Re-walking the SAME 119 entries (replay reproduces the
# live result exactly at 0.30R: 6W/21L/92BE, -$57.55 vs -$58.43 actual):
#   +0.30R  22.2% dec  -$0.49/trade (live)   |  +0.75R  44.7% dec  +$0.40/trade
#   off     41.0% dec  +$0.52/trade          |  +1.00R  38.5% dec  +$0.10/trade
# 0.75R is the level that keeps most of the protection while leaving the winners alone.
# Cascade-aware (no overlapping trades + SL cooldown), one regime, ~59 trades - a
# direction, not a forecast. Re-validate after ~2 more weeks.
BE_TRIGGER_R = 0.75

# Max-hold time stop (deployed 2026-09-21, docs/REVIEW-2026-09-21.md): pre-registered
# fallback step 1 after the 0.75R falsification bar tripped 2026-09-17 (-$0.595/trade
# at n=60; docs/REVIEW-2026-09-18.md). Any open trade older than MAX_HOLD_MINUTES is
# closed at market, whatever the P&L. It caps the >60-min holds (#95: 49.1 h weekend
# gap, #187: 65 min) and operationalises "close before the next scheduled macro
# event" with no news feed.
# Exit reason "TIME": own counter (time_exits), P&L-signed, EXCLUDED from decisive
# win-rate math like BE (TP/SL stay a pure signal read; era P&L/trade still books
# every dollar). Ignored by the SL streak / daily breaker (trade_filter.py), like BE.
# Checked AFTER price exits (a simultaneous TP/SL wins), on both the tick path
# (check_position) and the MT5 candle path (resolve_open_trade_on_candle, at close).
# Wall-clock: across a market closure the trade exits on the first candle/tick back.
# LIVE-mode note: like the BE ratchet this is engine-side only (run_live never calls
# check_position); a broker-side time stop is future work for any live pilot.
MAX_HOLD_MINUTES = 240

# ── TELEGRAM ROUTING (2026-10-23, ops only — no strategy/exit/gate change) ──────
# The engine talks to Telegram on every signal, skip, exit and feed event. Measured
# on the 10 trading days to 2026-10-23 that is ~82 messages/day, of which only the
# optional box-watch notice (~5/day) is the one the owner actually reads — every
# skipped bar during a cooldown or a blackout sends its own message (~37/day).
# Owner ask: keep Telegram for the indicator notice; the trade chatter belongs
# elsewhere (the dashboard + the 2×/day autosync digest).
#
# So each message carries a KIND and GOLD_TELEGRAM_KINDS selects which kinds the
# engine is allowed to send:
#   trade  entry alert (BUY/SELL + SL/TP)
#   exit   TP / SL / BE exit, TIME stop, BE-ratchet armed
#   skip   "BUY SETUP SKIPPED" (cooldown / blackout / breaker / ATR)
#   risk   sizer refusals, LIVE order failures, account_info unavailable
#   feed   stale-feed alert and feed recovery
# Unset or blank = send everything (today's behaviour, byte for byte) so a deploy
# of this code alone changes nothing. GOLD_TELEGRAM_KINDS=none mutes the engine
# entirely; a typo falls back to "everything" rather than silently muting it.
# Nothing here touches the trading path: the same trades, exits and skips happen
# whether or not a message is sent, and every event still lands in trades.csv,
# skipped_trades.csv, status.json and forward_test_log.csv.
TELEGRAM_KINDS = ("trade", "exit", "skip", "risk", "feed")


def notify_kinds(env=None):
    """Kinds the engine is allowed to send, from GOLD_TELEGRAM_KINDS (pure)."""
    env = os.environ if env is None else env
    raw = env.get("GOLD_TELEGRAM_KINDS")
    if raw is None or not str(raw).strip():
        return set(TELEGRAM_KINDS)
    raw = str(raw).strip().lower()
    if raw in ("none", "off", "0"):
        return set()
    wanted = {k.strip() for k in raw.split(",") if k.strip()}
    known = {k for k in wanted if k in TELEGRAM_KINDS}
    return known or set(TELEGRAM_KINDS)   # a typo must never silence the bot


def notify_enabled(kind, env=None):
    """True if a message of this kind should be sent. Pure; no clock, no network."""
    return kind in notify_kinds(env)


REQUIRE_VOLUME_CONFIRM = False
VOLUME_SPIKE_MULTIPLIER = 0.9
REQUIRE_TREND_CONFIRM = True
RSI_MIN = 30.0
RSI_MAX = 68.0
MIN_ATR = 1.10

# --- Stale feed guard (silent Twelve Data WebSocket stalls, 2026-09-10) ---
STALE_FEED_SECONDS = 10 * 60            # force reconnect if no price event this long
STALE_ALERT_COOLDOWN_SECONDS = 30 * 60  # Telegram alert at most this often

# --- MT5 publisher heartbeat (silent frozen-file stall, 2026-09-29) ---
# tools/mt5_feed.py rewrites MT5_FEED_FILE every poll (5 s) *even when the
# market is closed* (it republishes the last closed bar). So a file whose mtime
# stops moving means the *publisher* died (MT5 terminal logged out / stuck /
# wine prefix gone) - NOT that the market is quiet. This is the signal the
# price-event guard cannot see: with a frozen file no candle is ever accepted,
# so `_last_price_mono` never advances (and after a restart it stays None),
# which is how a 2026-09-29 host reboot left the engine looping silently for
# 6 h while the dashboard said STALE and nothing else complained.
MT5_FEED_PUBLISHER_STALE_SECONDS = 3 * 60   # stale mtime = 36 missed 5-s polls
MT5_FEED_PROBLEM_LOG_COOLDOWN_SECONDS = 5 * 60  # journal print at most this often

# --- Regime gates (EMA Slope & Distance from Mean) ---
REQUIRE_EMA_SLOPE = True       # EMA50 slope direction filter
EMA_SLOPE_LOOKBACK = 30        # Compare EMA50 vs N candles ago
MAX_BELOW_EMA_ATR = 0.30       # Entry distance buffer from EMA50

SYMBOL = "GOLD"
LOT_SIZE = 0.01
MAGIC_NUMBER = 987654

# --- Position sizing / risk gate (adds %-risk control; does NOT touch stop/TP geometry) ---
# Keeps R-invariant: R = P&L / $risk scales with lots, so the open struct-stop
# era metrics (R/trade, WR, SL share) are unaffected by lot sizing.
RISK_PCT        = 1.0     # % of balance risked per trade (balance excludes non-withdrawable credit)
CONTRACT_SIZE   = 100     # XM GOLD Standard = 100 oz; GOLDmicro = 1
VOLUME_MIN      = 0.01    # MT5 symbol spec: minimum volume
VOLUME_STEP     = 0.01    # MT5 symbol spec: volume step

# ── LIVE execution safety (2026-10-26; LIVE path ONLY, paper untouched) ──────
# Flipping TRADING_MODE to "LIVE" is NOT sufficient to place a real order.
# An operator must explicitly arm the process (GOLD_LIVE_ARMED=1) and must not
# have dropped the kill-switch file. Both are re-checked on every loop and
# again immediately before an order, so `touch /opt/gold/LIVE_HALT` stops new
# exposure without a code change or a restart. See
# docs/REVIEW-2026-10-26-full-system-audit.md and tools/live_readiness.py.
# None of this changes FORWARD_TEST behaviour, entries, exits or the ledger.
LIVE_ARM_ENV = "GOLD_LIVE_ARMED"
LIVE_HALT_FILE = os.getenv("GOLD_LIVE_HALT_FILE", "/opt/gold/LIVE_HALT")

LOG_FILE_PATH = "/opt/gold/forward_test_log.csv"
STATUS_FILE_PATH = "/opt/gold/status.json"
# DATA_SOURCE=MT5: the Wine sidecar (tools/mt5_feed.py) publishes the latest
# closed M1 candle here; the engine reads this file instead of importing
# MetaTrader5 (no Linux wheels exist for that package).
MT5_FEED_FILE = os.getenv("MT5_FEED_FILE", "/opt/gold/mt5_last_candle.json")
TRADES_LOG_PATH = "/opt/gold/trades.csv"

# Canonical trades.csv schema (what log_trade() writes). Trade_Type was added
# when SELL support went live (2026-09-09); older rows/files have 15 fields.
TRADES_FIELDNAMES = [
    "Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
    "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
    "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry",
]


def migrate_trades_csv(path: str = TRADES_LOG_PATH) -> bool:
    """Self-heal trades.csv schema drift (2026-09-10 incident).

    log_trade() writes 16-field rows (Trade_Type in position 2), but if the
    file on disk still has the pre-SELL 15-field header, every appended row is
    silently MISALIGNED with it: Exit_Reason reads as the exit price, Profit
    reads as "SL"/"TP", Balance_After reads as the profit. Downstream readers
    (engine stats reload, daily-loss circuit breaker, SL cooldowns) then
    quietly stop counting those trades - the risk gates were effectively OFF
    for SELL trade #41 on 2026-09-10.

    This rewrites the file in place (backup kept next to it as
    <path>.bak-pre-migration) so that:
      - the header is the 16-field schema above
      - old 15-field rows get Trade_Type="BUY" inserted (every pre-SELL trade was a buy)
      - already-16-field rows are kept byte-for-byte
    Returns True if a migration was performed, False if already current.
    """
    if not os.path.isfile(path):
        return False
    try:
        with open(path, newline="") as f:
            raw = [r for r in csv.reader(f) if r]
    except Exception as e:
        print(f"WARNING: could not read {path} for schema check: {e}")
        return False
    if not raw:
        return False

    header = [h.strip() for h in raw[0]]
    if header == TRADES_FIELDNAMES:
        return False  # already current

    migrated, odd = [], 0
    for r in raw[1:]:
        if len(r) == len(TRADES_FIELDNAMES):          # already new-schema row
            migrated.append(r)
        elif len(r) == len(TRADES_FIELDNAMES) - 1:    # pre-SELL row -> all buys
            migrated.append([r[0], "BUY"] + r[1:])
        else:
            migrated.append(r)
            odd += 1

    backup = path + ".bak-pre-migration"
    tmp = path + ".tmp-migration"
    try:
        shutil.copy2(path, backup)
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(TRADES_FIELDNAMES)
            w.writerows(migrated)
        os.replace(tmp, path)
    except Exception as e:
        print(f"WARNING: trades.csv schema migration FAILED ({e}) - "
              f"risk gates may miscount SELL trades until fixed!")
        return False

    print(f"WARNING: migrated {path} to the 16-field schema "
          f"(Trade_Type column added; {len(raw) - 1} rows rewritten, "
          f"{odd} unrecognisable). Backup saved to {backup}.")
    return True


def utc_now_str() -> str:
    """All timestamps in this bot are UTC (matches trade_filter.py)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_log_ts(s: str):
    """Parse a forward_test_log.csv timestamp (UTC) or return None."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
    return None


def _modal_minute_of_day(samples):
    """Most common minute-of-day in `samples` [(h, m)], ties broken by the median.

    Used to turn a handful of observed breaks into one signature. The break clock is
    stable to the minute in the log (20:58 every day in the current era), so the mode
    is the right estimator; the median keeps a tie from being arbitrary.
    """
    if not samples:
        return None
    counts = {}
    for s in samples:
        counts[s] = counts.get(s, 0) + 1
    best = max(counts.values())
    winners = sorted(k for k, v in counts.items() if v == best)
    if len(winners) == 1:
        return winners[0]
    mins = sorted(h * 60 + m for h, m in winners)
    mid = mins[len(mins) // 2]
    return (mid // 60, mid % 60)


def _signed_tod_diff_min(tod_a, tod_b) -> int:
    """Signed circular difference `tod_a - tod_b` in minutes, in [-720, +720)."""
    a = tod_a[0] * 60 + tod_a[1]
    b = tod_b[0] * 60 + tod_b[1]
    return (a - b + 720) % 1440 - 720


def _dst_shift_min(observed_tod, base_tod, tol_min: int = GUARD_DST_TOL_MIN):
    """Return +60 or -60 when `observed_tod` sits 1 h (+/- tol_min) from `base_tod`, else None."""
    diff = _signed_tod_diff_min(observed_tod, base_tod)
    if abs(diff - 60) <= tol_min:
        return 60
    if abs(diff + 60) <= tol_min:
        return -60
    return None


def _shift_tod(tod, delta_min: int):
    """Shift an `(hour, minute)` tuple by `delta_min` minutes modulo 24 h."""
    total = (tod[0] * 60 + tod[1] + delta_min) % 1440
    return (total // 60, total % 60)


def derive_daily_closure(log_path: str = None, lookback_days: int = GUARD_LOOKBACK_DAYS):
    """Derive the broker's daily-break signature from the observed price log.

    Returns `(close_tod, reopen_tod)` as (hour, minute) UTC tuples, or None when the
    signature cannot be established. Read-only: the log is never modified.

    A "daily break" is a hole in the bar series of 30-180 minutes; fewer than
    GUARD_MIN_SAMPLES observed breaks in `lookback_days` -> None (caller fails open).

    DST responsiveness (2026-10-25 refinement):
      * Baseline mode is taken over the most recent GUARD_RECENT_SAMPLES (5) daily
        breaks rather than the whole 30-day window, so any schedule shift converges
        within 3 trading days while staying immune to isolated mid-day feed outages.
      * Across a Sunday +-1 h DST transition (EU last Sunday of Mar/Oct, US 2nd
        Sunday of Mar / 1st Sunday of Nov), the Sunday weekly reopen shares the exact
        minute-of-day of the daily reopen. Before 5 post-weekend breaks accumulate:
        - if post-weekend daily break(s) shifted by a consistent +-60 min (+/-2 min)
          on both close and reopen vs the pre-weekend mode (and none stayed at the
          old hour), return the modal signature of those shifted breaks;
        - else if no post-weekend break matched either hour yet (Sunday night /
          Monday Day 1 before the close, or only a mid-day outage so far) and the
          weekend reopen shifted by +-60 min (+/-2 min), shift the pre-weekend
          signature by that exact +-60 min. Arbitrary outage hours never match +-60 m.
    """
    path = log_path or LOG_FILE_PATH
    try:
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
    except (OSError, ValueError):
        return None
    if len(rows) < 2:
        return None

    stamps = []
    for row in rows[1:]:
        if not row:
            continue
        ts = _parse_log_ts(row[0])
        if ts is not None:
            stamps.append(ts)
    if len(stamps) < 2:
        return None

    cutoff = stamps[-1] - timedelta(days=lookback_days)
    daily_breaks = []
    weekends = []
    for a, b in zip(stamps, stamps[1:]):
        if a < cutoff:
            continue
        mins = (b - a).total_seconds() / 60.0
        if GUARD_MIN_BREAK_MIN <= mins <= GUARD_MAX_BREAK_MIN:
            daily_breaks.append((a, (a.hour, a.minute), (b.hour, b.minute)))
        elif mins >= GUARD_WEEKEND_MIN:
            weekends.append((a, (a.hour, a.minute), (b.hour, b.minute)))
    if len(daily_breaks) < GUARD_MIN_SAMPLES:
        return None

    recent = daily_breaks[-GUARD_RECENT_SAMPLES:]
    base_close = _modal_minute_of_day([c for _, c, _ in recent])
    base_reopen = _modal_minute_of_day([r for _, _, r in recent])
    if base_close is None or base_reopen is None:
        return None

    if weekends:
        wk_ts, _, wk_reopen = weekends[-1]
        pre_wk = [b for b in daily_breaks if b[0] < wk_ts]
        post_wk = [b for b in daily_breaks if b[0] > wk_ts]
        if len(post_wk) < GUARD_RECENT_SAMPLES and len(pre_wk) >= GUARD_MIN_SAMPLES:
            pre_recent = pre_wk[-GUARD_RECENT_SAMPLES:]
            pre_close = _modal_minute_of_day([c for _, c, _ in pre_recent])
            pre_reopen = _modal_minute_of_day([r for _, _, r in pre_recent])
            unshifted = [
                b for b in post_wk
                if abs(_signed_tod_diff_min(b[1], pre_close)) <= GUARD_DST_TOL_MIN
                and abs(_signed_tod_diff_min(b[2], pre_reopen)) <= GUARD_DST_TOL_MIN
            ]
            shifted = []
            for _, c_tod, r_tod in post_wk:
                sc = _dst_shift_min(c_tod, pre_close)
                sr = _dst_shift_min(r_tod, pre_reopen)
                if sc is not None and sc == sr:
                    shifted.append((c_tod, r_tod))
            if shifted and not unshifted:
                return (
                    _modal_minute_of_day([c for c, _ in shifted]),
                    _modal_minute_of_day([r for _, r in shifted]),
                )
            if not unshifted and not shifted:
                wk_shift = _dst_shift_min(wk_reopen, pre_reopen)
                if wk_shift is not None:
                    return (_shift_tod(pre_close, wk_shift), _shift_tod(pre_reopen, wk_shift))
                return pre_close, pre_reopen
    else:
        tail_shifted = []
        for _, c_tod, r_tod in reversed(recent):
            sc = _dst_shift_min(c_tod, base_close)
            sr = _dst_shift_min(r_tod, base_reopen)
            if sc is not None and sc == sr:
                tail_shifted.append((c_tod, r_tod))
            else:
                break
        if tail_shifted:
            return (
                _modal_minute_of_day([c for c, _ in tail_shifted]),
                _modal_minute_of_day([r for _, r in tail_shifted]),
            )

    return base_close, base_reopen


def guard_blocks_entry(now_utc: datetime, closure, cutoff_min: int = GUARD_CUTOFF_MIN) -> bool:
    """True when a NEW entry must be suppressed by the daily-closure gap guard.

    The blocked window is `[daily_close - cutoff_min, daily_reopen)`, evaluated on the
    UTC minute-of-day, and it wraps past midnight if the broker's break does. `closure`
    is the (close_tod, reopen_tod) tuple from derive_daily_closure(); None -> never
    block (fail-open, see the constant block).
    """
    if not closure or now_utc is None:
        return False
    close_tod, reopen_tod = closure
    close_min = close_tod[0] * 60 + close_tod[1]
    reopen_min = reopen_tod[0] * 60 + reopen_tod[1]
    now_min = now_utc.hour * 60 + now_utc.minute
    start_min = (close_min - cutoff_min) % (24 * 60)

    if start_min <= reopen_min:
        return start_min <= now_min < reopen_min
    # window wraps midnight
    return now_min >= start_min or now_min < reopen_min


def is_market_quiet(now_utc: datetime = None) -> bool:
    """True during hours where no price ticks are expected.

    Gold spot trades roughly 02:00-21:00 UTC Mon-Fri; the broker daily break
    observed in our price log runs ~21:15-01:41 UTC. Outside that window (and
    all weekend) a silent feed is normal, so the stale-feed guard reconnects
    quietly instead of alerting.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:  # Saturday/Sunday
        return True
    return now_utc.hour >= 21 or now_utc.hour < 2


def latest_closed_candle_ts(rates):
    """Timestamp of the most recent closed M1 candle from mt5.copy_rates_*
    results (position 1), or None if no data was returned."""
    if rates is None or len(rates) == 0:
        return None
    return int(rates[0]["time"])


def live_armed(env=None, halt_path=None) -> bool:
    """True only when LIVE is explicitly armed AND no kill-switch file exists.

    Pure apart from one os.path.isfile; `env` and `halt_path` are injectable so
    tests are hermetic. Fails CLOSED on any error. LIVE path only — the paper
    engine never consults this. Deliberate two-key design: an accidental
    TRADING_MODE="LIVE" (or a bad config edit) cannot place real orders on its
    own, and a single file stops new exposure without touching the process.
    """
    env = os.environ if env is None else env
    if str(env.get(LIVE_ARM_ENV, "")).strip() != "1":
        return False
    path = halt_path if halt_path is not None else LIVE_HALT_FILE
    try:
        return not os.path.isfile(path)
    except OSError:
        return False


def resolve_order_filling(mt5_mod, symbol_info):
    """Return the ORDER_FILLING_* constant this symbol actually supports.

    `symbol_info().filling_mode` is a bitmask: bit0 = FOK, bit1 = IOC, bit2 = BOC
    (same decoding as tools/mt5_quotes.py FILLING_BITS). The captured XM spec
    (xm_data/symbol_spec.json, 2026-10-26) reports filling_mode = 2 => IOC ONLY,
    so the previously hard-coded ORDER_FILLING_FOK would be rejected by the
    broker. None means "no supported policy is known" — the caller must refuse
    the order rather than guess. Read-only and pure; no MT5 call here.
    """
    mode = int(getattr(symbol_info, "filling_mode", 0) or 0)
    if mode & 1 and getattr(mt5_mod, "ORDER_FILLING_FOK", None) is not None:
        return mt5_mod.ORDER_FILLING_FOK
    if mode & 2 and getattr(mt5_mod, "ORDER_FILLING_IOC", None) is not None:
        return mt5_mod.ORDER_FILLING_IOC
    return None


if TRADING_MODE == "LIVE":
    import MetaTrader5 as mt5
else:
    from twelvedata import TDClient


class GoldEngine:
    def __init__(self):
        self.lows = deque(maxlen=EMA_SLOW)
        self.highs = deque(maxlen=EMA_SLOW)
        self.closes = deque(maxlen=EMA_SLOW)
        self.volumes = deque(maxlen=EMA_SLOW)
        self.tr_list = deque(maxlen=ATR_PERIOD)
        self.rsi_gains = deque(maxlen=RSI_PERIOD)
        self.rsi_losses = deque(maxlen=RSI_PERIOD)
        self.ema50_history = deque(maxlen=EMA_SLOW)   # for the EMA-slope regime gate

        # Daily-closure entry guard (registered 2026-10-25): the break signature is
        # derived from the price log at most once per UTC day, never hard-coded.
        self._guard_closure = None
        self._guard_closure_date = None
        self._guard_closure_path = None

        self.prev_close = None
        self.rsi = None
        self.ema_fast = None
        self.ema_slow = None
        self.atr = None

        self.k_fast = 2 / (EMA_FAST + 1)
        self.k_slow = 2 / (EMA_SLOW + 1)

        self.current_minute = None
        self.tick_pool = []

        self.balance = 500.00
        self.trade_lots = LOT_SIZE                  # current position size (set by risk sizer)
        self.pnl_scale = LOT_SIZE * CONTRACT_SIZE   # $ P&L per $1 move for trade_lots (0.01 GOLD = 1.0)
        self.account_balance = None                 # live MT5 balance, used by the risk sizer
        self.trade_active = False
        self.trade_type = "BUY"  # "BUY" or "SELL"
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.structural_stop_bound = False   # True when the 20-bar level (not the ATR floor) set the stop
        self.be_armed = False  # True once the breakeven ratchet (BE_TRIGGER_R) fired
        self.current_trade_num = None

        self.next_trade_num = 1
        self.wins = 0
        self.losses = 0

        self.entry_time = None
        self.entry_rsi = None
        self.entry_atr = None
        self.entry_wick_ratio = None
        self.entry_ema_fast = None
        self.entry_ema_slow = None

        self.load_trade_stats()
        # Restore open trade if process died mid-trade (status.json)
        self.restore_open_trade_from_status()

        self.warmup_logged = False
        self.candles_evaluated = 0

        # Stale-feed guard state (see run_forward_test)
        self._last_price_mono = None
        self._last_stale_alert_mono = None
        # MT5 candle dedup watermark. This MUST be restored from status.json
        # *here*, before the save_status() calls at the end of __init__:
        # save_status() writes _mt5_last_candle_ts back out, so starting it at
        # None clobbered the persisted watermark with null before
        # run_mt5_test() ever read it -> the dedup floor came back 0 and the
        # restart re-played the boundary candle (re-logged to
        # forward_test_log.csv and free to re-enter a trade on it).
        self._mt5_last_candle_ts = None
        self.restore_mt5_candle_ts_from_status()

        # LIVE closed-bar watermark. Separate status.json key on purpose: a
        # live/demo pilot must never inherit or clobber the paper feed's
        # mt5_last_candle_ts (the two paths can run from different data dirs).
        self._live_last_bar_ts = None
        self.restore_live_bar_ts_from_status()

        # MT5 feed-health state (see mt5_feed_problem / run_mt5_test)
        self._mt5_feed_read_error = None      # last read_mt5_feed() failure, if any
        self._mt5_feed_problem_active = False  # already reported the current stall
        self._last_feed_problem_log_mono = None

        # Buy Funnel Counters
        self.hit_tested_floor = 0
        self.hit_valid_rejection = 0
        self.hit_held_support = 0
        self.hit_volume_confirmed = 0
        self.hit_trend_confirmed = 0
        self.hit_slope_confirmed = 0
        self.hit_price_near_ema = 0
        self.hit_all = 0

        # Sell Funnel Counters
        self.hit_sell_tested_ceiling = 0
        self.hit_sell_valid_rejection = 0
        self.hit_sell_held_resistance = 0
        self.hit_sell_trend_confirmed = 0
        self.hit_sell_slope_confirmed = 0
        self.hit_sell_price_near_ema = 0
        self.hit_sell_all = 0

        if TRADING_MODE == "LIVE":
            if not mt5.initialize():
                print(f"MT5 Initialize failed: {mt5.last_error()}")
                sys.exit(1)
            account = mt5.account_info()
            print(f"Connected to MT5 | Account: {account.login} | Balance: {account.balance} {account.currency}")
            mt5.symbol_select(SYMBOL, True)
        elif DATA_SOURCE == "MT5":
            # Simulated trading, but real broker data: the Wine sidecar
            # (tools/mt5_feed.py, same pattern as the mt5-balance alias)
            # publishes closed M1 candles to MT5_FEED_FILE.
            if os.path.isfile(MT5_FEED_FILE):
                print(f"MT5 feed file found: {MT5_FEED_FILE}")
            else:
                print(f"NOTE: {MT5_FEED_FILE} not found yet - is the mt5feed sidecar running? "
                      f"(WINEPREFIX=~/.mt5 xvfb-run wine C:/Python312/python.exe "
                      f"Z:/opt/gold/tools/mt5_feed.py)")
            self.load_history_from_csv()
            self.save_status()
        else:
            self.load_history_from_csv()
            self.save_status()

    def load_trade_stats(self):
        self.next_trade_num = 1
        self.wins = 0
        self.losses = 0
        self.be_exits = 0
        self.time_exits = 0
        self.balance = 500.00

        if not os.path.isfile(TRADES_LOG_PATH):
            prior_closed = 0
            if os.path.isfile(STATUS_FILE_PATH):
                try:
                    with open(STATUS_FILE_PATH) as f:
                        prior_closed = json.load(f).get("total_trades", 0) or 0
                except Exception:
                    pass
            if prior_closed:
                print(f"WARNING: trades.csv is MISSING but status.json shows {prior_closed} "
                      f"closed trades - balance/numbering will RESET to $500/#1!")
            else:
                print("No trades.csv found - starting fresh (balance $500)")
            return

        # Self-heal schema drift (e.g. pre-SELL header + 16-field SELL rows)
        migrate_trades_csv(TRADES_LOG_PATH)

        try:
            with open(TRADES_LOG_PATH, newline="") as f:
                reader = csv.DictReader(f)
                max_num = 0
                last_balance = None
                for row in reader:
                    try:
                        num = int(row.get("Trade_Num", 0) or 0)
                        if num > max_num:
                            max_num = num
                    except (ValueError, TypeError):
                        pass

                    reason = (row.get("Exit_Reason") or "").strip().upper()
                    if reason == "TP":
                        self.wins += 1
                    elif reason == "SL":
                        self.losses += 1
                    elif reason == "BE":
                        self.be_exits += 1
                    elif reason == "TIME":
                        self.time_exits += 1

                    try:
                        bal = float(row.get("Balance_After", 0) or 0)
                        if math.isfinite(bal):
                            last_balance = bal
                    except (ValueError, TypeError):
                        pass

                self.next_trade_num = max_num + 1
                if last_balance is not None:
                    self.balance = last_balance

            closed = self.wins + self.losses
            print(f"Loaded trade stats -> next_trade=#{self.next_trade_num} | "
                  f"closed={closed} ({self.wins}W/{self.losses}L) | balance=${self.balance:.2f}")
        except Exception as e:
            print(f"Failed to load trade stats: {e}")
            self.next_trade_num = 1
            self.wins = 0
            self.losses = 0
            self.be_exits = 0
            self.time_exits = 0
            self.balance = 500.00

    def restore_mt5_candle_ts_from_status(self):
        """Restore the MT5 candle dedup watermark from status.json.

        Called from __init__ BEFORE any save_status(), because save_status()
        re-publishes _mt5_last_candle_ts: without this restore the field was
        written back out as null on every boot and run_mt5_test() lost the
        previous session's watermark. The boundary candle was then re-accepted
        (ts <= 0 is never true), re-logged and re-traded - breaking the
        documented invariant that a restart never re-logs the boundary candle.

        Silent and non-fatal by design: a missing/corrupt status.json just
        means a fresh start (watermark None), same as before.
        """
        if not os.path.isfile(STATUS_FILE_PATH):
            return
        try:
            with open(STATUS_FILE_PATH) as f:
                ts = json.load(f).get("mt5_last_candle_ts")
            self._mt5_last_candle_ts = int(ts) if ts else None
        except Exception as e:
            print(f"Could not read status.json for MT5 candle-ts restore: {e}")
            return
        if self._mt5_last_candle_ts:
            print(f"Restored MT5 candle watermark -> "
                  f"{datetime.fromtimestamp(self._mt5_last_candle_ts, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC "
                  f"(restart will not re-play this candle)")

    def restore_live_bar_ts_from_status(self):
        """Restore the LIVE closed-bar dedup watermark (own key, fail-open)."""
        if not os.path.isfile(STATUS_FILE_PATH):
            return
        try:
            with open(STATUS_FILE_PATH) as f:
                ts = json.load(f).get("live_last_candle_ts")
            self._live_last_bar_ts = int(ts) if ts else None
        except Exception:
            self._live_last_bar_ts = None

    def restore_open_trade_from_status(self):
        """Restore open simulated trade from status.json after crash/restart."""
        if not os.path.isfile(STATUS_FILE_PATH):
            return
        try:
            with open(STATUS_FILE_PATH) as f:
                data = json.load(f)
        except Exception as e:
            print(f"Could not read status.json for open-trade restore: {e}")
            return

        if not data.get("trade_active"):
            return

        entry = data.get("entry_price")
        sl = data.get("stop_loss")
        tp = data.get("take_profit")
        if entry is None or sl is None or tp is None:
            print("status.json marks trade_active but missing entry/SL/TP - ignoring")
            return

        self.trade_active = True
        self.trade_type = data.get("trade_type", "BUY")
        self.entry_price = float(entry)
        self.stop_loss = float(sl)
        self.take_profit = float(tp)
        # Breakeven ratchet state survives restarts; if the flag disagrees
        # with the stored SL, the ratcheted (safer) level wins.
        self.be_armed = bool(data.get("be_armed", False))
        if self.be_armed:
            self.stop_loss = round(self.entry_price, 2)
        self.entry_time = data.get("entry_time") or utc_now_str()
        self.current_trade_num = data.get("current_trade_num")
        if self.current_trade_num is None:
            self.current_trade_num = max(1, self.next_trade_num - 1)
        # Restore next_trade_num too: after a restart-with-open-trade the CSV still
        # ends at the open trade's number - 1, so load_trade_stats() resets
        # next_trade_num to the open trade's own number and the NEXT trade reuses it
        # (duplicate #697, 2026-10-25). status.json carries next_trade_num; take it
        # when it is ahead of the CSV-derived value - never move the number backwards.
        stored_next = data.get("next_trade_num")
        if isinstance(stored_next, int) and stored_next > self.next_trade_num:
            self.next_trade_num = stored_next
        self.entry_rsi = data.get("entry_rsi")
        self.entry_atr = data.get("entry_atr")
        self.entry_wick_ratio = data.get("entry_wick_ratio")
        self.entry_ema_fast = data.get("entry_ema_fast")
        self.entry_ema_slow = data.get("entry_ema_slow")

        print(f"Restored OPEN {self.trade_type} trade #{self.current_trade_num} | "
              f"Entry=${self.entry_price:.2f} SL=${self.stop_loss:.2f} TP=${self.take_profit:.2f}")

    def load_history_from_csv(self):
        if not os.path.isfile(LOG_FILE_PATH):
            print("No existing log found. Starting fresh.")
            return
        print(f"Loading history from {LOG_FILE_PATH}...")
        try:
            rows = []
            with open(LOG_FILE_PATH, mode="r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            if not rows:
                return
            recent = rows[-EMA_SLOW:] if len(rows) > EMA_SLOW else rows
            print(f"Found {len(rows)} total rows -> using last {len(recent)}")
            for row in recent:
                try:
                    low = float(row["Low"])
                    high = float(row.get("High", low))
                    close = float(row["Close"])
                    vol_str = row.get("Volume", "1")
                    volume = float(vol_str) if vol_str not in ("Calculating", "", None) else 1.0
                    self.lows.append(low)
                    self.highs.append(high)
                    self.closes.append(close)
                    self.volumes.append(volume)
                    # Seed EMA50 history for the slope gate
                    ema50_str = row.get("EMA_50")
                    try:
                        if ema50_str not in ("Calculating", "", None):
                            self.ema50_history.append(float(ema50_str))
                    except (TypeError, ValueError):
                        pass
                    if self.prev_close is not None:
                        change = close - self.prev_close
                        self.rsi_gains.append(max(change, 0))
                        self.rsi_losses.append(max(-change, 0))
                        tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
                        self.tr_list.append(tr)
                    self.prev_close = close
                except Exception:
                    continue
            closes_list = list(self.closes)
            if len(closes_list) >= EMA_FAST:
                self.ema_fast = sum(closes_list[:EMA_FAST]) / EMA_FAST
                for price in closes_list[EMA_FAST:]:
                    self.ema_fast = (price * self.k_fast) + (self.ema_fast * (1 - self.k_fast))
            if len(closes_list) >= EMA_SLOW:
                self.ema_slow = sum(closes_list[:EMA_SLOW]) / EMA_SLOW
                for price in closes_list[EMA_SLOW:]:
                    self.ema_slow = (price * self.k_slow) + (self.ema_slow * (1 - self.k_slow))
            self.calculate_rsi()
            self.calculate_atr()
            print(f"Loaded {len(self.closes)} candles")
        except Exception as e:
            print(f"Failed to load history: {e}")

    def calculate_rsi(self):
        if len(self.rsi_gains) < RSI_PERIOD:
            self.rsi = None
            return
        avg_gain = sum(self.rsi_gains) / RSI_PERIOD
        avg_loss = sum(self.rsi_losses) / RSI_PERIOD
        self.rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

    def calculate_atr(self):
        if len(self.tr_list) < ATR_PERIOD:
            self.atr = None
            return
        self.atr = sum(self.tr_list) / ATR_PERIOD

    def update_indicators(self, high, low, close):
        if self.ema_fast is None:
            if len(self.closes) >= EMA_FAST:
                self.ema_fast = sum(list(self.closes)[-EMA_FAST:]) / EMA_FAST
        else:
            self.ema_fast = (close * self.k_fast) + (self.ema_fast * (1 - self.k_fast))
        if self.ema_slow is None:
            if len(self.closes) >= EMA_SLOW:
                self.ema_slow = sum(list(self.closes)[-EMA_SLOW:]) / EMA_SLOW
        else:
            self.ema_slow = (close * self.k_slow) + (self.ema_slow * (1 - self.k_slow))
        if self.prev_close is not None:
            change = close - self.prev_close
            self.rsi_gains.append(max(change, 0))
            self.rsi_losses.append(max(-change, 0))
            self.calculate_rsi()
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
            self.tr_list.append(tr)
            self.calculate_atr()
        self.prev_close = close

    def save_status(self):
        closed = self.wins + self.losses + self.be_exits + self.time_exits
        # win_rate is over decisive trades only; BE scratches and TIME exits are neutral
        decisive = self.wins + self.losses
        win_rate = (self.wins / decisive * 100) if decisive > 0 else 0.0
        active_trade = self.trade_active

        # Calculate daily losses count for circuit breaker visibility
        recent = load_recent_trades(50)
        daily_losses = get_daily_sl_count(recent)

        data = {
            "equity": round(self.balance, 2),
            "total_trades": closed,
            "next_trade_num": self.next_trade_num,
            "wins": self.wins,
            "losses": self.losses,
            "be_exits": self.be_exits,
            "time_exits": self.time_exits,
            "win_rate": round(win_rate, 1),
            "trade_active": active_trade,
            "trade_type": self.trade_type if active_trade else None,
            "daily_losses": daily_losses,
            "max_daily_losses": MAX_DAILY_LOSSES,
            "last_update": utc_now_str(),
            "mt5_last_candle_ts": self._mt5_last_candle_ts,
            "live_last_candle_ts": self._live_last_bar_ts,
            "rsi": round(self.rsi, 1) if self.rsi else None,
            "ema_fast": round(self.ema_fast, 2) if self.ema_fast else None,
            "ema_slow": round(self.ema_slow, 2) if self.ema_slow else None,
            "atr": round(self.atr, 2) if self.atr else None,
            "entry_price": round(self.entry_price, 2) if active_trade and self.entry_price else None,
            "stop_loss": round(self.stop_loss, 2) if active_trade and self.stop_loss else None,
            "take_profit": round(self.take_profit, 2) if active_trade and self.take_profit else None,
            "be_armed": self.be_armed if active_trade else None,
            "entry_time": self.entry_time if active_trade else None,
            "current_trade_num": self.current_trade_num if active_trade else None,
            "entry_rsi": round(self.entry_rsi, 1) if active_trade and self.entry_rsi is not None else None,
            "entry_atr": round(self.entry_atr, 2) if active_trade and self.entry_atr is not None else None,
            "entry_wick_ratio": self.entry_wick_ratio if active_trade else None,
            "entry_ema_fast": round(self.entry_ema_fast, 2) if active_trade and self.entry_ema_fast is not None else None,
            "entry_ema_slow": round(self.entry_ema_slow, 2) if active_trade and self.entry_ema_slow is not None else None,
            "funnel": {
                "candles_evaluated": self.candles_evaluated,
                "tested_floor": self.hit_tested_floor,
                "valid_rejection": self.hit_valid_rejection,
                "held_support": self.hit_held_support,
                "volume_confirmed": self.hit_volume_confirmed,
                "trend_confirmed": self.hit_trend_confirmed,
                "slope_confirmed": self.hit_slope_confirmed,
                "price_near_ema": self.hit_price_near_ema,
                "all_confirmed": self.hit_all,
                "sell_tested_ceiling": self.hit_sell_tested_ceiling,
                "sell_valid_rejection": self.hit_sell_valid_rejection,
                "sell_held_resistance": self.hit_sell_held_resistance,
                "sell_trend_confirmed": self.hit_sell_trend_confirmed,
                "sell_slope_confirmed": self.hit_sell_slope_confirmed,
                "sell_price_near_ema": self.hit_sell_price_near_ema,
                "sell_all_confirmed": self.hit_sell_all,
            },
        }
        try:
            with open(STATUS_FILE_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to write status.json: {e}")

    def send_telegram(self, text: str, kind: str = "trade"):
        """Send one Telegram message, unless its KIND is filtered out.

        Filtering is silent by design (a suppressed skip must not become a print
        flood instead); the engine still prints the skip line that matters and
        still writes every event to its CSV. See TELEGRAM_KINDS above.
        """
        if not notify_enabled(kind):
            return
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": str(TELEGRAM_CHAT_ID), "text": text, "parse_mode": "Markdown"},
                timeout=4,
            )
        except Exception as e:
            print(f"Telegram failed: {e}")

    def feed_stale_seconds(self, now_mono: float = None) -> float:
        """Seconds since the last price event (0.0 while the feed is fresh)."""
        if self._last_price_mono is None:
            return 0.0
        if now_mono is None:
            now_mono = time.monotonic()
        return max(0.0, now_mono - self._last_price_mono)

    def maybe_alert_stale_feed(self, stale_seconds: float, detail: str = None) -> bool:
        """Rate-limited Telegram alert for a stalled feed. True if it alerted.

        `detail` overrides the default Twelve Data wording so the MT5 path can
        say what actually died (2026-09-29: frozen feed file).
        """
        if self._last_stale_alert_mono is not None and \
                time.monotonic() - self._last_stale_alert_mono < STALE_ALERT_COOLDOWN_SECONDS:
            return False
        self._last_stale_alert_mono = time.monotonic()
        if detail:
            self.send_telegram(detail, kind="feed")
            return True
        self.send_telegram(
            f"⚠️ gold engine: no price ticks for {stale_seconds / 60:.0f} min — "
            f"stale-feed guard forced a WebSocket reconnect",
            kind="feed",
        )
        return True

    def feed_publisher_age_seconds(self) -> float:
        """Seconds since the MT5 sidecar last rewrote MT5_FEED_FILE (its
        heartbeat), or None if the file cannot be stat'ed.

        The sidecar republishes every poll (5 s) even on a closed market, so
        this tracks the *publisher*, not the market (see the constants block).
        """
        try:
            return max(0.0, time.time() - os.path.getmtime(MT5_FEED_FILE))
        except OSError:
            return None

    def mt5_feed_problem(self) -> str:
        """A short human reason when the MT5 feed looks dead, else None.

        Checked *before* the candle dedup in run_mt5_test on purpose: the dedup
        path `continue`s (the same closed candle is republished every poll), and
        the old guard sat below it, so a frozen feed file was never reported
        (2026-09-29: host reboot -> MT5 terminal stuck -> 6 h of silent
        starvation, zero journal lines, zero Telegram alerts).

        Three failure modes, in order of certainty:
          1. file missing / unreadable  -> sidecar never started or wrong path;
          2. publisher heartbeat stale  -> terminal down/logged out: the file
             stopped being rewritten (this fires even right after a restart,
             when no candle has been accepted yet and the price-event clock is
             still None);
          3. no closed candle accepted for > STALE_FEED_SECONDS *in market
             hours* while the publisher is alive -> feed stalled but terminal
             reachable.

        A closed market (weekend / daily break) is explicitly NOT a problem -
        the sidecar keeps the heartbeat fresh and is_market_quiet() suppresses
        (3) - and hard failures (1)/(2) are still reported then, because a
        dead publisher means no data when the market reopens.

        Call this right after read_mt5_feed() (as run_mt5_test does): (1) and
        the parse check below read the flag that call sets.
        """
        age = self.feed_publisher_age_seconds()
        if age is None:
            return (f"feed file {MT5_FEED_FILE} missing/unreadable"
                    f"{' (' + self._mt5_feed_read_error + ')' if self._mt5_feed_read_error else ''}"
                    " — is mt5feed running? wrong path?")
        if self._mt5_feed_read_error:
            return f"cannot parse {MT5_FEED_FILE}: {self._mt5_feed_read_error}"
        if age > MT5_FEED_PUBLISHER_STALE_SECONDS:
            return (f"sidecar stopped publishing {MT5_FEED_FILE} "
                    f"{age / 60:.0f} min ago — mt5feed dead or MT5 terminal not "
                    f"logged in (check: systemctl status mt5 mt5feed)")
        stale = self.feed_stale_seconds()
        if stale > STALE_FEED_SECONDS and not is_market_quiet():
            return f"no new closed candles for {stale / 60:.0f} min — feed stalled"
        return None

    def report_mt5_feed_problem(self, problem: str) -> bool:
        """Print (rate-limited) + Telegram-alert on a dead MT5 feed.

        Telegram keeps the 30-min cooldown and quiet-hours suppression of the
        Twelve Data guard (weekend peace); the journal print repeats every
        MT5_FEED_PROBLEM_LOG_COOLDOWN_SECONDS so the outage is visible in
        `journalctl -u goldbot` even when alerts are suppressed. The 3-hourly
        autosync digest is the always-on backstop.
        """
        self._mt5_feed_problem_active = True
        now = time.monotonic()
        if self._last_feed_problem_log_mono is None or \
                now - self._last_feed_problem_log_mono > MT5_FEED_PROBLEM_LOG_COOLDOWN_SECONDS:
            print(f"\nMT5 feed problem: {problem}", flush=True)
            self._last_feed_problem_log_mono = now
        if not is_market_quiet():
            return self.maybe_alert_stale_feed(
                0.0, detail=f"⚠️ gold engine: MT5 feed dead — {problem}")
        return False

    def report_mt5_feed_recovered(self, ts: int) -> bool:
        """One journal + Telegram line when the feed comes back after a stall."""
        if not self._mt5_feed_problem_active:
            return False
        self._mt5_feed_problem_active = False
        self._last_feed_problem_log_mono = None
        when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"\nMT5 feed recovered: candle @ {when} UTC", flush=True)
        self.send_telegram(f"✅ gold engine: MT5 feed recovered (candle @ {when} UTC)", kind="feed")
        return True

    def log_candle(self, timestamp, o, h, l, c, ratio, tick_count, vol_ma, dynamic_floor, ema_f, ema_s, tested, rejected, held, vol_conf, trend_conf, rsi_val, atr_val):
        file_exists = os.path.isfile(LOG_FILE_PATH)
        with open(LOG_FILE_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Timestamp", "Open", "High", "Low", "Close", "Wick_Ratio", "Volume", "Vol_MA",
                    "Vol_Confirmed", "Dynamic_Floor", "EMA_50", "EMA_200", "Trend_Confirmed",
                    "Tested_Floor", "Valid_Rejection", "Held_Floor", "RSI", "ATR",
                ],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "Timestamp": timestamp,
                "Open": f"{o:.2f}",
                "High": f"{h:.2f}",
                "Low": f"{l:.2f}",
                "Close": f"{c:.2f}",
                "Wick_Ratio": f"{ratio:.1%}",
                "Volume": f"{tick_count:.0f}",
                "Vol_MA": f"{vol_ma:.1f}" if vol_ma else "Calculating",
                "Vol_Confirmed": str(vol_conf),
                "Dynamic_Floor": f"{dynamic_floor:.2f}" if dynamic_floor else "Calculating",
                "EMA_50": f"{ema_f:.2f}" if ema_f else "Calculating",
                "EMA_200": f"{ema_s:.2f}" if ema_s else "Calculating",
                "Trend_Confirmed": str(trend_conf),
                "Tested_Floor": str(tested),
                "Valid_Rejection": str(rejected),
                "Held_Floor": str(held),
                "RSI": f"{rsi_val:.1f}" if rsi_val else "Calculating",
                "ATR": f"{atr_val:.2f}" if atr_val else "Calculating",
            })

    def log_trade(self, exit_price, exit_reason, profit):
        file_exists = os.path.isfile(TRADES_LOG_PATH)
        if file_exists:
            # Never append new-schema rows under an old-schema header
            # (that misaligns every field and blinds the risk gates - see
            # migrate_trades_csv). migrate_trades_csv is a no-op if current.
            migrate_trades_csv(TRADES_LOG_PATH)
        with open(TRADES_LOG_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price", "Stop_Loss", "Take_Profit",
                    "Exit_Price", "Exit_Reason", "Profit", "Balance_After", "RSI_At_Entry",
                    "ATR_At_Entry", "Wick_Ratio_At_Entry", "EMA50_At_Entry", "EMA200_At_Entry",
                ],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "Trade_Num": self.current_trade_num,
                "Trade_Type": self.trade_type,
                "Entry_Time": self.entry_time,
                "Exit_Time": utc_now_str(),
                "Entry_Price": f"{self.entry_price:.2f}",
                "Stop_Loss": f"{self.stop_loss:.2f}",
                "Take_Profit": f"{self.take_profit:.2f}",
                "Exit_Price": f"{exit_price:.2f}",
                "Exit_Reason": exit_reason,
                "Profit": f"{profit:.2f}",
                "Balance_After": f"{self.balance:.2f}",
                "RSI_At_Entry": f"{self.entry_rsi:.1f}" if self.entry_rsi is not None else "",
                "ATR_At_Entry": f"{self.entry_atr:.2f}" if self.entry_atr is not None else "",
                "Wick_Ratio_At_Entry": f"{self.entry_wick_ratio:.1%}" if self.entry_wick_ratio is not None else "",
                "EMA50_At_Entry": f"{self.entry_ema_fast:.2f}" if self.entry_ema_fast is not None else "",
                "EMA200_At_Entry": f"{self.entry_ema_slow:.2f}" if self.entry_ema_slow is not None else "",
            })

    def _arm_breakeven(self):
        """Ratchet the stop to entry once the trade is +BE_TRIGGER_R ahead.
        One-way: once armed it stays armed (and persists via save_status)."""
        self.be_armed = True
        self.stop_loss = round(self.entry_price, 2)
        print(f"🛡 BE stop armed for trade #{self.current_trade_num}: "
              f"SL -> entry ${self.stop_loss:.2f}")
        self.send_telegram(
            f"🛡 BE STOP ARMED (#{self.current_trade_num})\n"
            f"SL moved to entry: `${self.stop_loss:.2f}`",
            kind="exit",
        )
        self.save_status()

    def _maybe_arm_breakeven(self, price: float = None, h: float = None, l: float = None):
        """Arm the BE ratchet if unrealized profit >= BE_TRIGGER_R * initial risk.
        Tick path passes price=; candle path passes h=/l= (pessimistic SL-first
        ordering is preserved because arming happens before the SL check)."""
        if not self.trade_active or self.be_armed:
            return
        risk = abs(self.entry_price - self.stop_loss)
        if risk <= 0:
            return
        if price is not None:
            gain = (price - self.entry_price) if self.trade_type == "BUY" else (self.entry_price - price)
        elif self.trade_type == "BUY":
            gain = (h - self.entry_price) if h is not None else 0.0
        else:
            gain = (self.entry_price - l) if l is not None else 0.0
        if gain >= BE_TRIGGER_R * risk - 1e-9:  # epsilon: exact-boundary float dust
            self._arm_breakeven()

    def _minutes_in_trade(self, now: datetime = None):
        """Wall-clock minutes since entry, or None if unknown/unparseable."""
        if not self.trade_active or not self.entry_time:
            return None
        try:
            entry_dt = datetime.strptime(self.entry_time, "%Y-%m-%d %H:%M:%S")
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        return (now - entry_dt).total_seconds() / 60.0

    def _pnl(self, price: float) -> float:
        """P&L for the active trade at `price`, scaled by the sized lot (BUY/SELL aware)."""
        raw = (price - self.entry_price) if self.trade_type == "BUY" else (self.entry_price - price)
        return raw * getattr(self, "pnl_scale", 1.0)

    def _maybe_time_stop(self, price: float, now: datetime = None) -> bool:
        """Max-hold time stop: close at market once the trade is older than
        MAX_HOLD_MINUTES. Returns True if it exited. Deliberately neutral:
        reason TIME is P&L-signed (balance books it) but excluded from
        decisive win-rate math and from the SL streak / daily breaker, like BE.
        Callers check price exits FIRST, so a simultaneous TP/SL wins."""
        if not self.trade_active:
            return False
        held = self._minutes_in_trade(now=now)
        if held is None or held < MAX_HOLD_MINUTES:
            return False
        profit = self._pnl(price)
        self.balance += profit
        self.time_exits += 1
        self.trade_active = False
        self.be_armed = False
        self.log_trade(exit_price=price, exit_reason="TIME", profit=profit)
        self.send_telegram(
            f"\u23f1 TIME STOP ({self.trade_type} #{self.current_trade_num})\n"
            f"Held {held:.0f} min (>{MAX_HOLD_MINUTES}) | Exit: `${price:.2f}` ({profit:+.2f})\n"
            f"Equity: `${self.balance:.2f}`",
            kind="exit",
        )
        self.save_status()
        return True

    def _validate_position_prices(self):
        """Fail closed on corrupt paper positions; never book an exit at zero.

        Keep the evidence/state intact for operator reconciliation rather than
        silently clearing an unknown position or manufacturing a ledger repair.
        """
        prices = (self.entry_price, self.stop_loss, self.take_profit)
        if (self.trade_type not in ("BUY", "SELL")
                or any(not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0
                       for p in prices)
                or (self.trade_type == "BUY" and not
                    self.stop_loss <= self.entry_price < self.take_profit)
                or (self.trade_type == "SELL" and not
                    self.take_profit < self.entry_price <= self.stop_loss)):
            raise ValueError("Invalid paper position geometry; pause engine and reconcile status/ledger")

    def resolve_open_trade_on_candle(self, o: float, h: float, l: float, c: float):
        """Forward-test exit resolution for candle-driven data sources
        (MT5 sidecar): there are no tick events, so an open simulated
        position must be checked against the candle range BEFORE evaluating
        new entries. Pessimistic intra-candle assumption: if both SL and TP
        fall inside the range, the SL is assumed to have been hit first.
        """
        if not self.trade_active:
            return
        self._validate_position_prices()
        self._maybe_arm_breakeven(h=h, l=l)
        if self.trade_type == "BUY":
            if l <= self.stop_loss:
                self.check_position(self.stop_loss)
            elif h >= self.take_profit:
                self.check_position(self.take_profit)
        else:
            if h >= self.stop_loss:
                self.check_position(self.stop_loss)
            elif l <= self.take_profit:
                self.check_position(self.take_profit)
        # Price exits above take priority; the time stop only binds when the
        # candle touched neither level. Exit at the close (first price we see).
        if self.trade_active:
            self._maybe_time_stop(c)

    def evaluate_candle(self, o, h, l, c, tick_count):
        candle_range = h - l
        if candle_range <= 0:
            # Degenerate/flat candle: still consumed from the feed, so persist
            # the watermark before bailing. Otherwise the caller's advanced
            # last_ts never reaches status.json (its only writer for a
            # no-trade candle is the save_status() further down) and a restart
            # replays this candle plus every candle after it.
            self.save_status()
            return
        
        self.candles_evaluated += 1

        # Calculate wicks
        body_bottom = min(o, c)
        body_top = max(o, c)
        lower_wick = body_bottom - l
        upper_wick = h - body_top
        
        lower_wick_ratio = lower_wick / candle_range
        upper_wick_ratio = upper_wick / candle_range
        
        valid_buy_rejection = lower_wick_ratio >= WICK_RATIO_TARGET
        valid_sell_rejection = upper_wick_ratio >= WICK_RATIO_TARGET

        dynamic_floor, dynamic_ceiling, volume_ma = None, None, None
        tested_floor, held_support = False, False
        tested_ceiling, held_resistance = False, False
        volume_confirmed = False

        if len(self.closes) >= LOOKBACK_PERIOD:
            dynamic_floor = min(list(self.lows)[-LOOKBACK_PERIOD:])
            dynamic_ceiling = max(list(self.highs)[-LOOKBACK_PERIOD:])
            volume_ma = sum(list(self.volumes)[-LOOKBACK_PERIOD:]) / LOOKBACK_PERIOD
            
            # Buy support conditions
            tested_floor = l <= (dynamic_floor * (1 + FLOOR_BUFFER_PCT))
            held_support = c > dynamic_floor

            # Sell resistance conditions
            tested_ceiling = h >= (dynamic_ceiling * (1 - FLOOR_BUFFER_PCT))
            held_resistance = c < dynamic_ceiling

            volume_confirmed = tick_count >= (volume_ma * VOLUME_SPIKE_MULTIPLIER) if volume_ma else True

        # Trend evaluations
        if self.ema_fast is not None and self.ema_slow is not None:
            buy_trend_confirmed = self.ema_fast > self.ema_slow
            sell_trend_confirmed = self.ema_fast < self.ema_slow
        elif self.ema_fast is not None:
            buy_trend_confirmed = c > self.ema_fast
            sell_trend_confirmed = c < self.ema_fast
        else:
            buy_trend_confirmed = False
            sell_trend_confirmed = False

        if len(self.closes) < EMA_SLOW:
            if not self.warmup_logged or len(self.closes) % 30 == 0:
                print(f"Warming up... {len(self.closes)}/{EMA_SLOW}")
                self.warmup_logged = True
        else:
            print(
                f"Floor:${dynamic_floor:.2f} Ceil:${dynamic_ceiling:.2f} | EMA50:${self.ema_fast:.2f} EMA200:${self.ema_slow:.2f} "
                f"| RSI:{self.rsi} ATR:{self.atr} | C:${c:.2f}"
            )
            print(
                f"   [BUY] Tested:{tested_floor} | Rej:{valid_buy_rejection} ({lower_wick_ratio:.0%}) | Held:{held_support} | Trend:{buy_trend_confirmed}"
            )
            print(
                f"   [SELL] Tested:{tested_ceiling} | Rej:{valid_sell_rejection} ({upper_wick_ratio:.0%}) | Held:{held_resistance} | Trend:{sell_trend_confirmed}"
            )

        ts = utc_now_str()
        self.log_candle(
            ts, o, h, l, c, lower_wick_ratio, tick_count, volume_ma, dynamic_floor,
            self.ema_fast, self.ema_slow, tested_floor, valid_buy_rejection, held_support,
            volume_confirmed, buy_trend_confirmed, self.rsi, self.atr,
        )
        self.lows.append(l)
        self.highs.append(h)
        self.volumes.append(tick_count)
        self.closes.append(c)
        self.update_indicators(h, l, c)
        self.save_status()

        # --- Regime gates (Slope & Price Proximity) ---
        buy_slope_confirmed = False
        sell_slope_confirmed = False
        if self.ema_fast is not None and len(self.ema50_history) >= EMA_SLOPE_LOOKBACK:
            buy_slope_confirmed = self.ema_fast > self.ema50_history[-EMA_SLOPE_LOOKBACK]
            sell_slope_confirmed = self.ema_fast < self.ema50_history[-EMA_SLOPE_LOOKBACK]
        if self.ema_fast is not None:
            self.ema50_history.append(self.ema_fast)

        # Proximity to EMA50 (prevent buying collapsed candles or selling spiked candles)
        buy_price_near_ema = False
        sell_price_near_ema = False
        if self.ema_fast is not None and self.atr is not None:
            buy_price_near_ema = c >= (self.ema_fast - (self.atr * MAX_BELOW_EMA_ATR))
            sell_price_near_ema = c <= (self.ema_fast + (self.atr * MAX_BELOW_EMA_ATR))

        vol_ok = volume_confirmed if REQUIRE_VOLUME_CONFIRM else True
        atr_ok = (self.atr is not None and self.atr > MIN_ATR)

        # Long checks
        buy_trend_ok = buy_trend_confirmed if REQUIRE_TREND_CONFIRM else True
        buy_slope_ok = buy_slope_confirmed if REQUIRE_EMA_SLOPE else True
        buy_rsi_ok = (self.rsi is not None and RSI_MIN < self.rsi < RSI_MAX)

        # Short checks (symmetric bounds)
        sell_trend_ok = sell_trend_confirmed if REQUIRE_TREND_CONFIRM else True
        sell_slope_ok = sell_slope_confirmed if REQUIRE_EMA_SLOPE else True
        sell_rsi_ok = (self.rsi is not None and (100.0 - RSI_MAX) < self.rsi < (100.0 - RSI_MIN))

        in_trade = self.trade_active
        if TRADING_MODE == "LIVE":
            positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_NUMBER)
            in_trade = (positions is not None and len(positions) > 0)

        # Spread for the minimum-spread filter (LIVE only; paper has no spread feed)
        live_spread_points = None
        if TRADING_MODE == "LIVE":
            try:
                _tk = mt5.symbol_info_tick(SYMBOL)
                live_spread_points = _tk.spread if _tk else None
            except Exception:
                live_spread_points = None

        # Funnel tracking
        if dynamic_floor is not None:
            if tested_floor:
                self.hit_tested_floor += 1
            if valid_buy_rejection:
                self.hit_valid_rejection += 1
            if held_support:
                self.hit_held_support += 1
            if volume_confirmed:
                self.hit_volume_confirmed += 1
            if buy_trend_confirmed:
                self.hit_trend_confirmed += 1
            if buy_slope_ok:
                self.hit_slope_confirmed += 1
            if buy_price_near_ema:
                self.hit_price_near_ema += 1

            if tested_ceiling:
                self.hit_sell_tested_ceiling += 1
            if valid_sell_rejection:
                self.hit_sell_valid_rejection += 1
            if held_resistance:
                self.hit_sell_held_resistance += 1
            if sell_trend_confirmed:
                self.hit_sell_trend_confirmed += 1
            if sell_slope_ok:
                self.hit_sell_slope_confirmed += 1
            if sell_price_near_ema:
                self.hit_sell_price_near_ema += 1

        buy_signal = (
            dynamic_floor is not None
            and self.ema_slow is not None
            and self.atr is not None
            and tested_floor
            and valid_buy_rejection
            and held_support
            and vol_ok
            and buy_trend_ok
            and buy_slope_ok
            and buy_price_near_ema
            and buy_rsi_ok
            and atr_ok
            and not in_trade
        )

        sell_signal = (
            dynamic_ceiling is not None
            and self.ema_slow is not None
            and self.atr is not None
            and tested_ceiling
            and valid_sell_rejection
            and held_resistance
            and vol_ok
            and sell_trend_ok
            and sell_slope_ok
            and sell_price_near_ema
            and sell_rsi_ok
            and atr_ok
            and not in_trade
        )

        if buy_signal:
            self.hit_all += 1
            allow, reason = should_take_trade(
                current_atr=self.atr,
                current_price=c,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                side="BUY",
                current_spread_points=live_spread_points,
            )

            if not allow:
                msg = (
                    f"BUY SETUP SKIPPED\nReason: `{reason}`\n"
                    f"Price: `${c:.2f}` | RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`"
                )
                self.send_telegram(msg, kind="skip")
                print(f"\nTrade skipped -> {reason}\n")
                return

            if TRADING_MODE == "LIVE":
                self.execute_live_trade("BUY", c, lower_wick_ratio, ts, level=dynamic_floor)
            else:
                self.execute_simulated_trade("BUY", c, lower_wick_ratio, ts, level=dynamic_floor)

        elif sell_signal:
            self.hit_sell_all += 1
            allow, reason = should_take_trade(
                current_atr=self.atr,
                current_price=c,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                side="SELL",
                current_spread_points=live_spread_points,
            )

            if not allow:
                msg = (
                    f"SELL SETUP SKIPPED\nReason: `{reason}`\n"
                    f"Price: `${c:.2f}` | RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`"
                )
                self.send_telegram(msg, kind="skip")
                print(f"\nTrade skipped -> {reason}\n")
                return

            if TRADING_MODE == "LIVE":
                self.execute_live_trade("SELL", c, upper_wick_ratio, ts, level=dynamic_ceiling)
            else:
                self.execute_simulated_trade("SELL", c, upper_wick_ratio, ts, level=dynamic_ceiling)

    def structural_risk(self, direction: str, entry: float, atr: float, level) -> float:
        """Stop distance in $: the ATR floor, or further if the level demands it.

        `level` is the 20-bar floor (BUY) / ceiling (SELL) that the rejection gate was
        measured against, or None when history is too short. Returns ATR_SL_MULT * atr
        unchanged when level is None or the ATR stop already clears the level by
        SL_CLEAR_ATR, so trades taken right at the level keep the old geometry.
        """
        risk = atr * ATR_SL_MULT
        if level and atr > 0:
            beyond = abs(entry - level) + SL_CLEAR_ATR * atr
            if beyond > risk:
                risk = beyond
        return risk

    def size_lots(self, stop_usd: float):
        """Target lots for a RISK_PCT-of-balance stop, or None when the required lot
        is below the broker volume_min (structural dead-end at this balance -> SKIP).
        R-invariant where it does apply: R = P&L / $risk scales with lots.
        LIVE only (2026-10-17 correction): the paper/forward test has no broker account to
        size off, so it keeps the fixed LOT_SIZE. Sizing the paper book off its own ledger
        balance did NOT merely refuse dead-ends - replayed on the struct-stop era (n=127) it
        skipped 76% of setups on the era's rolling balance and 84-91% at $180/$151, and at
        the $500 ledger start it would have chosen 0.02 lots on 16/127 (128/449 in the
        0.75R book). That is a flow stop and a confound for the open struct-stop window
        (§6.1), not an R-invariant no-op. The %-risk rule belongs to the live path."""
        if stop_usd is None or stop_usd <= 0:
            return None
        base = getattr(self, "account_balance", None)
        if not base:
            return LOT_SIZE
        risk_usd = base * RISK_PCT / 100.0
        lots = risk_usd / (stop_usd * CONTRACT_SIZE)
        lots = round(lots / VOLUME_STEP) * VOLUME_STEP
        return lots if lots >= VOLUME_MIN else None

    def execute_live_trade(self, direction: str, c: float, wick_ratio: float, ts: str, level=None):
        # LIVE arming / kill switch (2026-10-26): checked AGAIN here, not only in
        # run_live, so no code path can place a real order while disarmed.
        if not live_armed():
            print("\nLIVE ORDER BLOCKED -> GOLD_LIVE_ARMED != 1 or LIVE_HALT present\n")
            self.send_telegram(
                f"LIVE ORDER BLOCKED\nLive execution is not armed ({LIVE_ARM_ENV} != 1 "
                "or kill-switch file present)", kind="risk")
            return
        # Daily-closure gap guard (registered 2026-10-25) — same rule as the paper path:
        # no NEW entry inside the window before the broker's daily break.
        _guard = self.entry_guard_reason(self._guard_now())
        if _guard:
            print(f"\nTrade skipped -> {_guard}\n")
            self.send_telegram(
                f"{direction} SETUP SKIPPED\nReason: `{_guard}`\n"
                f"Price: `${c:.2f}`", kind="skip")
            return
        print(f"\nALL CONDITIONS MET! PREPARING LIVE {direction} ORDER...")
        symbol_info = mt5.symbol_info(SYMBOL)
        if symbol_info is None:
            print("LIVE order skipped -> symbol_info() unavailable, no point/filling data")
            self.send_telegram("LIVE ORDER SKIPPED\nsymbol_info() unavailable - no point/filling data",
                              kind="risk")
            return
        # The captured XM spec reports filling_mode = 2 (IOC only). Sending the
        # old hard-coded ORDER_FILLING_FOK would be rejected on every real order.
        filling = resolve_order_filling(mt5, symbol_info)
        if filling is None:
            print("LIVE order skipped -> no supported FOK/IOC filling policy for this symbol")
            self.send_telegram(
                "LIVE ORDER SKIPPED\nNo supported FOK/IOC order filling policy "
                f"(filling_mode={getattr(symbol_info, 'filling_mode', None)})", kind="risk")
            return
        point = symbol_info.point
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            print("Failed to get tick data")
            return

        # Live SL/TP mirror the paper engine: risk is the ATR floor, pushed out when
        # the 20-bar level the entry was anchored to sits further away (structural_risk).
        # Distance is measured from the ORDER price, which is the fill, not the bar close.
        if direction == "BUY":
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
            risk = self.structural_risk(direction, price, self.atr, level)
            sl_price = price - risk
            tp_price = price + RR_TARGET * risk
        else:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
            risk = self.structural_risk(direction, price, self.atr, level)
            sl_price = price + risk
            tp_price = price - RR_TARGET * risk

        # --- Risk sizer (live): size lots for RISK_PCT, refuse if below volume_min ---
        info = mt5.account_info()
        if info is None:
            # Never size a real order off the paper ledger (2026-10-17 correction).
            print("\nLIVE order skipped -> account_info() unavailable, no risk base\n")
            self.send_telegram("LIVE ORDER SKIPPED\naccount_info() unavailable - no risk base",
                              kind="risk")
            return
        self.account_balance = info.balance
        self.trade_lots = self.size_lots(risk)
        if self.trade_lots is None:
            print(f"\nLIVE order skipped -> {RISK_PCT}% risk needs <{VOLUME_MIN} lot at stop ${risk:.2f}\n")
            self.send_telegram(
                f"LIVE POSITION SIZE SKIPPED\nStop ${risk:.2f} needs <{VOLUME_MIN} lot for {RISK_PCT}% risk",
                kind="risk")
            return
        self.pnl_scale = self.trade_lots * CONTRACT_SIZE

        sl_price = round(sl_price / point) * point
        tp_price = round(tp_price / point) * point

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": self.trade_lots,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": MAGIC_NUMBER,
            "comment": f"Gold Engine Live {direction}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        print(f"   Sending: {direction} {self.trade_lots} {SYMBOL} @ {price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}")

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order failed: {result.retcode} - {result.comment}")
            self.send_telegram(f"ORDER FAILED\nCode: {result.retcode}\nMsg: {result.comment}",
                              kind="risk")
        else:
            self.current_trade_num = self.next_trade_num
            self.next_trade_num += 1
            self.be_armed = False
            print(f"ORDER SUCCESS! Ticket: {result.order} | Trade #{self.current_trade_num}")
            self.send_telegram(
                f"LIVE GOLD {direction} EXECUTED\n"
                f"Ticket: `{result.order}` | Trade #{self.current_trade_num}\n"
                f"Entry: `${price:.2f}`\n"
                f"SL: `${sl_price:.2f}`\n"
                f"TP: `${tp_price:.2f}`",
                kind="trade",
            )

    def _guard_now(self):
        """Current UTC time for the guard; `guard_now_override` makes it testable."""
        override = getattr(self, "guard_now_override", None)
        if override is not None:
            return override
        return datetime.now(timezone.utc)

    def guard_closure(self, now_utc: datetime = None):
        """The daily-break signature, re-derived at most once per UTC day.

        Deriving it walks the whole price log, so it is cached per calendar day rather
        than per candle. Returns None when the signature is not observable (fail-open).
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        today = now_utc.date()
        if self._guard_closure_date != today or self._guard_closure_path != LOG_FILE_PATH:
            self._guard_closure = derive_daily_closure(LOG_FILE_PATH)
            self._guard_closure_date = today
            self._guard_closure_path = LOG_FILE_PATH
            if self._guard_closure:
                ct, rt = self._guard_closure
                print(f"Gap guard: daily break {ct[0]:02d}:{ct[1]:02d} -> "
                      f"{rt[0]:02d}:{rt[1]:02d} UTC (entries blocked "
                      f"{GUARD_CUTOFF_MIN} min before the close)")
            else:
                print("Gap guard: no daily-break signature in the price log yet "
                      "- entries not blocked (fail-open)")
        return self._guard_closure

    def entry_guard_reason(self, now_utc: datetime = None):
        """None when a new entry is allowed, else the skip reason (gap guard).

        Registered scope (2026-10-25): NEW ENTRIES only, in the
        [daily_close - GUARD_CUTOFF_MIN, daily_reopen) window. Open positions are not
        touched. See docs/PREREG-2026-10-25-gap-guard-daily-closure.md.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        closure = self.guard_closure(now_utc)
        if guard_blocks_entry(now_utc, closure):
            ct, rt = closure
            return (f"Gap guard: within {GUARD_CUTOFF_MIN} min of the daily close "
                    f"({ct[0]:02d}:{ct[1]:02d} -> {rt[0]:02d}:{rt[1]:02d} UTC) - "
                    f"no new entry rides the market closure")
        return None

    def execute_simulated_trade(self, direction: str, c: float, wick_ratio: float, ts: str, level=None):
        # Daily-closure gap guard: refuse BEFORE a trade number is consumed, so a
        # suppressed setup burns nothing (same rule as the sizer refusal below).
        _guard = self.entry_guard_reason(self._guard_now())
        if _guard:
            print(f"\nTrade skipped -> {_guard}\n")
            self.send_telegram(
                f"{direction} SETUP SKIPPED\nReason: `{_guard}`\n"
                f"Price: `${c:.2f}` | RSI: `{self.rsi if self.rsi is not None else 0:.1f}` "
                f"| ATR: `{self.atr if self.atr is not None else 0:.2f}`",
                kind="skip")
            return
        # risk = ATR floor, pushed out beyond the tested 20-bar level when that level
        # sits further away (see structural_risk / SL_CLEAR_ATR). TP keeps the 1:1.5
        # ratio against the ACTUAL risk, so the BE ratchet trigger (0.75R) and every
        # R-denominated stat mean the same thing as before.
        risk = self.structural_risk(direction, c, self.atr, level)
        # --- Risk sizer: enforce RISK_PCT of balance; refuse if below volume_min ---
        self.trade_lots = self.size_lots(risk)
        if self.trade_lots is None:
            # Refuse BEFORE arming anything: a skipped setup must leave no position, no
            # trade number and no stale SL/TP behind (2026-10-17 correction).
            print(f"\nTrade skipped -> {RISK_PCT}% risk needs <{VOLUME_MIN} lot at stop ${risk:.2f} "
                  f"(structural dead-end at this balance) - not taken\n")
            self.send_telegram(
                f"POSITION SIZE SKIPPED\nStop ${risk:.2f} needs <{VOLUME_MIN} lot for {RISK_PCT}% risk",
                kind="risk")
            return
        # --- commit the trade only now that it is known to be takeable ---
        # (2026-10-17 correction: the sizer check used to sit AFTER this block, and its
        # refuse branch returned without clearing trade_active/trade_type/entry_price -
        # leaving the previous trade's SL/TP armed against the new entry price. The next
        # published candle resolved it and logged a trade that was never taken.)
        self.trade_active = True
        self.trade_type = direction
        self.current_trade_num = self.next_trade_num
        self.next_trade_num += 1
        self.be_armed = False  # fresh trade: ratchet re-arms at +BE_TRIGGER_R

        self.entry_price = c
        self.pnl_scale = self.trade_lots * CONTRACT_SIZE
        self.structural_stop_bound = risk > self.atr * ATR_SL_MULT + 1e-9
        if direction == "BUY":
            self.stop_loss = c - risk
            self.take_profit = c + RR_TARGET * risk
        else:
            self.stop_loss = c + risk
            self.take_profit = c - RR_TARGET * risk

        self.entry_time = ts
        self.entry_rsi = self.rsi
        self.entry_atr = self.atr
        self.entry_wick_ratio = wick_ratio
        self.entry_ema_fast = self.ema_fast
        self.entry_ema_slow = self.ema_slow

        bound = (f" (level-bound: {'floor' if direction == 'BUY' else 'ceiling'} "
                 f"${level:.2f} +{SL_CLEAR_ATR:.2f}ATR)") if level and self.structural_stop_bound else ""
        msg = (
            f"GOLD {direction} SETUP #{self.current_trade_num}\n"
            f"Entry: `${self.entry_price:.2f}`\n"
            f"RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`\n"
            f"SL: `${self.stop_loss:.2f}`{bound}\n"
            f"TP: `${self.take_profit:.2f}`"
        )
        self.send_telegram(msg, kind="trade")
        print(f"\nAlert sent -> {direction} Trade #{self.current_trade_num}\n")
        self.save_status()

    def check_position(self, price: float):
        if not self.trade_active:
            return

        self._validate_position_prices()
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid paper exit price; refusing to book P&L")
        self._maybe_arm_breakeven(price=price)

        if self.trade_type == "BUY":
            if price >= self.take_profit:
                profit = self._pnl(price)
                self.balance += profit
                self.wins += 1
                self.trade_active = False
                self.be_armed = False
                self.log_trade(exit_price=price, exit_reason="TP", profit=profit)
                self.send_telegram(
                    f"TP HIT (BUY #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (+${profit:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
               ,
                    kind="exit",
                )
                self.save_status()
            elif price <= self.stop_loss:
                loss = -self._pnl(price)
                self.balance -= loss
                was_be = self.be_armed
                if was_be:
                    self.be_exits += 1   # scratch: not a loss, not a win
                else:
                    self.losses += 1
                self.trade_active = False
                self.be_armed = False
                reason = "BE" if was_be else "SL"
                self.log_trade(exit_price=price, exit_reason=reason, profit=-loss)
                self.send_telegram(
                    f"{'🛡 BE EXIT' if was_be else 'SL HIT'} (BUY #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (-${loss:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
               ,
                    kind="exit",
                )
                self.save_status()

        elif self.trade_type == "SELL":
            if price <= self.take_profit:
                profit = self._pnl(price)
                self.balance += profit
                self.wins += 1
                self.trade_active = False
                self.be_armed = False
                self.log_trade(exit_price=price, exit_reason="TP", profit=profit)
                self.send_telegram(
                    f"TP HIT (SELL #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (+${profit:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
               ,
                    kind="exit",
                )
                self.save_status()
            elif price >= self.stop_loss:
                loss = -self._pnl(price)
                self.balance -= loss
                was_be = self.be_armed
                if was_be:
                    self.be_exits += 1   # scratch: not a loss, not a win
                else:
                    self.losses += 1
                self.trade_active = False
                self.be_armed = False
                reason = "BE" if was_be else "SL"
                self.log_trade(exit_price=price, exit_reason=reason, profit=-loss)
                self.send_telegram(
                    f"{'🛡 BE EXIT' if was_be else 'SL HIT'} (SELL #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (-${loss:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
               ,
                    kind="exit",
                )
                self.save_status()

        # Max-hold time stop (tick path): price exits above take priority; if
        # the trade is still open and older than MAX_HOLD_MINUTES, close here.
        if self.trade_active:
            self._maybe_time_stop(price)

    def aggregate_tick(self, price: float):
        minute_now = int(datetime.now(timezone.utc).timestamp() // 60)
        if self.current_minute is None:
            self.current_minute = minute_now
        if minute_now != self.current_minute:
            if self.tick_pool:
                o, h, l, c = self.tick_pool[0], max(self.tick_pool), min(self.tick_pool), self.tick_pool[-1]
                self.evaluate_candle(o, h, l, c, len(self.tick_pool))
            self.tick_pool.clear()
            self.current_minute = minute_now
        self.tick_pool.append(price)

    def on_event(self, event):
        if event.get("event") == "price":
            self._last_price_mono = time.monotonic()
            price = float(event["price"])
            self.check_position(price)
            self.aggregate_tick(price)

    def run_live(self):
        """LIVE loop: CLOSED M1 bars only, deduplicated by candle timestamp.

        2026-10-26 hardening (LIVE path only; paper behaviour unchanged):
          * position 0 is the still-FORMING bar. Evaluating it made every live
            signal differ from the paper engine (which only ever sees closed
            bars) and re-evaluated the same minute repeatedly. Use position 1.
          * `mt5_next_candle` + a status.json watermark (live_last_candle_ts)
            means each closed bar is evaluated exactly once, including across
            a restart — the same invariant the MT5 paper feed already has.
          * `live_armed()` is checked every loop; a kill-switch file or an
            unarmed process stops NEW exposure (execute_live_trade re-checks).
          * Known divergence still open: broker-side BE ratchet / TIME stop,
            deal-level reconciliation and demo-account evidence. See
            tools/live_readiness.py — this loop is NOT live-ready on its own.
        """
        print("Gold Engine LIVE starting... (closed M1 bars only)")
        if not live_armed():
            print(f"LIVE NOT ARMED: {LIVE_ARM_ENV} != 1 or {LIVE_HALT_FILE} exists. "
                  "Bars will be read but NO real order can be placed.")
        last_ts = self._live_last_bar_ts or 0
        if last_ts:
            print(f"Resuming LIVE after bar ts={last_ts} "
                  f"({datetime.fromtimestamp(last_ts, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC)")
        candles_fetched = 0
        while True:
            try:
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
                candle = self.mt5_next_candle(rates, last_ts)
                if candle is None:
                    time.sleep(5)
                    continue
                ts, o, h, l, c, vol = candle
                last_ts = ts
                self._live_last_bar_ts = ts
                self.evaluate_candle(o, h, l, c, vol)
                candles_fetched += 1
                if candles_fetched % 10 == 1:
                    print(
                        f"Heartbeat: closed candle @ "
                        f"{datetime.fromtimestamp(ts, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC "
                        f"| Close: {c} | armed: {live_armed()}"
                    )
                time.sleep(5)
            except KeyboardInterrupt:
                print("\nShutting down...")
                mt5.shutdown()
                break
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(10)

    def read_mt5_feed(self):
        """Read the latest closed M1 candle published by tools/mt5_feed.py
        (Wine sidecar), normalized to the mt5 rate-dict shape, or None if the
        file is missing/unreadable. Records the failure reason in
        `_mt5_feed_read_error` for mt5_feed_problem().
        """
        try:
            with open(MT5_FEED_FILE) as f:
                d = json.load(f)
            rates = [{
                "time": int(d["ts"]),
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "tick_volume": int(d["tick_volume"]),
            }]
            self._mt5_feed_read_error = None
            return rates
        except Exception as e:
            self._mt5_feed_read_error = f"{type(e).__name__}: {e}"
            return None

    def mt5_next_candle(self, rates, last_ts):
        """Return (ts, o, h, l, c, tick_volume) if `rates` holds a closed M1
        candle newer than last_ts, else None. Dedup guard: a restart must
        never re-log the candle the previous session already wrote."""
        ts = latest_closed_candle_ts(rates)
        if ts is None or ts <= last_ts:
            return None
        r = rates[0]
        return (ts, float(r["open"]), float(r["high"]), float(r["low"]),
                float(r["close"]), int(r["tick_volume"]))

    def run_mt5_test(self):
        """Forward test fed by the Wine MT5 sidecar's closed M1 candles.

        Same strategy/risk code as run_forward_test(), but the data source is
        the broker feed (tools/mt5_feed.py publishes MT5_FEED_FILE, immune to
        Twelve Data plan / WS-trial limits). One candle row per closed minute,
        deduplicated by candle timestamp.
        """
        print("Gold Engine FORWARD TEST (MT5 feed) starting...")
        # Dedup floor. __init__ already restored the watermark from status.json
        # (restore_mt5_candle_ts_from_status); prefer that in-memory value over
        # a second read of the file, which __init__'s own save_status() has
        # just rewritten. Same value when the restore worked, but this no
        # longer depends on file read/write ordering.
        last_ts = self._mt5_last_candle_ts or 0
        try:
            with open(STATUS_FILE_PATH) as f:
                last_ts = max(last_ts, int(json.load(f).get("mt5_last_candle_ts") or 0))
        except Exception:
            pass
        if last_ts:
            print(f"Resuming after candle ts={last_ts} "
                  f"({datetime.fromtimestamp(last_ts, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC) - "
                  f"that candle and earlier will not be re-logged")
        try:
            while True:
                rates = self.read_mt5_feed()

                # Feed-health check FIRST: it must also run on the dedup path
                # below (a frozen file republishes the same candle forever, and
                # the old guard sat *after* that `continue`, so a dead feed was
                # never logged or alerted - 2026-09-29 incident).
                problem = self.mt5_feed_problem()
                if problem is not None:
                    self.report_mt5_feed_problem(problem)

                if rates is not None and len(rates) > 0:
                    candle = self.mt5_next_candle(rates, last_ts)
                    if candle is None:
                        time.sleep(5)  # same closed candle - wait for next minute
                        continue
                    ts, o, h, l, c, vol = candle
                    last_ts = ts
                    self._mt5_last_candle_ts = ts
                    self._last_price_mono = time.monotonic()
                    self.report_mt5_feed_recovered(ts)
                    try:
                        # Candle-driven feed: no tick events, so SL/TP for an
                        # open simulated position must be resolved against the
                        # candle range before new entries are evaluated.
                        self.resolve_open_trade_on_candle(o, h, l, c)
                        self.evaluate_candle(o, h, l, c, vol)
                    except Exception as e:
                        print(f"\nError evaluating candle @ {ts}: {e}", flush=True)
                        # last_ts already advanced past this candle in memory;
                        # persist it so a restart does not replay a candle that
                        # errored (the error path never reaches save_status()).
                        self.save_status()
                    if ts % 3600 == 0:
                        print(f"Heartbeat: candle @ "
                              f"{datetime.fromtimestamp(ts, tz=timezone.utc):%Y-%m-%d %H:%M} MT5-server-time "
                              f"| close {c:.2f}", flush=True)
                else:
                    # No readable feed file: already reported at the top of the
                    # loop by mt5_feed_problem() / report_mt5_feed_problem().
                    time.sleep(5)
                    continue

                time.sleep(5)
        except KeyboardInterrupt:
            print("\nShutting down...")

    def run_forward_test(self):
        print("Gold Engine FORWARD TEST starting...")
        if not TWELVE_DATA_KEY:
            print("TWELVE_DATA_API_KEY missing")
            sys.exit(1)
        while True:
            ws = None
            try:
                td = TDClient(apikey=TWELVE_DATA_KEY)
                ws = td.websocket(on_event=self.on_event)
                ws.subscribe(["XAU/USD"])
                ws.connect()
                print("Connected to Twelve Data\n")
                self._last_price_mono = time.monotonic()
                while True:
                    try:
                        ws.heartbeat()
                        time.sleep(15)
                        # Stale-feed guard: a silently-dead WebSocket delivers no
                        # price events and heartbeat() never raises, so without
                        # this the engine idles forever collecting nothing
                        # (2026-09-10: 00:47 and 02:05 UTC stalls, 2.5h+ of lost
                        # data, zero alerts). Force a reconnect if the feed is
                        # quiet beyond STALE_FEED_SECONDS.
                        stale = self.feed_stale_seconds()
                        if stale > STALE_FEED_SECONDS:
                            print(f"\nStale feed: no price events for {stale:.0f}s - forcing reconnect")
                            if not is_market_quiet():
                                self.maybe_alert_stale_feed(stale)
                            break
                    except Exception as e:
                        print(f"\nConnection issue: {e}")
                        print("Reconnecting in 10s...")
                        time.sleep(10)
                        break
            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"\nError: {e}")
                print("Restarting in 15s...")
                time.sleep(15)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

    def run(self):
        if TRADING_MODE == "LIVE":
            self.run_live()
        elif DATA_SOURCE == "MT5":
            self.run_mt5_test()
        else:
            self.run_forward_test()


if __name__ == "__main__":
    engine = GoldEngine()
    engine.run()
