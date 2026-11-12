# ANALYSIS 2026-11-12 — B4: LIVE pre-order safety (connection, sizing, cost-as-%‑of‑R)

**Status:** IMPLEMENTED (LIVE path only). `live_readiness.py` **14→17 PASS, 3→0 TODO**, 3 MANUAL; **LIVE GATE
still CLOSED**. No strategy variable, no cost assumption, no paper-ledger row and no order changed.

**Plan item:** `docs/EXECUTION-PLAN.md` Track B, **B4** — *"Pre-order safety: `terminal_info().connected`,
`volume_max`/step/stops/freeze levels from the live spec, and a **spread-as-%-of-R** veto (measured $0.55 is
~10% of 1R; `MIN_SPREAD_POINTS=60` is too loose)."* Completion test named in the plan: `disconnect_safety`,
`sizing_limits`, `cost_guard` PASS **and** unit tests with a fake spec.

**Why this step and not something else (§6 precedence).** The 2026-11-06 digest flagged the quote logger
STALE; the collection-480 snapshot (2026-11-12 00:00:01 UTC, data through `2026-11-11 23:59:05`) shows the
logger and the price feed both healthy and continuous to the collection boundary (§1), so there is no feed
outage to fix. **A2 remains host-blocked** (needs a verified flat position on the production host, which this
checkout cannot see). No time gate is expired. Track B is therefore the next eligible work, and B4 is its
lowest-numbered open step.

---

## 1. Session ritual — what was verified before any change

| Check | Result |
|---|---|
| `tools/check_data.py` | **0 fail / 9 warn** (all documented) — 887 trades, 67 149 log bars, `status.json` agrees with the ledger |
| `tools/handoff_check.py` | **STALE** (8 problems) — snapshot last refreshed at collection 435, now 480 (+47 closed trades) → refreshed in this session (§6) |
| `tools/check_structural_stop.py` | **PASS** — struct-stop era n=390, 83.6% level-bound, **0 stops inside the level**, +0.50 ATR median clearance, 3.26 ATR median risk |
| `tools/check_gap_rides.py` | Registered count **6** (threshold 2) → the §7 REVERT trigger remains REACHED, unchanged by this session. 1 reopen gapped through the stop, **0 exits worse than the stop**, 3 rides were scratch stops, **0 weekend rides** |
| `tools/pressure_report.py` | Era n=390, SCREEN MET on all bars (B1/B2/B3/C1/C2/A4/A5 OK), gross **−0.028R/trade**; pressure composite still **collinear with side** |
| `tools/xm_quote_report.py` | **27 complete UTC days / 3 weekends** (target 14/2); spread-only median **$0.55**, p90 $0.57; broker offset **+2h**, EU rule fits **100.00%** of 56 304 rows |
| `tools/live_readiness.py` (before) | 14 PASS / 3 TODO / 3 MANUAL, gate **CLOSED** |
| `tools/smoke_test.py` (before) | PASSED (A–AC) |

**One new observation, recorded not judged:** the broker's daily break moved from `20:58→22:00` UTC to
`21:58→23:00` UTC starting **2026-11-02**, with **no** change in the server offset (still `+7200 s` on both
sides of the move — so this is a broker schedule change, not DST). The deployed guard follows it:
`derive_daily_closure()` now returns **`((21, 58), (23, 0))`** from the price log alone, and trade #887
(`2026-11-11 20:42`) still shows a ride because it was entered **76 min** before the moved close, far outside
the 30-min guard window. So the guard is behaving as registered; the registered count stays **6**. No change,
no re-judgement — the §7 judgement stays closed as recorded on 2026-11-06.

---

## 2. What was actually missing in the order path

`engine.GoldEngine.execute_live_trade()` sent a real order after: arming + kill switch, B3 reconciliation,
the gap guard, `symbol_info`, filling resolution, the sizer (`size_lots`, which is `RISK_PCT` of
`account_info().balance` with a hard-coded `VOLUME_MIN/VOLUME_STEP`) and rounding. Three gaps:

1. **No liveness check.** Nothing asked the terminal whether it was connected or permitted to trade. MT5 can
   return a result object from a terminal that has since dropped, and `terminal_info().trade_allowed=False`
   (AutoTrading off / EA trading disabled) turns every send into a rejection *after* the entry decision.
2. **No broker sizing limits.** `volume_max`, `volume_step` and `trade_stops_level`/`trade_freeze_level` were
   never read. The captured spec is min 0.01 / step 0.01 / **max 50.0** with stops 0 pts — so today this is
   latent, but a spec change (or a bigger account) would produce a rejection or an unattachable SL/TP.
3. **No cost-relative veto.** `trade_filter.MIN_SPREAD_POINTS = 60` is a **flat $0.60 cap**. The measured
   median is $0.55, so the filter is nearly always *inactive* — it never asks the only question that matters:
   **how big is the round trip compared with this trade's 1R?**

---

## 3. The measurement that sets the cost-guard threshold

309 struct-stop-era trades joined to a measured quote within ±75 s of their entry
(`xm_data/quotes-*.csv`), with 1R recovered from the reward leg (`|TP − Entry| / 1.5` — the definition this
repo uses on rows whose stop was ratcheted to entry).

**Round trip as a share of 1R:** p50 **9.3%**, p75 12.2%, p90 **16.0%**, p95 18.9%, max **24.5%**, mean 10.1%.

**And the expensive deciles are also the worst-performing ones** (same trades, $0.55 round trip charged):

| cost as % of 1R | n | decisive | decisive WR | gross R/trade | **net @ $0.55 R/trade** |
|---|---|---|---|---|---|
| 0–8% | 114 | 80 | 38.8% | −0.022R | −0.086R |
| 8–12% | 116 | 84 | 39.3% | −0.013R | −0.112R |
| 12–16% | 46 | 29 | 34.5% | −0.087R | −0.227R |
| 16–20% | 24 | 19 | 21.1% | −0.375R | −0.555R |
| **20%+** | **9** | 6 | **16.7%** | **−0.389R** | **−0.610R** |

**Chosen bar: `LIVE_COST_MAX_PCT_OF_R = 20.0`.**

- It vetoes the two worst buckets (33 trades, **−0.58R/trade** between them) and keeps 89.3% of the flow
  (276/309).
- It is **above** the p90 (16.0%) so it does not fire on ordinary tape: it vetoes **9/309 = 2.9%** of era
  trades. A 15% bar would veto 45 (14.6%) and a 12.5% bar 70 (22.7%) — both cut deeper into normal flow than
  the evidence justifies on n=33 expensive trades.
- **Disclosure — this is not a proven edge.** The mechanism is cost arithmetic (the repo's registered 40%
  decisive-WR break-even at 1:1.5 plus cost), and the buckets above are descriptive, not a pre-registered
  experiment. At n=9 in the vetoed tail the confidence interval is very wide; the bucket ordering is
  consistent and monotone, which is why it is adopted as a **live-path veto**, and why it can never move a
  paper result. **No paper trade, R/trade, era DD or registered bar changes** — the guard is LIVE-only and
  the paper engine has no spread feed at all.

The bar is a **constant, not a strategy parameter**: it is compared against a *measured* quote at order time
and cannot alter entries that the paper book records.

---

## 4. What shipped

`engine.py` — new pure helpers, reachable **only** from the LIVE order path:

| Helper | Refuses when |
|---|---|
| `live_connection_problem` | module missing, `terminal_info()` raises/returns nothing, `connected=False`, `trade_allowed=False`, or the fields are absent (missing ≠ True) |
| `live_symbol_limits` | `symbol_info()` unavailable, `volume_max <= 0`, `volume_step <= 0`, spec unreadable |
| `live_sizing_problem` | lots ≤ 0 / non-finite, below `volume_min`, above **`volume_max`**, or off the `volume_step` grid |
| `live_stop_distance_problem` | inverted geometry, or SL/TP inside a raised `trade_stops_level` |
| `live_cost_guard` | round trip > `LIVE_COST_MAX_PCT_OF_R` of 1R; unreadable/negative/NaN inputs |
| `live_cost_measure` (method) | returns `(None, None, reason)` rather than assume a cost — a zero/inverted quote is a **data fault, not a cheap trade** |
| `live_free_margin_problem` (method) | `margin_free` unreported or ≤ 0, `order_calc_margin()` unavailable/raising, or the order needs more than 70% of free margin |

Wiring in `execute_live_trade()`, in order: connection → B3 reconciliation → gap guard → spec/filling →
**limits** → sizer → **sizing grid** → **margin** → **cost veto** → **stops distance** → send. Every refusal
returns before `order_send`, prints the reason and sends a rate-limited Telegram `risk`/`skip` notice.

**Two defects found and fixed while writing this** (both would have shipped as fail-open/fail-all):

1. *Fail-open:* a zero spread measured $0.00 cost and **passed every limit**. Gold never trades at zero spread
   on this broker (measured median $0.55), so a zero read is a fault. Now refused.
2. *Fail-all:* the first margin guard priced the raw **notional** and ignored leverage. The captured spec is
   **1:1000**, so 0.01 lot of GOLD is ~$4 of margin on a ~$4,000 notional — the naive form demanded 1000% of
   free margin and would have refused **every** sound order. It now asks the broker:
   `order_calc_margin()`. Pinned by `TestMarginGuard.test_leveraged_small_order_passes`.

---

## 5. Completion test — met

- `tools/live_readiness.py`: **17 PASS / 0 TODO / 3 MANUAL**, `LIVE GATE: CLOSED`. The three checks were
  rewritten from substring matches to **call-graph + field-read** checks (`live_connection_problem` must be
  called from `execute_live_trade` and must read `terminal_info`/`connected`/`trade_allowed`; the sizing path
  must call `live_symbol_limits`/`live_sizing_problem`/`live_stop_distance_problem` and read `volume_max`,
  `volume_step`, `trade_stops_level`; the cost path must reach `live_cost_guard`). A new `_refers_to()` helper
  recognises broker fields spelled as attributes, `getattr(..., "field")` **or** dict keys — without it the
  first wiring reported TODO while the code was in fact correct. Docstrings/comments never satisfy a check.
- `tools/test_live_safety.py` (**new, 28 tests**): every guard, every failure mode, the boundary at exactly
  20%, the measured median inside / the worst tail outside, the leverage trap, and proof that none of it is
  reachable from `execute_simulated_trade`.
- `tools/test_live_readiness.py` (**24**, was 22): three new tests — B4 checks PASS, **no code TODO remains**,
  and each guard goes **red again** if it is disconnected from the order path.
- `tools/smoke_test.py`: **Scenario AD** (11 checks) drives the real order path against a fake broker: a sound
  order still sends exactly one order at a size on the broker's grid; disconnected / AutoTrading-off /
  `volume_max` too small / raised `stops_level` / cost > 20% / unmeasurable spread each send **nothing**; the
  *same* $0.55 quote is refused when 1R is small (risk-relative, not spread-relative); paper mode makes **no**
  broker call. A–AC unchanged and still PASSED.
- `tools/test_live_manage.py` **25 OK** (its fake broker gained `terminal_info`/`order_calc_margin`/volume
  fields), `test_manual_chart.py` 32 OK, `goldbot/tests` 64 OK, `test_readiness_tab.py` **16 OK** (its
  scorecard pin moved 11→17 pass, 6→0 todo, 9→3 pending; the module also needs `flask`, which the container
  did not have — installed for the test run only).
- `python3 -m py_compile engine.py trade_filter.py` OK.
- **AST proof the paper path is untouched:** diffing every function against `HEAD`, the **only** changed
  function is `execute_live_trade`; `evaluate_candle`, `execute_simulated_trade`, `structural_risk`,
  `size_lots`, `log_trade`, `close_trade`, `run_forward_test` and `run` are **byte-identical**. Strategy
  constants unchanged: `SL_CLEAR_ATR 0.5`, `BE_TRIGGER_R 0.75`, `MAX_HOLD_MINUTES 240`, `RR_TARGET 1.5`,
  `TRADING_MODE FORWARD_TEST`.

---

## 6. Refresh at collection 480 (2026-11-12 00:00:01 UTC; data through `2026-11-11 23:59:05`)

Read with `docs/EXECUTION-PLAN.md` §2–§2e; a current-state refresh, not a re-judgement of any closed experiment.

- **887 closed** (191W/388L/305BE/3TIME, decisive **33.0% [29.3–36.9]**), engine ledger **$130.70**, true
  equity **$113.76**, net **−$741.04** at the registered $0.40 round trip. No open trade
  (`next_trade_num: 888`). `check_data`: 0 fail / 9 documented warnings.
- **Structural-stop era n=390** (106W/177L/105BE/2TIME): decisive **37.5% [32.0–43.2]**, gross **−0.028R/trade**
  (pressure-report scale), SL/day **5.90**, SL share **45.4%**, scratch **26.9%**, avg SL **$6.01**, era DD
  **$200.06**. Geometry guard **PASS**. Grown-sample observation only — the 10-19 judgement is closed and the
  lapsed n=150 arm is not reopened. **No demonstrated edge after costs.**
- **Cost sample 27 complete UTC days / 3 weekends** (target 14/2 — well past it). Spread-only median **$0.55**,
  p90 $0.57; measured round trip on **309** matched trades mean/median **$0.55**, p90 $0.57, max $1.66. Still
  spread-only, so it is **not** the all-in model (slippage/commission/swap unresolved) and **$0.40 remains
  registered** pending the dated A6 analysis.
- **Quote + price feed healthy at collection time:** quotes continuous to `2026-11-11 23:59:30` (every one of
  the last 30 daily files has 2880 rows / zero gaps > 2 min, except the recorded 11-04 outage), price log
  through `23:59:05` with 59–60 bars/hour. The 2026-11-06 "STALE" flag was a collection-boundary artifact of
  the prior snapshot, not a dead logger. No host action is implied by this checkout.
- **Broker:** offset **+2h** (EU rule fits 100.00% of rows); spec captured 2026-11-11 19:54:21 UTC — **REAL**,
  RETAIL_HEDGING, 1:1000, build 6230, **IOC only**, contract 100, min/step/max 0.01/0.01/50, stops 0 pts,
  swap long −78.59 / short +16.81 pts triple Wednesday, spread 49 pts floating.
- **Gap rides:** registered count **6** (threshold 2), 1 reopen gapped through the stop, **0** exits worse than
  the stop, 3 scratch stops, **0** weekend rides. Count and damage recorded separately, as required.
- **Paper runway:** true equity $113.76 against the era's ~−$0.80/closed trade → still a counter, not capital.
  The owner's signed **"no rebaseline ever — let it go negative"** stands; nothing here edits the ledger.
- **LIVE gate: CLOSED — 17 PASS / 0 TODO / 3 MANUAL.** The three MANUAL items are the complete cost model
  (A6), DEMO-account evidence (B5, host/operator action) and independent edge evidence (Track A). **A green
  code scorecard is not permission**: `TRADING_MODE` stays `FORWARD_TEST` until G2.

---

## 7. What is next

1. **A2** — still **blocked on the production host**: `SL_CLEAR_ATR 0.5 → 1.5` may only land in a verified
   flat-position window, with the cutover taken from the host's `autosync: merge upstream` commit time.
2. **B5** — **host/operator action**, now the lowest-numbered open Track-B step: DEMO-account evidence
   (`docs/DEMO-EVIDENCE.md` does not exist) covering fill (IOC), SL/TP, BE/time management, rejection
   handling, disconnect, restart, reconciliation and a 48 h stable run. **Use a DEMO account and a separate
   data directory — the captured spec says REAL.**
3. **A6** — cost sample gate met; follows the preceding Track-B queue step. It needs slippage/commission/swap
   evidence, not just spread, before any re-costing of the ledger or the registered $0.40.
4. **A8** — still waiting on the owner to **define** the manual pressure/hold rule before anything is coded.

No real order, no arming, no LIVE switch, no strategy change, no ledger edit was made in this session.

---

## 8. Addendum — the guard's first real setups (post-hoc, not a test)

Recorded after the merge, because it is the first concrete check of the bar against setups that arrived
*after* the measurement window. **This is a post-hoc observation on n=2; it is not a pre-registered test, it
is not evidence of edge, and it changes nothing about the bar.**

| Trade | Entry (UTC) | 1R | Measured spread | Round trip | % of 1R | B4 verdict | Outcome |
|---|---|---|---|---|---|---|---|
| #885 | 2026-11-11 18:15:04 | $5.99 | $0.54 | $1.08 | **18.0%** | allow | — |
| #886 | 2026-11-11 19:28:08 | $2.51 | $0.49 | $0.98 | **39.0%** | **VETO** | **SL −$2.51** |
| #887 | 2026-11-11 20:42:07 | $3.95 | $0.55 | $1.10 | **27.9%** | **VETO** | **SL −$3.94** |

The first two setups the guard would have seen at the 20% bar (#886, #887) were both **structural-stop losses**,
and the one inside the bar (#885) was allowed. The vetoed pair is exactly the failure mode §3 describes: a
tight structural stop (`max(2·ATR, |entry − level| + 0.5·ATR)`) on a quiet tape makes 1R small enough that the
measured round trip is a third of it — the trade has to win ~2 in 3 to break even, against a book running 37.5%.

**Two caveats, stated plainly.** (1) n=2, and being stopped out is the modal outcome of this strategy — the
veto's value is that it declines a *badly-priced* bet, not that it predicted these two. (2) This is the
**paper** book: B4 is a LIVE-path veto and would **not** have prevented #886/#887 from being recorded, because
the paper engine has no spread feed. Do not cite this as "the guard would have saved $6.45"; cite it as "the
guard's first live setups were the ones it exists to refuse".

The honest way to accumulate real evidence is unchanged: `sim_trades`-free, in LIVE/B5 and later A7, count how
many setups the veto refuses and what they would have done.
