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
      --days 365 --timeframe M1 --out Z:/opt/gold/history_m1.csv

Or shorter (last N bars):

  wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \\
      --bars 50000 --timeframe M1 --out Z:/opt/gold/history_m1.csv

Env overrides (same style as mt5_feed.py):
  MT5_FEED_SYMBOL   default GOLD
  MT5_HISTORY_OUT   default Z:/opt/gold/mt5_history.csv

Notes
-----
- Broker historical data is useful for research speed but is NOT identical
  to the live feed the engine uses (spreads, gaps, exact candle formation).
  Always treat live forward-test results as the final authority.
- Large requests can take a while; the script prints progress.
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
        help="How many calendar days back from now to request",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Alternative: request the last N bars (overrides --days)",
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

    if args.bars is None and args.days is None:
        args.days = 365  # sensible default

    if not mt5.initialize():
        print(f"mt5_history_dump: initialize failed: {mt5.last_error()}")
        print("(Is the MT5 terminal running and logged in under this Wine prefix?)")
        sys.exit(1)

    if not mt5.symbol_select(args.symbol, True):
        print(f"mt5_history_dump: symbol_select({args.symbol}) failed: {mt5.last_error()}")
        print("Check the exact symbol name in Market Watch (e.g. GOLD, GOLDm, XAUUSD).")
        mt5.shutdown()
        sys.exit(1)

    tf = TF_MAP[args.timeframe]
    print(f"mt5_history_dump: symbol={args.symbol}  timeframe={args.timeframe}")

    rates = None
    if args.bars is not None:
        count = min(args.bars, args.max_bars)
        print(f"Requesting last {count} bars ...")
        rates = mt5.copy_rates_from_pos(args.symbol, tf, 0, count)
    else:
        date_to = utc_now()
        date_from = date_to - timedelta(days=args.days)
        print(f"Requesting bars from {date_from.date()} to {date_to.date()} ...")
        rates = mt5.copy_rates_range(args.symbol, tf, date_from, date_to)

    if rates is None or len(rates) == 0:
        print(f"mt5_history_dump: no data returned: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    if len(rates) > args.max_bars:
        print(f"Truncating to max-bars={args.max_bars} (got {len(rates)})")
        rates = rates[-args.max_bars:]

    # Write CSV
    out_path = args.out
    # Ensure directory exists (Wine paths are visible under the prefix)
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
            ts = datetime.fromtimestamp(r["time"], tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            writer.writerow(
                [
                    ts,
                    f"{r['open']:.5f}".rstrip("0").rstrip("."),
                    f"{r['high']:.5f}".rstrip("0").rstrip("."),
                    f"{r['low']:.5f}".rstrip("0").rstrip("."),
                    f"{r['close']:.5f}".rstrip("0").rstrip("."),
                    int(r["tick_volume"]),
                    int(r["spread"]) if "spread" in r.dtype.names else "",
                ]
            )

    first_ts = datetime.fromtimestamp(rates[0]["time"], tz=timezone.utc)
    last_ts = datetime.fromtimestamp(rates[-1]["time"], tz=timezone.utc)
    print(f"Wrote {len(rates)} bars → {out_path}")
    print(f"Range: {first_ts}  →  {last_ts}")
    mt5.shutdown()
    print("Done.")


if __name__ == "__main__":
    main()
