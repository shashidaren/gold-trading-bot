#!/usr/bin/env python3
import json
import csv
import os
from datetime import datetime

STATUS_FILE = "/opt/gold/status.json"
SKIP_FILE   = "/opt/gold/skipped_trades.csv"
TRADES_FILE = "/opt/gold/trades.csv"

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

def last_n_rows(path, n=8):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # skip completely empty rows
            if any(v and str(v).strip() for v in row.values()):
                rows.append(row)
    return rows[-n:] if rows else []

def main():
    status = load_json(STATUS_FILE)
    print("=" * 52)
    print("GOLD ENGINE STATUS")
    print("=" * 52)
    print(f"Last update     : {status.get('last_update', 'N/A')}")
    print(f"Equity          : ${status.get('equity', 0):.2f}")
    print(f"Total trades    : {status.get('total_trades', 0)}")
    print(f"Win rate        : {status.get('win_rate', 0)}%")
    print()

    rsi   = status.get("rsi")
    atr   = status.get("atr")
    ema50 = status.get("ema_fast")
    ema200= status.get("ema_slow")

    print("Current Indicators")
    print(f"  RSI            : {rsi}")
    print(f"  ATR            : {atr}")
    print(f"  EMA50          : {ema50}")
    print(f"  EMA200         : {ema200}")

    if ema50 is not None and ema200 is not None:
        gap = ema50 - ema200
        print(f"  EMA Gap        : {gap:+.2f}")
        if gap >= 5.0:
            print("  Trend          : Bullish (strong enough)")
        elif gap > 0:
            print("  Trend          : Weak bullish (gap too small)")
        else:
            print("  Trend          : Bearish / neutral")
    print()

    funnel = status.get("funnel", {})
    print("Funnel (since last restart)")
    print(f"  Candles evaluated : {funnel.get('candles_evaluated', 0)}")
    print(f"  Tested floor      : {funnel.get('tested_floor', 0)}")
    print(f"  Valid rejection   : {funnel.get('valid_rejection', 0)}")
    print(f"  Held support      : {funnel.get('held_support', 0)}")
    print(f"  Trend confirmed   : {funnel.get('trend_confirmed', 0)}")
    print(f"  All confirmed     : {funnel.get('all_confirmed', 0)}")
    print()

    skips = last_n_rows(SKIP_FILE, 8)
    print("Recent Skips (last 8)")
    if not skips:
        print("  (none recorded)")
    else:
        for s in skips:
            ts = s.get("Timestamp", "")
            reason = s.get("Reason", "")
            if ts or reason:
                print(f"  {ts}  |  {reason}")
    print()

    trades = last_n_rows(TRADES_FILE, 5)
    print("Last Trades")
    if not trades:
        print("  (none)")
    else:
        for t in trades:
            print(f"  {t.get('Entry_Time','')}  {t.get('Exit_Reason','')}  P/L: {t.get('Profit','')}")
    print("=" * 52)

if __name__ == "__main__":
    main()
