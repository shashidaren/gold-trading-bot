#!/usr/bin/env python3
"""indicator_lab.py — do any MORE indicators improve this bot? Measured, not guessed.

Owner ask (2026-10-23): "need help with the indicators — if there's any more we
can add to further improve".

The repo's rule is that an indicator earns its place by measurement, never by
popularity (docs/PROPOSAL-2026-10-23-manual-chart-tab.md). This tool answers the
question in three separate ways, because they can disagree:

  1. ON THE BOT'S OWN ENTRIES — every closed trade is a full 8/8 signal. For
     each candidate, a pre-declared split (indicators.SPLITS) puts the entries
     into two buckets and compares decisive WR, R/trade and costed $/trade.
     A permutation test shuffles outcomes 200 times and reports the best lift
     random labels produce across all features; a feature only counts if the
     real lift clears that family-wise noise floor. Split-half stability and
     redundancy against RSI/ATR/EMA/side are checked too.

  2. ON THE WHOLE TAPE — each indicator is turned into its own deterministic
     direction call (MACD histogram sign, +DI vs -DI, %K vs %D, ...) and walked
     forward over non-overlapping 30-minute windows, censored at log gaps. Hit
     rate with a Wilson CI vs the 50% driftless reference. Nine rules = nine
     looks, so the report also prints the Bonferroni line.

  3. WHEN DOES THE TAPE MOVE? — the same indicators split the tape by regime
     and compare median |drift| (and the share of moves ≥ 1 ATR). This is the
     one place a "more indicators" idea can survive without predicting
     direction: it might predict *opportunity*, and that would matter for
     sizing/hold research later.

WHAT THIS IS NOT
    Not a gate, not a sizing input, not a reason to touch engine.py. A result
    here is a hypothesis to pre-register, not a change (docs/HANDOFF.md §11).
    Read-only, stdlib only, exits 0.

Usage:
    python3 tools/indicator_lab.py                      # board on struct-stop entries + tape
    python3 tools/indicator_lab.py --root DIR
    python3 tools/indicator_lab.py --era all            # scoreboard on every era
    python3 tools/indicator_lab.py --tape-era all --horizon 30 --stride 30
    python3 tools/indicator_lab.py --permutations 500
    python3 tools/indicator_lab.py --json
"""
import argparse
import bisect
import json
import math
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import indicators as IND  # noqa: E402
import journal as J  # noqa: E402
import pressure as P  # noqa: E402

HORIZON_MIN = 30
STRIDE = 30
MAX_GAP_MIN = 5.0
TAIL_SLACK_MIN = 2.0
MIN_COVER = 0.8
MIN_SAMPLES = 60


# ─────────────────────────────────────────────────────────────────────────────
# tape walk-forward (causal: the call is made on bar i, the drift is measured
# strictly after it, and a window that spans a log gap is censored, not guessed)
# ─────────────────────────────────────────────────────────────────────────────

def forward_end(series, i, horizon=HORIZON_MIN):
    ts = series["ts"]
    end = ts[i] + timedelta(minutes=horizon)
    j = bisect.bisect_right(ts, end)
    if j <= i + 1:
        return None
    prev = ts[i]
    for k in range(i + 1, j):
        if (ts[k] - prev).total_seconds() / 60.0 > MAX_GAP_MIN:
            return None
        prev = ts[k]
    if (end - ts[j - 1]).total_seconds() / 60.0 > TAIL_SLACK_MIN:
        return None
    if (j - i - 1) < MIN_COVER * horizon:
        return None
    return j - 1


def _g(series, key, i):
    vals = series.get(key)
    return vals[i] if vals is not None else None


def direction_call(series, rule, i):
    """+1 BUY, -1 SELL, 0 no call. Every input is at bar i or earlier."""
    close = series["close"][i]
    if rule == "trend_baseline":
        a, b = _g(series, "ema50", i), _g(series, "ema200", i)
        return 0 if a is None or b is None or a == b else (1 if a > b else -1)
    if rule == "macd":
        h = _g(series, "macd_hist", i)
        return 0 if h is None or h == 0 else (1 if h > 0 else -1)
    if rule == "adx_di":
        adx, pdi, mdi = _g(series, "adx", i), _g(series, "plus_di", i), _g(series, "minus_di", i)
        if adx is None or pdi is None or mdi is None or adx < 20 or pdi == mdi:
            return 0
        return 1 if pdi > mdi else -1
    if rule == "stoch":
        k, d = _g(series, "stoch_k", i), _g(series, "stoch_d", i)
        return 0 if k is None or d is None or k == d else (1 if k > d else -1)
    if rule == "bb_momentum":
        b = _g(series, "bb_pct_b", i)
        return 0 if b is None or b == 0.5 else (1 if b > 0.5 else -1)
    if rule == "bb_fade":
        b = _g(series, "bb_pct_b", i)
        if b is None:
            return 0
        return -1 if b >= 0.95 else (1 if b <= 0.05 else 0)
    if rule == "donchian":
        pos = _g(series, "donchian_pos", i)
        return 0 if pos is None or pos == 0.5 else (1 if pos > 0.5 else -1)
    if rule == "er_direction":
        er = _g(series, "er30", i)
        if er is None or er < 0.3 or i < 30:
            return 0
        past = series["close"][i - 30]
        if past is None or close == past:
            return 0
        return 1 if close > past else -1
    if rule == "rsi_slope":
        s = _g(series, "rsi_slope", i)
        return 0 if s is None or s == 0 else (1 if s > 0 else -1)
    if rule == "body":
        o = series["open"][i]
        return 0 if o is None or close is None or close == o else (1 if close > o else -1)
    return 0


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def tape_walk(series, start=None, end=None, horizon=HORIZON_MIN, stride=STRIDE):
    """Sample the tape, call each rule, measure the forward drift in ATR."""
    n = series["n"]
    ts = series["ts"]
    rows = []
    for i in range(0, n, max(1, stride)):
        if start is not None and ts[i] < start:
            continue
        if end is not None and ts[i] >= end:
            continue
        atr = _g(series, "atr_logged", i)
        if atr is None or atr <= 0:
            continue
        j = forward_end(series, i, horizon)
        if j is None:
            continue
        drift = (series["close"][j] - series["close"][i]) / atr
        rows.append((i, j, drift, atr))

    by_rule = {}
    for rule in IND.DIRECTIONAL_RULES:
        samples = []
        for i, j, drift, atr in rows:
            call = direction_call(series, rule, i)
            if call == 0:
                continue
            samples.append((call * drift, drift, atr, ts[i]))
        n_r = len(samples)
        hits = sum(1 for d, *_ in samples if d > 0)
        med_fav = _median([d for d, *_ in samples])
        med_abs = _median([abs(d) for _, d, _, _ in samples])
        # split-half stability of the hit rate
        half = n_r // 2
        h1 = [d for d, *_ in samples[:half]]
        h2 = [d for d, *_ in samples[half:]]
        hit1 = (100.0 * sum(1 for d in h1 if d > 0) / len(h1)) if h1 else None
        hit2 = (100.0 * sum(1 for d in h2 if d > 0) / len(h2)) if h2 else None
        lb, ub = P.wilson_interval(hits, n_r) if n_r else (None, None)
        by_rule[rule] = {
            "label": IND.DIRECTIONAL_RULES[rule][0], "rule": IND.DIRECTIONAL_RULES[rule][1],
            "status": IND.DIRECTIONAL_RULES[rule][2], "n": n_r, "hits": hits,
            "hit_pct": (100.0 * hits / n_r) if n_r else None, "hit_ci": (lb, ub),
            "median_fav_atr": med_fav, "median_abs_atr": med_abs,
            "half1": hit1, "half2": hit2,
            "stable": (hit1 is not None and hit2 is not None
                       and ((hit1 > 50) == (hit2 > 50))),
        }

    always_buy = sum(1 for _, _, d, _ in rows if d > 0)
    baseline = {
        "n": len(rows),
        "buy_pct": (100.0 * always_buy / len(rows)) if rows else None,
        "buy_ci": P.wilson_interval(always_buy, len(rows)) if rows else (None, None),
        "median_abs_atr": _median([abs(d) for _, _, d, _ in rows]),
        "median_drift_atr": _median([d for _, _, d, _ in rows]),
    }

    # regime table: does the feature say the tape will MOVE (not which way)?
    regime = []
    for key in ("adx", "bb_bandwidth", "er30", "atr_pct", "rvol", "stoch_k",
                "bb_pct_b", "keltner_pos", "rsi_slope", "body_atr", "close_loc"):
        rule = IND.SPLITS.get(key)
        values = [_g(series, key, i) for i, _, _, _ in rows]
        if rule is None:
            rule = IND.split_value(key, values)
        if rule is None:
            continue
        hi = [abs(rows[k][2]) for k in range(len(rows)) if values[k] is not None and values[k] >= rule]
        lo = [abs(rows[k][2]) for k in range(len(rows)) if values[k] is not None and values[k] < rule]
        if len(hi) < MIN_SAMPLES or len(lo) < MIN_SAMPLES:
            continue
        regime.append({
            "key": key, "label": IND.describe(key)["label"], "split": rule,
            "high_n": len(hi), "low_n": len(lo),
            "high_median_abs_atr": _median(hi), "low_median_abs_atr": _median(lo),
            "high_move_pct": 100.0 * sum(1 for v in hi if v >= 1.0) / len(hi),
            "low_move_pct": 100.0 * sum(1 for v in lo if v >= 1.0) / len(lo),
            "diff": (_median(hi) or 0) - (_median(lo) or 0),
        })
    regime.sort(key=lambda r: -abs(r["diff"]))
    return {"rows": len(rows), "baseline": baseline, "rules": by_rule, "regime": regime,
            "horizon": horizon, "stride": stride}


# ─────────────────────────────────────────────────────────────────────────────
# verdicts
# ─────────────────────────────────────────────────────────────────────────────

def tape_verdict(walk, rules_tested=None):
    rules_tested = rules_tested or len(walk["rules"])
    bonferroni = 0.05 / max(1, rules_tested)
    passing = []
    for rule, r in walk["rules"].items():
        if r["n"] < MIN_SAMPLES or r["hit_pct"] is None:
            continue
        lb = r["hit_ci"][0]
        p_one = 0.5 * math.erfc((r["hit_pct"] / 100.0 - 0.5) * math.sqrt(r["n"]))
        if lb is not None and lb > 50.0 and p_one < bonferroni and r["stable"]:
            passing.append((rule, r))
    if passing:
        names = ", ".join(f"{r['label']} ({r['hit_pct']:.1f}%, LB {r['hit_ci'][0]:.1f}%)"
                          for _, r in passing)
        return (f"{len(passing)} directional rule(s) clear the 50% reference even after a "
                f"Bonferroni correction for {rules_tested} looks: {names}. That is a "
                f"hypothesis to pre-register and confirm out of sample — not an entry rule."), passing
    return (f"None of {rules_tested} directional rules beats a coin flip on the forward "
            f"{walk['horizon']}-minute drift after correcting for the number of looks. "
            f"These indicators describe the tape; they do not predict it."), passing


# ─────────────────────────────────────────────────────────────────────────────
# printing
# ─────────────────────────────────────────────────────────────────────────────

def _pct(v, d=1):
    return "—" if v is None else f"{v:.{d}f}%"


def _num(v, d=2, sign=True):
    if v is None:
        return "—"
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def print_report(report, walk, args, parity):
    rev = report["entries"]
    era = [e for e in rev if e["era"] == "struct-stop"] if args.era == "structstop" else (
        [e for e in rev if e["era"] != "struct-stop"] if args.era == "pre" else rev)
    print("INDICATOR LAB — which candidates add information, measured on this repo's tape")
    print(f"data through {report['as_of']:%Y-%m-%d %H:%M} · cost ${args.cost:.2f} round trip · "
          f"board era: {args.era} ({len(era)} closed, "
          f"{sum(1 for e in era if e['reason'] in ('TP', 'SL'))} decisive)")
    print("")
    print("0. DATA CHECK")
    print(f"   bars {report['series']['n']:,} · trades joined {len(rev)} · unparsed ledger rows "
          f"{report['unparsed_rows']}")
    print(f"   engine-column parity (logged vs recomputed, median |diff|): "
          f"ATR {parity['atr']['median_abs_diff']} · RSI {parity['rsi']['median_abs_diff']} · "
          f"EMA50 {parity['ema50']['median_abs_diff']} · EMA200 {parity['ema200']['median_abs_diff']}")
    print("   (the engine logs indicators BEFORE updating them, so parity compares row i with i−1;")
    print("    EMA200 can show a few dollars of restart-seeding drift — it is not used for any test)")
    print("")

    board = report.get("board") or J.indicator_board(era, permutations=0)
    print("1. ON THE BOT'S OWN ENTRIES — does a filter split the outcomes?")
    print(f"   {board['n_entries']} closed / {board['n_decisive']} decisive · "
          f"{board['permutations']} permutations · family-wise alpha {board['alpha']}")
    print("   feature                     split       high bucket           low bucket          lift   verdict")
    for r in board["rows"]:
        hi, lo = r["high"], r["low"]
        print(f"   {r['label'][:27]:<27} {r['high_label'][:10]:<10} "
              f"{_pct(hi['wr'], 0):>5} ({hi['decisive']:>3} dec)   "
              f"{_pct(lo['wr'], 0):>5} ({lo['decisive']:>3} dec)   "
              f"{_num(r['lift'], 1):>6} pp  {r['verdict']}")
    for sk in board.get("skipped", []):
        print(f"   {sk['label'][:27]:<27} not testable: {sk['reason']}")
    if board["p_global_wr"] is not None:
        print(f"   best lift {_num(board['observed_max_lift_pp'], 1)} pp vs the 95th percentile of "
              f"random-label best lifts {_num(board['null_max_lift_95_pp'], 1)} pp "
              f"(global p={board['p_global_wr']:.3f})")
        print(f"   best R/trade lift {_num(board['observed_max_r_lift'], 3)}R vs random "
              f"{_num(board['null_max_r_lift_95'], 3)}R (global p={board['p_global_r']:.3f})")
    print(f"   VERDICT: {board['verdict']}")
    print("")

    print(f"2. ON THE WHOLE TAPE — {walk['horizon']}-min forward drift, "
          f"non-overlapping every {walk['stride']} bars, gaps censored")
    b = walk["baseline"]
    print(f"   sample {b['n']} windows · always-BUY hit rate {_pct(b['buy_pct'])} "
          f"[{_pct(b['buy_ci'][0])}–{_pct(b['buy_ci'][1])}] · median |drift| "
          f"{_num(b['median_abs_atr'], 2, False)} ATR · median drift {_num(b['median_drift_atr'])} ATR")
    print("   rule                     n      hit% [95% CI]          median fav   halves      verdict")
    verdict, passing = tape_verdict(walk)
    for rule, r in walk["rules"].items():
        if r["n"] < MIN_SAMPLES:
            continue
        ci = r["hit_ci"]
        tag = "clears" if any(rule == p[0] for p in passing) else (
            "coin flip" if ci[0] is not None and ci[0] <= 50.0 <= ci[1] else "—")
        print(f"   {r['label'][:24]:<24} {r['n']:>5}  {_pct(r['hit_pct']):>5} "
              f"[{_pct(ci[0])}–{_pct(ci[1])}]   {_num(r['median_fav_atr']):>7} ATR   "
              f"{_pct(r['half1'], 0):>4}/{_pct(r['half2'], 0):<4}  {tag}")
    print(f"   VERDICT: {verdict}")
    print("")

    print("3. WHEN DOES THE TAPE MOVE? — regime buckets vs |drift| (direction-free)")
    print("   feature                     split      high: |drift| ATR  ≥1 ATR    low: |drift| ATR  ≥1 ATR")
    for r in walk["regime"][:8]:
        print(f"   {r['label'][:27]:<27} {r['split']:<9.3g}  "
              f"{_num(r['high_median_abs_atr'], 2, False):>7} ({r['high_n']:,})   "
              f"{_pct(r['high_move_pct'], 0):>4}    "
              f"{_num(r['low_median_abs_atr'], 2, False):>7} ({r['low_n']:,})   "
              f"{_pct(r['low_move_pct'], 0):>4}")
    print("   (a regime read is not a direction read. It can size or pace a trade; it cannot pick one.)")
    print("")
    print("HOW TO USE THIS")
    print("   Nothing above is an entry rule, and nothing was added to engine.py. A candidate that")
    print("   clears the noise floor becomes a dated pre-registration with an out-of-sample split;")
    print("   everything else stays journal context. Re-run after the sample roughly doubles.")
    return 0


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure whether more indicators add information.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--cost", type=float, default=J.COST_USD)
    ap.add_argument("--era", choices=("structstop", "pre", "all"), default="structstop",
                    help="entries for the scoreboard (default: structstop)")
    ap.add_argument("--tape-era", choices=("all", "structstop", "pre"), default="all",
                    help="tape span for the forward walk (default: all)")
    ap.add_argument("--horizon", type=int, default=HORIZON_MIN)
    ap.add_argument("--stride", type=int, default=STRIDE)
    ap.add_argument("--permutations", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    log = os.path.join(root, "forward_test_log.csv")
    trades = os.path.join(root, "trades.csv")
    skips = os.path.join(root, "skipped_trades.csv")
    status_file = os.path.join(root, "status.json")
    if not (os.path.isfile(log) and os.path.isfile(trades)):
        print("Need forward_test_log.csv and trades.csv under --root", file=sys.stderr)
        return 2
    status = None
    try:
        with open(status_file, encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        pass

    report = J.build(P.read_rows(log), P.read_rows(trades), status,
                     P.read_rows(skips) if os.path.isfile(skips) else [],
                     cost=args.cost, permutations=0)
    if args.era == "structstop":
        scored = [e for e in report["entries"] if e["era"] == "struct-stop"]
    elif args.era == "pre":
        scored = [e for e in report["entries"] if e["era"] != "struct-stop"]
    else:
        scored = report["entries"]
    report["board"] = J.indicator_board(scored, permutations=max(0, args.permutations))
    report["board_era"] = args.era

    start = end = None
    if args.tape_era == "structstop":
        start = J.CUTOVER
    elif args.tape_era == "pre":
        end = J.CUTOVER
    walk = tape_walk(report["series"], start=start, end=end,
                     horizon=args.horizon, stride=args.stride)

    parity = IND.engine_parity(report["series"])
    if args.json:
        payload = {"as_of": report["as_of"], "cost": args.cost, "era": args.era,
                   "tape_era": args.tape_era, "parity": parity, "board": report["board"],
                   "tape": walk}
        print(json.dumps(_jsonable(payload), indent=2))
        return 0
    return print_report(report, walk, args, parity)


if __name__ == "__main__":
    sys.exit(main())
