#!/usr/bin/env python3
"""tools/stop_hunt_markout.py — descriptive stop-hunt mark-outs (2026-10-25)

Read-only. Reads trades.csv + forward_test_log.csv and measures, for the
structural-stop era (entries >= strategy_lab.LIVE_CUTOVER), how the tape behaves
around the stop: pre-exit hovers near the stop level, how fast a stopped price
returns to entry, how deep the "hunt" goes past the stop before a fast bounce,
and the full stop -> bounce -> target signature.

DESIGN RULES (docs/EXECUTION-PLAN.md guardrails):
- Every number here is a BOUNDED mark-out (24 h horizon, observed log bars only —
  gaps are never bridged). It is a description, not a rule: nothing here may be
  turned into an entry/hold/stop change without a costed strategy_lab replay and
  a dated pre-registration.
- Ratcheted rows (Stop_Loss == Entry_Price) recover the original stop from the
  reward leg: risk = |TP - Entry| / RR_TARGET (HANDOFF "Definitions (binding)").
- Trade_Num is NOT a key (duplicate #697 exists since the 10-23 sync); rows are
  processed positionally.

Usage:  python3 tools/stop_hunt_markout.py [--era structstop|all]
"""
import argparse
import bisect
import csv
import os
import statistics
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES = os.path.join(HERE, "trades.csv")
LOG = os.path.join(HERE, "forward_test_log.csv")
HORIZON_MIN = 24 * 60          # bounded mark-out horizon
FAST_BOUNCE_MIN = 15           # "tag and bounce" definition
RR_TARGET = 1.5                # engine TP = 1.5 x actual risk


def load_log(path=LOG):
    ts, highs, lows = [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            ts.append(row["Timestamp"])
            highs.append(float(row["High"]))
            lows.append(float(row["Low"]))
    return ts, highs, lows


def load_era_trades(path=TRADES, cutover="__default__"):
    if cutover == "__default__":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import strategy_lab  # LIVE_CUTOVER must stay the single source of truth
        cutover = strategy_lab.LIVE_CUTOVER.strftime("%Y-%m-%d %H:%M")
    out = []
    with open(path) as f:
        for row in csv.DictReader(f):
            if cutover == "" or row["Entry_Time"] >= cutover:
                out.append(row)
    return out


def risk_of(t):
    """Actual risk; ratcheted rows recover it from the reward leg."""
    e = float(t["Entry_Price"]); sl = float(t["Stop_Loss"]); tp = float(t["Take_Profit"])
    return abs(tp - e) / RR_TARGET if abs(e - sl) < 1e-9 else abs(e - sl)


def orig_stop(t):
    e = float(t["Entry_Price"]); sl = float(t["Stop_Loss"]); r = risk_of(t)
    if abs(e - sl) < 1e-9:
        return e - r if t["Trade_Type"] == "BUY" else e + r
    return sl


def mts(ts):
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", choices=["structstop", "all"], default="structstop",
                    help="structstop = entries >= LIVE_CUTOVER (default)")
    args = ap.parse_args()

    ts, H, L = load_log()
    N = len(ts)

    def idx(s):
        return bisect.bisect_left(ts, s)

    def addmin(s, m):
        return (mts(s) + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")

    rows = load_era_trades(cutover="" if args.era == "all" else "__default__")
    sl = [t for t in rows if t["Exit_Reason"] == "SL"]
    tp = [t for t in rows if t["Exit_Reason"] == "TP"]
    be = [t for t in rows if t["Exit_Reason"] == "BE"]

    era_lbl = "all entries" if args.era == "all" else "structural-stop era (entries >= LIVE_CUTOVER)"
    print(f"stop-hunt mark-outs — {len(rows)} trades, {era_lbl} | data through {ts[-1]} "
          f"| outcomes {len(tp)}W/{len(sl)}L/{len(be)}BE | horizon {HORIZON_MIN // 60} h, observed bars only")
    print("DESCRIPTIVE: bounded mark-outs for a dated ANALYSIS, never an entry/hold/stop rule.\n")

    # ------------------------------------------------ 1. pre-exit hover near stop
    print("== 1. Pre-exit hover: price within X of the original stop level before the exit bar ==")
    for band in (0.25, 0.10):
        cells = []
        for name, grp in (("SL", sl), ("TP", tp), ("BE", be), ("ALL", rows)):
            h = n = 0
            for t in grp:
                i0, i1 = idx(t["Entry_Time"]), idx(t["Exit_Time"])
                if i0 >= N or i1 <= i0:
                    continue
                n += 1
                S, r = orig_stop(t), risk_of(t)
                if t["Trade_Type"] == "BUY":
                    if any(S < L[j] <= S + band * r for j in range(i0, i1)):
                        h += 1
                elif any(S - band * r <= H[j] < S for j in range(i0, i1)):
                    h += 1
            cells.append(f"{name} {h}/{n} ({100 * h / n:.0f}%)" if n else f"{name} 0")
        print(f"  within {band:.2f}R: " + "  |  ".join(cells))
    print("  (selection caveat: the stop IS the boundary — approaching it is a prerequisite to")
    print("   printing, so this row is context, not a predictor.)")

    # ------------------------------------------------ 2. return to entry + hunt depth
    print(f"\n== 2. After an SL print: time to return to ENTRY (24 h horizon) ==")
    buckets, fast_depths = {}, []
    for t in sl:
        i1 = idx(t["Exit_Time"])
        if i1 >= N:
            continue
        e = float(t["Entry_Price"]); r = risk_of(t)
        end = idx(addmin(t["Exit_Time"], HORIZON_MIN))
        back = (lambda j: H[j] >= e) if t["Trade_Type"] == "BUY" else (lambda j: L[j] <= e)
        S = orig_stop(t)
        depth_before, first_back = 0.0, None
        for j in range(i1, end):
            if first_back is None:
                adverse = (S - L[j]) if t["Trade_Type"] == "BUY" else (H[j] - S)
                depth_before = max(depth_before, adverse)
                if back(j):
                    first_back = j
        if first_back is None:
            buckets["no-return-24h"] = buckets.get("no-return-24h", 0) + 1
            continue
        mins = (mts(ts[first_back]) - mts(t["Exit_Time"])).total_seconds() / 60
        k = (f"<={FAST_BOUNCE_MIN}" if mins <= FAST_BOUNCE_MIN
             else "15-60" if mins <= 60 else "1-4h" if mins <= 240 else "4-24h")
        buckets[k] = buckets.get(k, 0) + 1
        if mins <= FAST_BOUNCE_MIN:
            fast_depths.append(depth_before / r)
    for k in (f"<={FAST_BOUNCE_MIN}", "15-60", "1-4h", "4-24h", "no-return-24h"):
        v = buckets.get(k, 0)
        print(f"  {k:>14}: {v:3d} ({100 * v / max(1, len(sl)):.0f}%)")
    if fast_depths:
        d = sorted(fast_depths)
        print(f"  hunt depth PAST THE STOP before a <={FAST_BOUNCE_MIN}m bounce: "
              f"median {statistics.median(d):.2f}R  p75 {d[3 * len(d) // 4]:.2f}R  max {d[-1]:.2f}R")

    # ------------------------------------------------ 3. full signature
    print(f"\n== 3. Full signature: SL -> back to entry <={FAST_BOUNCE_MIN}m -> TP within 24 h ==")
    sig = b_fast = b_fast_tp = 0
    for t in sl:
        i1 = idx(t["Exit_Time"])
        if i1 >= N:
            continue
        e = float(t["Entry_Price"]); tp_p = float(t["Take_Profit"])
        end = idx(addmin(t["Exit_Time"], HORIZON_MIN))
        back = (lambda j: H[j] >= e) if t["Trade_Type"] == "BUY" else (lambda j: L[j] <= e)
        tphit = (lambda a: any(H[j] >= tp_p for j in range(a, end))) if t["Trade_Type"] == "BUY" \
            else (lambda a: any(L[j] <= tp_p for j in range(a, end)))
        first_back = None
        for j in range(i1, end):
            if back(j):
                first_back = j
                break
        if first_back is None:
            continue
        if (mts(ts[first_back]) - mts(t["Exit_Time"])).total_seconds() / 60 <= FAST_BOUNCE_MIN:
            b_fast += 1
            if tphit(first_back):
                b_fast_tp += 1
                sig += 1
    print(f"  {sig} of {len(sl)} SLs ({100 * sig / max(1, len(sl)):.0f}%) carry the full signature")
    print(f"  of the {b_fast} fast (<={FAST_BOUNCE_MIN}m) bounces, {b_fast_tp} "
          f"({100 * b_fast_tp / max(1, b_fast):.0f}%) reached the TP within 24 h")

    # ------------------------------------------------ 4. symmetry: adversity on winners
    print("\n== 4. Symmetry check: same adversity threatens winners ==")
    c = n = 0
    for t in tp:
        i0, i1 = idx(t["Entry_Time"]), idx(t["Exit_Time"])
        if i0 >= N or i1 <= i0:
            continue
        n += 1
        e = float(t["Entry_Price"]); r = risk_of(t)
        mae = max([0] + ([e - L[j] for j in range(i0, i1 + 1)] if t["Trade_Type"] == "BUY"
                         else [H[j] - e for j in range(i0, i1 + 1)]))
        c += mae / r >= 0.5
    print(f"  of {n} TP wins, {c} ({100 * c / max(1, n):.0f}%) survived an adverse move >= 0.5R before the target")


if __name__ == "__main__":
    main()
