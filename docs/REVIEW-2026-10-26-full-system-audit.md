# REVIEW — full-system audit and engine finalisation scope (2026-10-26)

**Date:** 2026-10-26 ~14:15 UTC
**Data:** collection 349, `trades.csv` 709 closed (142W/306L/258BE/3TIME), `forward_test_log.csv` 51 215 bars through `2026-10-26 11:59:07 UTC`, `skipped_trades.csv` 1 642 rows, 14 quote files / 35 571 rows.
**Trigger:** owner asked to review everything, finalise the engine as far as possible, and make progress drivable by the single phrase **“follow execution plan”** until something is workable for live trade.
**Status:** review + LIVE-path hardening only. **No strategy parameter, gate or exit changed. No order placed. `TRADING_MODE` stays `FORWARD_TEST`.** The strategy still has **no demonstrated edge**; the LIVE gate is **CLOSED**.

---

## 1. What was run (all reproducible)

| Check | Result today |
|---|---|
| `python3 tools/check_data.py` | **0 fail / 8 warn** — all warnings are the documented historical ones (duplicate `Trade_Num` resets, $500 ledger resets, feed gaps, 2 unjoinable rows). `status.json` agrees with the ledger. |
| `python3 tools/handoff_check.py` | **STALE** — snapshot was 63 h / 12 trades behind (`log_last_bar_utc` 10-23 20:57 vs 10-26 11:59). Refreshed this session (`--update`); prose brought current. |
| `python3 tools/check_structural_stop.py` | **PASS** at era n=212: 0 stops inside the tested level, 83.0% level-bound, median clearance +0.50 ATR, median risk 3.32 ATR. Deploy boundary still bracketed by #498 (OLD) / #499 (NEW) around `2026-10-06 03:00`. |
| `python3 tools/check_gap_rides.py` | **3/2 REACHED** (registered §7 trigger fired): #595/#610/#687, all daily breaks. 0 gapped through, 0 worse exits, 0 weekend rides; tightest reopen headroom +$4.15. |
| `python3 tools/pressure_report.py --root .` | §7 SCREEN MET on all five checks at n=212; gauge still **collinear with side** (BUY 81 aligned/6 mixed, SELL 120/5), i.e. context, never a signal. |
| `python3 tools/strategy_lab.py --calib-only` | recall **99.8%** on the 0.75R-master and max-hold eras (unchanged). Replay n=892 vs ledger n=709, net −0.190R/t vs ledger −0.253R/t — the cascade gap is cooldown timing, as documented. |
| `python3 tools/strategy_lab.py --table --only baseline,structstop,structstop1.0,structstop1.5` | see §3. |
| `python3 tools/xm_quote_report.py` | 11/14 complete UTC days, 1/2 weekends, 35 571 rows, median spread **$0.55** (p95 $0.58), measured round trip $0.55 on 131 matched trades. Spec `filling_mode = 2` → **IOC only**. |
| `python3 tools/smoke_test.py` | **PASSED** (Scenarios A–Z plus new AA). |
| `python3 -m unittest discover -s goldbot/tests -t .` | **64 tests OK**. |
| `python3 tools/test_live_readiness.py` | **18 tests OK** (new). |
| `python3 tools/live_readiness.py` | **9 PASS / 8 TODO / 3 MANUAL**, gate **CLOSED** (new, §4). |
| `python3 -m py_compile engine.py trade_filter.py pressure.py chart.py dashboard.py` | OK. |

---

## 2. Where the evidence actually stands

- **Whole book:** 709 closed, decisive WR **31.7%**; engine ledger **$131.30**, true equity **$114.34**, **net −$669.26** at the registered $0.40 round trip. No open trade (`next_trade_num: 710`). Gross engine P&L is only barely positive; every dollar of apparent profit disappears under the *assumed* cost, and the *measured* spread is worse ($0.55 vs $0.40).
- **Live structural-stop era (n=212, entries ≥ 2026-10-06 03:00):** 57W/95L/58BE/2TIME, decisive WR **37.5% [30.2–45.4]**, gross **−0.054R/trade** (−$0.32/trade), era drawdown $117.02, SL/day 5.94, SL share 44.8%, scratch 27.4%. Every registered SCREEN bar is met; the registered PASS was **never** met (the n=150 arm lapsed at the 10-19 time gate — do not re-judge on the grown sample).
- **Verdict unchanged:** the 2026-10-06 structural stop is mechanically correct and roughly halved the bleed, but **the strategy has no demonstrated positive expectancy after costs**. 709 mixed-era trades are not an independent test of one unchanged strategy.
- **Cost:** 98.2% of usable quote samples exceed the registered $0.40 round trip; median spread is 9.9% of median 1R ($5.53). Spread is a **lower bound** — slippage, commission and swap are unmeasured. The 14-day/two-weekend sample target is **not** met (11/14, 1/2); keep the $0.40 assumption until it is.
- **Pressure / manual hold hypothesis:** still unspecified as a rule. Mark-outs on the live era show the “hover–tag–bounce” pattern real but two-sided (29% of winners also survived ≥0.5R MAE). Context only, never a stop override.
- **Signal/outlook and indicator lab:** no additional 1-min oscillator clears the repo's adoption bar (`docs/INDICATOR-AUDIT-2026-10-23.md`). More indicators are not the missing piece.

**Broker clock — the DST gate is now MET.** `xm_quote_report.py` §4 observes **+3h** through `2026-10-23 20:59:30 UTC` and **+2h** from `2026-10-25 22:00:30 UTC`; the **EU rule fits 100%** of 24 379 observed rows across one offset change. This is exactly the observation the 10-25 owner decision (`hold_for_dst`) was waiting for. Two consequences:

1. `tools/history_to_log.py --dst eu` is now supported by observed rows (large-N path).
2. The gap guard's derived schedule is **still the pre-DST `(20:58, 22:00)`** — `derive_daily_closure('forward_test_log.csv')` returns that on today's log because **no post-DST daily break has been observed yet** (the first one is due tonight, 10-26). The Sunday weekly reopen stayed at 22:00 UTC, so the `±60 min` Day-1 adaptation correctly did **not** fire; the guard is currently over-blocking by roughly an hour rather than under-blocking. Verify after tonight's break (`docs/PREREG-2026-10-25-gap-guard-daily-closure.md` §2.4).

**Feed-health finding (host action).** The quote sidecar was live from `2026-10-25 22:00:30 UTC` with fresh ticks and a +2h offset, but the **price-bar log resumes only at `2026-10-25 23:59:24 UTC`** (weekend gap `2026-10-23 20:57:08 → 2026-10-25 23:59:24`, 3 062 min). Roughly **2 hours of open-market M1 bars are missing on the price path at the reopen**. The quote logger was healthy, so verify `mt5feed` / the `goldbot` restart on the host. This is an ops issue, not a strategy result; it does not invalidate the ledger but it does shorten the first post-DST session.

---

## 3. The one open strategy decision (DST gate now unblocked)

Refreshed costed/stateful replay, post-cutover era (net R/trade, `tools/strategy_lab.py --table`):

| cost/side | baseline (old 2·ATR/3·ATR) | live 0.5 ATR | 1.0 ATR | **1.5 ATR** |
|---|---|---|---|---|
| $0.00 | −0.012 | −0.030 | −0.027 | **+0.037** |
| $0.15 | −0.106 | −0.090 | −0.081 | **−0.009** |
| $0.20 (registered) | −0.137 | −0.110 | −0.099 | **−0.024** |
| $0.275 (measured $0.55 RT) | −0.184 | −0.140 | −0.126 | **−0.047** |
| $0.35 | −0.230 | −0.170 | −0.153 | **−0.070** |

All cells are net R/trade from today's log. The $0.275 row uses the lab's own `run()` with `cost_per_side=0.275` and `window=(LIVE_CUTOVER, None)` (the reproduction recipe in the 10-25 analysis), not a new implementation. Full rows at $0.20/side: live **n=219, 38.3% dec, −0.110R/t, maxDD 186.0**; 1.5 ATR **n=171, 41.7% dec, −0.024R/t, maxDD 165.3**. The pre-declared 4-point bar from `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md` still scores **3/4** on the refreshed data: (1) **+0.086R** at $0.20/side and **+0.093R** at $0.275/side, both ≥ +0.05R **PASS**, (2) decisive WR no drop (41.7 vs 38.3) **PASS**, (3) drawdown no worse (165.3 vs 186.0) **PASS**, (4) trade count −21.9% > 15% **FAIL** (mechanism disclosed: longer holds, 37 m vs 25 m median, more TIME caps). `structstop1.0` still fails bar 1; 0.25 ATR level test remains ineligible.

**Recommendation recorded in `docs/PREREG-2026-10-26-structstop1.5.md` (DRAFT):** take branch **(A)** — pre-register and stage `SL_CLEAR_ATR = 1.5` — rather than the literal §7 revert **(B)** to `2·ATR/3·ATR`, which is the **worst** cell at every cost and puts ~66% of stops back inside the tested level. The 10-25 owner decision explicitly reopened this choice; the new dated evidence satisfies the repo's "reopen a rejected candidate only with new pre-registered evidence" rule. **A is a breakeven hypothesis in replay, not a proven edge.** It is written as a draft because deviating from the literal registered revert is an owner-level decision; see §7.

---

## 4. Engine review: paper path is finished, LIVE path is not

### 4.1 Paper / forward-test path — stable, well covered

`engine.py` (2 156 lines) + `trade_filter.py` implement the funnel, structural stop, BE ratchet, TIME stop, cooldown/breaker/blackouts, daily-closure gap guard (DST-responsive), feed health, Telegram routing and restart recovery. `tools/smoke_test.py` pins all of it in 26 hermetic scenarios (A–Z + AA) and passes. Data integrity is 0 fail. `pressure.py` / `dashboard.py` / `chart.py` / `goldbot/` are read-only, stdlib-only, and never write to the trading path. **No paper change is needed to answer “is the engine finalised?” — the paper engine is.** The open question is whether it has an edge (§2: no).

### 4.2 LIVE path gaps found before this session

`docs/REVIEW-2026-10-20-live-readiness-timeline.md` listed these; this audit confirms them against the actual code:

| # | Gap (code location) | Consequence |
|---|---|---|
| 1 | `execute_live_trade` hard-coded `mt5.ORDER_FILLING_FOK`; captured spec `filling_mode = 2` = **IOC only** | every real market order would likely be rejected |
| 2 | `run_live` used `copy_rates_from_pos(..., 0, 1)` — the **forming** bar, re-evaluated ~every 60 s | live signals would not match the paper engine (closed bars), duplicate evaluations |
| 3 | `run_live` never calls `check_position` → `BE_TRIGGER_R` and `MAX_HOLD_MINUTES` are engine-side only | broker SL is never ratcheted, 240-min TIME stop cannot fire in LIVE |
| 4 | `run_live` had no candle watermark | a restart could re-evaluate a bar / re-enter |
| 5 | `positions_get` used only as an `in_trade` flag; no `history_deals_get` | no position/deal reconciliation, no trustworthy realized-loss gates after restart |
| 6 | no `terminal_info().connected` check, no `volume_max`/stops-level checks | dead terminal / invalid volume not refused before an order |
| 7 | `MIN_SPREAD_POINTS = 60` ($0.60) lets the measured $0.55 median through (~10% of 1R) | no risk-relative cost veto |
| 8 | nothing required an operator to arm real trading; one config edit could place real orders | no kill switch |
| 9 | captured spec says `account_kind: REAL` | a live pilot must be run on a **DEMO** account, with its own data dir |

### 4.3 What this session changed (LIVE path only — zero paper behaviour change)

1. **Arm gate + kill switch** (`live_armed()`): `GOLD_LIVE_ARMED=1` **and** no `/opt/gold/LIVE_HALT` file. Checked in `run_live` **and** again immediately before `order_send`. Fail-closed. Flipping `TRADING_MODE` alone can no longer place an order; `touch /opt/gold/LIVE_HALT` stops new exposure without a restart.
2. **Filling policy from the broker spec** (`resolve_order_filling()`): bitmask 1=FOK / 2=IOC / 4=BOC; refuses the order if neither is supported. On the captured XM spec it now sends **IOC**.
3. **Closed-bar parity + restart dedup** in `run_live`: position **1** (last closed M1), `mt5_next_candle()` dedup, a **separate** persisted watermark `live_last_candle_ts` in `status.json` (so a live/demo pilot cannot clobber the paper feed's `mt5_last_candle_ts`). `symbol_info() is None` now refuses instead of raising.
4. **`tools/live_readiness.py`** — a read-only, AST-based 20-check scorecard (`--json`, `--strict`) that turns the checklist above into a measurable gate: **9 PASS / 8 TODO / 3 MANUAL, LIVE GATE CLOSED**. A PASS is a code check, not a demo test; the three MANUAL items are operator/evidence gates.
5. Tests: new **Scenario AA** in `tools/smoke_test.py` (arm gate, filling bitmask, captured spec, closed-bar source pins, a functional fake-MT5 loop proving one evaluation per closed bar and no re-evaluation after a simulated restart) and `tools/test_live_readiness.py` (**18 tests**).

### 4.4 What still has to be built (Track B in the plan)

`broker_be`, `broker_time_stop`, `position_reconcile`, `deal_reconcile`, `disconnect_safety`, `sizing_limits`, `cost_guard`, `quote_sample`, `cost_model`, `demo_evidence`, `edge_evidence`. Each is one bounded step with a named completion test in `docs/EXECUTION-PLAN.md`. None can be waved through by this review.

---

## 5. Honest live-readiness verdict

**The engine is not finalisable for live trade today, and neither is the strategy.** Two independent tracks must both complete:

- **Track A — evidence.** One unchanged strategy, one pre-registered forward window, a complete cost model, positive net expectancy with acceptable drawdown on an independent sample across multiple regimes. Today: net negative after cost, no independent window, cost model incomplete.
- **Track B — execution engineering.** The 8 code TODOs above, then a **demo-account** test report covering fill/IOC, broker-side SL/TP, BE/time management, rejection handling, restart/reconciliation, disconnect safety and the kill switch. Today: 9/20 checks green, gate closed.

**Hard gate:** no real order until every blocking `live_readiness.py` check is PASS, the three MANUAL items have dated evidence, and the owner **separately and explicitly** approves real-money trading. Time elapsed, a higher win rate, or a bigger mixed-era trade count cannot substitute.

**Conditional timing (estimate, not a promise):** the cost sample needs ~3 more complete days and one more weekend (~end of October); the 14-day/two-weekend review follows. Track B's code steps are a few focused sessions; demo evidence needs host access and a DEMO account. The earliest useful strategy reassessment remains **December 2026–February 2027** (2–4 month horizon) and a separate live-readiness review **April–October 2027** (6–12 month horizon) — consistent with `docs/REVIEW-2026-10-20-live-readiness-timeline.md`. A failed gate extends this indefinitely. **No date can be promised for profitable live trading.**

---

## 6. Decisions recorded this session

1. **DST gate MET** (EU rule, +2h observed). `hold_for_dst` is released; the quote logger is healthy again (11/14 days), and `mt5quotes-gold` is no longer the blocker it was on 10-25. The **price-bar 2 h reopen hole** is the new host action.
2. **No strategy parameter changed.** `SL_CLEAR_ATR = 0.5`, `RR_TARGET = 1.5`, `BE_TRIGGER_R = 0.75`, `MAX_HOLD_MINUTES = 240`, gap guard 30 min — all frozen. One variable at a time remains binding.
3. **LIVE-path hardening shipped on the session branch** (§4.3). Paper forward-test behaviour is unchanged and all tests pass.
4. **Branch (A) recommended for the stop-geometry choice**, with a drafted pre-registration (`docs/PREREG-2026-10-26-structstop1.5.md`). It is **not registered and not deployed** until owner sign-off, because it supersedes the literal §7 revert.
5. **“Follow execution plan” is now the canonical one-line prompt** (`docs/EXECUTION-PLAN.md`), with the existing “Execute the plan.” kept as an alias. Its exact authority and its two hard approval gates are written down so no future session has to guess.

---

## 7. Blocker / owner decision

One decision is genuinely owner-level: **approve branch (A) — pre-register `structstop1.5` — or insist on the literal §7 revert (B).** The plan records (A) as the recommended default with the evidence above; it cannot be merged on the strength of a replay alone without a dated registration *and* the owner's approval of that deviation. Everything else in the plan (data verification, cost model, Track B code, demo evidence, documentation) can proceed with “follow execution plan” alone.

---

## 8. Reproduction

```bash
python3 tools/check_data.py
python3 tools/handoff_check.py
python3 tools/check_structural_stop.py
python3 tools/check_gap_rides.py
python3 tools/pressure_report.py --root .
python3 tools/strategy_lab.py --calib-only
python3 tools/strategy_lab.py --table --only baseline,structstop,structstop1.0,structstop1.5
python3 tools/xm_quote_report.py
python3 tools/live_readiness.py            # --json / --strict
python3 tools/test_live_readiness.py
python3 tools/smoke_test.py
python3 -m unittest discover -s goldbot/tests -t .
python3 -m py_compile engine.py trade_filter.py
```
