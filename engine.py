#!/usr/bin/env python3
import os
import csv
import json
import time
import sys
import shutil
import requests
from collections import deque
from datetime import datetime, timezone
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
FLOOR_BUFFER_PCT = 0.0020

ATR_SL_MULT = 2.0
ATR_TP_MULT = 3.0

# Breakeven stop ratchet (adopted 2026-09-10, docs/ANALYSIS-2026-09-10-losing-trades.md):
# once a trade is +0.30R in profit, SL moves to entry. Sequence-aware replay of all
# 45 sample trades: -82.51 actual -> ~-63 with the ratchet (12-14 losers scratch).
BE_TRIGGER_R = 0.30

REQUIRE_VOLUME_CONFIRM = False
VOLUME_SPIKE_MULTIPLIER = 0.9
REQUIRE_TREND_CONFIRM = True
RSI_MIN = 30.0
RSI_MAX = 68.0
MIN_ATR = 1.10

# --- Stale feed guard (silent Twelve Data WebSocket stalls, 2026-09-10) ---
STALE_FEED_SECONDS = 10 * 60            # force reconnect if no price event this long
STALE_ALERT_COOLDOWN_SECONDS = 30 * 60  # Telegram alert at most this often

# --- Regime gates (EMA Slope & Distance from Mean) ---
REQUIRE_EMA_SLOPE = True       # EMA50 slope direction filter
EMA_SLOPE_LOOKBACK = 30        # Compare EMA50 vs N candles ago
MAX_BELOW_EMA_ATR = 0.30       # Entry distance buffer from EMA50

SYMBOL = "GOLD"
LOT_SIZE = 0.01
MAGIC_NUMBER = 987654

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
        self.trade_active = False
        self.trade_type = "BUY"  # "BUY" or "SELL"
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
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
        self._mt5_last_candle_ts = None

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

                    try:
                        bal = float(row.get("Balance_After", 0) or 0)
                        if bal > 0:
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
            self.balance = 500.00

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
        closed = self.wins + self.losses + self.be_exits
        # win_rate is over decisive trades only; BE scratches are neutral
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
            "win_rate": round(win_rate, 1),
            "trade_active": active_trade,
            "trade_type": self.trade_type if active_trade else None,
            "daily_losses": daily_losses,
            "max_daily_losses": MAX_DAILY_LOSSES,
            "last_update": utc_now_str(),
            "mt5_last_candle_ts": self._mt5_last_candle_ts,
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

    def send_telegram(self, text: str):
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

    def maybe_alert_stale_feed(self, stale_seconds: float) -> bool:
        """Rate-limited Telegram alert for a stalled feed. True if it alerted."""
        if self._last_stale_alert_mono is not None and \
                time.monotonic() - self._last_stale_alert_mono < STALE_ALERT_COOLDOWN_SECONDS:
            return False
        self._last_stale_alert_mono = time.monotonic()
        self.send_telegram(
            f"⚠️ gold engine: no price ticks for {stale_seconds / 60:.0f} min — "
            f"stale-feed guard forced a WebSocket reconnect"
        )
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
            f"SL moved to entry: `${self.stop_loss:.2f}`"
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

    def resolve_open_trade_on_candle(self, o: float, h: float, l: float, c: float):
        """Forward-test exit resolution for candle-driven data sources
        (MT5 sidecar): there are no tick events, so an open simulated
        position must be checked against the candle range BEFORE evaluating
        new entries. Pessimistic intra-candle assumption: if both SL and TP
        fall inside the range, the SL is assumed to have been hit first.
        """
        if not self.trade_active:
            return
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

    def evaluate_candle(self, o, h, l, c, tick_count):
        candle_range = h - l
        if candle_range <= 0:
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
            )

            if not allow:
                msg = (
                    f"BUY SETUP SKIPPED\nReason: `{reason}`\n"
                    f"Price: `${c:.2f}` | RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`"
                )
                self.send_telegram(msg)
                print(f"\nTrade skipped -> {reason}\n")
                return

            if TRADING_MODE == "LIVE":
                self.execute_live_trade("BUY", c, lower_wick_ratio, ts)
            else:
                self.execute_simulated_trade("BUY", c, lower_wick_ratio, ts)

        elif sell_signal:
            self.hit_sell_all += 1
            allow, reason = should_take_trade(
                current_atr=self.atr,
                current_price=c,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                side="SELL",
            )

            if not allow:
                msg = (
                    f"SELL SETUP SKIPPED\nReason: `{reason}`\n"
                    f"Price: `${c:.2f}` | RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`"
                )
                self.send_telegram(msg)
                print(f"\nTrade skipped -> {reason}\n")
                return

            if TRADING_MODE == "LIVE":
                self.execute_live_trade("SELL", c, upper_wick_ratio, ts)
            else:
                self.execute_simulated_trade("SELL", c, upper_wick_ratio, ts)

    def execute_live_trade(self, direction: str, c: float, wick_ratio: float, ts: str):
        print(f"\nALL CONDITIONS MET! PREPARING LIVE {direction} ORDER...")
        point = mt5.symbol_info(SYMBOL).point
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            print("Failed to get tick data")
            return

        if direction == "BUY":
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
            sl_price = price - (self.atr * ATR_SL_MULT)
            tp_price = price + (self.atr * ATR_TP_MULT)
        else:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
            sl_price = price + (self.atr * ATR_SL_MULT)
            tp_price = price - (self.atr * ATR_TP_MULT)

        sl_price = round(sl_price / point) * point
        tp_price = round(tp_price / point) * point

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": LOT_SIZE,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": MAGIC_NUMBER,
            "comment": f"Gold Engine Live {direction}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        print(f"   Sending: {direction} {LOT_SIZE} {SYMBOL} @ {price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}")

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order failed: {result.retcode} - {result.comment}")
            self.send_telegram(f"ORDER FAILED\nCode: {result.retcode}\nMsg: {result.comment}")
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
                f"TP: `${tp_price:.2f}`"
            )

    def execute_simulated_trade(self, direction: str, c: float, wick_ratio: float, ts: str):
        self.trade_active = True
        self.trade_type = direction
        self.current_trade_num = self.next_trade_num
        self.next_trade_num += 1
        self.be_armed = False  # fresh trade: ratchet re-arms at +BE_TRIGGER_R

        self.entry_price = c
        if direction == "BUY":
            self.stop_loss = c - (self.atr * ATR_SL_MULT)
            self.take_profit = c + (self.atr * ATR_TP_MULT)
        else:
            self.stop_loss = c + (self.atr * ATR_SL_MULT)
            self.take_profit = c - (self.atr * ATR_TP_MULT)

        self.entry_time = ts
        self.entry_rsi = self.rsi
        self.entry_atr = self.atr
        self.entry_wick_ratio = wick_ratio
        self.entry_ema_fast = self.ema_fast
        self.entry_ema_slow = self.ema_slow

        msg = (
            f"GOLD {direction} SETUP #{self.current_trade_num}\n"
            f"Entry: `${self.entry_price:.2f}`\n"
            f"RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`\n"
            f"SL: `${self.stop_loss:.2f}`\n"
            f"TP: `${self.take_profit:.2f}`"
        )
        self.send_telegram(msg)
        print(f"\nAlert sent -> {direction} Trade #{self.current_trade_num}\n")
        self.save_status()

    def check_position(self, price: float):
        if not self.trade_active:
            return

        self._maybe_arm_breakeven(price=price)

        if self.trade_type == "BUY":
            if price >= self.take_profit:
                profit = price - self.entry_price
                self.balance += profit
                self.wins += 1
                self.trade_active = False
                self.be_armed = False
                self.log_trade(exit_price=price, exit_reason="TP", profit=profit)
                self.send_telegram(
                    f"TP HIT (BUY #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (+${profit:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
                )
                self.save_status()
            elif price <= self.stop_loss:
                loss = self.entry_price - price
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
                )
                self.save_status()

        elif self.trade_type == "SELL":
            if price <= self.take_profit:
                profit = self.entry_price - price
                self.balance += profit
                self.wins += 1
                self.trade_active = False
                self.be_armed = False
                self.log_trade(exit_price=price, exit_reason="TP", profit=profit)
                self.send_telegram(
                    f"TP HIT (SELL #{self.current_trade_num})\n"
                    f"Exit: `${price:.2f}` (+${profit:.2f})\n"
                    f"Equity: `${self.balance:.2f}`"
                )
                self.save_status()
            elif price >= self.stop_loss:
                loss = price - self.entry_price
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
                )
                self.save_status()

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
        print("Gold Engine LIVE starting...")
        candles_fetched = 0
        while True:
            try:
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 1)
                if rates is None or len(rates) == 0:
                    time.sleep(1)
                    continue
                last_candle = rates[0]
                o, h, l, c, vol = (
                    float(last_candle["open"]),
                    float(last_candle["high"]),
                    float(last_candle["low"]),
                    float(last_candle["close"]),
                    int(last_candle["tick_volume"]),
                )
                self.evaluate_candle(o, h, l, c, vol)
                if candles_fetched % 10 == 0:
                    print(
                        f"Heartbeat: Processed candle @ "
                        f"{datetime.fromtimestamp(last_candle['time'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC "
                        f"| Close: {c}"
                    )
                candles_fetched += 1
                for _ in range(12):
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
        file is missing/unreadable."""
        try:
            with open(MT5_FEED_FILE) as f:
                d = json.load(f)
            return [{
                "time": int(d["ts"]),
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "tick_volume": int(d["tick_volume"]),
            }]
        except Exception:
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
        last_ts = 0
        try:
            with open(STATUS_FILE_PATH) as f:
                last_ts = int(json.load(f).get("mt5_last_candle_ts") or 0)
        except Exception:
            last_ts = 0
        try:
            while True:
                rates = self.read_mt5_feed()

                if rates is not None and len(rates) > 0:
                    candle = self.mt5_next_candle(rates, last_ts)
                    if candle is None:
                        time.sleep(5)  # same closed candle - wait for next minute
                        continue
                    ts, o, h, l, c, vol = candle
                    last_ts = ts
                    self._mt5_last_candle_ts = ts
                    self._last_price_mono = time.monotonic()
                    try:
                        # Candle-driven feed: no tick events, so SL/TP for an
                        # open simulated position must be resolved against the
                        # candle range before new entries are evaluated.
                        self.resolve_open_trade_on_candle(o, h, l, c)
                        self.evaluate_candle(o, h, l, c, vol)
                    except Exception as e:
                        print(f"\nError evaluating candle @ {ts}: {e}", flush=True)
                    if ts % 3600 == 0:
                        print(f"Heartbeat: candle @ "
                              f"{datetime.fromtimestamp(ts, tz=timezone.utc):%Y-%m-%d %H:%M} MT5-server-time "
                              f"| close {c:.2f}", flush=True)
                else:
                    print(f"MT5: no feed in {MT5_FEED_FILE} - retrying in 5s "
                          "(is the mt5feed sidecar running? terminal logged in?)", flush=True)
                    time.sleep(5)
                    continue

                # Stale-feed guard (same as run_forward_test): feed went quiet
                # (sidecar crashed / terminal logged out) -> alert. The sidecar
                # is a separate service: systemctl restart mt5feed.
                stale = self.feed_stale_seconds()
                if stale > STALE_FEED_SECONDS:
                    print(f"\nStale MT5 feed: no closed candles for {stale:.0f}s - "
                          f"check the mt5feed sidecar (systemctl restart mt5feed)", flush=True)
                    if not is_market_quiet():
                        self.maybe_alert_stale_feed(stale)
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
