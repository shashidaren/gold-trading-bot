#!/usr/bin/env python3
"""manual_trade.py — the manual trader's own numbers, and a private decision journal.

WHAT THIS IS FOR
    Everything else in this repo reports on the BOT. This tool answers the four
    questions a human taking a gold trade by hand asks just before clicking:

      1. where does the stop go, and what is 1R worth?
      2. how many lots is that for the money I am willing to lose?
      3. what share of that risk does the spread take (now, and at the median)?
      4. how long until the daily break makes the stop unenforceable?

    and then — optionally — it records what you actually did, in the private journal
    docs/EXECUTION-PLAN.md §7 asks for. Recording the decision BEFORE the outcome is
    the entire point: a journal filled in afterwards measures memory, not method.

WHAT IT DOES NOT DO
    No order, no engine import, no LIVE arming, no gate. It is the same display-only
    layer as the dashboard's Manual tab, plus one host-local append. Nothing it prints
    has been shown to predict direction — the measured base rate for these geometries
    is no edge (0 of 8 box cells, ~74% of breaks close back inside in 15 min, and the
    paper book is negative before costs).

USAGE
    python3 tools/manual_trade.py
        the read: both sides' stop/target/R, the cost share, the size table, the clock

    python3 tools/manual_trade.py --side BUY --entry 3580.63 --stop 3571.89 --budget 10
        one side, your own numbers (--stop optional: the structural stop is proposed)

    python3 tools/manual_trade.py --log-decision --side BUY --entry 3580.63 --stop 3571.89 \
        --reason-code level_retest --action took_it --post-stop 15,30,60
        validate + append ONE row to the private journal (refuses to write in the repo)

    python3 tools/manual_trade.py --journal-summary
        count the rows, split by side and by action — never prints the notes text

    python3 tools/manual_trade.py --json

Exit code 0 for a report. --strict exits 1 when the read is unavailable (no bars).
Reading the private journal is the only thing that touches a file outside the repo,
and --journal-summary prints counts only, never the free-text notes.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import manual_plan as M  # noqa: E402
import pressure as P     # noqa: E402

# Defaults follow the box/readiness tools: the production data dir when it exists,
# otherwise the checkout you are standing in. `--dir` and `--log` win over both.
DATA_DIR = os.getenv("GOLD_DATA_DIR") or ("/opt/gold" if os.path.isdir("/opt/gold") else ROOT)
LOG_FILE = os.getenv("GOLD_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
QUOTE_DIR = os.getenv("GOLD_QUOTE_DIR", os.path.join(DATA_DIR, "xm_data"))
JOURNAL_FILE = os.getenv("GOLD_MANUAL_JOURNAL_FILE",
                         os.path.join(DATA_DIR, "manual_trade_journal.jsonl"))
# The journal must never be able to land in the repo, so when the data dir resolves to
# the checkout the journal falls back to the state dir instead of a subdirectory of it.
if M.inside_repo(JOURNAL_FILE, ROOT):
    JOURNAL_FILE = os.path.join(os.getenv("XDG_STATE_HOME",
                                          os.path.expanduser("~/.local/state")),
                                "gold", "manual_trade_journal.jsonl")
TAIL_ROWS = 9000


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_quotes(qdir, now=None):
    """Today's quote rows (the live-spread source), or [] when the logger is absent."""
    now = now or utcnow()
    path = os.path.join(qdir, "quotes-" + now.strftime("%Y-%m-%d") + ".csv")
    return P.tail_rows(path, 240) if os.path.isfile(path) else []


def build(args, now=None):
    now = now or utcnow()
    rows = P.tail_rows(args.log, TAIL_ROWS, window_bytes=1024 * 1024)
    spec = M.load_spec(args.dir or QUOTE_DIR)
    quotes = today_quotes(args.dir or QUOTE_DIR, now)
    read = M.read(log_rows=rows, quotes=quotes, spec=spec, now=now,
                  spread_rt=args.spread, risk_budgets=_budgets(args.budget))
    return read


def _budgets(single=None):
    if single is None:
        return M.DEFAULT_RISK_BUDGETS
    try:
        value = float(single)
    except (TypeError, ValueError):
        return M.DEFAULT_RISK_BUDGETS
    return (value,) if value > 0 else M.DEFAULT_RISK_BUDGETS


# ───────────────────────────────────────────────────────────────── the read, printed
def _money(value, places=2):
    return "—" if value is None else f"${value:,.{places}f}"


def _lots(value, spec):
    """Lot size with enough decimals for the broker's own step (0.001 since 11-20)."""
    step = (spec or {}).get("volume_step") or M.VOLUME_STEP
    places = 2
    while places < 5 and round(step, places) != step:
        places += 1
    return f"{value:.{places}f}"


def _pct(value):
    return "—" if value is None else f"{value:.0f}%"


def print_read(read, only_side=None, custom=None):
    print("manual trade read — display-only, no order, no forecast")
    if not read.get("ok"):
        print("  no usable last bar yet — the feed may still be warming up")
        return
    spec = read["spec"]
    print(f"  last closed bar {read['as_of']} UTC · close ${read['entry']:,.2f} · "
          f"ATR ${read['atr']:.2f}")
    src = ("captured spec " + str(spec.get("captured_utc") or "")).strip() \
        if spec.get("source") == "captured" else "DEFAULT contract constants (no spec file)"
    print(f"  contract: {src} · {spec['contract_size']:g} oz/lot · lot grid "
          f"{spec['volume_min']:g}-{spec['volume_max']:g} step {spec['volume_step']:g} · "
          f"leverage 1:{spec['leverage']:g}")
    print(f"  cost: measured round trip ${read['spread_rt']:.2f} · registered "
          f"${M.COST_REGISTERED:.2f} · live spread "
          f"{_money(read.get('spread_now'))}")
    clock = read.get("clock") or {}
    print(f"  clock: {clock.get('detail', '—')}")

    sides = [only_side] if only_side else ["BUY", "SELL"]
    for side in sides:
        plan = dict(read["plans"][side])
        if custom and custom.get("side") == side:
            plan = custom
        if not plan.get("ok"):
            print(f"\n  {side}: no plan — {'; '.join(plan.get('reasons') or ['unavailable'])}")
            continue
        cost = plan["cost"]
        print(f"\n  {side}  ·  {plan['verdict_text']}")
        print(f"    entry   ${plan['entry']:,.2f}")
        print(f"    stop    ${plan['stop']:,.2f}   (1R = ${plan['risk']:.2f} per oz = "
              f"{(plan['risk'] / plan['atr']):.1f} ATR)")
        print(f"    target  ${plan['target']:,.2f}   (gross {cost['gross_rr']:.2f}:1, "
              f"net {cost['net_rr']:.2f}:1 after cost)")
        print(f"    cost    {_pct(cost['share_pct'])} of 1R at ${read['spread_rt']:.2f}"
              + (f"  ·  {_pct(cost['share_now_pct'])} at the live spread"
                 if cost.get("share_now_pct") is not None else "")
              + f"   [{'red' if cost['zone'] == 'red' else 'amber' if cost['zone'] == 'amber' else 'green'}]")
        if cost.get("breakeven_wr_pct") is not None:
            print(f"    beat    {cost['breakeven_wr_pct']:.0f}% decisive win rate to break even "
                  f"at this payoff (measured base rate: 33-37%)")
        print(f"    size    a {cost['min_risk_for_ok']:.2f}/oz stop is the tightest that keeps "
              f"cost under {M.COST_SHARE_OK_PCT:.0f}% of 1R")
        for row in plan["sizing"]:
            if not row["ok"]:
                print(f"    risk {_money(row['budget_usd'], 0):>6} -> no tradeable size"
                      + (f"  ({row['note']})" if row.get("note") else ""))
                continue
            margin = (f"  margin ~{_money(row['margin_usd'])}"
                      if row.get("margin_usd") is not None else "")
            print(f"    risk {_money(row['budget_usd'], 0):>6} -> {_lots(row['lots'], read['spec'])} lot · "
                  f"actually risks {_money(row['risk_usd'])} · spread costs "
                  f"{_money(row['cost_usd'])} on the round trip{margin}")
        view = plan.get("bot_view") or {}
        if view.get("text"):
            print(f"    bot   {view['text']}")
        for reason in plan.get("reasons") or ():
            print(f"    ✗ {reason}")
        for warning in plan.get("warnings") or ():
            print(f"    ! {warning}")

    measured = read.get("measured") or {}
    print("\n  measured, not assumed:")
    print("    " + (measured.get("line") or "no edge measured").replace("\n", " "))


def print_cost_ruler(cost):
    if not cost or not cost.get("ok"):
        print("\n  cost ruler: no ATR yet")
        return
    print(f"\n  cost ruler — spread as a share of 1R at ATR ${cost['atr']:.2f}")
    print(f"    {'stop':>7} {'risk/oz':>9} {'@$0.40':>8} {'@$0.55':>8}")
    for row in cost["rows"]:
        print(f"    {row['mult']:>5.1f} ATR {row['risk_usd']:>9.2f} "
              f"{row['share']['0.40']:>7.1f}% {row['share']['0.55']:>7.1f}%  [{row['zone']}]")
    print(f"    keep the cost under {M.COST_SHARE_OK_PCT:.0f}% of R: a stop of at least "
          f"{cost['min_mult']['0.55']:.1f} ATR (${cost['min_mult']['0.55'] * cost['atr']:.2f}) "
          f"does that at the measured cost.")


# ─────────────────────────────────────────────────────────────────────── the journal
def do_log(args, read=None):
    fields = {
        "timestamp_utc": args.timestamp or utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "side": args.side,
        "bot_entry": args.entry,
        "bot_sl": args.stop,
        "bot_tp": args.target,
        "manual_entry": args.entry,
        "manual_exit": args.exit,
        "reason_code": args.reason_code,
        "contemporaneous_action": args.action,
        "bot_trade_id": args.bot_trade_id,
        "max_hold_or_exit_rule": args.exit_rule,
        "post_stop_markout_horizons": args.post_stop,
        "last_closed_bar_utc": (read or {}).get("as_of"),
        "estimated_cost": args.spread,
        "notes_without_account_identifiers": args.notes,
        "pressure_source": args.pressure_source,
        "pressure_metric": args.pressure_metric,
        "pressure_timeframe": args.pressure_timeframe,
        "pressure_value_at_entry": args.pressure_value,
        "pressure_value_at_stop_touch": args.pressure_at_stop,
        "mfe": args.mfe,
        "mae": args.mae,
        "hypothetical_exit": args.hypothetical_exit,
    }
    row, problems = M.journal_row({k: v for k, v in fields.items() if v not in (None, "")})
    if problems:
        print("refused — the row is incomplete or unsafe:")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 2
    path = args.journal or JOURNAL_FILE
    ok, detail = M.append_journal(path, row, repo_root=ROOT)
    print(("✓ " if ok else "✗ ") + detail)
    return 0 if ok else 1


def journal_summary(path):
    """Counts only. The notes column is private and is never printed or aggregated."""
    rows, bad = [], 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    bad += 1
    except OSError:
        return None
    by_side, by_action, by_reason = {}, {}, {}
    for row in rows:
        for bucket, key in ((by_side, "side"), (by_action, "contemporaneous_action"),
                            (by_reason, "reason_code")):
            value = str(row.get(key) or "—")
            bucket[value] = bucket.get(value, 0) + 1
    return {"rows": len(rows), "unparseable": bad, "by_side": by_side,
            "by_action": by_action, "by_reason": by_reason,
            "first": rows[0].get("timestamp_utc") if rows else None,
            "last": rows[-1].get("timestamp_utc") if rows else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="unused; kept so a pasted command never breaks")
    ap.add_argument("--log", default=LOG_FILE, help=f"1-min log (default {LOG_FILE})")
    ap.add_argument("--dir", default=None, help=f"xm_data dir (default {QUOTE_DIR})")
    ap.add_argument("--spread", type=float, default=M.COST_ROUND_TRIP,
                    help=f"round-trip cost $/oz (default {M.COST_ROUND_TRIP}, the measured median)")
    ap.add_argument("--budget", type=float, default=None,
                    help="$ risk per trade (default: the presets 5/10/20/50)")
    ap.add_argument("--side", choices=("BUY", "SELL"), help="read one side only")
    ap.add_argument("--entry", type=float, default=None, help="your entry (default: last close)")
    ap.add_argument("--stop", type=float, default=None, help="your stop (default: the structural one)")
    ap.add_argument("--target", type=float, default=None, help="your target (default: 1.5R)")
    ap.add_argument("--json", action="store_true", help="dump the raw structures")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the read is unavailable")
    ap.add_argument("--contract-ruler", action="store_true",
                    help="just the cost ruler (spread as a share of 1R per stop width)")
    ap.add_argument("--log-decision", action="store_true",
                    help="validate and append ONE journal row (private, host-local)")
    ap.add_argument("--journal", default=None,
                    help=f"journal path (default $GOLD_MANUAL_JOURNAL_FILE or {JOURNAL_FILE}); "
                         f"must be outside this checkout")
    ap.add_argument("--journal-summary", action="store_true",
                    help="count the journal rows (never prints the notes)")
    ap.add_argument("--timestamp", default=None, help="journal row timestamp (default: now UTC)")
    ap.add_argument("--exit", dest="exit", default=None, help="journal: your exit price")
    ap.add_argument("--action", default=None,
                    help="journal: took_it / skipped / overrode_stop / waited / other")
    ap.add_argument("--reason-code", default=None,
                    help="journal: why (level_retest, breakout_close, news, stop_hunt, ...)")
    ap.add_argument("--exit-rule", default="stop_or_1.5R", help="journal: max hold / exit rule")
    ap.add_argument("--post-stop", default=None, help="journal: mark-out horizons, e.g. 15,30,60")
    ap.add_argument("--mfe", default=None, help="journal: max favourable excursion ($)")
    ap.add_argument("--mae", default=None, help="journal: max adverse excursion ($)")
    ap.add_argument("--hypothetical-exit", default=None,
                    help="journal: where an exit would have been had you held")
    ap.add_argument("--notes", default=None, help="journal: notes WITHOUT account identifiers")
    ap.add_argument("--bot-trade-id", default=None, help="journal: the bot's trade number, if any")
    ap.add_argument("--pressure-source", default=None, help="journal: where the pressure read came from")
    ap.add_argument("--pressure-metric", default=None, help="journal: the metric's definition")
    ap.add_argument("--pressure-timeframe", default=None, help="journal: the metric's timeframe")
    ap.add_argument("--pressure-value", default=None, help="journal: value at entry")
    ap.add_argument("--pressure-at-stop", default=None, help="journal: value when the stop was touched")
    args = ap.parse_args(argv)

    if args.journal_summary:
        summary = journal_summary(args.journal or JOURNAL_FILE)
        if summary is None:
            print(f"no journal at {args.journal or JOURNAL_FILE} yet — nothing recorded")
            return 0
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
            return 0
        print(f"manual journal — {summary['rows']} row(s)"
              + (f", {summary['unparseable']} unparseable" if summary["unparseable"] else ""))
        print(f"  first {summary['first']}  ·  last {summary['last']}")
        for label, bucket in (("side", summary["by_side"]), ("action", summary["by_action"]),
                              ("reason", summary["by_reason"])):
            pairs = ", ".join(f"{k} {v}" for k, v in sorted(bucket.items()))
            print(f"  by {label:7s}: {pairs or '—'}")
        print("  the notes column is private and is not printed here")
        return 0

    read = build(args)
    if args.json and not args.log_decision:
        print(json.dumps(read, indent=2, default=str))
        return 0 if read.get("ok") or not args.strict else 1

    if args.log_decision:
        return do_log(args, read)

    if args.contract_ruler:
        print_cost_ruler(read.get("cost_ruler"))
        return 0 if read.get("ok") or not args.strict else 1

    custom = None
    sides = ("BUY", "SELL")
    if args.entry is not None or args.stop is not None or args.target is not None:
        # A user-supplied geometry is judged on its own merits, once.
        side = args.side or ("BUY" if (read.get("setup") or {}).get("BUY", {}).get("ready") else "SELL")
        custom = _custom_plan(args, read, side)
        sides = (side,)
    print_read(read, only_side=args.side, custom=custom)
    if custom is None:
        print_cost_ruler(read.get("cost_ruler"))
    print("\n  journal: docs/EXECUTION-PLAN.md §7. Record the decision BEFORE the outcome,")
    print("           and record the losses too — a journal of wins measures memory.")
    return 0 if read.get("ok") or not args.strict else 1


def _custom_plan(args, read, side):
    """Judge the trader's own entry/stop/target with the SAME plan() maths.

    One code path on purpose: the risk, the cost share, the size table, the level
    clearance and every warning are derived from the geometry the trader actually
    typed, so the panel cannot show a number left over from the proposed stop.
    """
    entry = args.entry if args.entry is not None else read.get("entry")
    level = None
    if read.get("ok"):
        floor, ceiling, _logged = P.levels(P.tail_rows(args.log, 200))
        level = floor if side == "BUY" else ceiling
    plan_out = M.plan(side, entry, read.get("atr"), level=level,
                      target=args.target, stop=args.stop,
                      spread_now=read.get("spread_now"), spread_rt=read["spread_rt"],
                      spec=read["spec"], closure=read.get("closure"),
                      now=utcnow(), risk_budgets=_budgets(args.budget))
    M.attach_bot_view(plan_out, read.get("setup"), side)
    return plan_out


if __name__ == "__main__":
    sys.exit(main())
