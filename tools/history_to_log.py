#!/usr/bin/env python3
"""history_to_log - turn `mt5_history_dump.py` output into a UTC bar file `strategy_lab --bars` can replay.
(the large-N research path: docs/ACCELERATE-TESTING.md; port of the idea in bitcoin-trading-bot PR #18)

THE TRAP THIS EXISTS FOR. mt5_history_dump.py writes MT5's bar times as they come, i.e. BROKER-SERVER
time (XM: UTC+3 in summer, UTC+2 in winter), and labels them as UTC (its ts_to_str uses tz=utc). Every
UTC rule in the lab - the blackout windows, the Asia/London/NY bands, the daily-loss day - would be
silently hours off. forward_test_log.csv uses UTC and stamps a bar when it CLOSES; MT5 stamps it when
it OPENS. This tool fixes both, and it will not guess:

  python3 tools/history_to_log.py mt5_history.csv --out history_utc.csv     # convert (validated)
  python3 tools/history_to_log.py mt5_history.csv --check-only              # validate, write nothing

HOW THE TIME BASIS IS PROVEN (not assumed). From 2026-09-10 the engine's forward_test_log.csv is fed by
the MT5 sidecar, i.e. by the SAME terminal's closed M1 bars (before that it came from Twelve Data, whose
bars are a different vendor's and cannot validate XM history). So the log is an exact, UTC-stamped copy
of part of the history. This tool matches the two minute by minute on all four of OHLC, for every
candidate whole-hour offset, and refuses unless one offset explains the overlap (>= --min-match, default
90 %). It also does it per UTC day, so a DST change INSIDE the overlap is directly OBSERVED - the first
one the log will contain is Sunday 2026-10-25 - and the observed runs decide which DST rule (EU/US)
tools/broker_time.py should apply to bars OUTSIDE the overlap.

WHAT IS AND IS NOT VERIFIED. Bars inside the overlap are verified to the bar. Bars outside it (the
point of the exercise: more history) are converted with the DST rule, which is verified only if a
transition was observed. If the whole span lies inside one regime under BOTH rules (anything pulled
between 2026-03-29 and 2026-10-25 does), the conversion does not depend on the rule and the report
says so; otherwise it names the span that does depend on it.

Output: Timestamp,Open,High,Low,Close,Volume - UTC, Timestamp = bar CLOSE (open + 60 s), Volume = tick
volume, price text copied verbatim. The dump's LAST row is the still-forming bar (it reads from position 0,
the live feed reads position 1 = closed bars only), so the last bar is dropped unless --keep-last. It never overwrites forward_test_log.csv. Exit 0 ok, 1 refused, 2 usage.
Pure stdlib; the converter functions are importable (smoke_test.py Scenario S).
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import broker_time as BT  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"
OUT_FIELDS = ["Timestamp", "Open", "High", "Low", "Close", "Volume"]
# First full day the log is fed by the MT5 sidecar (docs/HANDOFF.md section 3: configured 2026-09-10; the
# log before that came from Twelve Data). Earlier log rows are a different vendor's bars: never compared.
MT5_FEED_START = datetime(2026, 9, 11)
MATCH_TOL = 0.006                  # prices are 2 digits; the dump strips trailing zeros of 5
CANDIDATES_H = range(-12, 15)      # whole-hour offsets scanned (server - UTC)
DAY_MIN_BARS = 200                 # a UTC day needs this many comparable bars to vote on its offset
DAY_MIN_MATCHES = 50               # ... and this many exact matches for the winner
RULE_FIT = 0.99                    # a DST rule "explains" the observed days at or above this share


class Refused(Exception):
    """Validation failed: the message is the diagnosis the operator needs."""


# =========================================================================================
# reading
# =========================================================================================
def read_raw(path):
    """-> (bars, skipped). bars = [(server_open_dt, o_txt, h_txt, l_txt, c_txt, vol_int, (o, h, l, c))]
    sorted, one per server minute. Raises Refused for a file that is not mt5_history_dump output."""
    try:
        fh = open(path, newline="", encoding="utf-8", errors="replace")
    except OSError as e:
        raise Refused("cannot read %s: %s" % (path, e))
    with fh:
        rd = csv.reader(fh)
        head = [h.strip() for h in (next(rd, None) or [])]
        need = ["Timestamp", "Open", "High", "Low", "Close"]
        if head[:5] != need or ("TickVolume" not in head and "Volume" not in head):
            raise Refused("%s is not mt5_history_dump output (header %s; expected Timestamp,Open,High,Low,Close,"
                          "TickVolume[,Spread])" % (path, ",".join(head[:8])))
        if "TickVolume" not in head:
            raise Refused("%s has a Volume column and no TickVolume: it already looks like a converted/log-format "
                          "file (UTC). Converting it again would shift it by the server offset a second time." % path)
        ivol = head.index("TickVolume")
        seen, bars, skipped = {}, [], 0
        for p in rd:
            if len(p) <= ivol:
                skipped += 1
                continue
            try:
                t = datetime.strptime(p[0].strip(), TS_FMT)
                px = tuple(float(x) for x in p[1:5])
                vol = int(float(p[ivol]))
            except ValueError:
                skipped += 1
                continue
            if not all(x > 0 for x in px) or px[1] < max(px[0], px[3]) - 1e-9 or px[2] > min(px[0], px[3]) + 1e-9:
                skipped += 1                              # a bar with high < open/close or low > open/close is corrupt
                continue
            seen[t] = (t, p[1].strip(), p[2].strip(), p[3].strip(), p[4].strip(), vol, px)
    bars = [seen[t] for t in sorted(seen)]
    return bars, skipped


def read_log_minutes(path, since):
    """forward_test_log.csv -> {close_minute: (o, h, l, c)} for rows at or after `since` (the MT5 era). The log
    stamps a row when the engine sees the bar CLOSE (a few seconds late), so the minute floor of the stamp
    IS the bar's close minute. The first row of a minute wins (a restart can re-log a candle)."""
    out = {}
    try:
        fh = open(path, newline="", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for r in csv.DictReader(fh):
            try:
                t = datetime.strptime(r["Timestamp"], TS_FMT)
                if t < since:
                    continue
                k = t.replace(second=0, microsecond=0)
                if k not in out:
                    out[k] = tuple(float(r[c]) for c in ("Open", "High", "Low", "Close"))
            except (ValueError, KeyError, TypeError):
                continue
    return out


# =========================================================================================
# the offset proof
# =========================================================================================
def _shift(off_s):
    """What to subtract from a bar's OPEN time (server clock) to get its UTC CLOSE minute: the offset, less the
    bar's own minute. Built once per candidate, not once per bar."""
    return timedelta(seconds=off_s) - timedelta(minutes=1)


def _same(px, lg):
    return all(abs(a - b) <= MATCH_TOL for a, b in zip(px, lg))


def day_tally(bars, log_map, candidates=CANDIDATES_H):
    """One pass over every candidate offset: {utc_date: {offset_h: [exact matches, compared]}}. The date is the UTC
    date of the matched LOG minute, so a DST change inside the overlap shows up as the winner moving between days."""
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    if not log_map:
        return per
    for h in candidates:
        shift = _shift(h * 3600)
        get = log_map.get
        for b in bars:
            k = b[0] - shift
            lg = get(k)
            if lg is None:
                continue
            c = per[k.date()][h]
            c[1] += 1
            c[0] += _same(b[6], lg)
    return per


def totals(per):
    """{offset_h: (matches, compared)} summed over every day - the diagnosis table."""
    tot = defaultdict(lambda: [0, 0])
    for d in per.values():
        for h, (m, n) in d.items():
            tot[h][0] += m
            tot[h][1] += n
    return {h: tuple(v) for h, v in tot.items()}


def day_offsets(per):
    """Per UTC day: the offset that explains it. -> [(date, offset_h or None, matches, compared, runner_up_matches)]
    ascending. A day votes only if it has enough comparable bars and its winner has at least twice the runner-up's
    matches; a weekend, a thin day or an ambiguous tape votes None."""
    out = []
    for d in sorted(per):
        ranked = sorted(per[d].items(), key=lambda kv: -kv[1][0])
        h1, (m1, n1) = ranked[0]
        m2 = ranked[1][1][0] if len(ranked) > 1 else 0
        ok = n1 >= DAY_MIN_BARS and m1 >= DAY_MIN_MATCHES and m1 >= 2 * max(m2, 1)
        out.append((d, h1 if ok else None, m1, n1, m2))
    return out


def offset_runs(days):
    """[(offset_h, first_date, last_date, n_days)] over the days that voted (undetermined days are skipped)."""
    runs = []
    for d, h, *_ in days:
        if h is None:
            continue
        if runs and runs[-1][0] == h:
            runs[-1] = (h, runs[-1][1], d, runs[-1][3] + 1)
        else:
            runs.append((h, d, d, 1))
    return runs


def rule_fit(days, rule):
    """Share of the voting days on which the DST rule predicts the observed offset (evaluated at noon UTC)."""
    voted = [(d, h) for d, h, *_ in days if h is not None]
    if not voted:
        return 0.0
    ok = sum(BT.server_offset_s(datetime(d.year, d.month, d.day, 12), rule) == h * 3600 for d, h in voted)
    return ok / len(voted)


def choose_rule(dst, days, runs):
    """-> (rule or 'fixed', fixed_offset_h or None, how). Raises Refused when the data contradicts the choice."""
    observed = runs[0][0] if runs else None
    if dst == "none":
        if len(runs) > 1:
            raise Refused("--dst none applies ONE fixed offset, but the overlap shows the server clock changed "
                          "(%s). Use --dst auto/eu/us." % ", ".join("%+dh %s..%s" % (h, a, b) for h, a, b, _ in runs))
        return "fixed", observed, "fixed %+dh, as measured in the overlap (valid only if the whole history lies in the " \
                                  "same DST regime)" % observed
    if dst in ("eu", "us"):
        f = rule_fit(days, dst)
        if f < RULE_FIT:
            raise Refused("the %s DST rule predicts the WRONG offset on %.0f%% of the overlap days (observed %s). Try the "
                          "other rule, or --dst none for a fixed offset." % (
                              dst.upper(), 100 * (1 - f), ", ".join("%+dh" % r[0] for r in runs)))
        return dst, None, "%s rule (fits %.0f%% of the overlap days%s)" % (
            dst.upper(), 100 * f, "; a transition was observed" if len(runs) > 1 else "; NO transition observed yet")
    # auto
    fits = {r: rule_fit(days, r) for r in ("eu", "us")}
    ok = [r for r in ("eu", "us") if fits[r] >= RULE_FIT]
    if len(runs) > 1:                                    # a transition inside the overlap: the data picks the rule
        if len(ok) == 1:
            return ok[0], None, "%s rule - the overlap OBSERVED a transition and only this rule explains it" % ok[0].upper()
        raise Refused("the overlap shows an offset change (%s) that %s DST rule explains (EU %.0f%%, US %.0f%% of days). "
                      "Do not guess: convert after the logger's xm_data confirms the rule, or split the history." % (
                          ", ".join("%+dh %s..%s" % (h, a, b) for h, a, b, _ in runs),
                          "neither" if not ok else "both", 100 * fits["eu"], 100 * fits["us"]))
    if "eu" in ok:                                       # one regime: EU is XM's documented rule
        return "eu", None, "EU rule (XM's documented behaviour; consistent with the overlap, NO transition observed yet)"
    raise Refused("the overlap says %+dh but the EU rule (XM's documented behaviour) predicts a different offset there "
                  "(EU %.0f%%, US %.0f%%). If the server really is on a fixed offset use --dst none; if on US time use "
                  "--dst us." % (observed, 100 * fits["eu"], 100 * fits["us"]))


# =========================================================================================
# conversion
# =========================================================================================
def convert(bars, rule, fixed_h=None):
    """-> (rows ascending [(utc_close_dt, o, h, l, c, vol)], dropped_duplicates)."""
    seen = {}
    for b in bars:
        if rule == "fixed":
            u_open = b[0] - timedelta(hours=fixed_h)
        else:
            u_open = BT.server_to_utc(b[0], rule)
        seen[u_open + timedelta(minutes=1)] = (u_open + timedelta(minutes=1), b[1], b[2], b[3], b[4], b[5])
    rows = [seen[t] for t in sorted(seen)]
    return rows, len(bars) - len(rows)


def span_offsets(bars, rule, fixed_h=None):
    """[(offset_h, first_server_dt, last_server_dt, n_bars)] actually APPLIED across the history."""
    runs = []
    for b in bars:
        if rule == "fixed":
            h = fixed_h
        else:
            u = BT.server_to_utc(b[0], rule)
            h = int((b[0] - u).total_seconds() // 3600)
        if runs and runs[-1][0] == h:
            runs[-1] = (h, runs[-1][1], b[0], runs[-1][3] + 1)
        else:
            runs.append((h, b[0], b[0], 1))
    return runs


def rule_dependence(first_utc, last_utc):
    """Does the conversion of [first, last] (UTC) depend on WHICH rule is right? True when EU and US predict a
    different offset anywhere in the span, or when either predicts a change inside it."""
    t, step, differs, offs = first_utc, timedelta(hours=6), False, set()
    while t <= last_utc:
        e, u = BT.server_offset_s(t, "eu"), BT.server_offset_s(t, "us")
        differs |= e != u
        offs.add(e)
        offs.add(u)
        t += step
    return differs, len(offs) > 1


def write_rows(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(OUT_FIELDS)
        for t, o, h, l, c, v in rows:
            w.writerow([t.strftime(TS_FMT), o, h, l, c, v])
    os.replace(tmp, path)


# =========================================================================================
# the tool
# =========================================================================================
def plan(raw, log_map, a):
    """Validate against the overlap and decide the conversion. -> dict(rule, fixed_h, how, lines, runs, days, match).
    Raises Refused."""
    lines = []
    if not log_map:
        if a.no_validate and (a.offset_hours is not None or a.dst in ("eu", "us")):
            lines.append("UNVALIDATED: --no-validate was given, so the time basis is whatever you asserted, not something "
                         "this run proved")
            rule, fixed = ("fixed", a.offset_hours) if a.offset_hours is not None else (a.dst, None)
            return dict(rule=rule, fixed_h=fixed, how="asserted, unvalidated", lines=lines, runs=[], days=[], match=None)
        raise Refused("no MT5-era rows in %s (from %s) to prove the time basis against. Run this on a checkout whose "
                      "forward_test_log.csv covers the history's recent end, or assert it yourself with "
                      "--offset-hours H (or --dst eu|us) --no-validate." % (a.log, a.overlap_from.date()))
    cands = [a.offset_hours] if a.offset_hours is not None else list(CANDIDATES_H)
    per = day_tally(raw, log_map, cands)
    tot = totals(per)
    ranked = sorted(tot.items(), key=lambda kv: -kv[1][0])
    if not ranked:
        raise Refused("the history and the log's MT5 era (from %s) share NO minute at any offset %+d..%+dh: the pull does "
                      "not reach the log's period. Pull more recent bars (the dump takes the LAST N)." % (
                          a.overlap_from.date(), min(cands), max(cands)))
    lines.append("overlap with %s (MT5 era from %s): %d minutes compared at the best offset" % (
        os.path.basename(a.log), a.overlap_from.date(), ranked[0][1][1]))
    for h, (m, n) in ranked[:3]:
        lines.append("   offset %+3dh : %5.1f%% exact OHLC match over the whole overlap (%d / %d)" % (
            h, 100 * m / max(n, 1), m, n))
    days = day_offsets(per)
    runs = offset_runs(days)
    voted = [d for d in days if d[1] is not None]
    if a.offset_hours is not None:
        # an asserted offset has no rival to out-vote, so judge it on EVERY compared bar, not just the days that voted
        m, n = tot.get(a.offset_hours, (0, 0))
        frac = m / max(n, 1)
    else:
        if not voted:
            raise Refused("no UTC day in the overlap has a clear winner (a day needs >= %d comparable bars and a best offset "
                          "with twice the runner-up's matches). The overlap is too thin or too flat to prove the time basis; "
                          "pull a longer, more recent history." % DAY_MIN_BARS)
        frac = sum(d[2] for d in voted) / max(sum(d[3] for d in voted), 1)
    lines.append("per-day offsets: %s over %d determined days (%.1f%% of their bars match exactly)" % (
        ", ".join("%+dh %s..%s (%dd)" % (h, a_, b_, n) for h, a_, b_, n in runs) or "none", len(voted), 100 * frac))
    if frac < a.min_match:
        raise Refused("the winning offset(s) explain only %.1f%% of the compared bars (need >= %.0f%%). Either the history is "
                      "not this symbol/terminal, or its bars differ from the live feed. If you accept that, lower "
                      "--min-match - but then read every result as an approximation." % (100 * frac, 100 * a.min_match))
    if a.offset_hours is not None:
        return dict(rule="fixed", fixed_h=a.offset_hours, how="--offset-hours %+d (validated: %.1f%% match)" % (
            a.offset_hours, 100 * frac), lines=lines, runs=runs, days=days, match=frac)
    rule, fixed, how = choose_rule(a.dst, days, runs)
    return dict(rule=rule, fixed_h=fixed, how=how, lines=lines, runs=runs, days=days, match=frac)


def run(a, out=print):
    raw, skipped = read_raw(a.history)
    if not raw:
        raise Refused("no usable bars in %s" % a.history)
    forming = None
    if not a.keep_last and len(raw) > 1:
        forming = raw.pop()                  # mt5_history_dump asks for start_pos 0: the LAST row is the bar still forming
    log_map = {} if a.no_validate else read_log_minutes(a.log, a.overlap_from)
    out("history_to_log: %d raw bars  %s .. %s  (server time, as labelled)%s" % (
        len(raw), raw[0][0].strftime(TS_FMT), raw[-1][0].strftime(TS_FMT),
        ("  [%d malformed rows skipped]" % skipped) if skipped else ""))
    if forming is not None:
        out("  dropped the last bar (%s): the dump reads from position 0, so it is the still-forming bar with partial OHLC "
            "(--keep-last to keep it)" % forming[0].strftime(TS_FMT))
    p = plan(raw, log_map, a)
    for ln in p["lines"]:
        out("  " + ln)
    out("  conversion: %s" % p["how"])
    applied = span_offsets(raw, p["rule"], p["fixed_h"])
    out("  offsets applied: %s" % "; ".join("%+dh %s .. %s (%d bars)" % (
        h, f.strftime("%Y-%m-%d"), l.strftime("%Y-%m-%d"), n) for h, f, l, n in applied))
    if p["rule"] == "fixed":
        first_u, last_u = (raw[0][0] - timedelta(hours=p["fixed_h"]), raw[-1][0] - timedelta(hours=p["fixed_h"]))
    else:
        first_u, last_u = BT.server_to_utc(raw[0][0], p["rule"]), BT.server_to_utc(raw[-1][0], p["rule"])
    differs, changes = rule_dependence(first_u, last_u)
    observed = len(p["runs"]) > 1
    if p["rule"] == "fixed":
        if differs or changes:
            out("  WARNING: one fixed offset is applied, but the EU/US rules predict a change (or disagree) inside this "
                "span: bars on the other side of it are shifted by an hour")
        else:
            out("  the span lies inside ONE offset regime under both the EU and the US rule: the conversion does not "
                "depend on which rule is right")
    elif len(applied) > 1:
        out("  NOTE: the span crosses a DST change (%s). Bars on each side use their own offset; the change itself is %s. "
            "tools/xm_quote_report.py section 4 (the logger's observed offsets) is the independent check." % (
                " -> ".join("%+dh" % h for h, *_ in applied),
                "OBSERVED in the overlap" if observed else "from the RULE ONLY - nothing in the overlap confirms it yet"))
    elif differs:
        out("  NOTE: the EU and US rules disagree somewhere inside this span, so the conversion there rests on the %s rule "
            "(%s)." % (p["rule"].upper(), "a transition was observed" if observed else "UNVERIFIED: nothing in the overlap "
                                                                                       "confirms it yet"))
    else:
        out("  the span lies inside ONE offset regime under both the EU and the US rule: the conversion does not depend "
            "on which rule is right")
    rows, dups = convert(raw, p["rule"], p["fixed_h"])
    if dups:
        out("  dropped %d bars that mapped onto an already-converted minute" % dups)
    if a.check_only:
        out("  --check-only: nothing written. Verdict: the conversion above would be used for %d bars." % len(rows))
        return 0
    abs_out = os.path.abspath(a.out)
    for guard in (a.log, os.path.join(ROOT, "forward_test_log.csv")):
        if os.path.abspath(guard) == abs_out:
            raise Refused("refusing to write over %s (the live log). Choose another --out." % guard)
    write_rows(a.out, rows)
    out("  wrote %d bars -> %s  (UTC, Timestamp = bar CLOSE, %s .. %s)" % (
        len(rows), a.out, rows[0][0].strftime(TS_FMT), rows[-1][0].strftime(TS_FMT)))
    out("  next: python3 tools/strategy_lab.py --bars %s" % a.out)
    return 0


def main(argv=None, out=print):
    ap = argparse.ArgumentParser(description="Convert mt5_history_dump output to a validated UTC bar file")
    ap.add_argument("history", help="CSV written by tools/mt5_history_dump.py (Timestamp,Open,High,Low,Close,TickVolume,Spread)")
    ap.add_argument("--out", default=None, help="output CSV (UTC, log format). Required unless --check-only")
    ap.add_argument("--log", default=os.path.join(ROOT, "forward_test_log.csv"),
                    help="the live log to prove the time basis against (default: the repo's)")
    ap.add_argument("--dst", choices=["auto", "eu", "us", "none"], default="auto",
                    help="DST rule for bars outside the overlap. auto = the data decides if it observed a transition, "
                         "else the EU rule (XM's documented behaviour); none = one fixed offset for everything")
    ap.add_argument("--offset-hours", type=int, default=None,
                    help="assert a fixed server-UTC offset (still validated against the overlap)")
    ap.add_argument("--min-match", type=float, default=0.90, help="exact-OHLC share the best offset must reach (0-1)")
    ap.add_argument("--overlap-from", default=MT5_FEED_START.strftime("%Y-%m-%d"),
                    help="first date of the log to trust as MT5-fed (default %(default)s)")
    ap.add_argument("--no-validate", action="store_true",
                    help="skip the overlap proof (only with --offset-hours or --dst eu|us); the result is unvalidated")
    ap.add_argument("--keep-last", action="store_true",
                    help="keep the final bar of the file (default: drop it - the dump's last row is the still-forming bar)")
    ap.add_argument("--check-only", action="store_true", help="validate and report; write nothing")
    a = ap.parse_args(argv)
    try:
        a.overlap_from = datetime.strptime(a.overlap_from, "%Y-%m-%d")
    except ValueError:
        out("--overlap-from needs YYYY-MM-DD")
        return 2
    if not a.check_only and not a.out:
        out("--out is required unless --check-only")
        return 2
    if not 0 < a.min_match <= 1:
        out("--min-match must be in (0, 1]")
        return 2
    if a.offset_hours is not None:
        if a.dst in ("eu", "us"):
            out("--offset-hours asserts ONE fixed offset; it cannot be combined with --dst %s" % a.dst)
            return 2
        a.dst = "none"
    try:
        return run(a, out=out)
    except Refused as e:
        out("REFUSED: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
