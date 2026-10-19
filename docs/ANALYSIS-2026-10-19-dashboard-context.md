# Dashboard context — 2026-10-19

Owner approved a read-only dashboard upgrade and PR. No engine/filter changes,
no revised experiment decision, no deployment or live-order authorization.

## Delivered

- **Risk now:** indicative next weekday 21:00 UTC closure (existing quiet-window
  heuristic, explicitly NOT a verified broker schedule); cap time remaining and
  potential closure overlap; latest valid spread from today's last 240 quote rows,
  timestamp and stale warning at >120 seconds; existing open-trade R/SL distance.
  Bad/flagged, nonfinite, future and unsuccessful quotes excluded. Missing is unknown.
- **Market map:** M15/H1 four-close momentum, not EMA alignment. Requires four
  consecutive completed UTC buckets with every minute present; forming buckets and
  outage-spanning readings are refused. Last 6,000 logged bars; prior trading-day
  observed high/low only if the read window begins before that day. Signed ATR
  distance uses last logged ATR. All reference levels are log-derived, not guaranteed
  full broker-session extremes. As-of timestamp remains visible on stale data.
- **Costed evidence:** current structural-stop era, ALL/BUY/SELL; all valid exits
  including BE/TIME charged $0.40 each. Mean per-trade net R uses TP-leg original risk;
  PF is sum positive net exits / absolute sum negative net exits; closed-trade dollar
  drawdown starts at zero and follows exit timestamps. No-loss PF is undefined.
  Excluded rows counted. No open P/L, private balances or broker account data added.

## Deliberately deferred

Verified broker holiday/DST schedule; session levels/day open; full M15/H1 EMA
alignment (needs longer, reliable resampled history); spread session percentiles and
risk ratio; session-split evidence; economic calendar; MFE/MAE path reconstruction.
These must not be represented by guessed or partial data. Spread is not a complete
commission/slippage model and does not replace the registered $0.40 assumption.
No added measure is calibrated as an entry/hold/stop-override signal.

## Verification

`python3 tools/smoke_test.py` passes; `python3 tools/check_data.py` returns 0 fail,
8 historical warnings; structural-stop invariant passes; closure-gap trigger remains
at its existing threshold (no rule changed). `tools/test_dashboard_context.py` has
four hermetic tests for costed scratches/exit-order DD, complete buckets/forming-bar
exclusion/gaps, quote validity/freshness/closure overlap, and Flask page rendering.
Run with Flask installed: `.venv/bin/python tools/test_dashboard_context.py`.
Compile checks pass. Production deployment remains unverified/operator-controlled.
