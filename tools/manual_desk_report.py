#!/usr/bin/env python3
"""Print the display-only MANUAL DESK brief (no writes, no orders, no gates).

  python3 tools/manual_desk_report.py                 # one-screen human brief
  python3 tools/manual_desk_report.py --json        # the same read as JSON
  python3 tools/manual_desk_report.py --root DIR    # another checkout / data dir
  python3 tools/manual_desk_report.py --template    # the PRIVATE §7 observation CSV header

The template is a header only. Filled manual rows are private and must never be
committed (`manual_observations*.csv` is git-ignored). Nothing in this tool
reads a journal, writes a file, imports the engine or changes a strategy
variable. See docs/ANALYSIS-2026-11-26-manual-desk.md.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import manual_desk as MD  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Display-only manual trading desk")
    p.add_argument("--root", default=ROOT, help="checkout / data directory (default: repo root)")
    p.add_argument("--json", action="store_true", help="print the brief as JSON")
    p.add_argument("--template", action="store_true",
                   help="print only the private observation CSV header + its rules")
    return p.parse_args(argv)


def template_text():
    lines = ["# Private manual observation log — HEADER ONLY (docs/EXECUTION-PLAN.md §7)",
             "# Keep the filled file outside Git. No account identifiers, no balances.",
             MD.CSV_HEADER, "", "# Rules"]
    lines += [f"# {i + 1}. {r}" for i, r in enumerate(MD.OBSERVATION_RULES)]
    return "\n".join(lines)


def load(root, now):
    """Read the same files the dashboard reads, through pressure.py's read layer."""
    root = os.path.abspath(root)
    os.environ["GOLD_DATA_DIR"] = root
    os.environ["GOLD_LOG_FILE"] = os.path.join(root, "forward_test_log.csv")
    os.environ["GOLD_STATUS_FILE"] = os.path.join(root, "status.json")
    os.environ["GOLD_TRADES_FILE"] = os.path.join(root, "trades.csv")
    os.environ["GOLD_SKIP_FILE"] = os.path.join(root, "skipped_trades.csv")
    import pressure as PR  # imported AFTER the env is set (module-level paths)
    status = {}
    path = os.path.join(root, "status.json")
    if os.path.isfile(path):
        try:
            with open(path) as f:
                status = json.load(f)
        except (OSError, ValueError):
            status = {}
    ctx = PR.build(now=now)
    quotes = PR.tail_rows(os.path.join(root, "xm_data",
                                       "quotes-" + now.strftime("%Y-%m-%d") + ".csv"), 240)
    ctx["risk_now"] = PR.risk_read(status, quotes, now)
    return status, ctx


def text(brief):
    v = brief["verdict"]
    out = [f"MANUAL DESK — {brief['as_of']}",
           "Display-only · paper only · no order, no gate, no file write.",
           "",
           f"VERDICT  {v['headline']}",
           f"  pass {v['counts']['pass']} / warn {v['counts']['warn']} / "
           f"block {v['counts']['block']} / unknown {v['counts']['unknown']}"]
    p = brief["open"]
    if p.get("ok"):
        out += ["",
                f"OPEN PAPER POSITION  {p['side']} #{p['trade_num'] or '—'} "
                f"(simulated, not a broker order)",
                f"  entry ${p['entry']:.2f} · stop ${p['stop']:.2f} · "
                f"target ${p['target']:.2f} · risk ${p['risk_usd']:.2f} · "
                f"R:R {p['rr'] or '—'}",
                f"  entered {p['entry_time'] or '—'} · age {p['age_min']} min · "
                f"240-min TIME stop in {p['time_left_min']} min"
                f"{' · BE (stop at entry)' if p['ratcheted'] else ''}",
                f"  {p['note']}"]
    else:
        out += ["", f"OPEN PAPER POSITION  none ({p['reason']})"]
    out += ["", "CHECKLIST (advice, never a gate)"]
    for c in brief["checks"]:
        mark = {"pass": "OK  ", "warn": "WARN", "block": "BLOCK", "unknown": "?   "}[c["state"]]
        out.append(f"  [{mark}] {c['label']:<24} {c['value']:<12} {c['detail']}")
    cost = brief["cost"]
    be = brief["break_even"]
    out += ["", "COST & BREAK-EVEN",
            f"  {cost['sentence']}",
            f"  Decisive break-even at 1:1.5 on a $6 stop: {be['pct_nocost']:.1f}% uncosted, "
            f"{be['pct_registered']:.1f}% at $0.40, {be['pct_with_scratches']:.1f}% with "
            f"~27% scratches, {be['pct_next_cost']:.1f}% at $0.57.",
            f"  {be['note']}"]
    if brief["ruler"]:
        out += ["", f"COST RULER (ATR ${brief['atr']:.2f}) — spread as % of your risk"]
        for r in brief["ruler"]:
            shares = " / ".join(f"${s['cost_rt']:.2f}: {s['pct']:.1f}%" for s in r["shares"])
            out.append(f"  {r['atr_mult']:.1f} ATR stop = ${r['risk_usd']:.2f} risk  "
                       f"{shares}  {r['verdict']}")
    out += ["", "MEASURED CONTEXT (not predictions)"]
    out += [f"  - {n}" for n in brief["notes"]]
    out += ["", "PRIVATE OBSERVATION LOG",
            f"  {brief['observation']['hint']}",
            "  " + brief["observation"]["header"]]
    out += ["", brief["disclaimer"]]
    return "\n".join(out)


def main(argv=None):
    args = parse_args(argv)
    if args.template:
        print(template_text())
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        status, ctx = load(args.root, now)
        b = MD.brief(status, ctx, now)
    except Exception as exc:  # a broken read layer must never look like a verdict
        if args.json:
            print(json.dumps({"ok": False, "reason": f"manual desk read failed: {exc}"},
                             indent=2, sort_keys=True))
        else:
            print(f"MANUAL DESK UNAVAILABLE — {exc}")
        return 0
    print(json.dumps(b, indent=2, sort_keys=True) if args.json else text(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
