# Manual box watch cards — 2026-10-20

> **Partly superseded 2026-10-21.** The "Retests are **not tracked**" paragraph below is no
> longer true: `pressure.box_retest()` now tracks the last break on a box **frozen at the
> break bar** (`extended` / `retesting` / `held` / `failed`) and both watch cards render it,
> together with the measurement that entering the held retest showed **no edge** (59.0% vs a
> 57.2% reference, the same −$0.31/trade as entering the break). The frozen-box event
> definition and its tests that this document said a future feature would need are in
> `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md` §3 and `tools/test_box_alert.py`.
> Everything else below stands, and nothing there became an engine gate.

Owner approved the dashboard price-card proposal and requested a PR for owner merge.
Display only: engine.py and trade_filter.py are unchanged. No orders, deployment,
strategy promotion or changes to the registered structural-stop judgement.

## Display

Boxes & Timing now has BUY WATCH and SELL WATCH cards for the trigger's box,
or the nearest box if no trigger exists. Both directions are conditional breakout
references, not simultaneous trade recommendations. The existing rejection/setup
checklist is separate. Thresholds reuse BOX_BREAK_ATR and stop clearance reuses
BOX_CLEAR_ATR; prior bars still exclusively determine box boundaries.

Each card shows the boundary and buffered close threshold; completed-bar timestamp
and age; hypothetical entry reference (threshold while waiting, last close once
outside); stop beyond the opposite edge; one-box-width target from the reference;
gross and costed payoff. Costed reward/risk is (reward - spread)/(risk + spread),
not a prediction of expectancy. Spread remains the existing box display assumption
($0.55/oz), not a replacement for the registered engine cost. No executable quote,
slippage, commission or swap is included. A sub-1 costed ratio has an explicit
limited-reward warning.

Unknown/non-passing health, session, portfolio or volatility checks, and reference
bars older than 120 seconds force WAIT. Extensions >1 ATR past the boundary show
WAIT / do not chase: this is a labelled unvalidated display heuristic, not a new
engine gate. Already-outside prices without a fresh break are also WAIT.

Retests are **not tracked**, explicitly stated on both cards. Rolling bounds do
not establish that a fixed historical breakout level was retested and held. A
future retest feature needs a frozen-box event definition and its own tests.
No probabilities, validated-entry claims or trade buttons were added.

## Validation

- tools/test_box_watch.py: 6 synthetic tests pass (BUY/SELL symmetry, cost math,
  close reference, fresh-break/chase state, stale/unknown health, missing geometry,
  no geometry mutation).
- tools/test_dashboard_context.py: 13 pass with Flask installed in a local venv;
  render regression asserts both watch cards and their limitations are present.
- tools/test_box_report.py: 14 pass.
- tools/smoke_test.py: SMOKE TEST PASSED.
- py_compile: engine.py, trade_filter.py, pressure.py and dashboard.py pass.
- Flask test client with checked-in data: HTTP 200 and both watch cards render.
- Handoff machine snapshot refreshed to the checked-in 11:59 UTC data.

The production host was not inspected or deployed. Merge remains the owner's action.
