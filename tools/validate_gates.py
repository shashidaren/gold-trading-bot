#!/usr/bin/env python3
"""
Gate validator - replays entry gates against historical trades.

For every trade in trades.csv it finds the signal candle (the log row whose
timestamp == Entry_Time) in forward_test_log.csv and checks which gates would
have passed or blocked that entry.

Gates (the ones marked ADOPTED are implemented in engine.py / trade_filter.py
as of the 2026-09-09 review - see docs/REVIEW-2026-09-09.md):

  OLD0.2%   baseline: candle Low within 0.2% of the 20-bar floor (old rule, kept)
  PROX<k>   stricter ATR-scaled floor proximity - REJECTED by validation:
            it blocks every historical win (winners are bounce candles whose
            lows never reach the floor)
  SLOPE30   ADOPTED: EMA50 rising vs 30 candles ago
  ABV50s    ADOPTED: entry close no more than 0.3*ATR below EMA50
  NOH8      ADOPTED: entry outside the extended 07:55-09:00 UTC London blackout
  RISE<N>   20-bar floor flat-or-rising vs N candles ago (candidate, not adopted)
  ABOVE50   entry close above EMA50 (candidate, not adopted)

Usage: python3 tools/validate_gates.py [log.csv trades.csv]
Read-only - no files are modified.
"""
import csv
import sys
import os
import bisect
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "forward_test_log.csv")
TRADES = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "trades.csv")


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_log():
    rows = []
    with open(LOG, newline="") as f:
        for r in csv.DictReader(f):
            try:
                dt = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
            except (KeyError, ValueError):
                continue
            rows.append({
                "dt": dt,
                "low": fnum(r["Low"]), "close": fnum(r["Close"]),
                "floor": fnum(r["Dynamic_Floor"]), "atr": fnum(r["ATR"]),
                "ema50": fnum(r["EMA_50"]),
            })
    rows.sort(key=lambda x: x["dt"])
    return rows


def load_trades():
    out = []
    with open(TRADES, newline="") as f:
        for r in csv.DictReader(f):
            out.append({
                "dt": datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                "win": r["Exit_Reason"].strip().upper() == "TP",
                "pnl": float(r["Profit"]),
                "num": r["Trade_Num"],
            })
    return out


def main():
    log = load_log()
    trades = load_trades()
    stamps = [r["dt"] for r in log]

    report = []
    for t in trades:
        i = bisect.bisect_left(stamps, t["dt"])
        if i >= len(log) or stamps[i] != t["dt"]:
            i = min(i, len(log) - 1)  # nearest-row fallback
        row = log[i]

        def hist(n, field):
            j = i - n
            return log[j][field] if j >= 0 else None

        g = {}
        g["OLD0.2%"] = row["floor"] is not None and row["low"] <= row["floor"] * 1.002
        prev_atr = log[i - 1]["atr"] if i > 0 and log[i - 1]["atr"] else row["atr"]
        for k in (0.5, 1.0):
            g[f"PROX{k}"] = (row["floor"] is not None and prev_atr is not None
                             and row["low"] <= row["floor"] + k * prev_atr)
        g["SLOPE30"] = (row["ema50"] is not None and hist(30, "ema50") is not None
                        and row["ema50"] > hist(30, "ema50"))
        g["ABV50s"] = (row["ema50"] is not None and row["atr"] is not None
                       and row["close"] > row["ema50"] - 0.3 * row["atr"])
        h = t["dt"].hour * 60 + t["dt"].minute
        g["NOH8"] = not (7 * 60 + 55 <= h < 9 * 60)
        g["RISE120"] = (row["floor"] is not None and hist(120, "floor") is not None
                        and row["floor"] >= hist(120, "floor"))
        g["ABOVE50"] = row["ema50"] is not None and row["close"] > row["ema50"]
        report.append((t, g))

    names = ["SLOPE30", "ABV50s", "NOH8", "RISE120", "ABOVE50", "PROX0.5", "PROX1.0", "OLD0.2%"]
    print(f"{'trade':<13} {'res':<4} {'pnl':>6}  " + "  ".join(f"{n:>8}" for n in names))
    for t, g in report:
        mark = "WIN" if t["win"] else "loss"
        cells = "  ".join(f"{'PASS' if g[n] else 'BLOCK':>8}" for n in names)
        print(f"#{t['num']:>3} {t['dt'].strftime('%m-%d %H:%M'):<10} {mark:<4} {t['pnl']:>+6.2f}  {cells}")

    def summ(name, fn):
        kept = [(t, g) for t, g in report if fn(g)]
        w = sum(1 for t, g in kept if t["win"])
        l = len(kept) - w
        pnl = sum(t["pnl"] for t, g in kept)
        wr = w / len(kept) * 100 if kept else 0
        k8 = [(t, g) for t, g in kept if t["dt"] >= datetime(2026, 9, 8)]
        w8 = sum(1 for t, g in k8 if t["win"])
        p8 = sum(t["pnl"] for t, g in k8)
        print(f"  {name:<28} all: {len(kept):>2} kept {w}W/{l}L ({wr:3.0f}%) {pnl:+8.2f}   "
              f"9/8+: {len(k8)} kept {w8}W/{len(k8)-w8}L {p8:+7.2f}")

    print("\n=== SINGLE GATES ===")
    for n in names:
        summ(n, lambda g, n=n: g[n])

    print("\n=== ADOPTED COMBO: SLOPE30 + ABV50s + NOH8 ===")
    summ("adopted (all three)",
         lambda g: g["SLOPE30"] and g["ABV50s"] and g["NOH8"])
    print("\n=== other combos (reference) ===")
    summ("SLOPE30+NOH8", lambda g: g["SLOPE30"] and g["NOH8"])
    summ("SLOPE30+ABV50s+NOH8+RISE120",
         lambda g: g["SLOPE30"] and g["ABV50s"] and g["NOH8"] and g["RISE120"])


if __name__ == "__main__":
    main()
