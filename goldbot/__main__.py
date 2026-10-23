#!/usr/bin/env python3
"""goldbot — judge a v2 hypothesis on real bars. Read-only; writes nothing.

    python3 -m goldbot                                   # default H4 hypothesis
    python3 -m goldbot --bars history_utc.csv            # large-N research path
    python3 -m goldbot --compare                         # M15 / H1 / H4 / D1 side by side
    python3 -m goldbot --list                            # what can be replayed

WHY --compare IS THE DEFAULT THING TO RUN
-----------------------------------------
The v2 thesis is that timeframe, not signal quality, is what makes gold untradeable at
M1 — because the round trip is a fixed dollar amount and a tight stop makes it enormous
in R. That is a testable claim, and `--compare` tests it: same signal, same rules, only
the timeframe and the resulting cost share change. If the H4 book is not materially
better than the H1 book, the thesis is wrong and this package is decoration.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

# Absolute imports: this file is `python3 -m goldbot`, where a relative import has no
# package to resolve against. (`python3 -m goldbot.replay` runs the LIBRARY module and
# silently does nothing — use `python3 -m goldbot`.)
from goldbot.config import Config
from goldbot.data import aggregate, load_log
from goldbot.replay import format_report, judge, run
from goldbot.signal import SIGNALS

DEFAULT_LOG = "forward_test_log.csv"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m goldbot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bars", default=DEFAULT_LOG,
                    help=f"bar file in forward_test_log.csv schema (default {DEFAULT_LOG})")
    ap.add_argument("--timeframe", type=int, default=None, help="minutes per bar (default 240)")
    ap.add_argument("--cost", type=float, default=None, help="round-trip cost in $ (default 0.55)")
    ap.add_argument("--signal", default="trend_pullback", choices=sorted(SIGNALS),
                    help="entry hypothesis to replay")
    ap.add_argument("--lookback", type=int, default=None, help="box size in bars")
    ap.add_argument("--rr", type=float, default=None, help="reward:risk target")
    ap.add_argument("--no-ratchet", action="store_true", help="disable the breakeven ratchet")
    ap.add_argument("--min-risk-to-cost", type=float, default=None,
                    help="refuse setups whose risk is under this multiple of the round trip")
    ap.add_argument("--wick", type=float, default=None,
                    help="minimum rejection wick as a share of bar range")
    ap.add_argument("--ema-fast", type=int, default=None)
    ap.add_argument("--ema-slow", type=int, default=None)
    ap.add_argument("--min-stop-atr", type=float, default=None,
                    help="floor on stop distance in ATRs (default 1.5)")
    ap.add_argument("--compare", action="store_true",
                    help="replay M15 / H1 / H4 / D1 with one signal, to isolate the timeframe effect")
    ap.add_argument("--list", action="store_true", help="list the registered signals and exit")
    ap.add_argument("--trades", type=int, default=0, metavar="N",
                    help="print the last N trades with their entry reasons")
    return ap


def config_from(args: argparse.Namespace, timeframe: int | None = None) -> Config:
    cfg = Config(
        timeframe_minutes=timeframe if timeframe is not None else (args.timeframe or Config().timeframe_minutes),
    )
    over = {
        "cost_round_trip": args.cost,
        "lookback": args.lookback,
        "rr_target": args.rr,
        "breakeven_trigger_r": None if args.no_ratchet else cfg.breakeven_trigger_r,
        "min_risk_to_cost": args.min_risk_to_cost,
        "wick_ratio_min": args.wick,
        "ema_fast": args.ema_fast,
        "ema_slow": args.ema_slow,
        "min_stop_atr": args.min_stop_atr,
    }
    cfg = cfg.with_(**{k: v for k, v in over.items() if v is not None})
    # name the hypothesis after what was actually run, so a pasted result carries it
    tf = cfg.timeframe_minutes
    tf_label = f"{tf // 60}h" if tf >= 60 and tf % 60 == 0 else f"{tf}m"
    return cfg.with_(name=f"{args.signal}-{tf_label}")


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        print("registered entry hypotheses:")
        for name, fn in sorted(SIGNALS.items()):
            doc = (fn.__doc__ or "").strip().splitlines()
            print(f"  {name:<18} {doc[0] if doc else ''}")
        print("\nneither is a claim of edge; see goldbot/signal.py")
        return 0

    if not os.path.exists(args.bars):
        print(f"error: no bar file at {args.bars}", file=sys.stderr)
        print("  the live log is forward_test_log.csv; for the large-N path run", file=sys.stderr)
        print("  tools/mt5_history_dump.py | tools/history_to_log.py first", file=sys.stderr)
        return 2

    signal_fn = SIGNALS[args.signal]
    m1 = load_log(args.bars)
    if not m1:
        print(f"error: {args.bars} parsed to zero bars", file=sys.stderr)
        return 2

    timeframes = [15, 60, 240, 1440] if args.compare else [args.timeframe or 240]
    results = []
    for tf in timeframes:
        cfg = config_from(args, timeframe=tf)
        bars = aggregate(m1, tf)
        if len(bars) < cfg.ema_slow + 2:
            print(f"── {cfg.name} ── skipped: only {len(bars)} bars "
                  f"(needs > {cfg.ema_slow} before the slow EMA exists)")
            continue
        res = run(bars, cfg, signal_fn)
        results.append((cfg, res))
        print(format_report(res, cfg))
        print()

    if args.trades:
        for cfg, res in results:
            for t in res.trades[-args.trades:]:
                print(f"  {t.entry_ts:%Y-%m-%d %H:%M} {t.side} @ {t.entry:.2f} "
                      f"stop {t.stop:.2f} target {t.target:.2f} -> {t.reason} {t.exit_price:.2f} "
                      f"({t.r_multiple:+.2f}R, ${t.net:+.2f}) [{t.stop_basis}]")
                for why in t.reasons:
                    print(f"      · {why}")

    if len(results) > 1:
        print("── timeframe comparison (same signal, same rules) ──")
        print(f"  {'tf':<6}{'bars':>7}{'trades':>8}{'dec':>6}{'WR':>8}"
              f"{'med risk':>10}{'cost %R':>9}{'net':>10}{'net/trd':>9}")
        for cfg, res in results:
            v = judge(res, cfg)
            wr = f"{100 * v.win_rate:.1f}%" if v.win_rate is not None else "-"
            share = f"{100 * v.cost_share_of_risk:.1f}%" if v.cost_share_of_risk else "-"
            print(f"  {cfg.name.rsplit('-', 1)[-1]:<6}{res.bars:>7}{v.n_trades:>8}{v.decisive:>6}"
                  f"{wr:>8}{v.median_risk:>10.2f}{share:>9}{v.net:>+10.2f}{v.net_per_trade:>+9.2f}")
        print("\n  the cost %R column is the v2 thesis: if it falls and the book does not")
        print("  improve, the timeframe was not the problem.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
