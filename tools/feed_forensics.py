#!/usr/bin/env python3
"""feed_forensics — did we lose data, and was anything exposed while we did?

The two feeds are logged independently: `forward_test_log.csv` (M1 price bars, the
engine's input) and `xm_data/quotes-*.csv` (the broker's own tick, 30 s cadence).
Reviews have argued about a hole without a tool that separates the cases:

  * MARKET CLOSED      - the broker is shut (weekend / daily break). Not a fault.
  * BOTH FEEDS DOWN    - both stopped inside an open session. A host / terminal /
                         MT5 outage: the engine's input AND the evidence needed to
                         judge it are gone together. This is the one that matters.
  * PRICE-FEED ONLY    - quotes kept advancing while bars stopped: `mt5feed` /
                         `goldbot` is sick while the terminal is fine.
  * QUOTE-FEED ONLY    - bars kept coming while quotes stopped: `mt5quotes` is sick
                         and the engine is unaffected.

The discriminating evidence is the OTHER feed, not a clock heuristic. The quote
logger keeps writing while the market is closed, but those rows are flagged STALE
and `xm_quote_report.usable()` rejects them — so "a usable quote exists during an
expected-open minute with no bar" is real proof the terminal had a live tick.

The tool works MINUTE BY MINUTE over the expected-open window. That is what makes
it trustworthy: the same hole seen by two feeds de-duplicates itself, a closure
cannot be double-counted, and "which feed was missing in an expected-open minute"
is answered directly instead of inferred.

It also answers the question that actually matters operationally: **which trades
were open while the hole existed**. A lost hour with no exposure is an ops note; a
lost hour with a live position is an unreviewable trade.

    python3 tools/feed_forensics.py                  last 45 days
    python3 tools/feed_forensics.py --days 120
    python3 tools/feed_forensics.py --json

Read-only. Stdlib only. Never imports engine.py, never writes a file.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import xm_quote_report as QR   # noqa: E402  the one definition of a usable / fresh quote
import strategy_lab as L       # noqa: E402  the one ledger loader

UTC = timezone.utc
BARS = "forward_test_log.csv"
HOLE_MIN = 10                  # report a hole only when it is >= this many OPEN minutes

JITTER_MIN = 2                 # a feed "covers" a minute when it has a sample within +-2 min
                               # (bars and 30 s quotes sample on different clocks)
TRADE_TOL_MIN = 5              # a trade "overlaps" a hole if it spans it by more than this


# --------------------------------------------------------------------------- inputs
def load_bars(root):
    """Price-log timestamps, ascending. Corrupt/NUL rows are skipped, not fatal."""
    path = os.path.join(root, BARS)
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "rb") as fh:
        raw = fh.read().replace(b"\x00", b"")
    for line in raw.decode("utf-8", "replace").splitlines()[1:]:
        head = line.split(",", 1)[0].strip()
        try:
            out.append(datetime.strptime(head, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
    out.sort()
    return out


def load_fresh_quotes(qdir):
    """Naive-UTC timestamps of quote rows that are a real, fresh tick."""
    samples, _bad, _files = QR.load_quotes(qdir)
    return [QR.naive_utc(s.t) for s in samples if QR.usable(s)]


def expected_open(m):
    """Is this UTC minute one where gold is EXPECTED to tick? — `xm_quote_report.in_closed_window`.

    Reused, not re-invented: it already encodes the daily break (padded
    20:55-23:10 UTC so DST never turns a scheduled break into a stall) and the
    weekend (Fri 20:55 -> Sun 23:10, reopening Sunday 23:10). Deriving my own table
    here would be a second source of truth for the same question, and the two would
    drift — note the Sunday-reopen minute is OPEN, which a naive weekend test misses.
    """
    return not QR.in_closed_window(m.replace(tzinfo=UTC).timestamp())


def minute_sets(ts, since, until):
    """Set of whole minutes a feed covers (each sample covers +-JITTER_MIN)."""
    out = set()
    for t in ts:
        if t < since - timedelta(minutes=JITTER_MIN) or t > until + timedelta(minutes=JITTER_MIN):
            continue
        base = t.replace(second=0, microsecond=0)
        for k in range(-JITTER_MIN, JITTER_MIN + 1):
            out.add(base + timedelta(minutes=k))
    return out


def trades_spanning(trades, start, end, tol_min=TRADE_TOL_MIN):
    """Trades open while the hole existed (same tolerance the ledger reviews use)."""
    pad = timedelta(minutes=tol_min)
    return [t for t in trades if t["et"] < end - pad and t["xt"] > start + pad]


# --------------------------------------------------------------------------- the read
def analyse(root=ROOT, qdir=None, days=45, now=None):
    qdir = qdir or os.path.join(root, "xm_data")
    ledger = os.path.join(root, "trades.csv")
    trades = L.load_ledger(ledger) if os.path.exists(ledger) else []
    bar_ts = [t for t in load_bars(root) if t.tzinfo is None]
    fresh_ts = load_fresh_quotes(qdir)

    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    asked_since = (now - timedelta(days=days)).replace(second=0, microsecond=0)
    until = now.replace(second=0, microsecond=0)

    # A period with NO data from a feed at all is a coverage gap, not an outage.
    # Clamp the start to where BOTH feeds exist, and report the clamp honestly.
    first_bar = min(bar_ts) if bar_ts else None
    first_quote = min(fresh_ts) if fresh_ts else None
    starts = [t for t in (asked_since, first_bar, first_quote) if t is not None]
    since = (max(starts) if starts else asked_since).replace(second=0, microsecond=0)
    clamped = since > asked_since

    bars = minute_sets(bar_ts, since, until)
    quotes = minute_sets(fresh_ts, since, until)

    runs, cur = [], None
    m = since                          # a whole minute: the sets hold whole minutes only
    while m <= until:
        if not expected_open(m):
            # the market is not expected to be open now: not a hole, and it also
            if cur:                       # terminates any run in progress
                runs.append(cur)
                cur = None
        else:
            b_ok, q_ok = m in bars, m in quotes
            if b_ok and q_ok:
                if cur:
                    runs.append(cur)
                    cur = None
            else:
                if cur is None:
                    cur = dict(start=m, end=m, no_bar=not b_ok, no_quote=not q_ok)
                else:
                    cur["end"] = m
                    cur["no_bar"] = cur["no_bar"] or not b_ok
                    cur["no_quote"] = cur["no_quote"] or not q_ok
        m += timedelta(minutes=1)
    tail = cur                              # a run that reaches `until` is not an outage:
    if cur and cur["end"] < until.replace(second=0):   # it is the last data we have
        runs.append(cur)

    rows = []
    for r in runs:
        open_min = (r["end"] - r["start"]).total_seconds() / 60.0 + 1
        if open_min < HOLE_MIN:
            continue
        if r["no_bar"] and r["no_quote"]:
            kind = "BOTH FEEDS DOWN"
        elif r["no_bar"]:
            kind = "PRICE-FEED ONLY"
        else:
            kind = "QUOTE-FEED ONLY"
        span = trades_spanning(trades, r["start"], r["end"] + timedelta(minutes=1))
        rows.append(dict(start=r["start"].strftime("%Y-%m-%d %H:%M"),
                         end=(r["end"] + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"),
                         open_min=open_min, kind=kind,
                         trades=[dict(num=t["num"], side=t["side"],
                                      entry=t["et"].strftime("%Y-%m-%d %H:%M:%S"),
                                      exit=t["xt"].strftime("%Y-%m-%d %H:%M:%S"),
                                      reason=t["reason"], pnl=t["pnl"]) for t in span]))

    last_bar = max(bar_ts) if bar_ts else None
    last_quote = max(fresh_ts) if fresh_ts else None
    return dict(
        as_of=now.strftime("%Y-%m-%d %H:%M UTC"), days=days, jitter_min=JITTER_MIN,
        asked_since=asked_since.strftime("%Y-%m-%d %H:%M"),
        judged_since=since.strftime("%Y-%m-%d %H:%M"),
        clamped=clamped,
        first_bar=first_bar.strftime("%Y-%m-%d %H:%M") if first_bar else None,
        first_quote=first_quote.strftime("%Y-%m-%d %H:%M") if first_quote else None,
        bars=len(bar_ts), bar_last=last_bar.strftime("%Y-%m-%d %H:%M:%S") if last_bar else None,
        quotes_fresh=len(fresh_ts),
        quote_last=last_quote.strftime("%Y-%m-%d %H:%M:%S") if last_quote else None,
        lag_min=round((last_quote - last_bar).total_seconds() / 60.0, 1)
        if (last_bar and last_quote) else None,
        tail_missing=dict(from_=tail["start"].strftime("%Y-%m-%d %H:%M") if tail else None,
                          no_bar=bool(tail and tail["no_bar"]),
                          no_quote=bool(tail and tail["no_quote"])),
        holes=rows,
        summary=dict(
            total=len(rows),
            lost_open_minutes=sum(r["open_min"] for r in rows),
            both=[r for r in rows if r["kind"] == "BOTH FEEDS DOWN"],
            price_only=[r for r in rows if r["kind"] == "PRICE-FEED ONLY"],
            quote_only=[r for r in rows if r["kind"] == "QUOTE-FEED ONLY"],
            exposed=[r for r in rows if r["trades"]],
        ),
    )


# --------------------------------------------------------------------------- rendering
def render(res):
    out = []
    add = out.append
    add("feed forensics — which feed lost data, and was anything exposed?")
    add(f"  as of {res['as_of']}  ·  window {res['days']} d  ·  "
        f"±{res['jitter_min']} min coverage tolerance")
    if res["clamped"]:
        add(f"  judged from {res['judged_since']} UTC, not {res['asked_since']}: the two feeds only"
            " overlap from there")
        add(f"    first bar {res['first_bar']}  ·  first fresh quote {res['first_quote']}"
            "  (before that, absence is a COVERAGE gap, not an outage)")
    add(f"  price bars {res['bars']:,} through {res['bar_last']}  ·  "
        f"fresh quotes {res['quotes_fresh']:,} through {res['quote_last']}  ·  "
        f"lag {res['lag_min']} min (quotes minus bars)")
    add("  'fresh quote' = a row xm_quote_report.usable() accepts; the logger keeps writing")
    add("  STALE rows while the market is shut, so those are NOT evidence of a live tick.")
    add("  'expected open' = not inside xm_quote_report.in_closed_window (the repo's own closure")
    add("  rule: daily break 20:55-23:10 UTC padded for DST, weekend Fri 20:55 -> Sun 23:10).")
    add("")
    h = res["holes"]
    if not h:
        add(f"  no hole of {HOLE_MIN}+ expected-open minutes in this window")
        return "\n".join(out)
    add(f"  {len(h)} hole(s) of {HOLE_MIN}+ expected-open minutes:")
    add(f"    {'kind':16s}{'start (UTC)':17s}{'end (UTC)':17s}{'open':>6s}  exposure")
    for r in h:
        exp = ", ".join(f"#{t['num']} {t['side']}" for t in r["trades"]) or "—"
        add(f"    {r['kind']:16s}{r['start']:17s}{r['end']:17s}{r['open_min']:6.0f}  {exp}")
    add("")
    sm = res["summary"]
    add("  READ THIS WAY")
    add(f"    BOTH FEEDS DOWN  {len(sm['both']):2d}  — host/terminal/MT5 outage: the engine's input "
        "AND the evidence both stop")
    add(f"    PRICE-FEED ONLY  {len(sm['price_only']):2d}  — mt5feed/goldbot sick while the terminal is fine")
    add(f"    QUOTE-FEED ONLY  {len(sm['quote_only']):2d}  — mt5quotes sick; the engine is unaffected")
    add(f"    lost open time   {sm['lost_open_minutes']:.0f} min across {sm['total']} hole(s)")
    if sm["exposed"]:
        add(f"    EXPOSED TRADES   {len(sm['exposed']):2d}  — a position was open across a hole: "
            "NOT judgeable on that data")
    else:
        add("    EXPOSED TRADES    0  — no position was open across any hole in this window")
    t = res["tail_missing"]
    if t["from_"]:
        missing = " and ".join(x for x, ok in (("price bars", t["no_bar"]),
                                               ("fresh quotes", t["no_quote"])) if ok)
        add(f"  since {t['from_']} UTC: no {missing} at all (the feeds have simply stopped —")
        add("  a live feed that is merely behind is NOT reported as a hole)")
    add("")
    add("  A hole with no exposure is an ops note, not a data retraction. A hole WITH exposure")
    add("  makes that trade unreviewable — say so in the review instead of reading its P&L.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--dir", default=None, help="quote data dir (default <root>/xm_data)")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = analyse(root=a.root, qdir=a.dir, days=a.days)
    print(json.dumps(res, indent=2) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
