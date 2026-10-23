"""goldbot — the v2 gold strategy harness (paper only, stdlib only).

WHY THIS EXISTS
---------------
The v1 engine (`engine.py` + `trade_filter.py`) is an M1 mean-reversion funnel.
Measured on its own 696-trade ledger it does not work, and the reason is not the
one it looks like:

  * direction — after a full 8/8 signal the tape goes the trade's way 49%
    [41-57] at 30 min (docs/ANALYSIS-2026-10-19-signal-outlook.md). A coin flip.
  * exits cannot rescue it — every exit geometry in the book loses; the best
    cell in `tools/pathwalk_sims.py` is +$2.93 over 696 trades, gross of cost.
  * cost is the binding constraint — median risk $3.94 on a $4,000 instrument,
    $0.55 round trip = 14.0% of risk, which lifts the break-even decisive win
    rate at 1:1.5 from 40.0% to 43.2%.

Volatility is NOT the cause: the quietest ATR-at-entry bucket is the *worst*
one (14.3% decisive, n=18) and no volatility bucket survives a side split.
What gold's volatility actually does is force a stop so tight that a fixed
dollar cost becomes enormous in R. Widening the timeframe is the only lever
that gives it back:

    20-bar M1 box   risk  $2.82   cost = 19.5% of R
    1h box          risk  $3.13   cost = 17.6% of R
    4h box          risk $26.34   cost =  2.1% of R
    prior-day box   risk $127.15  cost =  0.4% of R

So v2 is built on higher timeframes, and it is built as a *harness*: the entry
is a named, swappable hypothesis with a measured verdict, not a claim of edge.

WHAT THIS PACKAGE WILL NOT DO
-----------------------------
  * place an order. There is no execution path, live or simulated-against-a-broker.
  * touch engine.py, trade_filter.py or pressure.py. The v1 forward test and its
    pre-registered §7 gate are preserved exactly as they stand.
  * import a third-party package. Stdlib only, so every test in
    `goldbot/tests/` runs anywhere Python 3.11 does — including a sandbox with
    no requests, no dotenv, no Flask, no pandas.

Read `docs/REDESIGN-2026-10-23-v2-harness.md` before changing a default.
"""

__all__ = ["config", "data", "indicators", "signal", "risk", "portfolio", "replay"]
__version__ = "2.0.0"
