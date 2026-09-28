#!/usr/bin/env python3
"""
Momentum / regime decomposition — "does the bot do better when gold falls?"

Read-only. Wrote for the 2026-09-28 question ("win ratio looks better when the
gold price is reducing") and meant to be re-run on every data drop:

    python3 tools/momentum_regime.py            # from the repo root

It answers the question in layers, because the naive cut is confounded:

  1. Book + day-level: gold's calendar-day change vs that day's trades. If
     "the bot does better when gold falls" were a day-level effect it shows up
     here — it does not (null, see ANALYSIS-2026-09-28).
  2. Pre-entry momentum: close-to-close change over the 30/60/120/240 min
     BEFORE entry (entry - 1 min, to respect the ~1-min feed lag) vs outcome.
  3. Side decomposition (BUY vs SELL) per era — the actual driver: the trend
     gate makes momentum and side nearly collinear (BUYs fire in rising tape,
     SELLs in falling tape), so "falling tape" mostly means "SELL side".
  4. Within-side momentum — the refutation test. If falling price were good per
     se, BUYs in falling tape would be fine; they are the single worst bucket.
  5. Trend alignment: is the trade entering WITH the 240-min move?
  6. Up-day counter-cases (auto-detected, no hardcoded dates): days where gold
     rose, split by side — the pattern inverts in up-legs.
  7. Chunked stability: the falling-vs-rising gap over 5-day calendar chunks —
     shows how unstable the effect is.
  8. The pre-registered bar for adopting any momentum/side gate (printed, so
     future sessions cannot quietly move the goalposts).

Conventions / gotchas handled:
  - Momentum uses bars STRICTLY before entry (close at entry-1min vs entry-1min
    minus the window) — no lookahead.
  - Decisive WR = TP/(TP+SL); BE and TIME are neutral buckets, never losers.
  - No ratchet geometry is needed here: outcomes come from Exit_Reason, P&L from
    the Profit column, so the "Stop_Loss == Entry_Price" logging quirk does not
    affect any number in this report.
  - trades.csv Trade_Num resets are irrelevant: everything is row-based.
  - Fisher exact two-sided p (method of small p-values) and Wilson 95% CIs are
    printed because all buckets here are small; a gap that does not clear both
    is noise.
"""
import bisect
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
TRADES = f"{ROOT}/trades.csv"
LOG = f"{ROOT}/forward_test_log.csv"

MOMENTUM_WINDOWS = (30, 60, 120, 240)
ERA_075R = datetime(2026, 9, 15, 6, 0)
ERA_MAXHOLD = datetime(2026, 9, 21, 6, 0)
WILSON_Z = 1.959964

# The bar registered on 2026-09-28 (HANDOFF §6). Print it verbatim.
PREREGISTERED_BAR = """\
Any momentum/side gate must clear ALL of these at the 2026-10-05 re-review,
otherwise it is dropped (no partial adoption, no re-slicing):
  a) >=25 decisive outcomes in the counter-trend bucket (the filter target);
  b) >=5 pp decisive-WR gap, in the SAME direction, separately WITHIN the BUY
     side and WITHIN the SELL side (a gap that lives only in the side mix is a
     side/regime effect, not a momentum edge);
  c) the gap must also hold in at least one rising-gold sub-period (>=1 day,
     gold up >=0.5%) — an effect that only exists while gold falls is a
     regime bet, not an edge;
  d) no change to P&L/trade worse than -$0.10 vs the current book on the same
     sample; and
  e) a REVIEW/ANALYSIS doc + isolation window before it goes live.
"""


def wilson(k, n, z=WILSON_Z):
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (100 * max(0.0, c - half), 100 * min(1.0, c + half))


def fisher_exact_2x2(a, b, c, d):
    """Two-sided Fisher exact p (method of small p-values) for [[a,b],[c,d]]."""
    n = a + b + c + d
    if min(a + b, c + d, a + c, b + d) == 0:
        return float("nan")

    def lfac(x):
        return math.lgamma(x + 1)

    def p_table(x):
        return math.exp(
            lfac(a + b) + lfac(c + d) + lfac(a + c) + lfac(b + d)
            - lfac(n) - lfac(x) - lfac(a + b - x) - lfac(a + c - x)
            - lfac(b + d - (a + b - x))
        )

    p0 = p_table(a)
    lo = max(0, (a + b) - (b + d))
    hi = min(a + b, a + c)
    total = 0.0
    for x in range(lo, hi + 1):
        px = p_table(x)
        if px <= p0 * (1 + 1e-9):
            total += px
    return min(1.0, total)


def load_trades():
    out = []
    with open(TRADES, newline="") as f:
        for r in csv.DictReader(f):
            try:
                et = datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                continue
            out.append(dict(
                num=int(r["Trade_Num"]), side=r["Trade_Type"].strip(),
                reason=r["Exit_Reason"].strip(), et=et,
                entry=float(r["Entry_Price"]), profit=float(r["Profit"]),
                atr=float(r["ATR_At_Entry"]),
            ))
    out.sort(key=lambda t: t["et"])
    return out


def load_bars():
    bars = []
    with open(LOG, newline="") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
                c = float(r["Close"])
            except (ValueError, KeyError):
                continue
            bars.append((t, c))
    bars.sort()
    return bars


def close_at(bars, times, t):
    i = bisect.bisect_right(times, t) - 1
    return bars[i][1] if i >= 0 else None


def annotate(trades, bars):
    times = [b[0] for b in bars]
    for tr in trades:
        t_eff = tr["et"] - timedelta(minutes=1)   # feed lags trades.csv ~1 min
        c_now = close_at(bars, times, t_eff)
        tr["c_now"] = c_now
        for win in MOMENTUM_WINDOWS:
            c_prev = close_at(bars, times, t_eff - timedelta(minutes=win))
            tr[f"m{win}"] = (c_now - c_prev) if (c_now is not None and c_prev is not None) else None
        day0 = datetime(tr["et"].year, tr["et"].month, tr["et"].day)
        c_day = close_at(bars, times, day0)
        tr["m_day"] = (c_now - c_day) if (c_now is not None and c_day is not None) else None
    return trades


def stats(rows):
    tp = sum(1 for r in rows if r["reason"] == "TP")
    sl = sum(1 for r in rows if r["reason"] == "SL")
    be = sum(1 for r in rows if r["reason"] == "BE")
    ti = sum(1 for r in rows if r["reason"] == "TIME")
    pnl = sum(r["profit"] for r in rows)
    n = len(rows)
    dec = 100 * tp / (tp + sl) if tp + sl else 0.0
    lo, hi = wilson(tp, tp + sl)
    return dict(n=n, tp=tp, sl=sl, be=be, time=ti, dec=dec, lo=lo, hi=hi,
                pnl=pnl, ppt=pnl / n if n else 0.0)


def line(label, s, width=42):
    if s["n"] == 0:
        print(f"  {label:{width}s}  (no trades)")
        return
    print(f"  {label:{width}s}  n={s['n']:3d} W={s['tp']:2d} L={s['sl']:2d} BE={s['be']:3d} "
          f"dec={s['dec']:5.1f}% [{s['lo']:4.1f}-{s['hi']:4.1f}] "
          f"P&L={s['pnl']:+8.2f} $/trade={s['ppt']:+6.2f}")


def fisher_between(ra, rb):
    sa, sb = stats(ra), stats(rb)
    if (sa["tp"] + sa["sl"]) == 0 or (sb["tp"] + sb["sl"]) == 0:
        return float("nan")
    return fisher_exact_2x2(sa["tp"], sa["sl"], sb["tp"], sb["sl"])


def pfmt(p):
    return "n/a" if (p is None or math.isnan(p)) else f"{p:.4f}"


def section(title):
    print()
    print("=" * 108)
    print(title)
    print("=" * 108)


def main():
    trades = annotate(load_trades(), load_bars())
    if not trades:
        print("no trades in the ledger — nothing to analyse")
        return

    bars = load_bars()
    first, last = trades[0]["et"], trades[-1]["et"]
    print(f"Momentum / regime report — {len(trades)} trades "
          f"({first} -> {last}), {len(bars)} bars")
    print("Momentum = close-to-close change strictly before entry (entry-1 min "
          "lag allowance). Decisive WR excludes BE/TIME.")

    # ---------------------------------------------------------------- 1
    section("1. DAY LEVEL — gold's calendar-day change vs that day's trades")
    day_open, day_last = {}, {}
    for t, c in bars:
        d = t.date()
        day_open.setdefault(d, c)
        day_last[d] = c
    by_day = defaultdict(list)
    for tr in trades:
        by_day[tr["et"].date()].append(tr)
    print("  day         gold%   n   W  L  BE   dec%     P&L")
    day_rows = []
    for d in sorted(by_day):
        if d not in day_last:
            continue
        s = stats(by_day[d])
        g = 100 * (day_last[d] - day_open[d]) / day_open[d]
        day_rows.append((g, s))
        print(f"  {d}  {g:+7.2f}%  {s['n']:3d}  {s['tp']:2d} {s['sl']:2d} {s['be']:3d}  "
              f"{s['dec']:5.1f}   {s['pnl']:+8.2f}")
    down = [r for r in day_rows if r[0] < 0]
    up = [r for r in day_rows if r[0] >= 0]

    def agg(rs):
        tp = sum(r[1]["tp"] for r in rs)
        sl = sum(r[1]["sl"] for r in rs)
        be = sum(r[1]["be"] for r in rs)
        n = sum(r[1]["n"] for r in rs)
        pnl = sum(r[1]["pnl"] for r in rs)
        return tp, sl, be, n, pnl

    for lab, rs in (("DOWN days (gold fell)", down), ("UP days (gold rose/flat)", up)):
        tp, sl, be, n, pnl = agg(rs)
        dec = 100 * tp / (tp + sl) if tp + sl else 0.0
        print(f"  {lab:24s} days={len(rs):2d} trades={n:3d} W={tp:2d} L={sl:2d} BE={be:3d} "
              f"dec={dec:5.1f}%  P&L={pnl:+8.2f}  $/trade={(pnl / n if n else 0):+6.2f}")

    # ---------------------------------------------------------------- 2
    section("2. PRE-ENTRY MOMENTUM — falling vs rising tape (pooled, all data)")
    for win in MOMENTUM_WINDOWS:
        key = f"m{win}"
        fall = [t for t in trades if t.get(key) is not None and t[key] < 0]
        rise = [t for t in trades if t.get(key) is not None and t[key] >= 0]
        print(f"- last {win} min")
        line("price FALLING", stats(fall))
        line("price rising/flat", stats(rise))
        print(f"    Fisher p (W/L falling vs rising) = {pfmt(fisher_between(fall, rise))}")
    fall = [t for t in trades if t.get("m_day") is not None and t["m_day"] < 0]
    rise = [t for t in trades if t.get("m_day") is not None and t["m_day"] >= 0]
    print("- since 00:00 UTC")
    line("price FALLING", stats(fall))
    line("price rising/flat", stats(rise))
    print(f"    Fisher p = {pfmt(fisher_between(fall, rise))}")

    # ---------------------------------------------------------------- 3
    section("3. SIDE DECOMPOSITION — the driver (momentum ~ side, see §4)")
    eras = [("all data", None), ("0.75R era (>=09-15 06:00)", ERA_075R),
            ("max-hold era (>=09-21 06:00)", ERA_MAXHOLD)]
    for lab, start in eras:
        rows = [t for t in trades if start is None or t["et"] >= start]
        b = [t for t in rows if t["side"] == "BUY"]
        s = [t for t in rows if t["side"] == "SELL"]
        print(f"- {lab}")
        line("BUY", stats(b))
        line("SELL", stats(s))
        print(f"    Fisher p (BUY vs SELL W/L) = {pfmt(fisher_between(b, s))}")

    print()
    print("  Side composition per momentum bucket (why 2 collapses into 3):")
    for lab, cond in (("falling 60m", lambda t: t.get("m60") is not None and t["m60"] < 0),
                      ("rising 60m ", lambda t: t.get("m60") is not None and t["m60"] >= 0)):
        rows = [t for t in trades if cond(t)]
        nb = sum(1 for t in rows if t["side"] == "BUY")
        if rows:
            print(f"    {lab}: n={len(rows):3d}  BUY={nb:3d} ({100 * nb / len(rows):3.0f}%)  "
                  f"SELL={len(rows) - nb:3d}")

    # ---------------------------------------------------------------- 4
    section("4. WITHIN-SIDE MOMENTUM — is 'falling price' good per se? (refutation)")
    for side in ("BUY", "SELL"):
        rows = [t for t in trades if t["side"] == side and t.get("m60") is not None]
        fall = [t for t in rows if t["m60"] < 0]
        rise = [t for t in rows if t["m60"] >= 0]
        print(f"- {side}")
        line("falling 60m", stats(fall))
        line("rising 60m", stats(rise))
        print(f"    Fisher p = {pfmt(fisher_between(fall, rise))}")

    # ---------------------------------------------------------------- 5
    section("5. TREND ALIGNMENT — entering WITH the 240-min move?")
    def aligned(t):
        m = t.get("m240")
        if m is None:
            return None
        return (t["side"] == "SELL" and m < 0) or (t["side"] == "BUY" and m >= 0)
    with_t = [t for t in trades if aligned(t) is True]
    against = [t for t in trades if aligned(t) is False]
    line("aligned with 240m move", stats(with_t))
    line("against 240m move", stats(against))
    print(f"    Fisher p = {pfmt(fisher_between(with_t, against))}")
    for side in ("BUY", "SELL"):
        line(f"  aligned {side}", stats([t for t in with_t if t["side"] == side]))
    for side in ("BUY", "SELL"):
        line(f"  against {side}", stats([t for t in against if t["side"] == side]))

    # ---------------------------------------------------------------- 6
    section("6. UP-DAY COUNTER-CASES — days gold rose >= +0.5%, split by side")
    up_days = [d for d in sorted(by_day)
               if d in day_last and day_last[d] > day_open[d]
               and 100 * (day_last[d] - day_open[d]) / day_open[d] >= 0.5]
    if not up_days:
        print("  no up-days >= +0.5% in the book yet")
    for d in up_days:
        rows = by_day[d]
        g = 100 * (day_last[d] - day_open[d]) / day_open[d]
        s_all = stats(rows)
        print(f"- {d} (gold {g:+.2f}%)  n={s_all['n']}  dec={s_all['dec']:.1f}%  P&L={s_all['pnl']:+.2f}")
        for side in ("BUY", "SELL"):
            line(f"  {side}", stats([t for t in rows if t["side"] == side]))

    # ---------------------------------------------------------------- 7
    section("7. CHUNKED STABILITY — falling-vs-rising 60m gap over calendar chunks")
    if trades:
        start = trades[0]["et"].date()
        end = trades[-1]["et"].date()
        lo = datetime(start.year, start.month, start.day)
        print("  chunk                 falling 60m                    rising 60m")
        while lo.date() <= end:
            hi = lo + timedelta(days=5)
            rows = [t for t in trades if lo <= t["et"] < hi and t.get("m60") is not None]
            if rows:
                f = stats([t for t in rows if t["m60"] < 0])
                r = stats([t for t in rows if t["m60"] >= 0])
                print(f"  {lo.date()}..{(hi - timedelta(days=1)).date()}  "
                      f"n={f['n']:3d} dec={f['dec']:5.1f}% $/t={f['ppt']:+5.2f}      "
                      f"n={r['n']:3d} dec={r['dec']:5.1f}% $/t={r['ppt']:+5.2f}")
            lo = hi

    # ---------------------------------------------------------------- 8
    section("8. PRE-REGISTERED BAR (registered 2026-09-28 — do not re-slice)")
    print(PREREGISTERED_BAR)
    print()
    print("Reminder: the max-hold isolation window ends ~2026-10-05. No entry-")
    print("filter change of any kind lands before that re-review (HANDOFF §6).")


if __name__ == "__main__":
    main()
