#!/usr/bin/env python3
"""
MT5 historical data dump (runs under Wine Python, same prefix as mt5_feed.py).

Pulls OHLCV bars for GOLD (or any symbol) and writes a clean CSV that can be
used for offline back-testing / filter research. Does NOT touch the live
engine or forward_test_log.csv.

Typical usage (from the Linux host):

  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum \\
    wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \\
      --bars 50000 --timeframe M1 --out Z:/opt/gold/history_m1.csv

Or by days (approximate):

  wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \\
      --days 180 --timeframe M1 --out Z:/opt/gold/history_m1.csv

Env overrides (same style as mt5_feed.py):
  MT5_FEED_SYMBOL   default GOLD
  MT5_HISTORY_OUT   default Z:/opt/gold/mt5_history.csv

Notes
-----
- Broker historical data is useful for research speed but is NOT identical
  to the live feed the engine uses (spreads, gaps, exact candle formation).
  Always treat live forward-test results as the final authority.
- Prefer --bars over --days; copy_rates_from_pos is more reliable across brokers.
- Output CSV columns: Timestamp,Open,High,Low,Close,TickVolume,Spread
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("mt5_history_dump: MetaTrader5 package missing.")
    print("Install inside the Wine Python:")
    print("  wine C:/Python312/python.exe -m pip install MetaTrader5")
    sys.exit(1)


# Map friendly names → MT5 constants
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

# Rough bars-per-day for estimating --days → --bars
BARS_PER_DAY = {
    "M1": 1440,
    "M5": 288,
    "M15": 96,
    "M30": 48,
    "H1": 24,
    "H4": 6,
    "D1": 1,
}


def ts_to_str(epoch: int) -> str:
    """Convert MT5 epoch to UTC string without deprecation warnings."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump historical GOLD (or other) bars from MT5 to CSV"
    )
    parser.add_argument(
        "--symbol",
        default=os.environ.get("MT5_FEED_SYMBOL", "GOLD"),
        help="Symbol name as shown in Market Watch (default: GOLD)",
    )
    parser.add_argument(
        "--timeframe", "-t",
        default="M1",
        choices=list(TF_MAP.keys()),
        help="Timeframe (default: M1)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Approximate calendar days back (converted to bars). Prefer --bars.",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Request the last N bars (most reliable method)",
    )
    parser.add_argument(
        "--out", "-o",
        default=os.environ.get("MT5_HISTORY_OUT", "Z:/opt/gold/mt5_history.csv"),
        help="Output CSV path (Wine path, e.g. Z:/opt/gold/...)",
    )
    parser.add_argument(
        "--max-bars",
        type=int,
        default=100_000,
        help="Safety cap on number of bars returned (default 100000)",
    )
    args = parser.parse_args()

    # Decide how many bars to request
    if args.bars is not None:
        count = args.bars
    elif args.days is not None:
        count = args.days * BARS_PER_DAY.get(args.timeframe, 1440)
        print(f"(Converted --days {args.days} → ~{count} bars for {args.timeframe})")
    else:
        count = 30 * BARS_PER_DAY.get(args.timeframe, 1440)  # default ~30 days
        print(f"No --bars/--days given; defaulting to ~30 days ({count} bars)")

    count = min(count, args.max_bars)

    if not mt5.initialize():
        print(f"mt5_history_dump: initialize failed: {mt5.last_error()}")
        print("(Is the MT5 terminal running and logged in under this Wine prefix?)")
        sys.exit(1)

    # Helpful diagnostics
    term = mt5.terminal_info()
    if term:
        print(f"Terminal connected: {term.connected}  |  company: {getattr(term, 'company', '?')}")

    if not mt5.symbol_select(args.symbol, True):
        print(f"mt5_history_dump: symbol_select({args.symbol}) failed: {mt5.last_error()}")
        print("Trying to list some symbols that contain 'GOLD' or 'XAU'...")
        symbols = mt5.symbols_get()
        if symbols:
            matches = [s.name for s in symbols if "GOLD" in s.name.upper() or "XAU" in s.name.upper()]
            print("Candidates:", matches[:20] if matches else "(none found)")
        mt5.shutdown()
        sys.exit(1)

    info = mt5.symbol_info(args.symbol)
    if info:
        print(f"Symbol OK: {args.symbol}  digits={info.digits}  point={info.point}  visible={info.visible}")

    tf = TF_MAP[args.timeframe]
    print(f"mt5_history_dump: symbol={args.symbol}  timeframe={args.timeframe}  requesting {count} bars")

    # Primary method: copy_rates_from_pos (most reliable across brokers)
    rates = mt5.copy_rates_from_pos(args.symbol, tf, 0, count)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        print(f"copy_rates_from_pos failed: {err}")
        print("Falling back to copy_rates_from with naive datetime...")

        # Fallback: naive datetime (many MT5 builds dislike tz-aware)
        date_from = datetime.utcnow() - timedelta(days=max(args.days or 30, 1))
        rates = mt5.copy_rates_from(args.symbol, tf, date_from, count)

    if rates is None or len(rates) == 0:
        print(f"mt5_history_dump: no data returned: {mt5.last_error()}")
        print("Possible causes:")
        print("  - Symbol name mismatch (check Market Watch exact name)")
        print("  - Broker does not provide that much history for this TF")
        print("  - Terminal not fully logged in / history not synchronized")
        print("Try a smaller request first, e.g. --bars 5000")
        mt5.shutdown()
        sys.exit(1)

    if len(rates) > args.max_bars:
        print(f"Truncating to max-bars={args.max_bars} (got {len(rates)})")
        rates = rates[-args.max_bars:]

    # Write CSV
    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            pass

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Timestamp", "Open", "High", "Low", "Close", "TickVolume", "Spread"]
        )
        for r in rates:
            ts = ts_to_str(int(r["time"]))
            spread = ""
            if hasattr(r, "dtype") and "spread" in r.dtype.names:
                spread = int(r["spread"])
            writer.writerow(
                [
                    ts,
                    f"{float(r['open']):.5f}".rstrip("0").rstrip("."),
                    f"{float(r['high']):.5f}".rstrip("0").rstrip("."),
                    f"{float(r['low']):.5f}".rstrip("0").rstrip("."),
                    f"{float(r['close']):.5f}".rstrip("0").rstrip("."),
                    int(r["tick_volume"]),
                    spread,
                ]
            )

    first_ts = ts_to_str(int(rates[0]["time"]))
    last_ts = ts_to_str(int(rates[-1]["time"]))
    print(f"Wrote {len(rates)} bars → {out_path}")
    print(f"Range: {first_ts}  →  {last_ts}")
    mt5.shutdown()
    print("Done.")


if __name__ == "__main__":
    main()
