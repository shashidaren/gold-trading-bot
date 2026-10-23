#!/usr/bin/env python3
"""journal_report.py — the bot's self-journal and success rate, printed.

Owner ask (2026-10-23): "self journal the buy/sell and see the success rate".

Reads the tracked files (`forward_test_log.csv`, `trades.csv`,
`skipped_trades.csv`, `status.json`) and rebuilds every decision with:

  * the engine's own context at the bar it acted on (RSI, ATR, wick, EMAs,
    distance to the 20-bar level),
  * the candidate-indicator snapshot (ADX, MACD, Bollinger, Stochastic, Keltner,
    Donchian, efficiency ratio, ATR percentile, RVOL, candle anatomy),
  * the outcome and the honest success accounting (decisive WR with a Wilson CI,
    all-in rate, R/trade, payoff, profit factor, drawdown, streaks),
  * what the journal noticed: scratches that were once +0.75R ahead, stop-outs
    that gave a gain back, winners that survived heat,
  * the open trade as an unfinished entry,
  * a measured scoreboard of every candidate indicator on these entries, with a
    permutation guard so a lucky bucket cannot be mistaken for an edge.

Read-only. Nothing here becomes an entry rule. A candidate that survives the
scoreboard still needs a dated pre-registration and out-of-sample confirmation
before any engine change (docs/HANDOFF.md §11).

Usage:
    python3 tools/journal_report.py                     # the whole journal
    python3 tools/journal_report.py --root DIR          # another checkout/data dir
    python3 tools/journal_report.py --permutations 0    # skip the noise floor (faster)
    python3 tools/journal_report.py --board-era all     # scoreboard on all eras
    python3 tools/journal_report.py --csv journal.csv   # flat per-trade export
    python3 tools/journal_report.py --json
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import journal as J  # noqa: E402
import pressure as P  # noqa: E402


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="Self-journal every BUY/SELL and report the success rate.")
    ap.add_argument("--root", default=".", help="directory holding the tracked CSVs (default: .)")
    ap.add_argument("--cost", type=float, default=J.COST_USD,
                    help="assumed round-trip cost in $ per trade (default: 0.40)")
    ap.add_argument("--permutations", type=int, default=200,
                    help="permutation draws for the indicator noise floor (0 = skip)")
    ap.add_argument("--board-era", choices=("structstop", "pre", "all"), default="structstop",
                    help="which entries the indicator scoreboard is measured on")
    ap.add_argument("--recent", type=int, default=J.RECENT_N, help="recent entries to print")
    ap.add_argument("--csv", help="write a flat per-trade journal CSV to this path")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    paths = {
        "log": os.path.join(root, "forward_test_log.csv"),
        "trades": os.path.join(root, "trades.csv"),
        "skips": os.path.join(root, "skipped_trades.csv"),
        "status": os.path.join(root, "status.json"),
    }
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    if missing:
        print("Missing input file(s): " + ", ".join(missing), file=sys.stderr)
        return 2

    status = None
    try:
        with open(paths["status"], encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"status.json unreadable ({exc}); the open trade will be omitted", file=sys.stderr)

    report = J.build(P.read_rows(paths["log"]), P.read_rows(paths["trades"]),
                     status, P.read_rows(paths["skips"]), cost=args.cost, permutations=0)
    if args.board_era == "structstop":
        scored = [e for e in report["entries"] if e["era"] == "struct-stop"]
    elif args.board_era == "pre":
        scored = [e for e in report["entries"] if e["era"] != "struct-stop"]
    else:
        scored = report["entries"]
    report["board_era"] = args.board_era
    if args.permutations >= 0 and scored:
        report["board"] = J.indicator_board(scored, permutations=max(0, args.permutations))
    report["recent"] = list(reversed(report["entries"][-max(1, args.recent):]))

    if args.csv:
        path = os.path.abspath(args.csv)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(J.entries_csv(report["entries"]))
        print(f"wrote {len(report['entries'])} journal rows to {path}", file=sys.stderr)

    if args.json:
        view = J.dashboard_view(report)
        view["board_era"] = args.board_era
        print(json.dumps(_jsonable(view), indent=2))
        return 0

    lines = J.report_lines(report)
    lines.insert(2, f"scoreboard: {args.board_era} entries")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
