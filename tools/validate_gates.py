#!/usr/bin/env python3
"""
Gate validator - replays entry gates against historical trades.

For every trade in trades.csv it finds the signal candle (the log row whose
timestamp == Entry_Time) in forward_test_log.csv and checks which gates would
have passed or blocked that entry.

Gates (the ones marked ADOPTED are implemented in engine.py / trade_filter.py
as of the 2026-09-09 review - see docs/REVIEW-2026-09-09.md):

  OLD0.2%   baseline: candle Low within 0.2% of the 20-bar floor (old rule, kept)
            (SELL: High within 0.2% of the 20-bar ceiling)
  PROX<k>   stricter ATR-scaled floor proximity - REJECTED by validation:
            it blocks every historical win (winners are bounce candles whose
            lows never reach the floor)
  SLOPE30   ADOPTED: EMA50 rising vs 30 candles ago (SELL: falling)
  ABV50s    ADOPTED: entry close no more than 0.3*ATR below EMA50
            (SELL: no more than 0.3*ATR above)
  NOH8      ADOPTED: entry outside the extended 07:55-09:00 UTC London blackout
  RISE<N>   20-bar floor flat-or-rising vs N candles ago (candidate, not adopted)
            (SELL: ceiling flat-or-falling)
  ABOVE50   entry close above EMA50 (candidate, not adopted; SELL: below)

Handles both the pre-SELL 15-field rows (all buys) and the current 16-field
schema with Trade_Type (auto-detected, so it works even on a drifted file).

BE scratches (exit reason BE, live since the 2026-09-10 BE ratchet) are
reported separately - they are neutral, neither wins nor losses, and win
rates below are over decisive (TP/SL) trades only.

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

LOOKBACK = 20          # dynamic floor/ceiling lookback (engine LOOKBACK_PERIOD)
K_FAST = 2 / (50 + 1)  # EMA50 smoothing (to reconstruct post-update values)


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
                "high": fnum(r["High"]), "low": fnum(r["Low"]), "close": fnum(r["Close"]),
                "floor": fnum(r["Dynamic_Floor"]), "atr": fnum(r["ATR"]),
                "ema50": fnum(r["EMA_50"]),
            })
    rows.sort(key=lambda x: x["dt"])
    return rows


def load_trades():
    """Load trades from either schema (15-field pre-SELL buy rows or 16-field
    rows with Trade_Type). A 15-field header with 16-field rows is the
    2026-09-10 drift incident - handled the same way the engine migration
    handles it, without modifying anything."""
    out = []
    with open(TRADES, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr, None)
        if header and "Trade_Type" not in [h.strip() for h in header]:
            print("NOTE: trades.csv header has no Trade_Type column (pre-SELL schema); "
                  "run the engine once to auto-migrate it.")
        for r in rdr:
            if len(r) == 16:                     # current schema
                side, entry_t = r[1].strip().upper(), r[2]
                reason, pnl, num = r[8], r[9], r[0]
            elif len(r) == 15:                   # pre-SELL schema (all buys)
                side, entry_t = "BUY", r[1]
                reason, pnl, num = r[7], r[8], r[0]
            else:
                print(f"WARNING: skipping unrecognisable trades.csv row: {r[:4]}...")
                continue
            try:
                out.append({
                    "dt": datetime.strptime(entry_t, "%Y-%m-%d %H:%M:%S"),
                    "side": side,
                    "reason": reason.strip().upper(),
                    "win": reason.strip().upper() == "TP",
                    "pnl": float(pnl),
                    "num": num,
                })
            except (ValueError, IndexError):
                print(f"WARNING: skipping unparsable trades.csv row: {r[:4]}...")
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

        # 20-bar ceiling is not logged - reconstruct it (same lookback the
        # engine uses, prior 20 bars excluding the signal candle).
        prior_lows = [x["low"] for x in log[max(0, i - LOOKBACK):i] if x["low"] is not None]
        prior_highs = [x["high"] for x in log[max(0, i - LOOKBACK):i] if x["high"] is not None]
        ceiling = max(prior_highs) if len(prior_highs) == LOOKBACK else None

        sell = t["side"] == "SELL"
        g = {}
        if sell:
            g["OLD0.2%"] = (ceiling is not None and row["high"] is not None
                            and row["high"] >= ceiling * (1 - 0.002))
        else:
            g["OLD0.2%"] = (row["floor"] is not None and row["low"] is not None
                            and row["low"] <= row["floor"] * 1.002)
        prev_atr = log[i - 1]["atr"] if i > 0 and log[i - 1]["atr"] else row["atr"]
        for k in (0.5, 1.0):
            if sell:
                g[f"PROX{k}"] = (ceiling is not None and prev_atr is not None
                                 and row["high"] is not None
                                 and row["high"] >= ceiling - k * prev_atr)
            else:
                g[f"PROX{k}"] = (row["floor"] is not None and prev_atr is not None
                                 and row["low"] is not None
                                 and row["low"] <= row["floor"] + k * prev_atr)
        if sell:
            g["SLOPE30"] = (row["ema50"] is not None and hist(30, "ema50") is not None
                            and row["ema50"] < hist(30, "ema50"))
            g["ABV50s"] = (row["ema50"] is not None and row["atr"] is not None
                           and row["close"] is not None
                           and row["close"] < row["ema50"] + 0.3 * row["atr"])
            g["RISE120"] = (ceiling is not None
                            and hist(120, "high") is not None
                            and ceiling <= hist(120, "high"))
            g["ABOVE50"] = (row["ema50"] is not None and row["close"] is not None
                            and row["close"] < row["ema50"])
        else:
            g["SLOPE30"] = (row["ema50"] is not None and hist(30, "ema50") is not None
                            and row["ema50"] > hist(30, "ema50"))
            g["ABV50s"] = (row["ema50"] is not None and row["atr"] is not None
                           and row["close"] is not None
                           and row["close"] > row["ema50"] - 0.3 * row["atr"])
            g["RISE120"] = (row["floor"] is not None and hist(120, "floor") is not None
                            and row["floor"] >= hist(120, "floor"))
            g["ABOVE50"] = (row["ema50"] is not None and row["close"] is not None
                            and row["close"] > row["ema50"])
        h = t["dt"].hour * 60 + t["dt"].minute
        g["NOH8"] = not (7 * 60 + 55 <= h < 9 * 60)
        report.append((t, g))

    names = ["SLOPE30", "ABV50s", "NOH8", "RISE120", "ABOVE50", "PROX0.5", "PROX1.0", "OLD0.2%"]
    print(f"{'trade':<13} {'res':<4} {'pnl':>6}  " + "  ".join(f"{n:>8}" for n in names))
    for t, g in report:
        mark = "WIN" if t["reason"] == "TP" else ("BE" if t["reason"] == "BE" else "loss")
        cells = "  ".join(f"{'PASS' if g[n] else 'BLOCK':>8}" for n in names)
        print(f"#{t['num']:>3} {t['side']:<4}{t['dt'].strftime('%m-%d %H:%M'):<10} {mark:<4} {t['pnl']:>+6.2f}  {cells}")

    def summ(name, fn):
        kept = [(t, g) for t, g in report if fn(t, g)]
        w = sum(1 for t, g in kept if t["reason"] == "TP")
        b = sum(1 for t, g in kept if t["reason"] == "BE")
        l = len(kept) - w - b
        pnl = sum(t["pnl"] for t, g in kept)
        dec = w + l
        wr = w / dec * 100 if dec else 0
        k8 = [(t, g) for t, g in kept if t["dt"] >= datetime(2026, 9, 8)]
        w8 = sum(1 for t, g in k8 if t["reason"] == "TP")
        b8 = sum(1 for t, g in k8 if t["reason"] == "BE")
        p8 = sum(t["pnl"] for t, g in k8)
        print(f"  {name:<28} all: {len(kept):>2} kept {w}W/{l}L/{b}BE ({wr:3.0f}% dec) {pnl:+8.2f}   "
              f"9/8+: {len(k8)} kept {w8}W/{len(k8)-w8-b8}L/{b8}BE {p8:+7.2f}")

    print("\n=== SINGLE GATES (WR over decisive trades; BE = neutral scratch) ===")
    for n in names:
        summ(n, lambda t, g, n=n: g[n])

    print("\n=== ADOPTED COMBO: SLOPE30 + ABV50s + NOH8 ===")
    summ("adopted (all three)",
         lambda t, g: g["SLOPE30"] and g["ABV50s"] and g["NOH8"])
    print("\n=== other combos (reference) ===")
    summ("SLOPE30+NOH8", lambda t, g: g["SLOPE30"] and g["NOH8"])
    summ("SLOPE30+ABV50s+NOH8+RISE120",
         lambda t, g: g["SLOPE30"] and g["ABV50s"] and g["NOH8"] and g["RISE120"])

    sells = [(t, g) for t, g in report if t["side"] == "SELL"]
    if sells:
        w = sum(1 for t, g in sells if t["reason"] == "TP")
        b = sum(1 for t, g in sells if t["reason"] == "BE")
        print(f"\n=== SELL trades: {len(sells)} ({w}W/{len(sells)-w-b}L/{b}BE, "
              f"{sum(t['pnl'] for t, g in sells):+.2f}) - n too small to validate gates ===")


if __name__ == "__main__":
    main()
