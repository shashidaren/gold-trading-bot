# Pre-registration — Ratchet-Off Experiment (Forward Shadow A/B)
**Date:** 2026-10-05  
**Branch:** arena/01a10a7f-gold-trading-bot  
**Status:** SIGNED OFF & PRE-REGISTERED (Forward Shadow Mode)  
**Control (Live):** `BE_TRIGGER_R = 0.75` (unchanged live engine)  
**Treatment (Shadow):** `BE_TRIGGER_R = None` (Ratchet Disabled, pure 2x/3x ATR geometry with 240m max-hold)

---

## 1. Context & Motivation

- **Historical Background:** On 2026-09-10, a breakeven (BE) ratchet was introduced at 0.30R, and subsequently widened to 0.75R on 2026-09-15 (PR #9).
- **Isolation Review (2026-10-05):** The scheduled 14-day max-hold isolation window closed at n=209 trades (data collection 172, commit `304551b`):
  - 45W / 100L / 63BE / 1TIME, 31.0% decisive WR [24.1–39.0], -$0.570/trade (-$8.64/calendar day).
  - The 240-min max-hold cap never bound an in-session trade (longest non-TIME hold 68.0 min). The single TIME exit was trade #476 (held 49.1 h across the weekend close where the cap cannot fire).
- **Trigger Met:** The pre-registered fallback step-2 trigger (`n >= 200` and `<= -$0.40/trade`) was met (-$0.570/trade at n=209). Ratchet-off experiment was signed off and pre-registered as a forward shadow A/B test.
- **Guardrail:** The live bot remains untouched running the 0.75R control. The treatment runs in shadow mode to prevent premature capital drawdown and to observe real execution costs and cooldown cascades. Never revert to 0.30R.

---

## 2. Hypothesis & Experimental Design

- **Core Hypothesis:** The breakeven ratchet (even at 0.75R) prematurely cuts winning trades that experience standard retracements, converting potential 1.5R winners into 0R scratches (which still incur round-trip execution costs) without sufficiently protecting against full losses. Turning the ratchet off will restore decisive win rate and net costed expectancy.
- **Design:** Forward Shadow A/B Test.
  - **Live Engine (Control):** Operates under existing production configuration (`BE_TRIGGER_R = 0.75`).
  - **Shadow Harness (`tools/ratchet_shadow.py`):** Consumes identical closed candles from `forward_test_log.csv` (or feed) in real time or post-candle step, evaluating trades with `BE_TRIGGER_R = None`.
  - **Statefulness:** The shadow engine maintains its own independent position state, SL streak cooldowns (30m base / 60m escalated after 2 consecutive SLs, where BE neither counts nor breaks the streak), daily breaker (10 SLs -> trend-side only), and execution rules.
  - **Isolation:** One position at a time. No overlap.

---

## 3. Frozen Bar (Success / Failure Criteria)

All of the following criteria must be met to clear the experiment:
1. **Calibration Gate Passed:** Prior to T0, the harness running at `BE_TRIGGER_R = 0.75` must reproduce the live ledger within:
   - `+/- 3%` taken trades
   - `+/- $10` cumulative P&L
   - `+/- 2 pp` decisive win rate
   - Exact reproduction of trade #476 weekend TIME exit behavior.
2. **Sample Size & Duration:** Whichever is later:
   - `>= 150` new shadow trades evaluated from T0, **AND**
   - `>= 21` calendar days after T0.
3. **Primary Expectancy:**
   - Costed P&L/trade `>= +$0.10`, **AND**
   - `>= +$0.15/trade` better than the live 0.75R control on the exact same time window.
4. **Win Rate:**
   - Decisive WR `>= 38.0%` point estimate, **AND**
   - Wilson 95% Confidence Interval Lower Bound `>= 30.0%`.
5. **Drawdown:**
   - Shadow maximum peak-to-trough drawdown `<= 1.5x` live control max drawdown over the same window.
6. **Sub-period Consistency:**
   - The sign of condition (3) (shadow > live) must hold in `>= 3 of 5` equal sub-chunks of the test period.

---

## 4. Cost Model & Execution Rules

- **Round-Trip Execution Costs:** Fixed fee schedule applied to EVERY exit including BE scratches and TIME exits:
  - Low tier: `$0.05` / trade
  - Mid tier: `$0.08` / trade
  - High tier: `$0.11` / trade
  - **Mandatory Bar:** The primary conclusion (Criterion 3) must hold at the `$0.11` high-cost tier.
- **Gap Fills:** Gap exits (such as market open jumps) must fill at the re-open bar price, never the logged stop level.
- **Exit Priority:** Bar-vs-tick: Price exits take absolute priority over TIME stops. SL-first tie-break on candles spanning both SL and TP.

---

## 5. Decision Rules Post-Experiment

- **If Cleared:** Pre-register a formal runtime switch pull request with its own dedicated deployment record, canary period, and rollback procedure.
- **If Not Cleared:** Record the full audited results in Section 6 below. Live engine maintains `BE_TRIGGER_R = 0.75`. Never revert to 0.30R.

---

## 6. Ledger of Results & Audit Trail

*(To be populated after sample size and duration requirements are met post-T0.)*

- **T0 Timestamp:** TBD (Recorded upon calibration and initial shadow forward run)
- **Evaluation Date:** TBD
- **Shadow Sample Size (n):** TBD
- **Live Control Sample Size (n):** TBD
- **Shadow vs Control Metrics:** TBD
