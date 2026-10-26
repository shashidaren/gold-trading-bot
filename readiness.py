#!/usr/bin/env python3
"""readiness — display-only read layer for the dashboard's 🚦 Readiness tab.

Like pressure.py / chart.py this module is stdlib-only, read-only, never imports
engine.py and never writes a file. It answers three owner questions in one view:

  * **How many days?** elapsed forward-test/era days and the days left to each
    conditional gate (cost sample, DST cross-check, registered window, edge
    review, live-readiness review). These are ESTIMATES, never deadlines.
  * **What is completed?** a dated milestone list (mirror of
    docs/EXECUTION-PLAN.md §4 — update both together).
  * **What is pending?** the live `tools/live_readiness.py` checks (TODO/MANUAL)
    plus the owner/host blockers that no code change can clear.

The single source of truth for the LIVE gate is `tools/live_readiness.py`; this
module only formats it. `readiness_view(root, now, checks, progress)` accepts an
injected clock and injected data so the tests are hermetic.

CLI (read-only): `python3 readiness.py` / `python3 readiness.py --json`.
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))

UTC = timezone.utc

# --- dated reference points (UTC) -------------------------------------------
LOG_START = datetime(2026, 9, 1, 14, 25, 2, tzinfo=UTC)      # first bar in the log
CUTOVER = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)             # structural-stop deploy
AUDIT = datetime(2026, 10, 26, 14, 15, tzinfo=UTC)            # full-system audit
US_DST_END = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)          # US-rule cross-check
REGISTERED_END = datetime(2026, 12, 1, 21, 0, tzinfo=UTC)     # structstop1.5 window end
ASSUMED_COST = 0.40                                           # registered round trip

# Conditional research horizons, measured from the audit date. Not promises.
EDGE_RANGE_DAYS = (61, 122)        # ~2–4 months
LIVE_RANGE_DAYS = (183, 365)       # ~6–12 months

# Mirror of docs/EXECUTION-PLAN.md §4 (compact history). Chronological here.
# Every `doc` must exist — tools/test_readiness_tab.py pins that.
MILESTONES = [
    ("2026-09-01", "Forward test started",
     "1-min bar log begins; the whole project stays paper-only.", "archive/PROJECT_LOG.md"),
    ("2026-09-15", "BE ratchet raised to 0.75R",
     "0.30R scratched 77% of trades; 0.75R restored a readable decisive rate.",
     "docs/REVIEW-2026-09-15.md"),
    ("2026-09-21", "240-min max-hold TIME stop live",
     "Caps weekend/long-hold exposure; TIME exits are a neutral bucket.",
     "docs/REVIEW-2026-09-21.md"),
    ("2026-10-06", "Structural stop deployed (0.5 ATR clearance)",
     "Stop must clear the 20-bar level the entry was built on; TP = 1.5 × actual risk.",
     "docs/ANALYSIS-2026-10-05-stop-loss-geometry.md"),
    ("2026-10-19", "Registered time-gate judgement",
     "SCREEN MET, PASS unavailable (n=139); §7 closure-gap REVERT trigger fired.",
     "docs/REVIEW-2026-10-19-struct-stop-judgement.md"),
    ("2026-10-25", "Gap guard + duplicate-number fix deployed",
     "30-min entries-only daily-closure guard; `71317da` into the closed weekend market.",
     "docs/PREREG-2026-10-25-gap-guard-daily-closure.md"),
    ("2026-10-25", "DST-responsive closure derivation",
     "5-break baseline + Day-1/Day-2 ±60 min adaptation; 7 extra smoke checks.",
     "docs/PREREG-2026-10-25-gap-guard-daily-closure.md"),
    ("2026-10-25", "Stop-hunt mark-outs + clearance grid",
     "Deeper stops monotone-better in costed replay; 1.5 ATR passes 3/4 of a pre-declared bar.",
     "docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md"),
    ("2026-10-26", "DST gate MET (+2h, EU rule)",
     "Observed offset change fits 100% of 24 379 rows; `hold_for_dst` released.",
     "docs/REVIEW-2026-10-26-full-system-audit.md"),
    ("2026-10-26", "LIVE-path hardening + 20-check gate",
     "Arm/kill switch, IOC filling from spec, closed-bar dedup; gate CLOSED.",
     "docs/REVIEW-2026-10-26-full-system-audit.md"),
    ("2026-10-26", "Full audit + 'Follow execution plan' queue",
     "Tracks A/B/C, two hard approval gates, and a written definition of live-ready.",
     "docs/EXECUTION-PLAN.md"),
]

# Blockers that no code commit can clear. `who` is the person/place that must act.
BLOCKERS = [
    ("Owner", "G1 — pre-registration sign-off",
     "Approve the structstop1.5 draft or choose the literal §7 revert. Nothing deploys before this.",
     "docs/PREREG-2026-10-26-structstop1.5.md"),
    ("Host", "Sunday-reopen price-bar hole",
     "~2 h of open-market M1 bars missing (quotes fresh from 22:00, bars resume 23:59). Verify mt5feed / goldbot.",
     "docs/REVIEW-2026-10-26-full-system-audit.md"),
    ("Host", "First post-DST daily break",
     "Confirm derive_daily_closure() matches the observed break; it still derives (20:58, 22:00).",
     "docs/PREREG-2026-10-25-gap-guard-daily-closure.md"),
    ("Host", "DEMO account + 48 h evidence",
     "Track B5 needs a demo account (captured spec says REAL) and a dated demo test report.",
     "docs/EXECUTION-PLAN.md"),
    ("Evidence", "Positive net expectancy",
     "Whole book net −$669 at the registered $0.40; no independent forward window yet.",
     "docs/REVIEW-2026-10-26-full-system-audit.md"),
    ("Owner", "G2 — real-money approval",
     "Never delegated to 'Follow execution plan'. Required even if every check is green.",
     "docs/EXECUTION-PLAN.md"),
]


def _ceil_days(target, now):
    """Whole days until `target` (0 once it has passed); never negative."""
    return max(0, math.ceil((target - now).total_seconds() / 86400.0))


def _elapsed_days(start, now):
    if now < start:
        return 0
    return int((now - start).total_seconds() // 86400)


def _next_weekend_end(now):
    """End of the next complete Sat+Sun weekend (Sunday 23:59 UTC)."""
    days_until_sunday = (6 - now.weekday()) % 7
    sunday = (now + timedelta(days=days_until_sunday)).replace(hour=23, minute=59,
                                                                second=0, microsecond=0)
    if sunday <= now:
        sunday += timedelta(days=7)
    return sunday


def _date(dt):
    return dt.strftime("%Y-%m-%d") if dt else "—"


def _row(rid, label, state, days_text, target, detail):
    tones = {"done": "ok", "active": "warn", "pending": "muted",
             "blocked": "block", "conditional": "muted"}
    return dict(id=rid, label=label, state=state, tone=tones.get(state, "muted"),
                days_text=days_text, target=target, detail=detail)


def build_timeline(now, progress, counts):
    """Ordered timeline rows — the 'gauge in days' the owner asked for."""
    pg = progress or {}
    days_done = pg.get("complete_days", 0)
    days_target = pg.get("target_days", 14)
    weekends_done = pg.get("weekends", 0)
    weekends_target = pg.get("target_weekends", 2)
    med = pg.get("median_spread")

    days_short = max(0, days_target - days_done)
    weekend_end = _next_weekend_end(now)
    weekend_days = _ceil_days(weekend_end, now)
    cost_days_left = max(days_short, weekend_days) if weekends_done < weekends_target else days_short
    cost_met = days_short == 0 and weekends_done >= weekends_target
    cost_eta = "met" if cost_met else _date(now + timedelta(days=cost_days_left))

    edge_lo, edge_hi = EDGE_RANGE_DAYS
    live_lo, live_hi = LIVE_RANGE_DAYS

    return [
        _row("forward_test", "Forward test running", "done",
             f"{_elapsed_days(LOG_START, now)} d elapsed", _date(LOG_START),
             "Paper-only since the first 1-min bar. No real order has ever been placed."),
        _row("structstop_era", "Structural-stop era", "active",
             f"{_elapsed_days(CUTOVER, now)} d elapsed", _date(CUTOVER),
             "One unchanged geometry. SCREEN MET at its registered gate; PASS arm lapsed."),
        _row("cost_sample", f"Cost sample {days_target} days / {weekends_target} weekends",
             "done" if cost_met else "active",
             "met" if cost_met else f"~{cost_days_left} d left", cost_eta,
             f"{days_done}/{days_target} complete UTC days, {weekends_done}/{weekends_target} weekends"
             + (f"; median spread ${med:.2f}" if med is not None else "")
             + ". Keep the registered $0.40 round trip until met."),
        _row("dst_us", "US DST discriminating window", "active",
             f"~{_ceil_days(US_DST_END, now)} d left", _date(US_DST_END),
             "Cross-check only: the EU rule is already confirmed on observed offsets (+2h)."),
        _row("g1", "G1 — pre-registration sign-off", "blocked", "— (owner)",
             "no date", "Draft written 2026-10-26. No deploy, no new isolation window before sign-off."),
        _row("window_15", "structstop1.5 window (n=150 or date gate)", "pending",
             f"~{_ceil_days(REGISTERED_END, now)} d left", _date(REGISTERED_END),
             "Not started (G1). ~15 trading days at 10–13 trades/day once deployed."),
        _row("track_b", "LIVE execution engineering (Track B)", "active",
             f"{counts['todo']} TODO · {counts['manual']} MANUAL", "one check / session",
             "Each step turns one live_readiness.py check green with a hermetic test."),
        _row("demo", "DEMO-account evidence", "blocked", "— (host)", "host action",
             "Needs a demo account + separate data dir; the captured spec says REAL."),
        _row("edge_review", "Independent edge reassessment (2–4 months)", "conditional",
             f"~{edge_lo}–{edge_hi} d",
             f"{_date(AUDIT + timedelta(days=edge_lo))} – {_date(AUDIT + timedelta(days=edge_hi))}",
             "Only after PASS: positive net expectancy after measured costs on an independent sample."),
        _row("live_review", "G2 — separate live-readiness review (6–12 months)", "conditional",
             f"~{live_lo}–{live_hi} d",
             f"{_date(AUDIT + timedelta(days=live_lo))} – {_date(AUDIT + timedelta(days=live_hi))}",
             "Both tracks complete + explicit owner approval. No date can be promised."),
    ]


def readiness_view(root=ROOT, now=None, checks=None, progress=None):
    """Build the whole read-only view. `now`/`checks`/`progress` are injectable."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    reason = None
    if checks is None or progress is None:
        try:
            import live_readiness as LR
            from_checks, from_progress = LR.snapshot(root)
            checks = checks if checks is not None else from_checks
            progress = progress if progress is not None else from_progress
        except Exception as exc:
            reason = f"readiness checks unavailable: {exc}"
            checks = checks or []
            progress = progress or {}

    if reason is None and not checks:
        # Never render a confident "0 checks" timeline: an unreadable scorecard
        # is a failure, not a closed gate with zero evidence.
        reason = "no checks returned by tools/live_readiness.py"
    counts = {
        "pass": sum(1 for c in checks if c.get("status") == "PASS"),
        "todo": sum(1 for c in checks if c.get("status") == "TODO"),
        "manual": sum(1 for c in checks if c.get("status") == "MANUAL"),
        "total": len(checks),
    }
    gate_open = bool(checks) and all(
        c.get("status") == "PASS" for c in checks if c.get("blocking", True))

    pg = progress or {}
    med = pg.get("median_spread")
    newest = pg.get("newest_ts")
    return {
        "ok": reason is None and bool(checks),
        "reason": reason,
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
        "gate": {
            "open": gate_open,
            "label": "OPEN" if gate_open else "CLOSED",
            "counts": counts,
            "headline": ("All blocking checks pass — still needs G2 owner approval"
                         if gate_open else "No real orders — paper forward test only"),
        },
        "elapsed": {
            "forward_test_days": _elapsed_days(LOG_START, now),
            "era_days": _elapsed_days(CUTOVER, now),
            "since_audit_days": _elapsed_days(AUDIT, now),
            "as_of_data": (datetime.fromtimestamp(newest, UTC).strftime("%Y-%m-%d %H:%M UTC")
                           if newest else "—"),
        },
        "progress": {
            "days_done": pg.get("complete_days", 0),
            "days_target": pg.get("target_days", 14),
            "weekends_done": pg.get("weekends", 0),
            "weekends_target": pg.get("target_weekends", 2),
            "median_spread_text": f"${med:.2f}" if med is not None else "—",
            "assumed_cost_text": f"${ASSUMED_COST:.2f}",
            "rows": pg.get("rows", 0),
            "offsets": pg.get("offsets", []),
            "filling_flags": pg.get("filling_flags") or [],
        },
        "timeline": build_timeline(now, pg, counts),
        "completed": [dict(date=d, title=t, detail=x, doc=doc)
                      for d, t, x, doc in reversed(MILESTONES)],
        "blockers": [dict(who=w, what=t, why=x, doc=doc) for w, t, x, doc in BLOCKERS],
        "pending_checks": [dict(c) for c in checks if c.get("status") != "PASS"],
        "checks": [dict(c) for c in checks],
        "disclaimer": (
            "Day counts are conditional estimates from the checked-in data, not deadlines or a "
            "profit forecast. A PASS is a code/evidence check, NOT a demo-test result. Time "
            "elapsed, a higher win rate or a bigger mixed-era trade count cannot substitute for "
            "positive expectancy after realistic costs. G2 (real money) is never implied here."),
        "sources": ["docs/EXECUTION-PLAN.md", "docs/REVIEW-2026-10-26-full-system-audit.md",
                    "tools/live_readiness.py", "docs/REVIEW-2026-10-20-live-readiness-timeline.md"],
    }


def _text(view):
    lines = [f"Readiness @ {view['as_of']} — LIVE GATE {view['gate']['label']}",
             f"checks: {view['gate']['counts']}",
             "", "TIMELINE (days)"]
    for row in view["timeline"]:
        lines.append(f"  {row['days_text']:<22} {row['label']}  [{row['state']}] {row['target']}")
    lines += ["", "COMPLETED"]
    for m in view["completed"]:
        lines.append(f"  {m['date']}  {m['title']}")
    lines += ["", "PENDING / BLOCKED"]
    for b in view["blockers"]:
        lines.append(f"  {b['who']}: {b['what']}")
    for c in view["pending_checks"]:
        lines.append(f"  {c['status']:<6} {c['id']}")
    lines += ["", view["disclaimer"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    view = readiness_view(a.root)
    print(json.dumps(view, indent=2) if a.json else _text(view))
    return 0


if __name__ == "__main__":
    sys.exit(main())
