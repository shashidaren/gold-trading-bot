# REVIEW — B3 position and deal reconciliation (2026-11-06)

## Decision / scope

**B3 is complete in code and hermetic tests.** This closes the next runnable Track-B engineering item after B2. No strategy variable, paper outcome, deployment, account setting, or live order changed. `TRADING_MODE` remains `FORWARD_TEST`; the LIVE gate remains CLOSED.

A2 remains blocked on the *host*, not on this checkout: the repository ledger is flat at this snapshot, but the production host is inaccessible here, so its current open-position state and the autosync cutover moment cannot be verified. The pre-registered `SL_CLEAR_ATR 0.5 → 1.5` change was not made.

## Implemented

- LIVE startup and every order attempt reconcile symbol positions filtered by `MAGIC_NUMBER`. One orphan position with valid entry/SL/TP geometry is adopted; its broker ticket and `current_trade_num` are persisted together in `status.json` and restored across restart.
- More than one strategy position, an unavailable query, a ticket mismatch, missing/invalid geometry, or an unrecognized close remains **fail-closed**: no new exposure is opened and no estimated outcome is booked.
- When a persisted position is absent, `history_deals_get` is queried for its lifetime. P&L is the sum of broker deal `profit`, `commission`, `swap`, and `fee`; exit price/time are sourced from closing deals. Only registered TP/SL/BE/TIME outcomes are booked. Unknown/manual close reasons remain pending for operator review.
- Broker time-stop closes now reconcile from the actual closing deals rather than the requested quote/fill estimate. Trade-number lookup prevents a duplicate ledger row after a crash between CSV append and status persistence.
- `live_readiness.py` now checks that position reconciliation is reachable from the LIVE loop and order path, and that deal P&L is reachable through the reconciliation call graph. The two B3 checks move TODO → PASS.

## Verification

- `python3 tools/test_live_manage.py` — **25 fake-MT5 tests passed**, including orphan adoption + restart recovery, net deal booking (including costs), duplicate-order prevention, fail-closed ambiguous positions/reasons, idempotency, and broker time-stop reconciliation.
- `python3 tools/test_live_readiness.py` — **22 tests passed**, including call-graph disconnection checks for B3.
- `python3 tools/smoke_test.py` — **PASSED A–AC**; Scenario AC now exercises broker-deal accounting for the time stop.
- `python3 -m unittest discover -s goldbot/tests -t .` — **64 passed**; `python3 -m goldbot --compare` completed.
- `python3 -m py_compile engine.py tools/live_readiness.py tools/test_live_manage.py` — passed.
- `python3 tools/live_readiness.py` — **14 PASS / 3 TODO / 3 MANUAL**, LIVE gate CLOSED. Remaining code TODOs are B4: disconnect safety, broker sizing/stops limits, and spread-as-%-of-risk cost guard. Manual demo, complete-cost, and independent-edge evidence remain unmet.
- Ritual snapshot on collection 435: `check_data.py` **0 fail / 9 documented warnings**; `check_structural_stop.py` PASS for its registered 0.5 ATR geometry; `check_gap_rides.py` reports 5 rides vs threshold 2 (1 reopen through stop, 0 worse exits, 0 weekend rides). These are observations, not a re-judgement of the closed 10-19 experiment.

## Boundary / safety notes

These checks prove code structure and behavior under a fake MT5 surface only. They do not prove behavior against a broker or a DEMO account, do not satisfy B5, and do not open the LIVE gate. The captured XM specification remains REAL/IOC-only; no order was sent in this session. Paper ledger and strategy behavior are unchanged.

## Queue

- The final ritual digest reported `mt5quotes-gold` **STALE** (newest row ≈0.6 h old while market-open). By §6 precedence, **first verify/recover that host-side feed**; the host is unavailable from this checkout, so report this exact blocker rather than claim it resolved. This does not alter the accepted sample target, but its ongoing freshness must be re-confirmed.
- After feed health is confirmed, **B4** is the next repo-code step: terminal connection check, symbol volume/stops limits, and risk-relative spread veto, each with hermetic tests.
- **A2 remains independently blocked** until the production host is verified flat at deploy time. The local ledger currently has no open position, which is not host evidence.
- The quote logger's sample meets 14 complete days + 2 weekends, so **A6 is eligible after the preceding Track-B queue work**. Spread-only evidence does not complete the all-in cost model or authorize changing the registered $0.40 cost assumption.
