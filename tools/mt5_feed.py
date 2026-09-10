#!/usr/bin/env python3
"""MT5 -> file sidecar for the gold engine.

The Linux engine cannot import MetaTrader5 (no Linux wheels on PyPI), so this
tiny daemon runs under the Wine Python in the SAME prefix as the MT5 terminal
(the same pattern as the mt5-balance / mt5-trades shell aliases) and publishes
the latest closed M1 candle for GOLD to a JSON file that engine.py
(DATA_SOURCE=MT5) reads.

Run (manual test, mirrors the mt5-balance alias):
  export WINEPREFIX=~/.mt5 && xvfb-run --auto-servernum \
      wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_feed.py
  # watch /opt/gold/mt5_last_candle.json appear/update, Ctrl-C

Or as a service (see deploy/mt5feed.service):
  sudo systemctl enable --now mt5feed

Publishes (atomic write, refreshed every 5s; the engine dedups by candle ts):
  Z:/opt/gold/mt5_last_candle.json
  {"ts": 1789015200, "open": 4400.0, "high": 4401.0, "low": 4399.0,
   "close": 4400.5, "tick_volume": 12, "updated_at": "2026-09-10 05:20:03"}

Env overrides: MT5_FEED_SYMBOL (default GOLD), MT5_FEED_FILE
(default Z:/opt/gold/mt5_last_candle.json), MT5_FEED_POLL (seconds, default 5).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("mt5_feed: MetaTrader5 package missing - install it in the WINE python:")
    print("  wine C:/Python312/python.exe -m pip install MetaTrader5")
    sys.exit(1)

SYMBOL = os.environ.get("MT5_FEED_SYMBOL", "GOLD")
OUT = os.environ.get("MT5_FEED_FILE", "Z:/opt/gold/mt5_last_candle.json")
POLL = float(os.environ.get("MT5_FEED_POLL", "5"))


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    if not mt5.initialize():
        print(f"mt5_feed: MT5 initialize failed: {mt5.last_error()} "
              f"(is the terminal running and logged in in this prefix?)", flush=True)
        sys.exit(1)
    if not mt5.symbol_select(SYMBOL, True):
        print(f"mt5_feed: symbol_select({SYMBOL}) failed: {mt5.last_error()} "
              f"(check the exact symbol name in Market Watch, e.g. GOLDm)", flush=True)
        sys.exit(1)
    account = mt5.account_info()
    acct = f" | account {account.login}" if account else ""
    print(f"mt5_feed: publishing closed M1 {SYMBOL} candles -> {OUT}{acct}", flush=True)

    while True:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
            if rates is not None and len(rates) > 0:
                r = rates[0]
                payload = {
                    "ts": int(r["time"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "tick_volume": int(r["tick_volume"]),
                    "updated_at": utc_now_str(),
                }
                tmp = OUT + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(payload, f)
                os.replace(tmp, OUT)  # atomic: readers never see a partial file
            else:
                print(f"mt5_feed: no M1 data for {SYMBOL}: {mt5.last_error()}", flush=True)
            time.sleep(POLL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"mt5_feed: error: {e} (retrying)", flush=True)
            time.sleep(POLL)
    mt5.shutdown()
    print("mt5_feed: stopped", flush=True)


if __name__ == "__main__":
    main()
