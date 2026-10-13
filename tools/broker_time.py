#!/usr/bin/env python3
"""Broker-server time for the XM MT5 terminal - one place for the DST rule.

MT5 candle/tick times are BROKER-SERVER epoch seconds, not UTC (gold shows it: status.json
`mt5_last_candle_ts` renders 3 h ahead of the engine's UTC wall clock). XM's server clock is
UTC+2 in winter and UTC+3 in summer on the EU DST rule: it moves at 01:00 UTC on the last
Sunday of March (forward) and of October (back) - XM's trading-hours page, next change Sunday
2026-10-25. The change happens while the market is shut, so no bar straddles it.

THIS RULE IS NOT VERIFIED FOR THE TERMINAL THIS REPO USES. It is the documented behaviour, and it
is checked two independent ways before anything depends on it:
  * tools/xm_quote_report.py compares it with the offsets the quote logger OBSERVES (srv_offset_s,
    learned from fresh ticks) - including the 2026-10-25 change, if the logger is running by then;
  * tools/history_to_log.py validates a converted history against the engine's own UTC log and a
    session-volume check, month by month, and refuses to emit a history that fails.

All datetimes here are NAIVE UTC unless a name says `server` (the repo's convention).
Pure stdlib, no I/O. `python3 tools/broker_time.py` prints the transitions for a year.
"""
import sys
from datetime import datetime, timedelta

HOUR = 3600
WINTER_S, SUMMER_S = 2 * HOUR, 3 * HOUR     # server - UTC


def _last_sunday(year, month):
    d = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)       # weekday(): Mon=0 .. Sun=6


def _nth_sunday(year, month, n):
    d = datetime(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def eu_transitions(year):
    """(start_utc, end_utc) of EU summer time: last Sunday of March / October, 01:00 UTC."""
    return (_last_sunday(year, 3).replace(hour=1), _last_sunday(year, 10).replace(hour=1))


def us_transitions(year):
    """(start_utc, end_utc) of US summer time: 2nd Sunday of March 07:00 UTC / 1st Sunday of
    November 06:00 UTC (02:00 local). Offered because many brokers anchor the server to New York
    - whether XM does is exactly what the observed offsets are for."""
    return (_nth_sunday(year, 3, 2).replace(hour=7), _nth_sunday(year, 11, 1).replace(hour=6))


def server_offset_s(utc_dt, rule="eu"):
    """server - UTC in seconds at the UTC instant `utc_dt`. rule: 'eu' | 'us' | 'fixed:<hours>'."""
    if rule.startswith("fixed:"):
        return int(float(rule.split(":", 1)[1]) * HOUR)
    if rule not in ("eu", "us"):
        raise ValueError("unknown DST rule %r (use eu, us or fixed:<hours>)" % rule)
    start, end = (eu_transitions if rule == "eu" else us_transitions)(utc_dt.year)
    return SUMMER_S if start <= utc_dt < end else WINTER_S


def server_to_utc(server_dt, rule="eu"):
    """Wall-clock SERVER time -> UTC. The offset depends on the UTC instant, so try both offsets and
    keep the one the rule agrees with. Both fit only inside the one repeated server hour of the
    October fall-back (03:00-03:59 server time happens twice, on a Sunday with gold shut and no
    bars); the first, summer-time occurrence wins there."""
    if rule.startswith("fixed:"):
        return server_dt - timedelta(seconds=server_offset_s(server_dt, rule))
    for off in (SUMMER_S, WINTER_S):
        u = server_dt - timedelta(seconds=off)
        if server_offset_s(u, rule) == off:
            return u
    return server_dt - timedelta(seconds=WINTER_S)


def describe(year, rule="eu"):
    a, b = (eu_transitions if rule == "eu" else us_transitions)(year)
    return "%s %d: summer time (server = UTC+3) from %s UTC to %s UTC, otherwise UTC+2" % (
        rule.upper(), year, a.strftime("%Y-%m-%d %H:%M"), b.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    y = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.utcnow().year
    print(describe(y, "eu"))
    print(describe(y, "us"))
