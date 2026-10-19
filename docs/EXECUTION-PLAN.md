# Gold bot execution plan

**Status:** living session queue — reconciled 2026-10-19 UTC (early session; judgement due 2026-10-19 21:00 UTC)  
**Purpose:** make progress consistent across sessions while the bot remains in paper/forward-test mode.

## The one-line prompt

In a new session, simply say:

> **Execute the plan.**

That means: read this plan and `docs/HANDOFF.md`, verify the current repository/data, and do the **first eligible step only**. Update the plan and handoff with what actually happened. Do not ask the owner to restate the project context. If a step needs a production-host action, a missing trading-rule definition, or new risk approval, do the safe work that is possible and report the exact blocker rather than pretending it was completed.

This prompt does **not** authorize real orders, a switch to LIVE, bypassing a pre-registration, or stacking strategy changes. The engine is in `FORWARD_TEST`; remain paper-only unless the owner separately makes an explicit, informed decision after the evidence gates below.

## Goal and guardrails

The goal is not to maximize win rate in isolation. It is to learn—using complete, time-stamped data—whether the bot can achieve positive expectancy **after realistic costs** without unacceptable drawdown. The owner's observation—that pressure-guided manual management can stay in positions the bot would stop out of, and those positions may later recover—is a valuable hypothesis, not yet matched to the bot's entries or measured as a rule.

Keep these guardrails in every phase:

- Preserve the currently open experiment and its original, dated decision bars. One runtime variable per forward-test window.
- Use the costed, stateful `tools/strategy_lab.py` replay for exit/gate ideas; quick path/exit scans are descriptive only.
- Keep rejected candidates rejected unless new, pre-registered evidence justifies reopening them. Do not tune thresholds after looking at the outcome.
- Evaluate net R/trade, payoff, drawdown, stop-loss severity, sample size and uncertainty—not win rate alone.
- Treat the dashboard pressure composite as context only. Its existing calibration says it is collinear with the bot's trade side and has no useful within-side contrast; it is not a validated entry/hold signal. The owner's manual pressure method may be different and must be defined separately.
- Never remove or widen a live stop because selected examples later recovered. Any “hold past stop” idea must first be bounded, costed, shadow-tested and pre-registered.
- Do not put account identifiers, credentials, personal balances or an unredacted manual-trade journal into this repository. Keep any owner-specific journal private and outside Git.

## Current baseline (from the checked-in data on 2026-10-17)

- **624 closed paper trades**; 122 wins, 271 stop losses, 229 breakeven exits and 2 time exits; decisive win rate 31.0%. At the assumed $0.40 round-trip cost, the overall ledger remains negative.
- **Structural-stop window:** 127 trades since the verified 2026-10-06 03:00 UTC cutover (37W/60L/29BE/1TIME; last era close #625, 2026-10-16 19:45 UTC; SELL #626 open in the synced status). `tools/check_structural_stop.py` passes: **zero** post-cutover stops inside the tested level.
- The pre-registered screen is **not yet met**: the current pressure report has the SL-share check at 47.24% against a strict ≤47.0% bar; the other currently reported screen checks pass. This is a marginal miss, not a pass. The scheduled judgement remains 2026-10-19 21:00 UTC or the pre-registered n=150 gate, whichever comes first. The dated experiment document—not this summary—owns the exact verdict/revert bars. **Open item for that judgement:** the §7 closure-gap revert trigger has a literal count of 2 era rides across the daily closure (#595, #610) that no tool counts and prior "revert clear" notes did not evaluate — the judgement session must resolve it first (`docs/REVIEW-2026-10-19-struct-stop-screen.md` §3).
- **Quote-cost logging is active but incomplete:** the latest report covers 5.5 days (5 complete UTC days, 1 of 2 complete weekends), with a first-look median spread/round trip of about $0.55. The existing $0.40 round-trip assumption stays in force until the logger's 14-complete-day/two-weekend sample target is met and the results are reviewed.
- **Pressure calibration:** the bot's dashboard composite remains a side proxy, not a signal. The manual method described by the owner is not yet specified or recorded in the repo.
- The engine remains `TRADING_MODE = "FORWARD_TEST"`. The measured/demo/account metadata is not permission to send real orders.

Always refresh these facts from the current data before relying on them. The plan is a queue, not a substitute for the ledger or the dated pre-registrations.

## Timeline and gated work

| When / gate | Work to execute | Completion test / next step |
|---|---|---|
| **Every session — start here** | Check branch/worktree and current data. Run `python3 tools/check_data.py`, `python3 tools/handoff_check.py`, `python3 tools/check_structural_stop.py`, and `python3 tools/pressure_report.py --root .`. Refresh the handoff snapshot after data changes. | State the current experiment, sample count, blockers and next eligible action. If code changes, also run `python3 tools/smoke_test.py`, `python3 -m py_compile engine.py trade_filter.py`, and the relevant replay/calibration checks. |
| **Now → 2026-10-19 21:00 UTC, or n=150 if earlier** | Finish the already-open structural-stop evaluation. Do not change the level test, stop, target, ratchet, blackout or another runtime rule in this window. Re-run the mechanical stop check and replay calibration first; then compute the complete registered screen and confirmatory metrics using current rows. | Record a dated review against `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7. The current n=127 report is not a final judgement. If an invariant fails, resolve the code/data issue before interpreting P&L. If a registered revert condition is actually met, document it and follow that pre-registered rule; do not invent a replacement threshold. |
| **After that judgement, only if its gates permit** | The next already-registered single-variable test is the **0.25 ATR level-test tolerance** in `docs/PREREG-2026-10-15-level-test-0.25.md` (owner approval is recorded there). Apply that document exactly; do not combine it with pressure-based holding, a new blackout, 1:2 target, flat-before-close gate or any other change. | Run the full smoke suite and replay/calibration checks before deployment. Record the actual host deploy time as the new experiment cutover—not the plan or merge time. If the prior judgement or any pre-check makes this ineligible, stop and report rather than deploying it. |
| **In parallel, as data becomes available** | Let the quote logger collect until it reports **14 complete days including 2 weekends**. Re-run `python3 tools/xm_quote_report.py`; cost the ledger and canonical replay using the measured figure and a sensitivity range. Check the broker-clock/DST transition around **2026-10-25** from observed offsets; do not guess the timezone. | Keep $0.20/side ($0.40 round trip) as the registered assumption until the sample target is reached. A spread-only result is not a complete slippage/commission model. If box/service inspection is needed, follow `docs/XM-LOGGER.md`; local repo access cannot verify systemd on the production host. |
| **In parallel, research only — start a private observation log** | Capture **all** eligible bot stop events, not just memorable recoveries, and the owner's manual decisions before the later price path is known. Record the exact pressure source/indicator, timeframe, raw reading and timestamp of the last closed bar; bot side/entry/SL/TP; pressure at entry and at the first hypothetical stop touch; whether the owner would hold/exit and why; and the later bounded mark-out (fixed horizons or a predeclared exit), including MFE/MAE and costs. Keep personal/account data out of Git. | This phase changes no bot behavior. At least 100 matched post-stop observations may be used as an **exploratory screen**, not proof; keep a chronological holdout and account for clustering by trading day. If the pressure measure or the hold/exit rule is not explicit, ask the owner for that definition before coding or testing it. |
| **After a pressure hypothesis is specified and screened** | Write a new dated pre-registration before any rule is tested or deployed. Compare the current stop with one bounded alternative on matched entries, both sides, costed data, full portfolio state, chronological holdout and relevant market regimes. Include worst-loss/tail-risk and drawdown, not only “recovered to target.” | Only if the pre-registered evidence is promising should a separate shadow/forward-test window be proposed. No pressure signal is promoted to an engine gate or stop override based on this plan or anecdotal winners. |
| **Next 2–4 months; then 6–12 months** | Accumulate a meaningful sample across different market regimes, review the registered experiment(s), measured costs, operational feed health and risk controls. | Stay paper-only until positive expectancy after realistic costs is demonstrated on a sufficiently large, independent forward sample and the owner explicitly approves any separate live-readiness work. No automatic go-live milestone. |

### Manual observation record (private; do not commit filled rows)

Use one row per eligible signal/stop event, including cases where the owner does **not** override the stop and cases that lose. Keep a bot entry and a manual entry separate; do not call them a matched trade unless the timestamps and setup actually match. Minimum fields:

`timestamp_utc, bot_trade_id, side, bot_entry, bot_sl, bot_tp, manual_entry, manual_exit, pressure_source, pressure_metric, pressure_timeframe, pressure_value_at_entry, pressure_value_at_stop_touch, last_closed_bar_utc, contemporaneous_action, reason_code, max_hold_or_exit_rule, post_stop_markout_horizons, mfe, mae, hypothetical_exit, estimated_cost, notes_without_account_identifiers`

A trade that later touches its former target after the bot's stop is a **counterfactual mark-out**, not a win under the bot's current rules. The entry, stop event, and decision must be timestamped before looking at the recovery path.

## Session log

- **2026-10-19 ~04:41 UTC (early session, data collection 279):** every-session step done — check_data 0 fail, handoff FRESH, structural-stop guard PASS, replay recall 100.0%, smoke PASSED; complete interim screen computed at n=127: **SCREEN NOT MET** (B2 47.24% vs ≤47.0% only; PASS also unreachable: n<150, Wilson LB 29.1% vs >32.1%). Judgement **not** taken (due 21:00 UTC tonight or n=150). Found the uncounted closure-gap revert count at its literal threshold (#595/#610) and recorded it for the judgement. No runtime change. Evidence: `docs/REVIEW-2026-10-19-struct-stop-screen.md`. Next eligible action: the 21:00 UTC judgement session, starting with the gap trigger.

## Session checklist

At the end of each execution session:

1. Mark the completed item and its evidence here; leave future gates untouched.
2. Update `docs/HANDOFF.md` where current state or next steps changed; run `python3 tools/handoff_check.py --update` only after checking the underlying files.
3. Record any conclusion in a dated review/pre-registration, not only in chat.
4. List the next eligible action and any owner/production-host blocker in the final response.
