#!/usr/bin/env python3
"""xm_quote_report - read what the GOLD quote logger collected (xm_data/) and answer the questions
it was built for. Stdlib only, read-only, runs anywhere the repo is checked out.
(port of bitcoin-trading-bot's tools/xm_quote_report.py, PR #10, reworked for a market that CLOSES)

  python3 tools/xm_quote_report.py              full report
  python3 tools/xm_quote_report.py --quiet      one advisory line (used by autosync's digest)
  python3 tools/xm_quote_report.py --days 14    only the newest 14 UTC days of quote rows
  python3 tools/xm_quote_report.py --dir xm_data --root .

Sections (docs/XM-LOGGER.md has the column dictionary and the decision rules):
  1. LOGGER       coverage: complete days/weekends against the sample target, logger outages, and
                  the difference between a CLOSED MARKET (scheduled break / weekend: rows kept, tick
                  frozen -> STALE) and a feed STALL while the market should be open
  2. SPREAD       what XM actually quoted, by session / weekly open / blackout window / UTC hour, in
                  $ per oz and in $ per trade at 0.01 lot, and as a share of 1R
  3. COST         the ASSUMED $0.40 round trip (strategy_lab --cost 0.20 per side) against the
                  spread measured at the moments the ledger's trades entered and exited
  4. SERVER TIME  the broker-clock offset the logger OBSERVED, checked against the EU and US DST
                  rules (tools/broker_time.py) - the evidence the history converter needs
  5. SPEC         contract facts (execution/filling modes, stops level, swap, demo vs real) and a
                  check of the 0.01-lot-x-$1-move-is-$1.00 arithmetic behind every ledger dollar

Every number here is a MEASUREMENT of the XM feed, not a trading rule - it changes nothing by
itself. Spread-only costs are a LOWER bound on the all-in round trip (slippage and commission are
not observable from quotes). To re-cost the ledger with a measured figure use the existing flags:
`win_rate_report.py --spread <round-trip $>` and `strategy_lab.py --cost <$ per side>` (section 3
prints both numbers). This tool deliberately has no --spread flag of its own.
"""
import argparse
import bisect
import csv
import glob
import json
import os
import statistics as st
import sys
import time
from collections import Counter, namedtuple
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import broker_time as BT  # noqa: E402
import mt5_quotes as Q  # noqa: E402
import strategy_lab as L  # noqa: E402     (load_ledger and the engine mirrors only)

try:                                    # the engine's own windows: never re-declare them here
    from trade_filter import BLACKOUT_WINDOWS  # noqa: E402
except Exception:                       # pragma: no cover - the report must not die on this
    BLACKOUT_WINDOWS = []

UTC = timezone.utc

# --- reference numbers (mirrors; the smoke test cross-checks them against their sources) ---
LOT = 0.01                              # the engine's fixed size: 0.01 lot = 1 oz at a 100 oz contract
ASSUMED_SIDE_USD = 0.20                 # strategy_lab.py --cost default ($ per side)
ASSUMED_USD_PER_TRADE = 2 * ASSUMED_SIDE_USD   # = win_rate_report.py --spread 0.40 (round trip)
RR = L.ATR_TP_MULT / L.ATR_SL_MULT      # 1.5: the ledger's TP survives the BE ratchet, so 1R = |TP - entry| / RR
SHARE_1R_CUTS = (0.05, 0.10, 0.20)      # spread as a share of 1R
TARGET_DAYS, TARGET_WEEKENDS = 14, 2    # sample target before the numbers are decision-grade
DAY_COMPLETE_FRAC = 0.80                # a UTC day counts as logged with >= 80 % of its rows
GAP_MIN_S = 300                         # a hole between rows longer than this is a logger outage
STALL_MIN_S = 600                       # an unusable run this long OUTSIDE a closure is a feed stall
STALE_AFTER_S = 15 * 60                 # --quiet: no new row for this long = the LOGGER is down
JOIN_TOL_S = 75                         # a ledger entry/exit joins a usable quote within this
QUIET_WINDOW_DAYS = 45                  # --quiet reads only this much history
BAD_FLAGS = frozenset({"STALE", "NOOFFSET", "NOQUOTE", "BADQUOTE"})
RULE_OK_PCT = 99.5                      # a DST rule "fits" the observed offsets at or above this
SESSIONS = (("ASIA 23-07", "ASIA"), ("LONDON 07-12", "LONDON"), ("NY 12-21", "NY"),
            ("ROLLOVER 21-23", "ROLLOVER"))

Sample = namedtuple("Sample", "t spread smin smax flags age n_ok n_bad off")


# =========================================================================================
# loading
# =========================================================================================
def _f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def load_quotes(qdir, since=None):
    """-> (samples ascending, malformed line count, number of files). Torn or misaligned
    lines are skipped and counted, never fatal."""
    rows, bad = [], 0
    files = sorted(glob.glob(os.path.join(qdir, "quotes-????-??-??.csv")))
    for path in files:
        if since is not None:                   # day files are named by UTC date: skip old ones unread
            try:
                day = datetime.strptime(os.path.basename(path)[7:17], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
                if day + 86400 <= since:
                    continue
            except ValueError:
                pass
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                rd = csv.reader(fh)
                if next(rd, None) != Q.QUOTE_FIELDS:
                    bad += 1
                    continue
                for p in rd:
                    if len(p) != len(Q.QUOTE_FIELDS):
                        bad += 1
                        continue
                    d = dict(zip(Q.QUOTE_FIELDS, p))
                    try:
                        t = Q.parse_utc(d["ts_utc"])
                        off = int(d["srv_offset_s"]) if d["srv_offset_s"] else None
                        n_ok, n_bad = int(d["n_ok"] or 0), int(d["n_bad"] or 0)
                    except ValueError:
                        bad += 1
                        continue
                    if since is not None and t < since:
                        continue
                    rows.append(Sample(t, _f(d["spread"]), _f(d["spread_min"]), _f(d["spread_max"]),
                                       frozenset(x for x in d["flags"].split(";") if x),
                                       _f(d["tick_age_s"]), n_ok, n_bad, off))
        except OSError:
            bad += 1
    rows.sort(key=lambda s: s.t)
    return rows, bad, len(files)


def load_spec(qdir):
    try:
        with open(os.path.join(qdir, Q.SPEC_FILE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def spec_changes(qdir):
    try:
        with open(os.path.join(qdir, Q.SPEC_HISTORY_FILE), encoding="utf-8") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


def load_trades(root):
    path = os.path.join(root, "trades.csv")
    try:
        return L.load_ledger(path) if os.path.exists(path) else []
    except OSError:
        return []


# =========================================================================================
# statistics
# =========================================================================================
def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarize(vals):
    v = sorted(vals)
    if not v:
        return dict(n=0)
    return dict(n=len(v), mean=sum(v) / len(v), med=pct(v, .5), p90=pct(v, .9), p95=pct(v, .95),
                p99=pct(v, .99), mx=v[-1])


def usable(s):
    """A row whose spread is a real, fresh point sample (not stale, not an outage row)."""
    return s.spread is not None and not (s.flags & BAD_FLAGS)


def share_above(vals, thr):
    return 100.0 * sum(1 for x in vals if x > thr) / len(vals) if vals else 0.0


def dt_of(t):
    return datetime.fromtimestamp(t, tz=UTC)


def naive_utc(t):
    return dt_of(t).replace(tzinfo=None)


def session_of(t):
    h = dt_of(t).hour
    if 21 <= h < 23:
        return "ROLLOVER"
    if h >= 23 or h < 7:
        return "ASIA"
    return "LONDON" if h < 12 else "NY"


def week_open_of(t):
    """The weekly re-open: UTC Sunday (gold is shut until ~22:00) through Monday 01:00. Spreads are
    usually widest here, so it is reported on its own."""
    d = dt_of(t)
    return d.weekday() == 6 or (d.weekday() == 0 and d.hour < 1)


def blackout_of(t):
    d = dt_of(t)
    m = d.hour * 60 + d.minute
    for sh, sm, eh, em, label, *_ in BLACKOUT_WINDOWS:
        if sh * 60 + sm <= m <= eh * 60 + em:
            return label
    return None


def in_closed_window(t):
    """True where gold is EXPECTED to be shut: the daily break (XM server 23:55-01:05, which is
    ~20:55-22:05 UTC in summer and an hour later in winter - padded to 20:55-23:10 here so DST never
    makes a scheduled break look like a stall) and the weekend (Fri 20:55 -> Sun 23:10 UTC)."""
    d = dt_of(t)
    m, wd = d.hour * 60 + d.minute, d.weekday()          # Mon=0 .. Sun=6
    if 20 * 60 + 55 <= m < 23 * 60 + 10:
        return True
    return (wd == 4 and m >= 20 * 60 + 55) or wd == 5 or (wd == 6 and m < 23 * 60 + 10)


def coverage(samples):
    """Rows per UTC day, complete days/weekends, logger outages (gaps between rows)."""
    if not samples:
        return None
    gaps_s = Counter(int(b.t - a.t) for a, b in zip(samples, samples[1:]) if 0 < b.t - a.t <= GAP_MIN_S)
    interval = gaps_s.most_common(1)[0][0] if gaps_s else 30
    per_day = 86400.0 / max(interval, 1)
    by_day = Counter(dt_of(s.t).date() for s in samples)
    complete = sorted(d for d, n in by_day.items() if n >= DAY_COMPLETE_FRAC * per_day)
    cset = set(complete)
    weekends = sorted(d for d in cset if d.weekday() == 5 and (d + timedelta(days=1)) in cset)
    outages = [(a.t, b.t - a.t) for a, b in zip(samples, samples[1:]) if b.t - a.t > GAP_MIN_S]
    span = samples[-1].t - samples[0].t
    return dict(interval=interval, by_day=by_day, complete=complete, weekends=weekends,
                outages=sorted(outages, key=lambda x: -x[1]), outage_s=sum(d for _, d in outages),
                expected=span / interval + 1, rows=len(samples), span_days=span / 86400.0)


def unusable_runs(samples, interval, min_s=GAP_MIN_S):
    """Runs of consecutive rows that carry NO usable quote. The logger kept writing rows through
    them, so a gap list cannot see them: they are the closed market (daily break, weekend, holiday)
    and any feed stall. -> [(start, duration)] longest first."""
    runs, start, last = [], None, None
    for sm in samples:
        if usable(sm):
            if start is not None and last - start + interval >= min_s:
                runs.append((start, last - start + interval))
            start = None
        else:
            if start is None:
                start = sm.t
            last = sm.t
    if start is not None and last - start + interval >= min_s:
        runs.append((start, last - start + interval))
    return sorted(runs, key=lambda r: -r[1])


def classify_runs(runs):
    """-> (scheduled, stalls). A run is a scheduled closure when it both starts and ends inside a
    window gold is expected to be shut; anything else is a stall worth a look (exchange holiday, news
    halt, a frozen terminal, a dropped broker connection)."""
    sched, stalls = [], []
    for t0, d in runs:
        (sched if in_closed_window(t0) and in_closed_window(t0 + d - 1) else stalls).append((t0, d))
    return sched, [r for r in stalls if r[1] >= STALL_MIN_S]


# =========================================================================================
# the analyses
# =========================================================================================
def nearest(ts, vals, t, tol):
    i = bisect.bisect_left(ts, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ts) and abs(ts[j] - t) <= tol and (best is None or abs(ts[j] - t) < abs(ts[best] - t)):
            best = j
    return None if best is None else vals[best]


def trade_costs(trades, samples, contract):
    """Measured cost of each trade. The paper P/L is bid-to-bid, so a round trip really pays ONE
    spread (a BUY at entry, a SELL at exit); entry and exit spreads differ, so the mean of the two is
    used. cost = (spread at entry + spread at exit) / 2 x lot x contract. Only trades whose entry AND
    exit have a usable quote within JOIN_TOL_S. -> [(trade, cost, se, sx)]"""
    pts = [s for s in samples if usable(s)]
    ts, sp = [s.t for s in pts], [s.spread for s in pts]
    out = []
    for t in trades:
        se = nearest(ts, sp, t["et"].replace(tzinfo=UTC).timestamp(), JOIN_TOL_S)
        sx = nearest(ts, sp, t["xt"].replace(tzinfo=UTC).timestamp(), JOIN_TOL_S)
        if se is not None and sx is not None:
            out.append((t, (se + sx) / 2.0 * LOT * contract, se, sx))
    return out


def median_1r(trades):
    """Median 1R in $ (price distance x 1 oz). Prefers the live structural-stop era, whose stop
    distances are the current rule's; falls back to the whole ledger. -> (usd, n, label)"""
    era = [t for t in trades if t["et"] >= L.LIVE_CUTOVER]
    use, label = (era, "struct-stop era") if len(era) >= 10 else (trades, "whole ledger")
    if len(use) < 10:
        return None, len(use), label
    return st.median(abs(t["tp"] - t["ep"]) / RR for t in use), len(use), label


def offset_runs(samples):
    """[[offset_s, first_t, last_t, rows]] over USABLE rows only: a carried-forward offset on a
    stale row is not evidence of anything."""
    runs = []
    for s in samples:
        if s.off is None or not usable(s):
            continue
        if runs and runs[-1][0] == s.off:
            runs[-1][2], runs[-1][3] = s.t, runs[-1][3] + 1
        else:
            runs.append([s.off, s.t, s.t, 1])
    return runs


def rule_agreement(samples, rule):
    """(rows where the DST rule predicts the offset the logger observed, rows judged)."""
    ok = n = 0
    for s in samples:
        if s.off is None or not usable(s):
            continue
        n += 1
        ok += BT.server_offset_s(naive_utc(s.t), rule) == s.off
    return ok, n


def next_transition(after_utc_dt):
    """Next EU and US summer-time change strictly after the given naive-UTC datetime."""
    out = {}
    for rule, fn in (("eu", BT.eu_transitions), ("us", BT.us_transitions)):
        cands = sorted(x for y in (after_utc_dt.year, after_utc_dt.year + 1) for x in fn(y))
        out[rule] = next(x for x in cands if x > after_utc_dt)
    return out


def server_time_verdict(samples):
    """-> (status, text). status: NONE | UNVERIFIED | EU | US | NEITHER.

    A rule only counts as CONFIRMED once a transition has been OBSERVED (two or more offset runs) and
    exactly one rule explains every observed row. A single offset proves nothing (a fixed server
    clock would fit just as well), so it stays UNVERIFIED - unless it fits neither rule at all."""
    runs = offset_runs(samples)
    if not runs:
        return "NONE", "no usable row with a known offset yet (the market has to be open to learn it)"
    eu, n = rule_agreement(samples, "eu")
    us, _ = rule_agreement(samples, "us")
    pe, pu = 100.0 * eu / n, 100.0 * us / n
    fits_eu, fits_us = pe >= RULE_OK_PCT, pu >= RULE_OK_PCT
    if not (fits_eu or fits_us):
        return "NEITHER", ("NEITHER rule fits (EU %.2f%%, US %.2f%%, n=%d): do not use --dst eu/us in "
                           "history_to_log; use --offset-hours" % (pe, pu, n))
    if len(runs) == 1:
        nx = next_transition(naive_utc(samples[-1].t))
        after = {r: BT.server_offset_s(nx[r] + timedelta(minutes=1), r) / 3600.0 for r in nx}
        return "UNVERIFIED", (
            "only one offset (%+gh) in the data, so no DST change has been observed and the rule is UNVERIFIED "
            "(fits: EU %.2f%%, US %.2f%%). Next change: EU rule %s UTC (to %+gh), US rule %s UTC (to %+gh); "
            "between those two dates the rules disagree, so that window tells them apart" % (
                runs[0][0] / 3600.0, pe, pu, nx["eu"].strftime("%Y-%m-%d %H:%M"), after["eu"],
                nx["us"].strftime("%Y-%m-%d %H:%M"), after["us"]))
    if fits_eu and not fits_us:
        return "EU", ("the EU rule fits %.2f%% of %d observed rows across %d offset changes (US rule %.2f%%): "
                      "confirmed" % (pe, n, len(runs) - 1, pu))
    if fits_us and not fits_eu:
        return "US", ("the US rule fits %.2f%% of %d observed rows across %d offset changes (EU rule %.2f%%): "
                      "the server follows NEW YORK time" % (pu, n, len(runs) - 1, pe))
    return "UNVERIFIED", ("both rules fit (EU %.2f%%, US %.2f%%, n=%d): the change did not fall in a window that "
                          "tells them apart" % (pe, pu, n))


# =========================================================================================
# rendering
# =========================================================================================
def money(x):
    return "     n/a" if x is None else "$%7.2f" % x


def row_line(label, s, unit):
    if not s.get("n"):
        return "  %-26s %7d" % (label, 0)
    return "  %-26s %7d %s %s %s %s %s   $%5.2f / $%5.2f" % (
        label, s["n"], money(s["med"]), money(s["p90"]), money(s["p95"]), money(s["p99"]), money(s["mx"]),
        s["med"] * unit, s["p95"] * unit)


TABLE_HEAD = "  %-26s %7s %8s %8s %8s %8s %8s   $/trade med / p95" % (
    "", "n", "median", "p90", "p95", "p99", "max")


def spread_tables(title, pts, unit):
    """pts = [(t, spread_usd_per_oz)]. Prints the session / weekly-open / blackout views."""
    print(TABLE_HEAD)
    print(row_line(title, summarize([v for _, v in pts]), unit))
    print("  -- by UTC session --")
    for label, name in SESSIONS:
        v = [x for t, x in pts if session_of(t) == name and not week_open_of(t)]
        if v:
            print(row_line(label, summarize(v), unit))
    v = [x for t, x in pts if week_open_of(t)]
    if v:
        print(row_line("WEEKLY OPEN (Sun-Mon 01h)", summarize(v), unit))
    if BLACKOUT_WINDOWS:
        print("  -- blackout windows (the engine's own, UTC) --")
        for sh, sm, eh, em, label, *_ in BLACKOUT_WINDOWS:
            v = [x for t, x in pts if blackout_of(t) == label]
            if v:
                print(row_line(("%02d:%02d-%02d:%02d %s" % (sh, sm, eh, em, label))[:26], summarize(v), unit))
        v = [x for t, x in pts if blackout_of(t) is None]
        if v:
            print(row_line("outside every blackout", summarize(v), unit))


def hour_table(pts):
    print("  UTC hour      n    med    p90    p95   ($ per oz)")
    for h in range(24):
        a = summarize([x for t, x in pts if dt_of(t).hour == h])
        line = "%7d %6.2f %6.2f %6.2f" % (a["n"], a["med"], a["p90"], a["p95"]) if a.get("n") else \
            "      -      -      -      -"
        print("     %02d  %s" % (h, line))


def _paths(a):
    qdir = a.dir if os.path.isabs(a.dir) else os.path.join(a.root, a.dir)
    return qdir, (a.now if a.now is not None else time.time())


def _contract(spec):
    return ((spec or {}).get("symbol_info") or {}).get("trade_contract_size") or 100.0


def report(a):
    qdir, now = _paths(a)
    since = now - a.days * 86400 if a.days else None
    samples, malformed, nfiles = load_quotes(qdir, since)
    spec = load_spec(qdir)
    contract = _contract(spec)
    unit = LOT * contract                          # $ per trade per $1 of spread

    print("xm_quote_report - %s  (%d quote files, %d rows%s)" % (
        qdir, nfiles, len(samples), ", %d malformed lines skipped" % malformed if malformed else ""))
    if not samples:
        print("  no quote rows yet. Install the sidecar (docs/XM-LOGGER.md) and let it run.")
        return 1

    # ---- 1. LOGGER --------------------------------------------------------------------
    cov = coverage(samples)
    newest = samples[-1]
    print("\n== 1. LOGGER: progress against the sample target (>= %d complete days incl. %d weekends) ==" % (
        TARGET_DAYS, TARGET_WEEKENDS))
    print("  %s -> %s UTC  (%.1f days)   newest row %.0f min ago (%s)" % (
        Q.utc_str(samples[0].t), Q.utc_str(newest.t), cov["span_days"], (now - newest.t) / 60.0,
        "market OPEN - fresh tick" if usable(newest) else "market CLOSED or feed frozen - rows continue, tick is stale"))
    nd, nw = len(cov["complete"]), len(cov["weekends"])
    print("  complete UTC days (>= %.0f%% of rows): %d / %d    complete weekends (Sat+Sun): %d / %d" % (
        100 * DAY_COMPLETE_FRAC, nd, TARGET_DAYS, nw, TARGET_WEEKENDS))
    print("  rows %d of ~%.0f expected (%.1f%%), interval %ds; LOGGER outage time %.1f h in %d gaps > %d min" % (
        cov["rows"], cov["expected"], 100.0 * cov["rows"] / max(cov["expected"], 1), cov["interval"],
        cov["outage_s"] / 3600.0, len(cov["outages"]), GAP_MIN_S // 60))
    for t0, d in cov["outages"][:3]:
        print("     longest gaps: %s UTC for %.0f min" % (Q.utc_str(t0), d / 60.0))
    runs = unusable_runs(samples, cov["interval"])
    sched, stalls = classify_runs(runs)
    print("  market closed (rows kept, tick frozen): %d scheduled runs (daily break / weekend), %.1f h in total" % (
        len(sched), sum(d for _, d in sched) / 3600.0))
    if stalls:
        print("  FEED STALLS while the market should be open (>= %d min): %d, %.1f h in total; longest: %s" % (
            STALL_MIN_S // 60, len(stalls), sum(d for _, d in stalls) / 3600.0,
            "; ".join("%s UTC (%s) %.0f min" % (Q.utc_str(t0), dt_of(t0).strftime("%a"), d / 60.0)
                      for t0, d in stalls[:3])))
        print("     (an exchange holiday or news halt looks like this too; a stall that repeats is a feed problem)")
    else:
        print("  feed stalls outside the scheduled closures: none")
    fl = Counter(f for s in samples for f in s.flags)
    print("  flags: %s    offsets seen: %s" % (
        ", ".join("%s %d" % kv for kv in sorted(fl.items())) or "none",
        ", ".join("%+gh" % (o / 3600.0) for o in sorted({s.off for s in samples if s.off is not None})) or "unknown"))
    ages = sorted(s.age for s in samples if usable(s) and s.age is not None)
    if ages:
        print("  tick age (fresh rows) median %.1f s, p99 %.1f s%s" % (
            pct(ages, .5), pct(ages, .99),
            "   <-- WARNING: large median age = box clock skew or a laggy feed" if pct(ages, .5) > 30 else ""))
    met = nd >= TARGET_DAYS and nw >= TARGET_WEEKENDS
    print("  sample target: %s" % ("MET - the cost numbers below are decision-grade" if met else
                                   "NOT YET (%d more complete days, %d more weekends) - read the numbers as a first look" % (
                                       max(0, TARGET_DAYS - nd), max(0, TARGET_WEEKENDS - nw))))

    # ---- 2. SPREAD --------------------------------------------------------------------
    good = [s for s in samples if usable(s)]
    pts = [(s.t, s.spread) for s in good]
    print("\n== 2. SPREAD: what XM quoted (usable %d of %d rows; $ per oz; x%.2f = $ per trade at %.2f lot) ==" % (
        len(good), len(samples), unit, LOT))
    if not good:
        print("  no usable (fresh) quote yet - the market was closed for the whole logged span")
    else:
        spread_tables("all usable samples", pts, unit)
        env = [s.smax for s in good if s.smax is not None]
        print(row_line("5 s spike envelope (max)", summarize(env), unit))
        vals = [v for _, v in pts]
        trades = load_trades(a.root)
        oneR, n1r, lab1r = median_1r(trades)
        print("\n  share of usable samples ABOVE:")
        cuts = [("assumed cost $%.2f/trade = $%.2f/oz" % (ASSUMED_USD_PER_TRADE, ASSUMED_USD_PER_TRADE / unit),
                 ASSUMED_USD_PER_TRADE / unit)]
        if oneR:
            for c in SHARE_1R_CUTS:
                cuts.append(("%.0f%% of the median 1R ($%.2f, %s n=%d) = $%.2f/oz" % (
                    100 * c, oneR, lab1r, n1r, c * oneR / unit), c * oneR / unit))
        for label, thr in sorted(cuts, key=lambda x: x[1]):
            print("    %5.1f%%   > %s" % (share_above(vals, thr), label))
        med = pct(sorted(vals), .5)
        if oneR:
            print("\n  median spread = %.1f%% of 1R ($%.2f/trade vs 1R $%.2f); the assumed $%.2f is %.1f%% of 1R" % (
                100 * med * unit / oneR, med * unit, oneR, ASSUMED_USD_PER_TRADE, 100 * ASSUMED_USD_PER_TRADE / oneR))
        print("\n  hour-of-day profile (usable samples):")
        hour_table(pts)

    # ---- 3. COST on the actual trades -------------------------------------------------
    print("\n== 3. COST: $%.2f assumed vs the spread measured when the ledger's trades entered/exited ==" % (
        ASSUMED_USD_PER_TRADE))
    trades = load_trades(a.root)
    if not trades:
        print("  no trades.csv at %s" % a.root)
    else:
        tc = trade_costs(trades, samples, contract)
        if not tc:
            print("  no closed trade overlaps the quote data yet (%d trades in the ledger; the logger "
                  "started %s UTC)" % (len(trades), Q.utc_str(samples[0].t)))
        else:
            costs = [c for _, c, _, _ in tc]
            gross_sum = sum(t["pnl"] for t, _, _, _ in tc)
            print("  %d trades with a usable quote at entry and exit (+-%ds)" % (len(tc), JOIN_TOL_S))
            print("  measured round trip: mean $%.2f  median $%.2f  p90 $%.2f  max $%.2f   (assumed $%.2f)" % (
                st.mean(costs), st.median(costs), pct(sorted(costs), .9), max(costs), ASSUMED_USD_PER_TRADE))
            print("  same trades: gross %+.2f | net at $%.2f flat %+.2f | net at the MEASURED cost %+.2f" % (
                gross_sum, ASSUMED_USD_PER_TRADE, gross_sum - ASSUMED_USD_PER_TRADE * len(tc), gross_sum - sum(costs)))
            by = {}
            for t, c, _, _ in tc:
                by.setdefault(session_of(t["et"].replace(tzinfo=UTC).timestamp()), []).append(c)
            print("  measured cost by entry session: %s" % "  ".join(
                "%s $%.2f (n=%d)" % (n, st.median(v), len(v)) for n, v in sorted(by.items())))
            m = st.median(costs)
            print("  to re-cost the ledger at the measured median:  win_rate_report.py --spread %.2f   |   "
                  "strategy_lab.py --cost %.2f   (per side)" % (m, m / 2.0))
            if len(tc) < 30:
                print("  (n=%d is far too small to conclude anything - this is a plumbing check until n >= ~30)" % len(tc))

    # ---- 4. SERVER TIME ---------------------------------------------------------------
    print("\n== 4. SERVER TIME: the broker clock the logger observed vs the DST rules ==")
    for off, t0, t1, n in offset_runs(samples):
        print("  %+gh   %s -> %s UTC   (%d fresh rows)" % (off / 3600.0, Q.utc_str(t0), Q.utc_str(t1), n))
    status, text = server_time_verdict(samples)
    print("  verdict [%s]: %s" % (status, text))
    if status in ("EU", "US"):
        print("  -> tools/history_to_log.py --dst %s" % status.lower())

    # ---- 5. SPEC ----------------------------------------------------------------------
    print("\n== 5. SPEC: contract facts ==")
    if not spec:
        print("  no symbol_spec.json yet")
    else:
        si, dec = spec.get("symbol_info") or {}, spec.get("decoded") or {}
        acct, term = spec.get("account") or {}, spec.get("terminal") or {}
        print("  captured %s UTC  label %r  history entries %d (a new one = XM changed something)" % (
            spec.get("captured_utc"), spec.get("label"), spec_changes(qdir)))
        print("  account: %s, %s, leverage 1:%s, %s | terminal build %s, maxbars %s" % (
            dec.get("account_kind"), dec.get("margin_mode"), acct.get("leverage"), acct.get("currency"),
            term.get("build"), term.get("maxbars")))
        print("  execution %s | filling flags %s | order types %s | symbol trade mode %s" % (
            dec.get("execution_mode"), dec.get("filling_allowed_flags"), dec.get("order_types_allowed"),
            dec.get("symbol_trade_mode")))
        print("  stops level %s pts, freeze level %s pts | volume min %s step %s max %s | contract %s | digits %s point %s" % (
            si.get("trade_stops_level"), si.get("trade_freeze_level"), si.get("volume_min"), si.get("volume_step"),
            si.get("volume_max"), si.get("trade_contract_size"), si.get("digits"), si.get("point")))
        print("  swap: %s long %s short %s, triple on %s | spread now %s pts (floating: %s)" % (
            dec.get("swap_mode"), si.get("swap_long"), si.get("swap_short"), dec.get("swap_triple_day"),
            spec.get("spread_points_now"), si.get("spread_float")))
        pr = (spec.get("probes") or {}).get("calc_profit_usd_0.01lot_plus_1usd")
        checks = [("contract size 100 oz (0.01 lot = 1 oz)", si.get("trade_contract_size") == 100.0),
                  ("min lot 0.01", si.get("volume_min") == 0.01),
                  ("0.01 lot x $1 move = $1.00 (order_calc_profit)", pr == 1.0)]
        print("  assumption checks: " + "; ".join(
            "%s %s" % (n, "OK" if ok else "MISMATCH (%s)" % (pr if "calc" in n else "see above")) for n, ok in checks))
        if not checks[2][1]:
            print("  WARNING: if the lot arithmetic is not 1.0 every dollar in trades.csv is mis-scaled against the broker")
        if dec.get("account_kind") == "DEMO":
            print("  NOTE: these spreads come from a DEMO account. XM demo normally mirrors live pricing, but any "
                  "go-live cost decision must be confirmed on the account that will actually trade.")
        if spec.get("errors"):
            print("  spec probe errors: %s" % spec["errors"])
    return 0


def quiet_line(a):
    qdir, now = _paths(a)
    samples, malformed, nfiles = load_quotes(qdir, since=now - QUIET_WINDOW_DAYS * 86400)
    if not samples:
        rel = os.path.relpath(qdir, a.root)
        return "xm logger: not collecting yet (no quote rows in %s)" % (qdir if rel.startswith("..") else rel)
    cov = coverage(samples)
    age_s = now - samples[-1].t
    good = sorted(s.spread for s in samples if usable(s))
    status = "OK" if age_s <= STALE_AFTER_S else \
        "STALE (newest row %.1f h old - is mt5quotes-gold running?)" % (age_s / 3600.0)
    tail = ""
    if good:
        unit = LOT * _contract(load_spec(qdir))
        tail = " | spread median $%.2f p95 $%.2f /oz ($%.2f/trade median)" % (
            pct(good, .5), pct(good, .95), pct(good, .5) * unit)
    mkt = "" if usable(samples[-1]) else " | market closed or feed frozen"
    return "xm logger: %s | %d/%d complete days, %d/%d weekends | rows %d, outage %.1f h%s%s" % (
        status, len(cov["complete"]), TARGET_DAYS, len(cov["weekends"]), TARGET_WEEKENDS, cov["rows"],
        cov["outage_s"] / 3600.0, tail, mkt)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report on the XM GOLD quote / spec logger data")
    ap.add_argument("--root", default=ROOT, help="repo root (trades.csv lives here)")
    ap.add_argument("--dir", default="xm_data", help="logger data directory (relative to --root)")
    ap.add_argument("--days", type=int, default=0, help="only the newest N UTC days of quote rows (0 = all)")
    ap.add_argument("--quiet", action="store_true", help="one advisory line; never fails")
    ap.add_argument("--now", type=float, default=None, help=argparse.SUPPRESS)   # tests
    a = ap.parse_args(argv)
    if a.quiet:
        try:
            print(quiet_line(a))
        except Exception as e:                      # advisory: must never break the autosync digest
            print("xm logger: report error (%s: %s)" % (type(e).__name__, e))
        return 0
    return report(a)


if __name__ == "__main__":
    sys.exit(main())
